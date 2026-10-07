# 智能域名生成工具 - 设计规格

**日期**：2026-10-07
**作者**：Cursor Assistant
**状态**：待批准

## 概述

构建一个 Web 工具，根据用户输入的**描述内容**、利用 AI 大模型（OpenAI）生成**与描述内容强相关**、且有寓意/故事/内涵的域名，并通过 dmcheck.app 自动检测可注册性，最终输出可注册的域名及其推荐理由。

**核心要求**：每个域名必须与用户输入的描述内容存在语义关联，而不仅仅是"有寓意"或"好听"。推荐理由必须明确说明域名与用户描述的关联点。

## 目标用户

- 个人开发者：基于自己的项目想法，寻找有意义的项目域名
- 创业者：为新产品/品牌寻找能表达产品定位的域名
- 内容创作者：基于内容主题，寻找符合调性的域名

**共同特征**：用户的输入描述将作为 AI 创意的唯一素材，每个域名都应能让用户感到"这就是我描述的那个东西"。

## 成功标准

1. 用户输入描述后，能在 30 秒内获得符合要求的域名列表
2. **生成的每个域名必须与用户描述内容存在明确关联**（词义层面、主题层面或隐喻层面）
3. 输出的所有域名均经过实际注册检测，过滤已注册/保留域名
4. 每个域名都附有清晰的推荐理由，**理由中需说明与描述内容的关联点**
5. 用户可灵活配置 TLD 后缀、长度、数量等参数

## 技术架构

```
┌─────────────────────────────────────────────────────────────┐
│                       浏览器前端                              │
│  ┌──────────────────────────────────────────────────────┐  │
│  │ 主界面：描述输入 + TLD选择 + 长度/数量配置 + 生成按钮  │  │
│  │ 设置弹窗：OpenAI API Key + Base URL + Model 配置     │  │
│  │ 结果展示：域名卡片（域名 + 推荐理由 + 可注册标识）     │  │
│  └──────────────────────────────────────────────────────┘  │
└─────────────────────────┬───────────────────────────────────┘
                          │ HTTP/JSON
                          ▼
┌─────────────────────────────────────────────────────────────┐
│                   Flask 后端服务                             │
│  ┌──────────────┐    ┌──────────────┐    ┌────────────────┐  │
│  │ AI 生成器     │───▶│ 域名检测器   │───▶│ 结果聚合器     │  │
│  │ (OpenAI API) │    │ (dmcheck.app)│    │ (过滤+理由)    │  │
│  └──────────────┘    └──────────────┘    └────────────────┘  │
└─────────────────────────────────────────────────────────────┘
                          │
                          ▼
              ┌──────────────────────┐
              │  OpenAI API          │
              │  dmcheck.app API     │
              └──────────────────────┘
```

## 组件设计

### 1. 前端组件

#### 1.1 主界面（`static/index.html`）

| 区域 | 组件 | 说明 |
|------|------|------|
| 顶部 | 标题 + 设置按钮 | 工具名称 + 齿轮图标打开设置 |
| 输入区 | 描述 textarea | 多行文本输入，支持 500-2000 字符 |
| 配置区 | TLD 多选 | 默认全部，选中显示已选后缀 |
| 配置区 | 长度范围 | min/max 两个数字输入 |
| 配置区 | 输出数量 | 单个数字输入，默认 10 |
| 操作区 | 生成按钮 | 触发生成请求 |
| 结果区 | 域名卡片列表 | 每个卡片展示域名 + 理由 + 状态 |

#### 1.2 设置弹窗

| 字段 | 类型 | 说明 |
|------|------|------|
| OpenAI API Key | password 输入 | 必填 |
| Base URL | text 输入 | 默认 `https://api.openai.com/v1` |
| Model | select | 默认 `gpt-4o-mini` |
| 取消/保存 | 按钮 | 保存到 localStorage |

#### 1.3 域名卡片

```
┌────────────────────────────────────────────────────────┐
│ mythforge.com                       [✓ 可注册]        │
│                                                        │
│ 推荐理由：                                              │
│ myth(神话) + forge(锻造) 组合                          │
│ 呼应描述中"打造开发者神话工具"的核心诉求                │
│ forge 暗示工匠精神，myth 暗示传奇色彩                  │
│                                                        │
│ 长度：9 | TLD：com                                     │
└────────────────────────────────────────────────────────┘
```

### 2. 后端组件

#### 2.1 AI 生成器（`generator.py`）

```python
class DomainGenerator:
    def __init__(self, api_key: str, base_url: str, model: str):
        self.client = OpenAI(api_key=api_key, base_url=base_url)
        self.model = model

    def generate(self, description: str, min_len: int, max_len: int,
                 tlds: list[str], count: int) -> list[dict]:
        """生成域名候选 + 推荐理由"""
        # 返回格式：[{"domain": "xxx", "reason": "xxx", "tld": "com"}, ...]
```

**Prompt 模板**：

```
你是一位顶尖的域名策划大师，擅长从用户描述中提炼核心概念，
创造与品牌内容高度相关、富有故事感和文化内涵的域名。

任务：根据用户描述，生成与描述内容强相关的域名。

核心要求（必须严格遵守）：
1. 【强相关性】每个域名必须与用户描述存在明确的关联：
   - 词义关联：域名词汇与描述关键词直接对应
   - 主题关联：域名传达的主题与描述主题一致
   - 隐喻关联：通过隐喻/象征表达描述的核心精神
2. 【有故事感】域名应蕴含背景故事，让人产生联想
3. 【有内涵】避免浅显直白的拼凑，需有文化/语义深度
4. 域名主体长度：{min_len}-{max_len} 个字符（不含后缀）
6. 避免无意义字母组合（如 xqzk、abcmn）
7. 避免与描述完全无关的通用词汇（如 search/descart/descart/descart 字面拼凑）
8. 严格输出 JSON 数组，不要包含任何其他文字

推荐理由必须包含：
- 域名构造拆解（词源、组合方式）
- 与用户描述内容的关联点（关键！）
- 寓意解读（故事感、内涵）

用户描述：
{description}

请输出 {count} 个域名，格式：
[{{"domain": "mythforge", "reason": "由 myth(神话) + forge(锻造) 组合而成，呼应描述中'打造开发者神话工具'的核心诉求；forge 暗示工匠精神，myth 暗示产品的传奇色彩..."}}]
```

#### 2.2 域名检测器（`checker.py`）

```python
class DomainChecker:
    BASE_URL = "https://dmcheck.app"

    def check(self, domains: list[str], tlds: list[str]) -> list[dict]:
        """批量检测域名可用性"""
        # 调用 dmcheck.app API，返回每个域名的状态
        # 状态：available | reserved | registered
```

**API 调用**（基于 dmcheck.app 公开接口）：

```
GET https://dmcheck.app/api/search?q=keyword&tlds=com,io,ai
```

返回格式：
```json
{
  "results": [
    {"domain": "mythforge.com", "status": "available"},
    {"domain": "mythforge.io", "status": "registered"}
  ]
}
```

> 注：实际 API 端点需要实现时根据 dmcheck.app 文档确认；若不可用则考虑自建或使用替代方案。

#### 2.3 结果聚合器（`app.py`）

```python
@app.route('/api/generate', methods=['POST'])
def generate():
    data = request.json
    # 1. 调用 AI 生成器，生成 2x count 个候选（预留过滤空间）
    # 2. 调用域名检测器，过滤已注册/保留
    # 3. 截取前 count 个
    # 4. 返回结果
```

## 数据流

```
1. 用户填写表单，点击"生成"
       │
       ▼
2. 前端发送 POST /api/generate
   {description, min_len, max_len, tlds, count, api_key, base_url, model}
       │
       ▼
3. 后端 generator.py 调用 OpenAI
   获取 2×count 个候选域名 + 理由
       │
       ▼
4. 后端 checker.py 调用 dmcheck.app
   批量检测所有候选域名的状态
       │
       ▼
5. 后端过滤：保留 status=available 的域名
       │
       ▼
6. 后端截取前 count 个，返回给前端
       │
       ▼
7. 前端渲染域名卡片列表
```

## API 规格

### POST /api/generate

**请求体**：

```json
{
  "description": "一个面向开发者的 AI 工具平台，专注于代码生成",
  "min_len": 4,
  "max_len": 12,
  "tlds": ["com", "io", "ai", "dev"],
  "count": 10,
  "api_key": "sk-xxx",
  "base_url": "https://api.openai.com/v1",
  "model": "gpt-4o-mini"
}
```

**响应体（成功）**：

```json
{
  "success": true,
  "domains": [
    {
      "domain": "mythforge.com",
      "reason": "由 myth(神话) + forge(锻造) 组合而成，呼应用户描述中'打造开发者神话工具'的核心诉求；forge 暗示工匠精神，myth 暗示产品的传奇色彩，整体表达'锻造开发者神话'的品牌愿景。",
      "length": 9,
      "tld": "com",
      "status": "available"
    }
  ],
  "stats": {
    "generated": 20,
    "available": 8,
    "registered": 12
  }
}
```

**响应体（失败）**：

```json
{
  "success": false,
  "error": "OpenAI API 调用失败：rate limit exceeded"
}
```

### GET /api/tlds

返回可用 TLD 列表（默认调用 dmcheck.app 获取，或使用预置列表）

```json
{
  "tlds": ["com", "io", "ai", "dev", ...]
}
```

## 错误处理

| 场景 | 处理 |
|------|------|
| API Key 未配置 | 前端提示打开设置 |
| OpenAI rate limit | 返回 429，提示稍后重试 |
| OpenAI 返回非 JSON | 重试一次，仍失败则报错 |
| dmcheck.app 不可达 | 返回错误，提示稍后重试 |
| 生成的域名全部已注册 | 返回可用数量 < count，建议用户调整描述 |
| TLD 列表为空 | 使用 dmcheck 默认全部 TLD |

## 安全考虑

1. **API Key 存储**：仅存浏览器 localStorage，不发送到日志
2. **输入验证**：后端验证 description 长度（≤ 2000 字符）
3. **输出过滤**：对 AI 生成内容做基本过滤，避免恶意域名
4. **限流**：后端可加简单的 IP 限流（可选）

## 测试策略

| 测试 | 方法 | 通过标准 |
|------|------|----------|
| AI 生成测试 | 提供描述，调用生成器 | 返回有效 JSON，域名符合长度 |
| **相关性测试** | 人工评估生成的域名 | 每个域名都能看出与描述的关联 |
| 域名检测测试 | 输入已知域名 | 返回正确状态 |
| 端到端测试 | 完整流程跑通 | 前端显示正确结果 |
| 错误处理测试 | 错误 API Key | 返回友好提示 |

## 相关性评判标准（实现时校验）

实现阶段需通过以下任一方式验证相关性：

1. **关键词命中**：域名词汇命中描述中的关键词或同义词
2. **语义相似度**：使用 embedding 模型计算域名与描述的相似度，阈值 ≥ 0.5
3. **人工抽检**：随机抽 5 个生成结果，确认每个域名都能用一句话解释"为什么这个域名适合描述的内容"

## 文件结构

```
P_yuming/
├── app.py              # Flask 主服务
├── generator.py        # OpenAI 域名生成器
├── checker.py          # dmcheck.app API 调用
├── static/
│   ├── index.html      # 主页面
│   ├── style.css       # 样式
│   └── app.js          # 前端逻辑
├── requirements.txt    # Python 依赖
├── docs/
│   └── superpowers/
│       └── specs/
│           └── 2026-10-07-smart-domain-generator-design.md
└── README.md           # 使用说明
```

## 依赖

```
Flask==3.0.0
openai==1.30.0
requests==2.31.0
```

## 后续扩展（不在本期范围）

- 域名收藏/导出功能
- 历史记录
- 多语言支持
- 批量 WHOIS 详情展示
- 注册商跳转链接

---

## 规格自检

1. **占位符扫描**：无 TODO/待定项
2. **内部一致性**：架构图、数据流、API 规格一致
3. **范围检查**：聚焦一个工具，可用一个实现计划覆盖
4. **模糊性检查**：dmcheck.app API 实际端点实现时确认