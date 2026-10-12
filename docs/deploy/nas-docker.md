# 智能域名生成器 + 微信推送服务（NAS / 家庭服务器部署）

## 目录

1. [架构](#架构)
2. [前置要求](#前置要求)
3. [首次部署](#首次部署)
4. [日常运维](#日常运维)
5. [微信扫码：远程访问方案](#微信扫码远程访问方案)
6. [常见问题](#常见问题)
7. [回滚 / 备份 / 迁移](#回滚--备份--迁移)
8. [CI 镜像更新机制说明](#ci-镜像更新机制说明)

---

## 架构

```
┌─────────────────────────────────────────────────────────────┐
│ NAS / 家庭服务器（Docker）                                    │
│                                                              │
│  ┌──────────────────┐         ┌──────────────────────┐      │
│  │  yuming :5001    │ ──────► │  yuming-bot :5002    │      │
│  │  Flask + gunicorn│  HTTP   │  Node.js + wechat-   │      │
│  │  (主服务)         │  token  │  channel             │      │
│  └──────────────────┘  鉴权   └──────────────────────┘      │
│         │                              │                    │
│         │  /app 目录（read-only 镜像）  │  /data/wechannel   │
│         │                              │  (volume 持久化)    │
│         ▼                              ▼                    │
│  OpenAI 兼容 API                  微信扫码登录                │
│                                                              │
└─────────────────────────────────────────────────────────────┘
```

**两个服务完全独立**：
- `yuming`（Flask）：跑主应用，暴露给用户用浏览器访问
- `yuming-bot`（Node.js）：微信扫码 + 消息推送，被 `yuming` 内部调用

**可选挂载**（用于自动更新，需手动配置，见 [升级](#升级)）：
- `/var/run/docker.sock` 挂到 `yuming` 容器内 → web 端"在线更新"按钮可用

---

## 前置要求

| 项目 | 要求 | 说明 |
| --- | --- | --- |
| 操作系统 | Linux（NAS 群晖/威联通/极空间，或任意 Linux 服务器） | 已在群晖 DSM 7、Ubuntu 22.04、Debian 12 验证 |
| Docker | 20.10+ | 建议用官方 Docker，**不建议用群晖 Container Manager 自带 compose**（版本太旧） |
| Docker Compose | v2（`docker compose` 命令） | **不要**装 v1（`docker-compose`），二者命令格式不同 |
| 架构 | `linux/amd64` 或 `linux/arm64` | 镜像同时支持两种架构，由 CI 自动构建 |
| 内存 | ≥ 1 GB | 两个容器加一起常驻 ~150 MB，OpenAI 调用时短暂峰值 ~300 MB |
| 端口 | `5001`（主服务）`5002`（微信 bot，可选） | 部署时需可访问；远程访问见 [微信扫码](#微信扫码远程访问方案) |
| OpenAI Key | 必填 | 兼容 OpenAI / Azure / 国内代理，填进 `.env` |

**检查 Docker / Compose 版本**：

```bash
docker --version          # 期望 Docker version 20.10+
docker compose version    # 期望 Docker Compose version v2.x
```

群晖用户安装 Compose v2：
```bash
sudo curl -L "https://github.com/docker/compose/releases/latest/download/docker-compose-$(uname -s)-$(uname -m)" \
  -o /usr/local/bin/docker-compose
sudo chmod +x /usr/local/bin/docker-compose
```

---

## 首次部署

### 步骤 1：克隆仓库

```bash
# 推荐：只 clone 最新一次
git clone --depth 1 https://github.com/adminmtan/domainsearch-.git
cd domainsearch-

# 或者从 GitHub 下载 zip 也能用，但 git clone 后续升级更方便
```

### 步骤 2：填入环境变量

```bash
cp .env.example .env
$EDITOR .env
```

`.env` 必填项（其余保持默认即可）：

```bash
OPENAI_API_KEY=sk-your-real-key

# 如果用国内代理 / Azure / 自建兼容服务
# OPENAI_BASE_URL=https://your-proxy.com/v1
# OPENAI_MODEL=gpt-4o-mini

# 微信推送（可选，不填也跑得起来）
# WECHAT_PUSHER_URL=https://your-wechat-plugin.example.com/webhook
# WECHAT_PUSHER_TOKEN=optional-bearer-token

# 主服务 ↔ 微信 bot 内部 token（生产环境务必改！）
WECHAT_BOT_TOKEN=please-change-me-to-a-long-random-string
```

> **安全提示**：`WECHAT_BOT_TOKEN` 是 Flask ↔ 微信 bot 之间的共享密钥。如果 `5002` 端口被暴露到公网，**必须**改默认值（防止别人调你的 bot 推消息给你）。

生成随机 token：
```bash
openssl rand -hex 32   # 64 字符，安全
# 或者
head -c 32 /dev/urandom | base64
```

### 步骤 3：拉取镜像 + 启动

**模式 A：拉预构建镜像**（推荐，体积小、快速）

```bash
# 拉 latest
docker compose pull
docker compose up -d
```

**模式 B：本地 build**（没网 / 想改 Dockerfile 时）

```bash
# docker-compose.yml 默认已配 build: .，直接：
docker compose build
docker compose up -d
```

> 提示：两种模式可以混用。`compose build` 会用 `image:` 字段打 tag，名字固定；`compose pull` 时会覆盖。

### 步骤 4：验证

```bash
# 看容器是否 healthy
docker compose ps
# 期望：
# NAME         IMAGE                              STATUS
# yuming       ghcr.io/adminmtan/yuming:latest   Up (healthy)
# yuming-bot   ghcr.io/adminmtan/yuming-bot:latest Up (healthy)

# 看实时日志
docker compose logs -f --tail 50

# 测试端点
curl -I http://127.0.0.1:5001/   # 期望 200 OK
curl    http://127.0.0.1:5002/health
# 期望：{"ok":true}
```

浏览器访问 `http://<NAS-IP>:5001/`，看到域名生成器界面 = 部署成功 🎉

### 步骤 5：（可选）配置自动更新

如果你想用 web 界面的"在线更新"按钮，让容器自己 `docker compose pull && up -d`：

```yaml
# docker-compose.yml -> services.yuming.volumes 加一行：
    volumes:
      - /var/run/docker.sock:/var/run/docker.sock:ro   # 必须只读（ro）
      - ./docker-compose.yml:/app/docker-compose.yml:ro  # 容器内 updater 找它
```

⚠️ **挂 docker.sock 等于给容器 root 等价权限**。只在你信任这个镜像 / 仓库时挂，并保持只读。

---

## 日常运维

### 启动 / 停止 / 重启

```bash
cd domainsearch-
docker compose up -d       # 启动
docker compose stop        # 停
docker compose restart     # 重启（不重建镜像）
docker compose down        # 停 + 删容器（保留 volume 和镜像）
docker compose down -v     # 连 volume 也删（**会清空微信登录状态**，谨慎）
```

### 看日志

```bash
docker compose logs -f yuming         # 只看主服务
docker compose logs -f yuming-bot     # 只看微信 bot
docker compose logs -f                # 两个一起
docker compose logs --since 10m       # 最近 10 分钟
```

每个容器已配日志轮转（`max-size: 10m, max-file: 3`），磁盘不会被日志撑爆。

### 升级

**方式 1：手动拉镜像（最稳）**

```bash
cd domainsearch-
git pull                    # 同步 docker-compose.yml / .env.example 的更新
docker compose pull
docker compose up -d        # 优雅停旧容器 + 起新容器
```

**方式 2：固定到某个版本（生产推荐）**

```bash
# 1) 在 .env 或 docker-compose.yml 里把 image 改成固定 tag
#    image: ghcr.io/adminmtan/yuming:sha-7fbf52a
# 2) 启动
docker compose up -d
```

可用 tag 见 [CI 镜像更新机制说明](#ci-镜像更新机制说明)。

**方式 3：Web 端"在线更新"**（需先按 [步骤 5](#步骤5可选配置自动更新) 挂 docker.sock）

访问 `http://<NAS-IP>:5001/`，等右上角出现"有新版本"提示 → 点"立即更新"。

> 升级主版本（第一位数字变化，如 1.x → 2.x）时 UI 会**拒绝自动升级**，提示去 GitHub 看 Release Notes。这是故意的，避免破坏性变更直接打到生产。

### 回滚

```bash
# 1) 改回上一个 tag
sed -i.bak 's/:latest/:sha-OLD_COMMIT/' docker-compose.yml
# 或者手动编辑 docker-compose.yml 把 image 改成旧 tag

# 2) 重启
docker compose up -d
```

回滚不会丢数据（`/data/wechannel` volume 还在）。

---

## 微信扫码：远程访问方案

**问题**：微信扫码登录需要在浏览器里看二维码（5002 端口的 web UI）。如果 NAS 在内网、你在外面，怎么扫码？

**方案 A：VPN / 内网穿透**（推荐）

把 NAS 的 5002 端口通过以下任一方式暴露到你能访问的网络：

| 方案 | 工具 | 难度 | 备注 |
| --- | --- | --- | --- |
| Tailscale / ZeroTier | 客户端 | ⭐ | 加机器到虚拟局域网，最简单 |
| FRP / nps | 自建 | ⭐⭐ | 需要一台公网 VPS |
| Cloudflare Tunnel | 免费 | ⭐⭐ | 走 Cloudflare 中转，限制多 |
| 群晖 QuickConnect | 自带 | ⭐ | 仅 DSM 6+ ，Web Station 不一定能跑 |

**方案 B：VNC / 远程桌面**（无 VPN 时）

在 NAS 上装个 VNC server，远程连进去用浏览器访问 5002，扫码。

**方案 C：API 调用**（不扫码，纯后端）

如果你只需要主服务（域名生成 + 推送），不需要在 UI 里看二维码，5002 端口**完全不用暴露**。主服务通过内部网络 `http://yuming-bot:5002` 调 bot，无需扫码。

启动后第一次用：
1. 浏览器打开 `http://<NAS-IP>:5002/`
2. 调 `POST /login` 触发登录
3. 看响应里 `qrcodeUrl` 字段 → 用手机微信扫码
4. 看到 `status: connected` = 完成
5. **强烈建议删掉 5002 端口的公网暴露**（除了扫码的几十秒），仅留 5001

---

## 常见问题

### Q1: `docker compose` 报 `version is obsolete` 警告

**A**: 不影响运行。新版 Compose v2 不再需要 `version: "3.8"` 字段，但保留也无害。如果想消警告，删 `docker-compose.yml` 顶行 `version: "3.8"` 即可。

### Q2: 5001 端口被占

**A**: macOS 的 `ControlCenter` 占着 5000，但 5001 应该空着。如果还是被占：

```bash
lsof -i :5001
# 找到占用进程，杀掉，或者改 docker-compose.yml 的 ports:
#   ports:
#     - "5050:5001"   # 宿主机 5050 -> 容器 5001
```

### Q3: `yuming` 容器一直 restarting

**A**: 看日志找原因：

```bash
docker compose logs --tail 100 yuming
```

常见原因：
- **gunicorn Permission denied** — 已修复（见 commit 7fbf52a，useradd 加 `-m -d /home/appuser`）
- **找不到 requirements.txt** — 已修复（见 commit 7fbf52a，删 `.dockerignore` 里的 `requirements.txt`）
- **`ModuleNotFoundError: gunicorn`** — 已修复（见 commit 7fbf52a，requirements.txt 加 `gunicorn>=21.2.0`）

### Q4: `yuming-bot` 容器 `npm ci` 失败

**A**: **已修复**（见 commit 7fbf52a，Dockerfile 加 `COPY package-lock.json`）。如果你用的旧版本，重新拉镜像即可。

### Q5: 拉镜像超时 / 国内慢

**A**: 给 Docker 配镜像加速器：

```bash
# /etc/docker/daemon.json
{
  "registry-mirrors": [
    "https://docker.mirrors.ustc.edu.cn",
    "https://hub-mirror.c.163.com"
  ]
}

sudo systemctl restart docker
```

或者改 `docker-compose.yml` 的 `image:` 字段，从 `ghcr.io` 换成你 push 过的镜像仓库。

### Q6: 微信扫码后立刻掉线

**A**: `wechat-channel` 客户端有反风控策略，**头 24 小时只能给"24h 内给你发过消息的人"推**。这不是 bug，是微信限制。

### Q7: 数据会不会丢？

| 数据 | 持久化方式 | 升级会丢吗 |
| --- | --- | --- |
| 主服务代码 | 镜像 | 不会（重启加载新镜像） |
| `.env` | 宿主机文件 | 不会（mount 不会动） |
| 微信登录状态 | `wechannel-data` volume | 不会 |
| 用户在前端存的 API Key | 浏览器 `localStorage` | 跟浏览器走，**清浏览器缓存会丢** |

### Q8: 想改 OpenAI 模型怎么办

```bash
# 改 .env，加一行
OPENAI_MODEL=gpt-4o
# 或 OPENAI_BASE_URL=https://your-proxy.com/v1
docker compose restart yuming
```

不需要重建镜像。

---

## 回滚 / 备份 / 迁移

### 备份

只需备份两个东西：

```bash
# 1) .env
cp .env .env.backup-$(date +%Y%m%d)

# 2) 微信登录状态（不想每次重扫码）
docker compose exec yuming-bot tar czf - /data/wechannel > wechannel-backup-$(date +%Y%m%d).tar.gz
```

代码本身无需备份，GitHub 仓库就是 source of truth。

### 迁移到另一台机器

```bash
# 旧机器
cd domainsearch-
cp .env .env.backup
docker compose exec yuming-bot tar czf - /data/wechannel > wechannel.tar.gz
# 把这两份文件 scp 到新机器

# 新机器
git clone https://github.com/adminmtan/domainsearch-.git
cd domainsearch-
cp <旧机器的 .env> .
docker compose pull
docker compose up -d
docker compose exec -T yuming-bot tar xzf - < wechannel.tar.gz
# 重启 bot 让它加载
docker compose restart yuming-bot
```

### 完全卸载

```bash
cd domainsearch-
docker compose down -v       # 停 + 删容器 + 删 volume
rm -rf /path/to/domainsearch-  # 删代码目录
docker image rm ghcr.io/adminmtan/yuming:latest ghcr.io/adminmtan/yuming-bot:latest
```

---

## CI 镜像更新机制说明

### 什么时候会自动构建

| 触发条件 | 构建吗 | 推送吗 | tag 列表 |
| --- | --- | --- | --- |
| `main` 分支 push | ✅ | ✅ | `latest`, `main`, `sha-xxxxxxx` |
| 其他分支 push | ✅ | ❌ | 仅 Actions artifact，不入 registry |
| PR | ✅ | ❌ | 同上 |
| 推送 tag `v*.*.*` | ✅ | ✅ | `v1.2.3`, `1.2`, `1`（加上 latest/main/sha） |
| 手动触发（Actions → Run workflow） | ✅ | ✅ | 同 main push |

### 镜像地址

| 镜像 | 地址 | 大小（粗略） |
| --- | --- | --- |
| 主服务（Flask :5001） | `ghcr.io/adminmtan/yuming` | ~200 MB（python:3.12-slim + deps） |
| 微信推送（Node :5002） | `ghcr.io/adminmtan/yuming-bot` | ~80 MB（node:20-alpine + deps） |

两个镜像都构建成 `linux/amd64,linux/arm64` 多架构，NAS 自带 docker 会自动选对应架构的 layer。

### 镜像默认是 latest 还是具体版本

**默认 `docker-compose.yml` 用 `:latest`**——意味着每次 `docker compose pull && up -d` 都会拉到 main 最新构建。

**生产建议用固定 tag**（如 `sha-xxxxxxx`），避免 latest 出问题时被打到生产：

```yaml
services:
  yuming:
    image: ghcr.io/adminmtan/yuming:sha-7fbf52a
  yuming-bot:
    image: ghcr.io/adminmtan/yuming-bot:sha-7fbf52a
```

升级时手动改 tag + `docker compose up -d`。
