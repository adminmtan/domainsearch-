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