# Configuration

ScholarAIO uses two config files:

| File | Tracked | Purpose |
|------|---------|---------|
| `config.yaml` | Yes | Default settings |
| `config.local.yaml` | No (git-ignored) | API keys and local overrides |

## API Keys

LLM API key lookup order:

1. `config.local.yaml` → `llm.api_key`
2. Environment variable `SCHOLARAIO_LLM_API_KEY`
3. Backend-specific environment variables, based on `llm.backend`:
   - `openai-compat`: `DEEPSEEK_API_KEY` → `OPENAI_API_KEY`
   - `anthropic`: `ANTHROPIC_API_KEY`
   - `google`: `GOOGLE_API_KEY` → `GEMINI_API_KEY`

### Example `config.local.yaml`

```yaml
llm:
  api_key: "sk-your-key-here"

ingest:
  mineru_api_key: "your-mineru-token"  # compatibility alias; MINERU_TOKEN is preferred
  s2_api_key: "your-semantic-scholar-key"  # optional

zotero:
  api_key: "your-zotero-key"  # optional
  library_id: "1234567"  # optional
```

You can also keep the token out of YAML entirely and set `MINERU_TOKEN` in the environment. `MINERU_API_KEY` is still accepted as a compatibility alias.

## Key Settings

### LLM Backend

Default: DeepSeek (`deepseek-chat`) via OpenAI-compatible protocol.

```yaml
llm:
  model: deepseek-chat
  base_url: https://api.deepseek.com
```

### Metadata Extraction

```yaml
ingest:
  extractor: robust  # regex + LLM (default)
  # Other options: auto, regex, llm
```

### Embedding Source

```yaml
embed:
  source: modelscope  # default (China)
  # source: huggingface  # for international users
```

### Backup Targets

ScholarAIO supports two rsync backup scopes:

- `data` preserves the existing behavior and syncs only `backup.source_dir`.
- `instance` creates a restorable runtime-instance backup containing `config.yaml`,
  `config.local.yaml` when present, the configured data root, `workspace/`,
  `published/`, and `.scholaraio-control/`.

SSH is always non-interactive. Key-authenticated targets use `BatchMode=yes`;
password targets use ScholarAIO's internal `SSH_ASKPASS` helper. Host-key
confirmation is never interactive.

```yaml
backup:
  source_dir: data
  connect_timeout_seconds: 15
  io_timeout_seconds: 300
  process_timeout_seconds: 86400
  targets:
    lab:
      host: backup.example.com
      user: alice
      path: /srv/scholaraio
      port: 22
      identity_file: ~/.ssh/id_ed25519
      scope: instance
      mode: default
      compress: true
      enabled: true
```

- `scope` supports `data` and `instance`; it defaults to `data` for backward compatibility.
- `connect_timeout_seconds` bounds SSH connection setup, `io_timeout_seconds` bounds idle rsync I/O and SSH keepalive detection, and `process_timeout_seconds` bounds each rsync/SSH subprocess.
- `mode` supports `default`, `append`, and `append-verify`.
- Use `default` for the full ScholarAIO `data/` tree, especially when it includes mutable files such as SQLite databases.
- Reserve `append` / `append-verify` for append-only artifacts where the remote copy is expected to be a prefix of the local file.
- `instance` requires `mode: default`, does not accept `exclude`, and should use a dedicated empty remote directory.
- Subsequent `instance` runs mirror deletions inside the backed-up component trees, preventing removed papers or metadata from reappearing after restore.
- Real `instance` runs use SQLite's online backup API plus `quick_check` for recognized `.db`, `.sqlite`, and `.sqlite3` files. WAL/SHM/journal sidecars are not restored; each database snapshot is consistent even if a writer remains active.
- Keep host-specific secrets such as `identity_file` in `config.local.yaml` when possible.
- Prepare SSH key-based authentication and the target host's `known_hosts` entry ahead of time; otherwise `backup run` will fail fast instead of waiting for interactive input.
- `config.local.yaml` is sent through encrypted SSH and keeps owner-only file permissions, but its API keys and passwords remain plaintext at rest on the backup server. Protect the remote account and storage accordingly.
- API keys supplied only through environment variables are not captured. Put a key in `config.local.yaml` if it must be restorable.

Recommended split:

```yaml
# config.yaml
backup:
  source_dir: data
  targets:
    lab:
      host: 192.168.31.229
      user: lzmo
      path: /srv/scholaraio
      port: 1393
      scope: instance
      mode: default
      compress: true
      enabled: true
```

```yaml
# config.local.yaml
backup:
  targets:
    lab:
      identity_file: ~/.ssh/id_ed25519
      # password: your-ssh-password  # Optional fallback when the server does not accept your key
```

Recommended first-run checklist:

1. Add the target host to `known_hosts`:
   `ssh-keyscan -p 1393 192.168.31.229 >> ~/.ssh/known_hosts`
2. If the server accepts your SSH key, verify it first:
   `ssh -i ~/.ssh/id_ed25519 -p 1393 lzmo@192.168.31.229 true`
3. If the server is password-only, place `password` in `config.local.yaml`; ScholarAIO will switch to internal non-interactive askpass mode automatically.
4. Dry-run first:
   `scholaraio backup run lab --dry-run`
5. Run the backup:
   `scholaraio backup run lab`

Restore into a new runtime-instance directory:

```bash
scholaraio backup restore lab --destination /path/to/new/scholaraio --dry-run
scholaraio backup restore lab --destination /path/to/new/scholaraio
```

The destination must be empty unless `--force` is supplied. `--force` merges the
backup into the destination and overwrites matching runtime files; it does not
delete unrelated source-code files. Restore first reads and validates the remote
backup manifest, and data-only targets cannot be restored as full instances.

On a replacement machine, create a minimal local target configuration first so
ScholarAIO knows how to reach the backup server. The restored
`config.local.yaml` then replaces that bootstrap configuration. After moving an
instance to a different root, run `scholaraio setup check` and rebuild
path-sensitive indexes.

ScholarAIO does not configure an external web discovery or extraction service.
Use the active agent's native web search and URL-reading tools instead.

### Paper2Any MCP Sidecar

Paper2Any is an optional external extension. ScholarAIO keeps the OpenDCAI/Paper2Any checkout outside tracked source, normally under `data/runtime/extensions/paper2any/Paper2Any`, and talks to it through a lightweight MCP sidecar:

```yaml
paper2any:
  transport: mcp
  mcp_url: http://127.0.0.1:8770/mcp
  root: null
  base_url: http://127.0.0.1:8000
  api_key: "optional-sidecar-token"
  backend_api_key: "optional-upstream-backend-token"
```

Agent workflows should start the sidecar with:

```bash
scholaraio paper2any setup
scholaraio paper2any mcp-serve
scholaraio paper2any backend-serve # optional, only when a FastAPI workflow is needed
scholaraio paper2any status
```

If the user wants the agent to prepare Paper2Any's isolated upstream Python runtime as well, the agent can run `scholaraio paper2any setup --install-runtime`.

### Publish Site

`published/` is a local, git-ignored archive for final audited deliverables. The `publish-site` command can generate a separate static site from `published/*/metadata.json`.

```yaml
publish:
  site_output_dir: ~/generated-report
  # published_dir: published
```

Run:

```bash
scholaraio publish-site
```

By default, PDFs and generated source ZIPs are copied into the output site so it can be deployed as a standalone GitHub Pages repository. Use `--symlink` only for local preview.
