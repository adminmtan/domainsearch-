# 智能域名生成器

根据用户输入的项目描述，利用 OpenAI 大模型产出**与描述内容强相关**、有故事、有内涵的域名，并通过 [dmcheck.app](https://dmcheck.app) 自动检测可注册性，最终输出可注册的域名及其推荐理由。

> 每个域名都必须与用户描述存在明确关联（词义 / 主题 / 隐喻），推荐理由需明确说明该关联点。

## 功能特性

- AI 生成与描述强相关的有故事域名
- 自动过滤已注册/保留域名
- 灵活配置 TLD 后缀、长度范围
- API Key 仅存浏览器 localStorage，不上传服务器
- 单页静态前端 + Flask 后端，零数据库

## 安装与启动

要求 Python 3.10+。**强烈推荐使用项目自带的虚拟环境**（避免 macOS 13+ 的 PEP 668 externally-managed 报错）。

### 方法一：一键启动（推荐）

```bash
cd /Users/mtan/Documents/01_Projects/P_yuming
./run.sh
```

脚本会自动：
1. 在项目根目录创建 `.venv/` 虚拟环境
2. 安装/更新 `requirements.txt` 里的依赖
3. 检测端口（默认 `5001`）是否被占用
4. 启动 Flask，访问 `http://127.0.0.1:5001/`

> 为什么默认 5001 而不是 5000？macOS 上 `ControlCenter` 系统服务默认占着 5000 端口（用于 AirPlay 接收），直接 `python app.py` 会失败。可用 `./run.sh --port 5050` 自定义。

### 方法二：手动 venv

```bash
cd /Users/mtan/Documents/01_Projects/P_yuming
python3 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
python app.py
```

### 方法三：Homebrew Python 全局安装（不推荐）

如果你确定要装到系统 Python（**会污染 Homebrew Python**，不推荐）：

```bash
python3 -m pip install -r requirements.txt --break-system-packages
python3 app.py
```

> 为什么不用 `pip install` 直接装？macOS 13+ / Homebrew Python 3.12+ 默认开启 PEP 668 保护，会报 `error: externally-managed-environment`。venv 是官方推荐的绕开方式。

## 使用步骤

1. 点击右上角「⚙ 设置」打开配置
2. 填入 API Key（默认 Base URL: `https://api.openai.com/v1`，Model: `gpt-4o-mini`）
3. 保存
4. 在主界面输入项目描述，选择 TLD 后缀，调整长度与数量
5. 点击「生成域名」等待结果

## 项目结构

```
.
├── app.py              # Flask 主服务（路由、参数校验）
├── generator.py        # OpenAI 域名生成器（Prompt + JSON 解析）
├── checker.py          # dmcheck.app API 客户端（含超时降级）
├── static/             # 前端（index.html / style.css / app.js）
├── tests/              # pytest 测试
├── requirements.txt
└── docs/
    └── superpowers/
        ├── specs/2026-10-07-smart-domain-generator-design.md
        └── plans/2026-10-07-smart-domain-generator.md
```

## 运行测试

```bash
pytest tests/ -v
```

## NAS / 家庭服务器部署（Docker）

镜像已自动构建并推送到 GitHub Container Registry：

| 镜像 | 地址 |
| --- | --- |
| 主服务（Flask :5001） | `ghcr.io/adminmtan/yuming:latest` |
| 微信推送服务（Node :5002） | `ghcr.io/adminmtan/yuming-bot:latest` |

### 拉取 + 启动

```bash
# 1) 克隆本仓库（或仅下载 docker-compose.yml + .env.example）
git clone https://github.com/adminmtan/domainsearch-.git
cd domainsearch-

# 2) 填入真实环境变量
cp .env.example .env
$EDITOR .env   # 必填 OPENAI_API_KEY

# 3) 拉取镜像并启动
docker compose pull
docker compose up -d

# 4) 查看状态
docker compose ps
docker compose logs -f yuming
```

访问 `http://<NAS-IP>:5001/` 即可。

### 镜像标签说明

每次 push 到 `main` 都会自动构建并打以下标签：

- `latest` — main 分支最新构建
- `main` — main 分支的 ref 标签
- `sha-xxxxxxx` — 提交 hash 短码
- `v1.2.3` / `1.2` — 推送 tag（`git tag v1.2.3 && git push --tags`）时生成

固定到某个版本：

```bash
# 拉取指定 commit
docker pull ghcr.io/adminmtan/yuming:sha-283d89e

# 或在 docker-compose.yml 改 image: ...:sha-283d89e 后 docker compose up -d
```

### 手动触发 CI 重新构建

GitHub 仓库 → Actions → CI → Run workflow，可不依赖 push 触发一次构建。

### 平台支持

镜像以 `linux/amd64,linux/arm64` 多架构构建，主流 NAS（群晖/威联通/极空间 x86 和 arm64 设备）均可直接拉取。

## 已知限制

- 未做生产部署（仅 Flask 内置开发服务器）
- 未做限流、用户系统、访问控制
- dmcheck.app 实际 API 端点需实现时确认（参见 `checker.py` 顶部的 `BASE_URL`）
- 未做前端单元测试（仅做后端测试 + smoke test）
- AI 模型输出非 100% 可控，可能偶发格式异常（`parse_response` 会鲁棒处理）

## 安全

- API Key 仅写入浏览器本地存储（`localStorage["yuming_config"]`），不会持久化到后端
- 后端只做透传和参数校验，不记录 API Key
- 描述长度上限 2000 字符（前端 `maxlength` + 后端校验双重保护）