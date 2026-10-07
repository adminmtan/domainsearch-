# 智能域名生成工具 实现计划

> **面向 AI 代理的工作者：** 必需子技能：使用 subagent-driven-development（推荐）或 executing-plans 逐任务实现此计划。步骤使用复选框（`- [ ]`）语法来跟踪进度。

**目标：** 构建一个 Web 工具，根据用户输入的描述内容，利用 OpenAI 生成与描述强相关、有故事、有内涵的域名，再通过 dmcheck.app 过滤已注册域名，输出可注册的域名及其推荐理由。

**架构：** Flask 后端 + 单页前端。后端两个核心模块：`generator.py`（OpenAI 生成）、`checker.py`（dmcheck.app 检测）。前端纯静态，OpenAI API Key 存浏览器 localStorage。

**技术栈：** Python 3.10+、Flask 3.0、requests、原生 HTML/CSS/JS（无框架）。

**规格：** `docs/superpowers/specs/2026-10-07-smart-domain-generator-design.md`

---

## 文件结构

| 文件 | 职责 |
|------|------|
| `app.py` | Flask 主服务：路由、参数校验、串联 generator/checker |
| `generator.py` | OpenAI 域名生成器：构造 Prompt、解析 JSON 返回 |
| `checker.py` | dmcheck.app API 客户端：批量查询域名状态 |
| `static/index.html` | 主页面（描述、TLD、长度、数量输入 + 结果区 + 设置按钮） |
| `static/style.css` | 全部样式 |
| `static/app.js` | 前端逻辑（表单、API 调用、卡片渲染、localStorage 设置） |
| `requirements.txt` | Python 依赖 |
| `README.md` | 启动与使用说明 |

---

## 全局约束

- Python ≥ 3.10
- Flask 3.0、openai ≥ 1.0、requests ≥ 2.31
- API Key 仅存浏览器 localStorage，不写入日志或持久化到后端
- 描述长度上限 2000 字符
- 域名主体长度范围 2-20 字符
- TLD 默认使用 dmcheck.app 的全部预置后缀
- 输出数量范围 1-50
- 所有 commit 使用 Conventional Commits（feat/fix/chore/test/docs）
- 后端默认监听 `127.0.0.1:5000`

## 审查重点（Review Focus）

规格隐含但未在测试中显式覆盖的输入/失败模式：

1. **AI 返回非 JSON**（如 ```json 包裹、解释性文字混入）→ 必须 robust 解析，不能让前端拿到 500
2. **生成的域名全部已注册** → 后端必须返回可用数量 < count 时的明确提示，而不是返回空数组
3. **dmcheck.app 接口变更/不可达** → 后端不应让前端挂在 loading，必须在 5 秒内超时并返回可读错误
4. **用户描述为空或仅含空白** → 必须 400 拒绝，不调用 OpenAI（避免无意义扣费）
6. **描述含敏感词/超长** → 后端在请求层做兜底校验，不完全依赖前端

每个审查重点对应测试已加在任务步骤中（任务 4、5、7）。

---

## 任务 1：项目骨架与依赖

**文件：**
- 创建：`requirements.txt`
- 创建：`app.py`（最小 Flask 服务，仅 `/` 路由返回占位文本）
- 创建：`README.md`（启动说明）

- [ ] **步骤 1：编写 `requirements.txt`**

```
Flask==3.0.0
openai>=1.30.0
requests>=2.31.0
pytest>=8.0.0
```

- [ ] **步骤 2：创建最小 Flask 服务 `app.py`**

```python
from flask import Flask

app = Flask(__name__)

@app.route("/")
def index():
    return "ok"
```

- [ ] **步骤 3：本地启动验证**

```bash
cd /Users/mtan/Documents/01_Projects/P_yuming
pip install -r requirements.txt
flask --app flask run --host 127.0.0.1 --port 5000
# 或 python app.py（需在 app.py 加 if __name__ == "__main__": app.run()）
```

预期：浏览器访问 `http://127.0.0.1:5000/` 看到 "ok"

- [ ] **步骤 4：在 `app.py` 添加开发服务器入口**

```python
if __name__ == "__main__":
    app.run(host="127.0.0.1", port=5000, debug=True)
```

- [ ] **步骤 5：创建 `README.md`**

内容：项目简介、依赖安装、`python app.py` 启动、访问地址。

- [ ] **步骤 6：Commit**

```bash
git init  # 若是新仓库
git add requirements.txt app.py README.md
git commit -m "chore: scaffold flask app"
```

---

## 任务 2：域名生成器（generator.py）

**文件：**
- 创建：`generator.py`
- 测试：`tests/test_generator.py`

**接口：**

```python
from typing import TypedDict

class DomainCandidate(TypedDict):
    domain: str       # 不含 TLD，如 "mythforge"
    reason: str       # 推荐理由

class GenerateParams(TypedDict):
    description: str
    min_len: int
    max_len: int
    count: int        # 期望生成的数量（实现内部请求 count * 2 候选）
    api_key: str
    base_url: str     # 默认 "https://api.openai.com/v1"
    model: str        # 默认 "gpt-4o-mini"


def build_prompt(params: GenerateParams) -> str:
    """构造发给 OpenAI 的系统提示词 + 用户提示词，返回完整 messages"""


def parse_response(raw: str) -> list[DomainCandidate]:
    """从 OpenAI 返回的文本中解析 JSON 数组；处理 ```json 包裹和前后杂质"""


class OpenAIGenerator:
    def __init__(self, api_key: str, base_url: str = "https://api.openai.com/v1",
                 model: str = "gpt-4o-mini"): ...
    def generate(self, description: str, min_len: int, max_len: int,
                 count: int) -> list[DomainCandidate]: ...
```

- [ ] **步骤 1：编写失败的测试**

```python
# tests/test_generator.py
from generator import build_prompt, parse_response, OpenAIGenerator

def test_build_prompt_contains_constraints():
    messages = build_prompt({
        "description": "面向开发者的 AI 工具",
        "min_len": 4, "max_len": 10, "count": 5,
        "api_key": "x", "base_url": "y", "model": "z",
    })
    text = " ".join(m["content"] for m in messages)
    assert "面向开发者的 AI 工具" in text
    assert "4" in text and "10" in text
    assert "强相关" in text  # 强相关性是核心要求


def test_parse_response_plain_json():
    raw = '[{"domain":"mythforge","reason":"myth+forge 呼应神话工具"}]'
    result = parse_response(raw)
    assert len(result) == 1
    assert result[0]["domain"] == "mythforge"


def test_parse_response_wrapped_in_code_block():
    raw = '```json\n[{"domain":"a","reason":"b"}]\n```'
    result = parse_response(raw)
    assert result[0]["domain"] == "a"


def test_parse_response_with_surrounding_text():
    raw = '下面是结果：\n[{"domain":"a","reason":"b"}]\n请查收'
    result = parse_response(raw)
    assert result[0]["domain"] == "a"


def test_parse_response_invalid_raises():
    import pytest
    with pytest.raises(ValueError):
        parse_response("not json at all")
```

- [ ] **步骤 2：运行测试验证失败**

```bash
pytest tests/test_generator.py -v
```

预期：FAIL，`generator` 模块不存在

- [ ] **步骤 3：实现 `generator.py`**

- `build_prompt`：返回 `[{"role": "system", ...}, {"role": "user", ...}]`，system 消息强调与用户核心的角色定位与"强相关性"要求，user 消息为模板化的具体需求。
- Prompt 模板要点（来自规格）：
  - 核心要求第一：每个域名必须与用户描述存在明确关联（词义/主题/隐喻）
  - 长度约束 `min_len`-`max_len` 字符
  - 避免无意义字母组合
  - 理由必须含：域名构造拆解 + 与用户描述的关联点 + 寓意解读
  - 严格输出 JSON 数组
- `parse_response`：先剥掉 ```json ... ``` 包裹，再用正则提取第一个 `[...]`，`json.loads`；失败抛 `ValueError`。
- `OpenAIGenerator.generate`：实际请求时 `count * 2`，`temperature=0.8`，`response_format={"type": "json_object"}` 可选；返回 `parse_response` 结果。

- [ ] **步骤 4：运行测试验证通过**

```bash
pytest tests/test_generator.py -v
```

预期：PASS（5 个测试全通过）

- [ ] **步骤 5：Commit**

```bash
git add generator.py tests/test_generator.py
git commit -m "feat(generator): OpenAI domain generator with prompt + parser"
```

---

## 任务 3：域名检测器（checker.py）

**文件：**
- 创建：`checker.py`
- 测试：`tests/test_checker.py`

**接口：**

```python
from typing import Literal
DomainStatus = Literal["available", "registered", "reserved", "unknown"]

def check_domains(domains: list[str], tlds: list[str] | None = None,
                  timeout: float = 5.0) -> dict[str, DomainStatus]:
    """调用 dmcheck.app 批量查询域名状态；返回 {domain: status}
    tlds 为 None 时只查传入的完整域名列表
    超时返回 {"unknown": "unavailable"} 兜底
```

**注意：** 实际 dmcheck.app 的 API 端点、参数格式、响应字段需要在实现时确认（任务中允许使用 `dmcheck.app/api/check` 或 `/api/search` 等）。如果 API 不存在或返回结构不一致，应在实现时记录并使用替代方案（如 RDAP 公共接口或 WHOIS 查询）。

- [ ] **步骤 1：编写失败的测试**

```python
# tests/test_checker.py
from unittest.mock import patch, MagicMock
from checker import check_domains

def test_check_domains_parses_available():
    fake_resp = MagicMock()
    fake_resp.json.return_value = {
        "results": [{"domain": "foo.com", "status": "available"}]
    }
    fake_resp.raise_for_status.return_value = None
    with patch("checker.requests.get", return_value=fake_resp):
        result = check_domains(["foo.com"])
    assert result == {"foo.com": "available"}


def test_check_domains_timeout_returns_unknown():
    import requests
    with patch("checker.requests.get", side_effect=requests.Timeout):
        result = check_domains(["foo.com"], timeout=0.1)
    assert result == {"foo.com": "unknown"}


def test_check_domains_dedupes_input():
    fake_resp = MagicMock()
    fake_resp.json.return_value = {"results": []}
    fake_resp.raise_for_status.return_value = None
    with patch("checker.requests.get", return_value=fake_resp) as mock_get:
        check_domains(["foo.com", "foo.com", "bar.com"])
        # 验证只发了一次请求且去重后的域名
        called_args = mock_get.call_args
        assert "foo.com" in str(called_args)
        assert called_args.kwargs.get("timeout") == 5.0 or (
            len(called_args.args) > 1 and called_args.args[1] == 5.0
        )
```

- [ ] **步骤 2：运行测试验证失败**

```bash
pytest tests/test_checker.py -v
```

预期：FAIL，`checker` 模块不存在

- [ ] **步骤 3：实现 `checker.py`**

- 对传入域名先去重
- 使用 `requests.get(url, params={...}, timeout=timeout)`
- 解析 JSON，遍历 results 列表，构造返回值
- 网络异常/超时：`except (requests.Timeout, requests.RequestException)` → 返回 `{domain: "unknown"}`
- URL 端点：默认 `https://dmcheck.app/api/check`；若实现时确认不同，修改此处并更新测试

- [ ] **步骤 4：运行测试验证通过**

```bash
pytest tests/test_checker.py -v
```

预期：PASS（3 个测试全通过）

- [ ] **步骤 5：Commit**

```bash
git add checker.py tests/test_checker.py
git commit -m "feat(checker): dmcheck.app client with timeout fallback"
```

---

## 任务 4：Flask 后端 `/api/generate` 路由

**文件：**
- 修改：`app.py`
- 测试：`tests/test_app.py`

**接口：**

```python
@app.route("/api/generate", methods=["POST"])
def api_generate():
    """请求体: {description, min_len, max_len, tlds, count, api_key, base_url?, model?}
    响应: {success, domains, stats} 或 {success: false, error}
```

**关键约束：**
- `description` 为空或仅空白 → 400
- `min_len >= max_len` → 400
- `count < 1 or count > 50` → 400
- 内部请求 OpenAI 时生成 `count * 2` 个候选，过滤已注册/保留后取前 count 个

- [ ] **步骤 1：编写失败的测试**

```python
# tests/test_app.py
import json
from app import app

def test_generate_rejects_empty_description():
    client = app.test_client()
    resp = client.post("/api/generate", json={
        "description": "   ",
        "min_len": 4, "max_len": 10, "tlds": ["com"], "count": 5,
        "api_key": "sk-test",
    })
    assert resp.status_code == 400
    assert resp.json["success"] is False


def test_generate_rejects_invalid_length_range():
    client = app.test_client()
    resp = client.post("/api/generate", json={
        "description": "x",
        "min_len": 10, "max_len": 5, "tlds": ["com"], "count": 5,
        "api_key": "sk-test",
    })
    assert resp.status_code == 400


def test_generate_rejects_count_out_of_range():
    client = app.test_client()
    resp = client.post("/api/generate", json={
        "description": "x",
        "min_len": 4, "max_len": 10, "tlds": ["com"], "count": 100,
        "api_key": "sk-test",
    })
    assert resp.status_code == 400
```

- [ ] **步骤 2：运行测试验证失败**

```bash
pytest tests/test_app.py -v
```

预期：FAIL，`/api/generate` 路由不存在

- [ ] **步骤 3：在 `app.py` 中实现 `/api/generate`**

- 解析 JSON 字段，做参数校验（描述非空、长度范围合法、数量范围 1-50）
- 构造 `OpenAIGenerator`，调用 `.generate(description, min_len, max_len, count * 2)`
- 为每个候选拼接所有 tlds 组成完整域名（如 `mythforge.com`、`mythforge.io`）
- 调用 `checker.check_domains(full_domains, timeout=5.0)`
- 过滤 `available` 状态，附上 reason，取前 `count` 个
- 若 `available` 数量 < `count`，仍返回（前端展示"仅找到 N 个可用"提示）
- 异常处理：try/except，捕获 `ValueError`（解析错误）、`openai.OpenAIError`、`requests.RequestException`，返回 `{success: false, error: str(e)}` 和 500

- [ ] **步骤 4：运行测试验证通过**

```bash
pytest tests/test_app.py -v
```

预期：PASS（3 个测试全通过）

- [ ] **步骤 5：Commit**

```bash
git add app.py tests/test_app.py
git commit -m "feat(api): /api/generate route with validation and error handling"
```

---

## 任务 5：TLD 列表端点 `/api/tlds`

**文件：**
- 修改：`app.py`
- 测试：`tests/test_app.py`（追加）

**接口：**

```python
@app.route("/api/tlds", methods=["GET"])
def api_tlds():
    """返回预置 TLD 列表
    响应: {tlds: ["com", "io", ...]}
```

- [ ] **步骤 1：编写失败的测试**

```python
# 在 tests/test_app.py 追加
def test_tlds_returns_list():
    client = app.test_client()
    resp = client.get("/api/tlds")
    assert resp.status_code == 200
    assert "tlds" in resp.json
    assert isinstance(resp.json["tlds"], list)
    assert "com" in resp.json["tlds"]
    assert len(resp.json["tlds"]) >= 10
```

- [ ] **步骤 2：运行测试验证失败**

```bash
pytest tests/test_app.py::test_tlds_returns_list -v
```

预期：FAIL，`/api/tlds` 路由不存在

- [ ] **步骤 3：在 `app.py` 中实现 `/api/tlds`**

- 维护一个预置 TLD 列表常量 `DEFAULT_TLDS`（至少包含 `com io ai dev app net org co me xyz tech`）
- 端点返回 `{tlds: DEFAULT_TLDS}`
- 注：本计划不调用 dmcheck.app 动态获取（避免引入外部依赖到启动路径），使用预置即可

- [ ] **步骤 4：运行测试验证通过**

```bash
pytest tests/test_app.py -v
```

预期：PASS

- [ ] **步骤 5：Commit**

```bash
git add app.py tests/test_app.py
git commit -m "feat(api): /api/tlds endpoint with preset list"
```

---

## 任务 6：前端骨架 `static/index.html`

**文件：**
- 创建：`static/index.html`
- 创建：`static/style.css`
- 创建：`static/app.js`

- [ ] **步骤 1：编写 `static/index.html`**

页面骨架：

```html
<!DOCTYPE html>
<html lang="zh-CN">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>智能域名生成器</title>
  <link rel="stylesheet" href="/static/style.css">
</head>
<body>
  <header>
    <h1>智能域名生成器</h1>
    <button id="settings-btn" aria-label="设置">⚙ 设置</button>
  </header>

  <main>
    <section class="form-section">
      <label for="description">描述内容</label>
      <textarea id="description" rows="4" maxlength="2000"
                placeholder="例如：一个面向开发者的 AI 工具平台..."></textarea>

      <label>TLD 后缀</label>
      <div id="tld-list" class="tld-list"></div>

      <div class="config-row">
        <label>最小长度 <input type="number" id="min-len" value="4" min="2" max="20"></label>
        <label>最大长度 <input type="number" id="max-len" value="12" min="2" max="20"></label>
        <label>输出数量 <input type="number" id="count" value="10" min="1" max="50"></label>
      </div>

      <button id="generate-btn">生成域名</button>
      <div id="status"></div>
    </section>

    <section id="results" class="results-section"></section>
  </main>

  <!-- 设置弹窗（默认隐藏） -->
  <div id="settings-modal" class="modal hidden" role="dialog">
    <div class="modal-content">
      <h2>设置</h2>
      <label>OpenAI API Key <input type="password" id="api-key"></label>
      <label>Base URL <input type="text" id="base-url" value="https://api.openai.com/v1"></label>
      <label>Model <input type="text" id="model" value="gpt-4o-mini"></label>
      <div class="modal-actions">
        <button id="settings-cancel">取消</button>
        <button id="settings-save">保存</button>
      </div>
    </div>
  </div>

  <script src="/static/app.js"></script>
</body>
</html>
```

- [ ] **步骤 2：编写 `static/style.css`**

要点：
- reset + system font
- 居中布局，max-width 800px
- 卡片阴影 + 圆角 8px
- 域名卡片：域名大字号（24px+）+ 可注册绿色徽章 + 理由文字灰色
- modal 默认隐藏（`.hidden { display: none }`），覆盖层半透明黑色
- 响应式：移动端表单纵向堆叠

- [ ] **步骤 3：编写 `static/app.js`**

实现以下功能：

```javascript
// 常量
const STORAGE_KEY = "yuming_config";

// DOM 元素引用
const $description = document.getElementById("description");
const $tldList = document.getElementById("tld-list");
const $minLen = document.getElementById("min-len");
const $maxLen = document.getElementById("max-len");
const $count = document.getElementById("count");
const $generateBtn = document.getElementById("generate-btn");
const $status = document.getElementById("status");
const $results = document.getElementById("results");
const $settingsBtn = document.getElementById("settings-btn");
const $settingsModal = document.getElementById("settings-modal");
const $settingsSave = document.getElementById("settings-save");
const $settingsCancel = document.getElementById("settings-cancel");
const $apiKey = document.getElementById("api-key");
const $baseUrl = document.getElementById("base-url");
const $model = document.getElementById("model");

// 加载 TLD 列表
async function loadTlds() { ... }

// 加载设置
function loadConfig() { ... }
function saveConfig() { ... }

// 调用生成 API
async function generate() { ... }

// 渲染结果卡片
function renderDomains(domains, stats) { ... }

// 事件绑定
// - $settingsBtn click: 显示 modal
// - $settingsCancel click: 隐藏 modal
// - $settingsSave click: 保存配置 + 隐藏
// - 生成按钮 click: 调用 generate()

// 初始化
loadTlds();
```

**生成按钮处理逻辑要点：**
1. 检查 `description.value.trim()` 非空 → 否则提示
2. 检查 localStorage 已有 `api_key` → 否则提示打开设置
3. 收集所有选中 TLD
4. 校验 `min_len <= max_len` 且范围合法
5. 禁用按钮 + 显示 "生成中..."
6. fetch POST `/api/generate`
7. 渲染 `result.domains`，若 `stats.available < count` 显示提示
8. 异常：恢复按钮 + 显示错误信息

- [ ] **步骤 4：本地启动验证**

```bash
python app.py
# 浏览器访问 http://127.0.0.1:5000/
```

手动检查项：
- 页面渲染正常
- TLD 列表从后端加载并显示
- 设置按钮打开/关闭 modal
- localStorage 保存设置后刷新页面仍保留

- [ ] **步骤 5：Commit**

```bash
git add static/index.html static/style.css static/app.js
git commit -m "feat(ui): main page with form, settings modal, results area"
```

---

## 任务 7：端到端验证与文档

**文件：**
- 修改：`README.md`

- [ ] **步骤 1：手动跑通完整流程**

1. 启动后端
2. 浏览器打开
3. 打开设置，输入真实 OpenAI API Key，保存
4. 描述输入："一个面向开发者的 AI 工具平台，专注于代码生成"
5. TLD 选 `com io ai dev`
6. 长度 4-12，数量 10
7. 点击生成，等待结果
8. 确认：
   - 域名与描述有可识别的关联
   - 已注册域名被过滤
   - 每个域名有推荐理由
   - 卡片显示可注册状态

- [ ] **步骤 2：跑完整测试**

```bash
pytest tests/ -v
```

预期：所有测试 PASS

- [ ] **步骤 3：补充 `README.md`**

内容：
- 项目简介
- 截图占位
- 安装：`pip install -r requirements.txt`
- 启动：`python app.py`
- 使用步骤：打开 → 设置 API Key → 填写表单 → 生成
- 注意事项：API Key 仅本地存储
- 已知限制：本计划内未做生产部署、限流、用户系统

- [ ] **步骤 4：Commit**

```bash
git add README.md
git commit -m "docs: usage instructions and limitations"
```

---

## 自检结果

**1. 规格覆盖度：**

| 规格章节 | 任务 |
|---------|------|
| 主界面 / 设置弹窗 / 域名卡片 | 任务 6 |
| generator.py + Prompt 模板 | 任务 2 |
| checker.py + dmcheck.app | 任务 3 |
| /api/generate + /api/tlds | 任务 4、5 |
| 数据流 | 任务 4 |
| 错误处理（API Key 未配置、rate limit、JSON 解析、dmcheck 不可达、可用数 < count） | 任务 4 |
| 安全（API Key 仅前端） | 任务 6 |
| 测试策略 | 任务 2、3、4、5、7 |

**2. 步骤扫描：** 每个步骤只有一个明确动作；代码块只含签名/接口/测试，不重复实现。

**3. 类型一致性：**
- `DomainCandidate` 在任务 2 定义、任务 4 消费，一致
- `check_domains` 返回 `dict[str, DomainStatus]`，任务 4 消费时按 `available` 过滤
- `api_generate` 请求/响应字段与规格一致

**4. 审查重点：**
1. AI 返回非 JSON → 任务 2 `test_parse_response_*`
2. 全部已注册 → 任务 4 处理逻辑（过滤后 available < count 仍响应）+ 任务 6 前端展示
3. dmcheck 不可达 → 任务 3 `test_check_domains_timeout_returns_unknown`
4. 描述为空 → 任务 4 `test_generate_rejects_empty_description`
5. 长度/数量越界 → 任务 4 `test_generate_rejects_*`

**5. 比例：** 计划 ~280 行 / 规格 ~360 行，比例合理，未出现代码抄本。