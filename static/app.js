// 智能域名生成器 - 前端逻辑

const STORAGE_KEY = "yuming_config";

// DOM refs
const $ = (id) => document.getElementById(id);
const $description = $("description");
const $tldList = $("tld-list");
const $minLen = $("min-len");
const $maxLen = $("max-len");
const $count = $("count");
const $generateBtn = $("generate-btn");
const $status = $("status");
const $results = $("results");
const $settingsBtn = $("settings-btn");
const $settingsModal = $("settings-modal");
const $settingsSave = $("settings-save");
const $settingsCancel = $("settings-cancel");
const $testConn = $("test-conn");
const $testResult = $("test-result");
const $apiKey = $("api-key");
const $baseUrl = $("base-url");
const $model = $("model");
const $stopBtn = $("stop-btn");
const $logList = $("log-list");
const $clearLog = $("clear-log");

let availableTlds = [];
const selectedTlds = new Set();
let currentJobId = null;
let currentEs = null;

// ---- Config persistence ----
function loadConfig() {
  try {
    const raw = localStorage.getItem(STORAGE_KEY);
    if (!raw) return;
    const cfg = JSON.parse(raw);
    if (cfg.api_key) $apiKey.value = cfg.api_key;
    if (cfg.base_url) $baseUrl.value = cfg.base_url;
    if (cfg.model) $model.value = cfg.model;
  } catch (e) {
    console.warn("load config failed", e);
  }
}

function saveConfig() {
  const cfg = {
    api_key: $apiKey.value.trim(),
    base_url: $baseUrl.value.trim(),
    model: $model.value.trim(),
  };
  localStorage.setItem(STORAGE_KEY, JSON.stringify(cfg));
}

function getConfig() {
  return {
    api_key: $apiKey.value.trim(),
    base_url: $baseUrl.value.trim() || "https://api.openai.com/v1",
    model: $model.value.trim() || "gpt-4o-mini",
  };
}

function hasConfig() {
  return $apiKey.value.trim().length > 0;
}

// ---- TLD loading ----
async function fetchJson(url, options) {
  try {
    const resp = await fetch(url, options);
    if (!resp.ok) {
      let body = "";
      try { body = await resp.text(); } catch (_) {}
      throw new Error(`HTTP ${resp.status}: ${body.slice(0, 200) || resp.statusText}`);
    }
    return await resp.json();
  } catch (e) {
    if (e instanceof TypeError && /fetch|network|abort/i.test(e.message)) {
      throw new Error("无法连接到后端（127.0.0.1:5001）。请确认已运行 ./run.sh");
    }
    throw e;
  }
}

// ---- 运行日志（倒序：最新在最上面） ----
function logLine(text, level = "info") {
  const li = document.createElement("li");
  li.className = "log-level-" + level;
  const t = new Date();
  const hh = String(t.getHours()).padStart(2, "0");
  const mm = String(t.getMinutes()).padStart(2, "0");
  const ss = String(t.getSeconds()).padStart(2, "0");
  const time = document.createElement("span");
  time.className = "log-time";
  time.textContent = `[${hh}:${mm}:${ss}]`;
  const msg = document.createElement("span");
  msg.textContent = " " + text;
  li.appendChild(time);
  li.appendChild(msg);
  // 倒序：插到最前
  $logList.insertBefore(li, $logList.firstChild);
}

async function loadTlds() {
  try {
    const data = await fetchJson("/api/tlds");
    availableTlds = data.tlds || [];
    // Default: select first 5
    availableTlds.slice(0, 5).forEach((t) => selectedTlds.add(t));
    renderTlds();
  } catch (e) {
    $status.textContent = "TLD 列表加载失败：" + e.message;
    $status.classList.add("error");
  }
}

function renderTlds() {
  $tldList.innerHTML = "";
  availableTlds.forEach((tld) => {
    const chip = document.createElement("span");
    chip.className = "tld-chip" + (selectedTlds.has(tld) ? " selected" : "");
    chip.textContent = "." + tld;
    chip.addEventListener("click", () => {
      if (selectedTlds.has(tld)) selectedTlds.delete(tld);
      else selectedTlds.add(tld);
      chip.classList.toggle("selected");
    });
    $tldList.appendChild(chip);
  });
}

// ---- Generation flow ----
function setStatus(msg, type) {
  $status.textContent = msg || "";
  $status.classList.remove("error", "success");
  if (type) $status.classList.add(type);
}

async function generate() {
  const description = $description.value.trim();
  if (!description) {
    setStatus("请输入描述", "error");
    return;
  }
  if (!hasConfig()) {
    setStatus("请先在设置中填入 OpenAI API Key", "error");
    openSettings();
    return;
  }
  if (selectedTlds.size === 0) {
    setStatus("请至少选择一个 TLD 后缀", "error");
    return;
  }

  const minLen = parseInt($minLen.value, 10);
  const maxLen = parseInt($maxLen.value, 10);
  const count = parseInt($count.value, 10);

  if (isNaN(minLen) || isNaN(maxLen) || minLen > maxLen) {
    setStatus("长度范围非法", "error");
    return;
  }
  if (isNaN(count) || count < 1) {
    setStatus("数量非法", "error");
    return;
  }

  const cfg = getConfig();
  $generateBtn.disabled = true;
  $stopBtn.classList.remove("hidden");
  $results.innerHTML = "";
  setStatus("生成中…");
  logLine(`开始生成：请求 ${count} 个，TLD=[${Array.from(selectedTlds).join(", ")}]，长度 ${minLen}-${maxLen}`, "info");

  // EventSource 不支持 POST + body；先 POST /api/generate-stream 启动任务，
  // 然后让后端在第一次 yield 时返回 job_id，前端再 EventSource 连 /api/generate-stream/<job_id>
  // —— 但这样会复杂。简化：直接用 fetch + ReadableStream 读 SSE，兼容 POST。
  let resp;
  try {
    resp = await fetch("/api/generate-stream", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        description,
        min_len: minLen,
        max_len: maxLen,
        tlds: Array.from(selectedTlds),
        count,
        api_key: cfg.api_key,
        base_url: cfg.base_url,
        model: cfg.model,
      }),
    });
  } catch (e) {
    setStatus("网络错误：" + e.message, "error");
    logLine("网络错误：" + e.message, "error");
    finishGenerate();
    return;
  }

  if (!resp.ok) {
    let body = "";
    try { body = await resp.text(); } catch (_) {}
    setStatus(`请求失败 (${resp.status})：${body.slice(0, 200)}`, "error");
    logLine(`请求失败 HTTP ${resp.status}：${body.slice(0, 200)}`, "error");
    finishGenerate();
    return;
  }

  if (!resp.body) {
    setStatus("浏览器不支持流式响应", "error");
    logLine("浏览器不支持流式响应", "error");
    finishGenerate();
    return;
  }

  // 解析 SSE
  const reader = resp.body.getReader();
  const decoder = new TextDecoder("utf-8");
  let buf = "";
  let finalDomains = null;
  let finalStats = null;
  let shouldStop = false;

  function handleEvent(eventName, dataObj) {
    switch (eventName) {
      case "start":
        currentJobId = dataObj.job_id;
        logLine(`任务 ${currentJobId} 启动（请求 ${dataObj.requested} 个）`, "info");
        break;
      case "batch_start":
        logLine(`批次 ${dataObj.n}：调用 OpenAI…`, "info");
        break;
      case "batch_check":
        logLine(`批次 ${dataObj.n}：生成 ${dataObj.generated} 个候选，去重后 ${dataObj.fresh} 个，待查 ${dataObj.to_check} 个`, "info");
        break;
      case "batch_done":
        logLine(
          `批次 ${dataObj.n} 完成：本批可注册 ${dataObj.available_this_batch} 个，累计 ${dataObj.total_available}/${count}（${dataObj.elapsed}s）`,
          dataObj.available_this_batch > 0 ? "info" : "warn"
        );
        break;
      case "stopped":
        logLine(`已停止（用户中止）：累计 ${dataObj.available} 个可注册（${dataObj.elapsed}s）`, "warn");
        shouldStop = true;
        break;
      case "error":
        logLine("错误：" + dataObj.msg, "error");
        break;
      case "done":
        finalDomains = dataObj.domains || [];
        finalStats = dataObj.stats || {};
        logLine(
          `完成：共 ${finalStats.batches} 批次，累计 ${finalStats.available} 个可注册，耗时 ${dataObj.elapsed}s`,
          "done"
        );
        shouldStop = true;
        break;
    }
  }

  try {
    while (!shouldStop) {
      const { value, done } = await reader.read();
      if (done) break;
      buf += decoder.decode(value, { stream: true });
      // SSE 事件以 \n\n 分隔
      let idx;
      while ((idx = buf.indexOf("\n\n")) >= 0) {
        const raw = buf.slice(0, idx);
        buf = buf.slice(idx + 2);
        // 解析 event: / data: 行
        let eventName = "message";
        const dataLines = [];
        for (const line of raw.split("\n")) {
          if (line.startsWith("event:")) {
            eventName = line.slice(6).trim();
          } else if (line.startsWith("data:")) {
            dataLines.push(line.slice(5).trim());
          }
        }
        if (!dataLines.length) continue;
        const dataStr = dataLines.join("\n");
        let dataObj = {};
        try { dataObj = JSON.parse(dataStr); } catch (_) { dataObj = { raw: dataStr }; }
        handleEvent(eventName, dataObj);
      }
      if (shouldStop) {
        try { await reader.cancel(); } catch (_) {}
        break;
      }
    }
  } catch (e) {
    if (!shouldStop) {
      logLine("读取日志流异常：" + e.message, "error");
    }
  }

  if (finalDomains !== null) {
    renderResults(finalDomains, finalStats || {});
    setStatus(
      `已生成 ${finalDomains.length} 个可注册域名${finalDomains.length < count ? `（请求 ${count} 个）` : ""}`,
      finalDomains.length > 0 ? "success" : "error"
    );
  } else {
    // stopped 事件路径：finalDomains 仍为 null
    setStatus("已手动停止", "error");
  }

  finishGenerate();
}

function finishGenerate() {
  $generateBtn.disabled = false;
  $stopBtn.classList.add("hidden");
  currentJobId = null;
  if (currentEs) { try { currentEs.close(); } catch (_) {} currentEs = null; }
}

async function stopGenerate() {
  if (!currentJobId) return;
  logLine(`请求停止任务 ${currentJobId}…`, "warn");
  try {
    await fetch(`/api/stop/${encodeURIComponent(currentJobId)}`, { method: "POST" });
  } catch (e) {
    logLine("停止请求失败：" + e.message, "error");
  }
}

function renderResults(domains, stats) {
  $results.innerHTML = "";
  if (!domains.length) {
    const empty = document.createElement("div");
    empty.className = "status";
    empty.textContent = "未找到符合要求且可注册的域名。可尝试增加 TLD 选项、放宽长度范围或调整措辞。";
    $results.appendChild(empty);
    return;
  }

  const header = document.createElement("h2");
  header.textContent = `结果（共 ${domains.length} 个）`;
  header.style.fontSize = "16px";
  header.style.margin = "0 0 12px";
  $results.appendChild(header);

  domains.forEach((d) => {
    const card = document.createElement("div");
    card.className = "domain-card";

    const head = document.createElement("div");
    head.className = "domain-card-head";
    const name = document.createElement("div");
    name.className = "domain-name";
    name.textContent = d.domain;
    const badge = document.createElement("span");
    badge.className = "badge " + (d.status === "available" ? "available" : "unknown");
    badge.textContent = d.status === "available" ? "✓ 可注册" : "? 状态未知";
    head.appendChild(name);
    head.appendChild(badge);

    const reason = document.createElement("p");
    reason.className = "domain-reason";
    reason.textContent = d.reason;

    const meta = document.createElement("div");
    meta.className = "domain-meta";
    meta.textContent = `长度：${d.length} | TLD：${d.tld}`;

    card.appendChild(head);
    card.appendChild(reason);
    card.appendChild(meta);
    $results.appendChild(card);
  });
}

// ---- Modal ----
function openSettings() {
  $settingsModal.classList.remove("hidden");
  $settingsModal.classList.add("open");
  $testResult.textContent = "";
  $testResult.className = "test-result";
}
function hideSettings() {
  $settingsModal.classList.add("hidden");
  $settingsModal.classList.remove("open");
}

function setTestResult(msg, type) {
  $testResult.textContent = msg || "";
  $testResult.className = "test-result" + (type ? " " + type : "");
}

async function testConnection() {
  const apiKey = $apiKey.value.trim();
  if (!apiKey) {
    setTestResult("请先填写 API Key", "error");
    return;
  }
  $testConn.disabled = true;
  setTestResult("测试中…", "loading");
  try {
    const data = await fetchJson("/api/validate-key", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        api_key: apiKey,
        base_url: $baseUrl.value.trim() || "https://api.openai.com/v1",
        model: $model.value.trim() || "gpt-4o-mini",
      }),
    });
    if (data.success) {
      const sample = (data.sample_models || []).slice(0, 3).join(", ");
      const available = data.requested_model_available;
      let msg = `✓ 连接成功（可用模型数：${data.model_count}）`;
      if (sample) msg += `，示例：${sample}`;
      if (available === false) msg += `。注意：模型 "${$model.value.trim()}" 不在示例模型中，请确认。`;
      setTestResult(msg, "success");
    } else {
      setTestResult("✗ " + (data.error || "连接失败"), "error");
    }
  } catch (e) {
    setTestResult("✗ 网络错误：" + e.message, "error");
  } finally {
    $testConn.disabled = false;
  }
}

// ---- Init ----
function init() {
  try {
    loadConfig();
    $settingsBtn.addEventListener("click", openSettings);
    $settingsCancel.addEventListener("click", hideSettings);
    $settingsSave.addEventListener("click", () => {
      saveConfig();
      hideSettings();
      setStatus("设置已保存", "success");
    });
    $testConn.addEventListener("click", testConnection);
    $settingsModal.addEventListener("click", (e) => {
      if (e.target === $settingsModal) hideSettings();
    });
    $generateBtn.addEventListener("click", generate);
    $stopBtn.addEventListener("click", stopGenerate);
    $clearLog.addEventListener("click", () => { $logList.innerHTML = ""; });
    loadTlds();
    console.log("[yuming] init OK");
  } catch (e) {
    console.error("[yuming] init failed:", e);
    $status.textContent = "前端初始化失败：" + e.message;
    $status.classList.add("error");
    throw e;
  }
}

try {
  init();
} catch (e) {
  // init 内部已打印并显示错误；这里再保险一次
  console.error("[yuming] init outer catch:", e);
}