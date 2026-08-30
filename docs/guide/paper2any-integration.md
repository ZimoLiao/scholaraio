# Paper2Any Integration

ScholarAIO integrates [OpenDCAI/Paper2Any](https://github.com/OpenDCAI/Paper2Any) as an optional external MCP capability. ScholarAIO does not vendor Paper2Any or expose its dependency graph as first-class ScholarAIO settings. The normal shape is:

1. an external Paper2Any checkout under `data/runtime/extensions/paper2any/Paper2Any`;
2. a lightweight ScholarAIO MCP sidecar at `http://127.0.0.1:8770/mcp`;
3. optional access to Paper2Any's own FastAPI backend at `http://127.0.0.1:8000`.

Paper2Any is an isolated, explicit opt-in extension. The current agent's native
capabilities remain the default for ordinary web research, paper reading,
writing, diagrams, and presentation generation. Paper2Any must not be promoted
to a default path until a fixed-corpus comparison records accuracy, editability,
layout quality, latency, cost, setup burden, and degradation behavior.

## Configuration

```yaml
paper2any:
  transport: mcp
  mcp_url: http://127.0.0.1:8770/mcp
  root: null
  base_url: http://127.0.0.1:8000
  api_key: null
  backend_api_key: null
```

When `root` is omitted, ScholarAIO uses:

```text
data/runtime/extensions/paper2any/Paper2Any
```

Keep real tokens in `config.local.yaml` or environment variables. `backend_api_key` is required for Paper2Any `/api/v1/...` routes because the upstream backend checks it as `BACKEND_API_KEY` / `X-API-Key`.

```yaml
paper2any:
  api_key: ""
  backend_api_key: ""
```

Environment fallbacks:

- `PAPER2ANY_ROOT`
- `PAPER2ANY_MCP_URL`
- `PAPER2ANY_MCP_API_KEY`
- `PAPER2ANY_BACKEND_URL`
- `PAPER2ANY_BACKEND_API_KEY`

## Commands

Prepare the external runtime checkout:

```bash
scholaraio paper2any setup
```

For agent-managed full runtime preparation, add:

```bash
scholaraio paper2any setup --install-runtime
```

This creates the upstream checkout under `data/runtime/extensions/paper2any/Paper2Any` and, when requested, installs the upstream `requirements-base.txt` and `requirements-paper.txt` into `data/runtime/extensions/paper2any/.venv`. If either manifest is absent, setup fails closed and asks you to update or select a supported checkout instead of reporting an empty runtime as ready. The dependency details stay in Paper2Any's own requirements files; the user-facing ScholarAIO config stays small.

`--install-runtime` installs Python dependencies only. Paper2Any's current
upstream installation guide lists workflow-dependent system tools such as
LibreOffice, Inkscape, Poppler, FFmpeg, wkhtmltopdf, and Tectonic; install only
the tools required by the workflow you intend to benchmark. ScholarAIO does not
silently modify the host OS.

Start the MCP sidecar:

```bash
scholaraio paper2any mcp-serve
```

Start the real upstream Paper2Any FastAPI backend when an API workflow is needed:

```bash
export PAPER2ANY_BACKEND_API_KEY="..."
scholaraio paper2any backend-serve
```

Inspect from ScholarAIO through MCP:

```bash
scholaraio paper2any tools
scholaraio paper2any status
scholaraio paper2any call paper2any_capabilities
```

Run a real upstream CLI script:

```bash
scholaraio paper2any call paper2any_run_cli --arguments-json '{
  "workflow": "paper2figure",
  "input": "workspace/example/paper.pdf",
  "output_dir": "workspace/_system/paper2any/example-figure",
  "extra_args": ["--graph-type", "model_arch"]
}'
```

If upstream Paper2Any requires outputs to stay under its own `Paper2Any/outputs` tree, the sidecar stages the real run there and then copies the generated artifacts back to the requested ScholarAIO workspace path. The MCP result reports both `paper2any_output_dir` and `requested_output_dir`.

Proxy a real Paper2Any FastAPI JSON route. This requires `paper2any.backend_api_key` in `config.local.yaml` or `PAPER2ANY_BACKEND_API_KEY` in the environment:

```bash
scholaraio paper2any call paper2any_call_api --arguments-json '{
  "path": "/api/v1/system/verify-llm",
  "json": {"model": "gpt-4o"}
}'
```

## MCP Tools

| Tool | Purpose |
| --- | --- |
| `paper2any_status` | Inspect external checkout, CLI scripts, and optional backend health. |
| `paper2any_capabilities` | List known CLI workflows and backend API workflow families. |
| `paper2any_run_cli` | Run a real standalone Paper2Any CLI script from the external checkout. |
| `paper2any_call_api` | Proxy a real Paper2Any backend JSON route under `/api/v1/...` or `/health`. |
| `paper2any_outputs` | List files produced under an output directory. |

## Covered Paper2Any Paths

Standalone CLI workflows:

| Workflow | Upstream script |
| --- | --- |
| `paper2figure` | `script/run_paper2figure_cli.py` |
| `paper2ppt` | `script/run_paper2ppt_cli.py` |
| `paper2ppt_frontend` | `script/run_paper2ppt_frontend_cli.py` |
| `pdf2ppt` | `script/run_pdf2ppt_cli.py` |
| `image2ppt` | `script/run_image2ppt_cli.py` |
| `ppt2polish` | `script/run_ppt2polish_cli.py` |
| `paper2poster` | `script/run_paper2poster_cli.py` |
| `paper2video` | `script/run_paper2video_cli.py` |

Backend workflow families:

- `paper2figure`, `paper2ppt`, `paper2citation`, `paper2video`, `paper2poster`
- `pdf2ppt`, `image2ppt`, `image2drawio`, `image_playground` (`/api/v1/image-playground/...`)
- `mindmap`, `kb`, `kb_workflows`, `kb_embedding`, `files` (`kb_workflows` and `kb_embedding` are under `/api/v1/kb/...`)
- `paper2drawio`, `paper2rebuttal`

## Agent MCP Registration

The project does not ship a `.mcp.json` and intentionally does not register Paper2Any. Register the
sidecar explicitly only for a Paper2Any request or fixed-corpus evaluation:

```json
{
  "mcpServers": {
    "paper2any": {
      "type": "http",
      "url": "http://127.0.0.1:8770/mcp"
    }
  }
}
```

Codex can register the same endpoint directly:

```bash
codex mcp add paper2any --url http://127.0.0.1:8770/mcp
```

Claude Code can register it with:

```bash
claude mcp add --transport http paper2any http://127.0.0.1:8770/mcp
```

## Operational Rules

- Do not fabricate Paper2Any outputs. Check actual MCP responses and inspect files under the reported output directory.
- Keep external Paper2Any code under `data/runtime/extensions/`, not under tracked ScholarAIO source.
- Keep generated deliverables under `workspace/_system/paper2any/` or a user workspace.
- If the external checkout, Paper2Any dependencies, upstream backend, or model credentials are missing, report that exact boundary instead of substituting a fake artifact.
