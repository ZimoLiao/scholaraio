---
name: paper2any
description: Use when the user wants Paper2Any-based paper-to-figure, PPT, poster, video, citation, rebuttal, DrawIO, mindmap, image, PDF-to-PPT, or KB workflows through the ScholarAIO Paper2Any MCP sidecar.
---

# paper2any - Paper2Any MCP 增强组件

Paper2Any 是外部项目 [OpenDCAI/Paper2Any](https://github.com/OpenDCAI/Paper2Any)。ScholarAIO 不 vendoring 它的代码和依赖；ScholarAIO 只提供一个轻量 MCP sidecar，把 agent 请求转交给真实 Paper2Any checkout 或它自己的 FastAPI 后端。

默认外部 checkout 位置：

```bash
data/runtime/extensions/paper2any/Paper2Any
```

## 使用顺序

1. 一键准备外部 Paper2Any runtime：

   ```bash
   scholaraio paper2any setup
   ```

   如果用户明确要让 agent 把 upstream Python runtime 也准备好，使用：

   ```bash
   scholaraio paper2any setup --install-runtime
   ```

   这个命令会使用 OpenDCAI/Paper2Any 自己的 requirements 在 `data/runtime/extensions/paper2any/.venv` 中准备隔离环境；不要把依赖清单转嫁给非开发者用户。

2. 确认 sidecar 是否可用：

   ```bash
   scholaraio paper2any status
   ```

3. 如果不可用，启动 ScholarAIO 轻量 MCP sidecar：

   ```bash
   scholaraio paper2any mcp-serve
   ```

   这只启动 ScholarAIO 的 MCP 代理，不会伪造 Paper2Any 结果。真实产物仍由外部 Paper2Any CLI 或 Paper2Any FastAPI 生成。

4. 如果需要 Paper2Any FastAPI 工作流，启动真实上游 backend。上游 `/api/v1/...` 路由要求 `BACKEND_API_KEY` / `X-API-Key`，因此先在 `config.local.yaml` 写入 `paper2any.backend_api_key`，或设置环境变量：

   ```bash
   export PAPER2ANY_BACKEND_API_KEY="..."
   scholaraio paper2any backend-serve
   ```

   这个命令只负责从外部 checkout 启动 Paper2Any 自己的 `fastapi_app.main:app`，优先使用 `data/runtime/extensions/paper2any/.venv`。

5. 列出可用工具：

   ```bash
   scholaraio paper2any tools
   scholaraio paper2any call paper2any_capabilities
   ```

6. 运行真实 CLI 工作流时，必须提供真实输入文件和输出目录：

   ```bash
   scholaraio paper2any call paper2any_run_cli --arguments-json '{
     "workflow": "paper2figure",
     "input": "workspace/example/paper.pdf",
     "output_dir": "workspace/_system/paper2any/example-figure",
     "extra_args": ["--graph-type", "model_arch"]
   }'
   ```

   如果 upstream Paper2Any 只允许写入自己的 `Paper2Any/outputs` 目录，sidecar 会先在那里真实运行，再把真实产物复制回请求中的 workspace 输出目录。结果里会同时给出 `paper2any_output_dir` 和 `requested_output_dir`。

7. 调用真实 Paper2Any FastAPI 后端 JSON 路径；这同样要求 `paper2any.backend_api_key` 或 `PAPER2ANY_BACKEND_API_KEY`：

   ```bash
   scholaraio paper2any call paper2any_call_api --arguments-json '{
     "path": "/api/v1/system/verify-llm",
     "json": {"model": "gpt-4o"}
   }'
   ```

## MCP 工具

- `paper2any_status`: 检查外部 checkout、CLI 脚本、FastAPI `/health`。
- `paper2any_capabilities`: 列出所有已知 CLI 工作流和 API 工作流族。
- `paper2any_run_cli`: 运行真实 upstream standalone CLI 脚本。
- `paper2any_call_api`: 代理真实 upstream FastAPI `/api/v1/...` 或 `/health`。
- `paper2any_outputs`: 列出输出目录中的真实产物。

## 覆盖的 Paper2Any 路径

真实 CLI 脚本路径：

- `paper2figure`: `script/run_paper2figure_cli.py`
- `paper2ppt`: `script/run_paper2ppt_cli.py`
- `paper2ppt_frontend`: `script/run_paper2ppt_frontend_cli.py`
- `pdf2ppt`: `script/run_pdf2ppt_cli.py`
- `image2ppt`: `script/run_image2ppt_cli.py`
- `ppt2polish`: `script/run_ppt2polish_cli.py`
- `paper2poster`: `script/run_paper2poster_cli.py`
- `paper2video`: `script/run_paper2video_cli.py`

真实 FastAPI 工作流族：

- `paper2figure`, `paper2ppt`, `paper2citation`, `paper2video`, `paper2poster`
- `pdf2ppt`, `image2ppt`, `image2drawio`, `image_playground`（实际路径为 `/api/v1/image-playground/...`）
- `mindmap`, `kb`, `kb_workflows`, `kb_embedding`, `files`（`kb_workflows` 与 `kb_embedding` 实际挂在 `/api/v1/kb/...` 下）
- `paper2drawio`, `paper2rebuttal`

## 配置

`config.yaml`:

```yaml
paper2any:
  transport: mcp
  mcp_url: http://127.0.0.1:8770/mcp
  root: null
  base_url: http://127.0.0.1:8000
  api_key: null
  backend_api_key: null  # required for upstream /api/v1/... routes
```

`config.local.yaml` 只放本机密钥：

```yaml
paper2any:
  api_key: ""
  backend_api_key: ""
```

可用环境变量：

- `PAPER2ANY_ROOT`
- `PAPER2ANY_MCP_URL`
- `PAPER2ANY_MCP_API_KEY`
- `PAPER2ANY_BACKEND_URL`
- `PAPER2ANY_BACKEND_API_KEY`（上游 `/api/v1/...` 路由必需）

## Agent 规则

- 不要 fake 产物；报告必须来自真实 `paper2any_run_cli`、真实 `paper2any_call_api` 或真实输出目录检查。
- 如果 upstream 依赖、模型 API key、Node/Python 环境缺失，明确报告边界，不要生成替代伪产物。
- 用户产物放在 `workspace/_system/paper2any/` 或用户指定 workspace；不要写到仓库根目录。
- 不要把 OpenDCAI/Paper2Any vendored 到 ScholarAIO 源码；外部 checkout 属于 runtime extension。
