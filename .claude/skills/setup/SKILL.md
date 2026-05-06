---
name: setup
description: Use when the user wants to install, configure, diagnose, or troubleshoot ScholarAIO, including setup check, dependency status, API keys, and bilingual setup flow.
---
# Setup / 环境配置

当用户需要配置、安装、初始化 ScholarAIO 时，按以下流程操作：

## 1. 诊断当前状态

```bash
scholaraio setup check --lang zh
```

阅读输出，了解哪些组件已就绪、哪些缺失。
如果用户明确是在让 agent 代为配置，而不是自己逐步操作：
- 默认先跑 `scholaraio setup check --lang zh`
- 优先利用检查输出中的错误说明和建议链接，直接继续下一步配置
- 只有在会影响后续决策时，才回头问用户一个关键问题
- 对失败项要用“现状 + 原因 + 建议动作”的方式转述，不要只说“没装”或“不可达”

## 1.5 核心配置 vs 附加配置

默认把 setup 分成两层：

- **核心配置**：依赖、`config.yaml`、LLM key、PDF 解析器选择、MinerU token、`contact_email`
- **附加配置**：`Semantic Scholar API key`、`Zotero API key`、非默认 LLM backend / base_url 等按需项目

执行顺序要求：

1. 先完成核心配置
2. 再明确告诉用户“还有一些附加配置，可提升特定能力，要不要继续配置”
3. 只有用户表示需要相关能力时，才继续展开附加配置

对每个附加项，agent 必须按同一模板说明：

- **用途**：它解决什么问题
- **何时需要**：哪些用户才值得配
- **做法**：写到哪里、命令或字段是什么
- **开销**：免费 / 通常单独计费 / 取决于第三方政策

## 2. 根据缺失项引导用户

### 依赖缺失
- 告诉用户缺少哪些依赖，解释每组依赖的用途：
  - `embed`: 语义向量检索（Qwen3 嵌入模型）
  - `topics`: BERTopic 主题建模
  - `import`: Endnote / Zotero 导入
  - `Graphviz dot`: `diagram --format svg` 的 DOT→SVG 渲染后端；Linux 可用 `sudo apt-get install graphviz`
  - `Inkscape`: Beamer `\includesvg` 插入 SVG 时需要；Linux 可用 `sudo apt-get install inkscape`
  - `full`: 全部功能
- 运行 `pip install -e ".[full]"` 或按需安装

### config.yaml 缺失
- 运行 `scholaraio setup` 交互式向导自动创建
- 或者直接帮用户创建（默认配置即可）

### API key 未配置
- **LLM key**（DeepSeek / OpenAI / Anthropic / Google）：问用户是否有。没有也能用，但元数据提取降级为纯正则、enrich 不可用。要明确说明：**这通常由所选提供商单独计费，不要默认认为 coding agent 订阅会自动覆盖 ScholarAIO 的 API 调用**
- **PDF 解析器选择**：先问用户想用 `MinerU` 还是 `Docling`
- 如果用户已经明确知道要用哪个解析器，**不要替用户改主意**，直接按用户选择继续配置
- 如果用户不知道选哪个：
  - 测试本地 `MinerU` 服务、`mineru-open-api`、MinerU token 状态，以及 `https://huggingface.co` 可达性
  - **只要网络能跑通 MinerU 路径，就默认优先推荐 `MinerU`**；这里的“MinerU 路径可走”包括：本地服务可达，或 `mineru-open-api` 已安装且可继续走免费 token 的云端路径
  - **次优先才是询问用户是否打算自行本地部署 MinerU**；不要先问“要不要本地部署”再决定推荐谁
  - 仅当 MinerU 本地服务不可达，且 `mineru-open-api` / 免费 token 云路径也走不通时，才改为优先建议 `Docling`
  - 推荐时要明确说明：这是建议，不是替用户做决定；如果用户已有偏好，以用户选择为准
  - **必须把检测结果原样转述给用户**，至少包括：
    - 本地 MinerU 服务是否可达
    - `mineru-open-api` 是否存在
    - 是否检测到现有 MinerU token
    - Hugging Face 是否可达
- **MinerU token**：仅在用户选择 `MinerU` 云端方案时提示。要明确说明：`MinerU token 是免费的，只需要注册并申请`；优先使用 `MINERU_TOKEN`，`MINERU_API_KEY` 只保留兼容
- **Contact email**：免费；用于 Crossref polite pool，加快 API 响应，可选但推荐
- 将密钥写入 `config.local.yaml`（不进 git）

### 附加配置如何问

完成核心配置后，再问一次：

- `Semantic Scholar API key`
  - 用途：用于 Semantic Scholar 认证访问；官方说明是“大多数端点可匿名访问，但部分端点需要 key”
  - 何时需要：用户会频繁做 citation/refetch，或后续需要依赖认证端点时
  - 做法：写入 `ingest.s2_api_key` 或环境变量 `S2_API_KEY`
  - 开销：**按第三方政策**；不要擅自承诺免费或收费
- `Zotero API key`
  - 用途：走 Zotero Web API 导入
  - 何时需要：用户明确要用 `import-zotero` 的 Web API 路径，而不是本地 `zotero.sqlite`
  - 补充说明：Zotero 官方允许对**公开库**做匿名只读访问，但 ScholarAIO 当前的 Web API 导入路径按“提供 key”设计；如果用户不想配 key，优先建议本地 `zotero.sqlite` 导入
  - 做法：写入 `zotero.api_key` 或环境变量 `ZOTERO_API_KEY`
  - 开销：**按第三方政策**
- 自定义 LLM backend / model / base_url
  - 用途：切换到 Claude / Gemini / Ollama / 自建 OpenAI-compatible 服务
  - 何时需要：用户明确不想用默认 DeepSeek，或已有自己的兼容后端
  - 做法：修改 `config.yaml` 的 `llm.backend / model / base_url`
  - 开销：**取决于所选提供商**

### MinerU 高级字段约束
- 对用户暴露时，默认坚持“能不改就不改”，优先开箱即用
- `mineru_model_version_cloud`
  - ScholarAIO 当前是 PDF 解析场景，云端只建议 `pipeline` 或 `vlm`
  - 不要引导用户设置 `MinerU-HTML`；那是 HTML 解析专用，不是 PDF 默认路径
- `mineru_parse_method`
  - 对云端精准解析 API，不存在通用的 `parse_method` 请求字段
  - ScholarAIO 只在用户明确要求 `ocr` 时映射为官方 `file.is_ocr=true`
  - `auto` / `txt` 默认都按“不强制 OCR”处理，不要过度解释成不同云端模式
- `mineru_enable_formula` / `mineru_enable_table` / `mineru_lang`
  - 这些字段只对 `pipeline` / `vlm` 有效
  - 没有强需求时保留默认值
- `mineru_batch_size`
  - 官方 batch 上限是 200
  - 默认值保持保守即可，不要主动调大
- `mineru_backend_local`
  - 仅在用户明确要本地部署 MinerU 时才讨论
  - 对纯云端用户，不要把它当成需要配置的字段

### 部署引导
- **MinerU**
  - 若推荐 `MinerU`，默认先说明：云端路径可直接继续，且免费 token 可注册申请
  - 在说明完“优先推荐 MinerU”和“免费 token 路径”之后，**再**问用户是否打算本地部署
  - 若打算本地部署，给出官方 Quick Start、Docker 部署、GitHub 链接，并提示本地模型/ModelScope 方案
  - 若不打算本地部署，明确告诉用户去申请免费 token
- **Docling**
  - 给出官方安装文档、CLI 文档、GitHub 链接
  - 至少提供 `pip install docling`，以及 Linux CPU-only 场景的官方安装示例

### 能写成代码的优先写成代码
- `scholaraio setup` 里应尽量直接实现：
  - 网络可达性探测
  - 解析器推荐逻辑
  - MinerU 本地/云端分流提问
  - 官方部署入口链接打印
- 更偏 agent 行为规范的内容保留在本 skill，例如：
  - 什么时候主动帮用户做网络探测
  - 如何向用户解释“为什么推荐这个解析器”
  - 遇到两边都不通时的默认建议
  - 如何在用户已有明确偏好时停止“自动推荐”

### 沙盒 / 提权说明（对 Codex 等 agent 很重要）
- 如果 agent 运行在沙盒里，**不要把沙盒内的网络探测结果直接当成用户真实网络环境**
- 对 `MinerU cloud`、`Hugging Face`、以及 `localhost:8000` 这类连通性测试：
  - 优先在允许的情况下提权后再测
  - 如果不能提权，就必须明确告诉用户“这是沙盒视角结果，可能误判”
- 特别注意：
  - agent 沙盒里的 `localhost` 不一定等于用户宿主机的 `localhost`
  - agent 沙盒里的外网策略可能比用户宿主机更严格
- 如果用户愿意自己在宿主机验证，优先让用户运行：
  - `curl -I --max-time 10 http://localhost:8000`
  - `curl -I --max-time 10 https://mineru.net/apiManage/token`
  - `curl -I --max-time 10 https://huggingface.co`

### 成本透明要求

setup 过程中，agent 不要只说“需要 key”，必须同时说明：

- `LLM API key`：通常单独计费；不配则降级
- `MinerU token`：免费申请；不配仍可走本地 MinerU / Docling / PyMuPDF
- `contact_email`：免费
- 其他附加 API key：明确说“按第三方政策”，不要替对方做费用承诺

简短答法模板：

- `LLM API key`：用于元数据提取和内容富化；不配会降级为纯正则，通常单独计费
- `MinerU token`：用于 MinerU 云端解析；免费，不配仍可走本地 MinerU / Docling / PyMuPDF
- `contact_email`：用于 Crossref polite pool；免费，不配通常只是请求识别度和服务礼貌性更弱
- `Semantic Scholar API key`：用于认证访问；不配多数端点仍可用，但部分端点需要 key
- `Zotero API key`：用于当前的 Zotero Web API 导入路径；不配就改走本地 `zotero.sqlite`

### 目录不存在
- 运行 `scholaraio setup check` 后如果目录缺失，运行任意 scholaraio 命令会自动创建（`ensure_dirs()`）

## 3. 验证

配置完成后再次运行 `scholaraio setup check` 确认所有项目 [OK]。

## 注意

- 用户也可以直接运行 `scholaraio setup` 进入交互式向导（bilingual EN/ZH）
- `config.local.yaml` 存放敏感信息（API key），不进 git
- 嵌入模型（~1.2GB）会在首次 embed/vsearch 时自动下载，setup 不触发下载
