// 微信扫码登录 + 消息推送服务
//
// 设计：
// 1. 启动时调用 wechat-channel 客户端 -> 登录 -> 长轮询收消息
// 2. 收消息时把 (accountId, peerId, displayName, lastText, lastTs) 存到内存里的联系人列表
// 3. 提供 REST API 给 Flask 调用：
//    GET  /status           -> 登录状态 + 联系人列表
//    POST /send             -> {peerId, text} 主动推送（wechat-channel 限制：只能给 24h 内收到过消息的人发）
//    POST /login            -> 触发扫码
//    POST /logout           -> 退出
//
// 依赖：wechat-channel 1.x（基于 ilinkai.weixin.qq.com）
import express from 'express';
import cors from 'cors';
import { WeixinClient } from 'wechat-channel';

const PORT = Number(process.env.PORT || 5002);
const STATE_DIR = process.env.WECHANNEL_STATE_DIR || '/data/wechannel';
const API_TOKEN = process.env.BOT_API_TOKEN || '';

// 自动重连配置
const RECONNECT_DELAY_MS = 30_000;      // 检测到掉线后，等待多久开始重连
const RECONNECT_INTERVAL_MS = 60_000;   // 重连失败后，多久再试一次
const MAX_RECONNECT_ATTEMPTS = 0;       // 0 表示无限重试（直到成功或手动 logout）
const HEALTH_CHECK_INTERVAL_MS = 60_000; // 健康检查间隔（检测静默掉线）

const app = express();
app.use(cors());
app.use(express.json({ limit: '64kb' }));

// --- 简单的 token 鉴权，防止任意人调用本服务 ---
function auth(req, res, next) {
  const token = req.header('X-Bot-Token') || req.query.token || '';
  if (token !== API_TOKEN) {
    return res.status(401).json({ ok: false, error: 'unauthorized' });
  }
  next();
}
app.use(auth);

// --- 重连状态 ---
let reconnectAttempts = 0;
let reconnectTimer = null;
let healthCheckTimer = null;
let isReconnecting = false;           // 防止重复重连
let lastConnectedAt = null;           // 上次成功连接的时间
const state = {
  status: 'disconnected', // disconnected | logging_in | connected | session_expired
  qrcode: null,           // legacy, kept for compat
  qrcodeUrl: null,       // 当前展示用的二维码 URL（liteapp.weixin.qq.com/q/...）
  connectedAt: null,     // 本次 connected 时间戳（用于判断是否刚连接）
  awaitingFirstMessage: false, // connected 且尚未收到任何消息 → 引导发消息
  accountId: null,
  // 联系人：peerId -> { displayName, lastText, lastTs, accountId, messages: 计数 }
  contacts: new Map(),
  // 日志限长
  logs: [],
};

function pushLog(msg) {
  const line = `[${new Date().toISOString()}] ${msg}`;
  state.logs.push(line);
  if (state.logs.length > 200) state.logs.shift();
  console.log(line);
}

// --- 微信客户端 ---
const client = new WeixinClient({
  stateDir: STATE_DIR,
  log: pushLog,
  errorLog: pushLog,
});

client.on('message', async (msg) => {
  pushLog(`收到消息: account=${msg.accountId} from=${msg.from} text=${(msg.text || '').slice(0, 50)}`);
  const existing = state.contacts.get(msg.from) || {
    displayName: msg.from,
    messages: 0,
  };
  const isFirstMessage = !existing.messages; // 本次登录后第一条消息
  state.contacts.set(msg.from, {
    accountId: msg.accountId,
    peerId: msg.from,
    displayName: msg.from, // wechat-channel 默认不带昵称，使用 from 作为兜底
    lastText: (msg.text || `[${msg.image ? 'image' : msg.file ? 'file' : msg.voice ? 'voice' : 'media'}]`),
    lastTs: msg.timestamp || Date.now(),
    messages: existing.messages + 1,
    contextToken: msg.contextToken, // 最近一条可用的 contextToken
  });
  if (isFirstMessage) {
    state.awaitingFirstMessage = false;
    state.firstMessageArrived = true; // 一次性标记，前端轮询到后清
    pushLog(`收到第一条消息 from=${msg.from}，通知前端刷新`);
  }
});

client.on('session_status', ({ accountId, status }) => {
  state.status = status;
  state.accountId = accountId;
  pushLog(`session_status: ${accountId} -> ${status}`);

  // 监听会话状态变化，触发自动重连
  if (status === 'session_expired' || status === 'disconnected') {
    pushLog(`检测到会话掉线 (${status})，${RECONNECT_DELAY_MS / 1000}s 后开始自动重连...`);
    scheduleReconnect(RECONNECT_DELAY_MS);
  }

  if (status === 'connected') {
    lastConnectedAt = Date.now();
    reconnectAttempts = 0;
    pushLog(`连接恢复成功`);
  }
});

client.on('login', (account) => {
  state.status = 'connected';
  state.accountId = account.id;
  state.qrcodeUrl = null;
  state.connectedAt = Date.now();
  state.awaitingFirstMessage = true; // 还没收到过消息，等对方发第一条
  lastConnectedAt = Date.now();
  reconnectAttempts = 0;
  pushLog(`登录成功: ${account.id}，等待第一条消息`);
});

client.on('error', (err) => {
  pushLog(`client error: ${err.message}`);
  // client.error 通常是 receiver 内部错误，可能导致掉线
  // 触发快速重连检查
  if (client.isReceiving(state.accountId) === false && state.accountId) {
    pushLog(`检测到接收器异常退出，${RECONNECT_DELAY_MS / 1000}s 后尝试重连...`);
    scheduleReconnect(RECONNECT_DELAY_MS);
  }
});

await client.init();

// --- 自动重连逻辑 ---

/**
 * 安排重连任务（防抖：避免重复安排）
 */
function scheduleReconnect(delayMs = RECONNECT_DELAY_MS) {
  // 如果正在重连或已经安排了重连，不再重复安排
  if (isReconnecting || reconnectTimer) {
    pushLog(`重连已在安排中，跳过此次调度`);
    return;
  }

  // 如果当前是 logged_in 状态（扫码登录中），不触发重连
  if (state.status === 'logging_in') {
    pushLog(`当前正在扫码登录中，暂不触发重连`);
    return;
  }

  reconnectTimer = setTimeout(() => {
    reconnectTimer = null;
    attemptReconnect();
  }, delayMs);
  pushLog(`已安排 ${delayMs / 1000}s 后执行重连`);
}

/**
 * 执行重连尝试
 */
async function attemptReconnect() {
  // 防止重复重连
  if (isReconnecting) {
    pushLog(`重连进行中，跳过`);
    return;
  }

  // 检查是否已连接
  if (state.status === 'connected' && client.isReceiving(state.accountId)) {
    pushLog(`当前已是 connected 状态，无需重连`);
    return;
  }

  // 检查是否有可用的账户
  const accounts = client.getAccounts();
  const configuredAccount = accounts.find(acc => acc.configured);

  if (!configuredAccount) {
    pushLog(`没有已配置的账户，无法自动重连（请先扫码登录）`);
    return;
  }

  isReconnecting = true;
  reconnectAttempts++;
  state.status = 'reconnecting';
  pushLog(`开始重连... (第 ${reconnectAttempts} 次尝试)`);

  try {
    // 先停止旧的 receiver（如果存在）
    if (state.accountId) {
      try {
        await client.stop(state.accountId);
      } catch (e) {
        // 忽略停止错误
      }
    }

    // 重新启动 receiver
    await client.start(configuredAccount.id);
    state.accountId = configuredAccount.id;

    // 检查会话状态
    const sess = client.getSessionStatus(configuredAccount.id);
    if (sess.status === 'connected') {
      state.status = 'connected';
      lastConnectedAt = Date.now();
      reconnectAttempts = 0;
      pushLog(`✅ 重连成功！账户 ${configuredAccount.id} 已恢复连接`);
    } else if (sess.status === 'session_expired') {
      // 会话已过期，需要重新扫码
      state.status = 'session_expired';
      pushLog(`⚠️ 会话已过期，需要重新扫码登录`);
      // 等待一段时间后再试（session_expired 通常需要人工介入）
      scheduleReconnect(RECONNECT_INTERVAL_MS);
    } else {
      // 其他状态，尝试继续
      state.status = sess.status;
      pushLog(`重连完成，当前状态: ${sess.status}`);
    }
  } catch (err) {
    pushLog(`❌ 重连失败: ${err.message}`);
    state.status = 'disconnected';

    // 检查是否达到最大重试次数
    if (MAX_RECONNECT_ATTEMPTS > 0 && reconnectAttempts >= MAX_RECONNECT_ATTEMPTS) {
      pushLog(`已达到最大重试次数 (${MAX_RECONNECT_ATTEMPTS})，停止自动重连`);
      return;
    }

    // 安排下次重连
    scheduleReconnect(RECONNECT_INTERVAL_MS);
  } finally {
    isReconnecting = false;
  }
}

/**
 * 健康检查：定期检查连接状态
 * 防止静默掉线（session_status 事件没有触发的情况）
 */
function startHealthCheck() {
  if (healthCheckTimer) return;

  healthCheckTimer = setInterval(async () => {
    // 只在应该连接但没有连接时检查
    if (state.status !== 'disconnected' && state.status !== 'session_expired') {
      return;
    }

    const accounts = client.getAccounts();
    const configuredAccount = accounts.find(acc => acc.configured);
    if (!configuredAccount) return;

    // 检查 receiver 是否真的在运行
    const isReceiving = client.isReceiving(configuredAccount.id);
    if (!isReceiving) {
      pushLog(`健康检查: receiver 未运行，触发重连`);
      scheduleReconnect(5_000); // 快速重连
    }
  }, HEALTH_CHECK_INTERVAL_MS);
  pushLog(`健康检查已启动 (间隔 ${HEALTH_CHECK_INTERVAL_MS / 1000}s)`);
}

async function startIfLoggedIn() {
  // 如果 stateDir 里已有持久化的账户，直接 start
  const accounts = client.getAccounts();
  for (const acc of accounts) {
    if (acc.configured) {
      try {
        await client.start(acc.id);
        state.accountId = acc.id;
        const sess = client.getSessionStatus(acc.id);
        if (sess.status === 'connected') {
          state.status = 'connected';
          lastConnectedAt = Date.now();
        } else if (sess.status === 'session_expired') {
          state.status = 'session_expired';
          // 已登录但会话过期，触发自动重连
          pushLog(`检测到已保存账户的会话已过期，将自动尝试重新登录...`);
          scheduleReconnect(RECONNECT_DELAY_MS);
        } else {
          state.status = sess.status;
        }
        pushLog(`从持久化恢复账户 ${acc.id}, session=${sess.status}`);
        // 启动健康检查
        startHealthCheck();
        return;
      } catch (e) {
        pushLog(`恢复失败: ${e.message}`);
        // 启动失败也触发重连
        scheduleReconnect(RECONNECT_DELAY_MS);
      }
    }
  }
  pushLog('未发现已登录账户，请调用 POST /login 扫码');
}
startIfLoggedIn().catch(e => pushLog(`start 失败: ${e.message}`));

// --- REST API ---

app.get('/status', (req, res) => {
  res.json({
    ok: true,
    status: state.status,
    accountId: state.accountId,
    qrcode: state.qrcode,
    qrcodeUrl: state.qrcodeUrl,
    awaitingFirstMessage: state.awaitingFirstMessage,
    contacts: Array.from(state.contacts.values())
      .sort((a, b) => (b.lastTs || 0) - (a.lastTs || 0))
      .slice(0, 100),
    logs: state.logs.slice(-30),
  });
  // 消费一次性标记（前端下次轮询就不会再看到）
  state.firstMessageArrived = false;
});

// 从 logs 解析最近一次的 QR url
function parseLatestQrcodeUrl() {
  // wechat-channel log 形如: "[ts] 请扫描二维码: https://liteapp.weixin.qq.com/q/XXX"
  // 或: "[ts] 新二维码: https://liteapp.weixin.qq.com/q/XXX"
  for (let i = state.logs.length - 1; i >= 0; i--) {
    const m = state.logs[i].match(/(?:请扫描二维码|新二维码): (https:\/\/\S+)/);
    if (m) return m[1];
  }
  return null;
}

// 异步 login，避免阻塞 HTTP（client.login 内置轮询可跑到 8 分钟）
async function performLogin() {
  state.status = 'logging_in';
  state.qrcodeUrl = null;

  // 取消待执行的重连任务（用户主动登录）
  if (reconnectTimer) {
    clearTimeout(reconnectTimer);
    reconnectTimer = null;
  }

  // 周期轮询 logs 抓 QR url（client.login 是同步等，不暴露 url 出来）
  const qrWatcher = setInterval(() => {
    const url = parseLatestQrcodeUrl();
    if (url) state.qrcodeUrl = url;
  }, 500);
  try {
    const result = await client.login({ timeoutMs: 8 * 60_000 });
    if (result.success && result.account) {
      state.accountId = result.account.id;
      state.status = 'connected';
      state.qrcodeUrl = null;
      await client.start(result.account.id);
      reconnectAttempts = 0;
      pushLog(`登录成功: ${result.account.id}`);
      // 登录成功后启动健康检查
      startHealthCheck();
      return;
    }
    state.status = 'disconnected';
    pushLog(`登录失败: ${result.error || 'unknown'}`);
  } catch (e) {
    state.status = 'disconnected';
    pushLog(`登录异常: ${e.message}`);
  } finally {
    clearInterval(qrWatcher);
  }
}

app.post('/login', (req, res) => {
  if (state.status === 'connected' || state.status === 'logging_in') {
    return res.json({ ok: false, error: `当前状态 ${state.status}，无法重复登录` });
  }
  // 立即返回（前端通过轮询 /status 拿 qrcodeUrl 和状态）
  res.json({ ok: true, message: '登录已启动，请通过 /status 轮询二维码和状态' });
  // 后台跑（不 await）
  performLogin().catch(e => pushLog(`performLogin 异常: ${e.message}`));
});

app.post('/logout', async (req, res) => {
  if (!state.accountId) return res.json({ ok: true });
  try {
    // 取消待执行的重连任务
    if (reconnectTimer) {
      clearTimeout(reconnectTimer);
      reconnectTimer = null;
      pushLog(`已取消待执行的重连任务`);
    }

    await client.stop(state.accountId);
    await client.logout(state.accountId);
    state.status = 'disconnected';
    state.accountId = null;
    state.contacts.clear();
    reconnectAttempts = 0;
    return res.json({ ok: true });
  } catch (e) {
    return res.status(500).json({ ok: false, error: e.message });
  }
});

app.post('/send', async (req, res) => {
  if (state.status !== 'connected' || !state.accountId) {
    return res.status(400).json({ ok: false, error: '未连接微信，请先扫码登录' });
  }
  const { peerId, text } = req.body || {};
  if (!peerId || !text) {
    return res.status(400).json({ ok: false, error: 'peerId 和 text 必填' });
  }
  try {
    const capability = await client.getReplyCapability(state.accountId, peerId);
    if (!capability.canReply) {
      return res.status(400).json({
        ok: false,
        error: `无法发送：${capability.reason}`,
        capability,
      });
    }
    const result = await client.sendText(state.accountId, peerId, text);
    return res.json({ ok: true, result });
  } catch (e) {
    return res.status(500).json({ ok: false, error: e.message });
  }
});

// 健康检查
app.get('/health', (req, res) => res.json({ ok: true }));

app.listen(PORT, '0.0.0.0', () => {
  pushLog(`微信 Bot 服务已启动 PORT=${PORT} STATE_DIR=${STATE_DIR}`);
});

// 优雅退出
process.on('SIGTERM', async () => {
  pushLog('SIGTERM, shutting down...');

  // 清理定时器
  if (reconnectTimer) {
    clearTimeout(reconnectTimer);
    reconnectTimer = null;
  }
  if (healthCheckTimer) {
    clearInterval(healthCheckTimer);
    healthCheckTimer = null;
  }

  await client.close();
  process.exit(0);
});
