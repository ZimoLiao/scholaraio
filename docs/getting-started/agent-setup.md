# Agent Setup

ScholarAIO can be used in two different ways:

1. Open this repository directly with your coding agent.
2. Register ScholarAIO skills or tools so they are available from another project.

The right setup depends on which agent you use and whether it supports native skills or plugins.

## Start Here

| If you want to... | Recommended path |
|-------------------|------------------|
| Try ScholarAIO, inspect the codebase, or contribute | Open this repository directly |
| Use ScholarAIO from any project in Claude Code | Install the Claude Code plugin |
| Reuse ScholarAIO from another project in Codex / OpenClaw / Qwen / Cursor / Cline / Windsurf / Copilot | Run `scholaraio setup agent` |

## Open This Repository Directly

This is the simplest and most complete experience. You get the bundled instructions and local skills exactly as maintained in this repo.

```bash
git clone https://github.com/ZimoLiao/scholaraio.git
cd scholaraio
pip install -e ".[full]"
scholaraio setup
```

`scholaraio setup check` is the companion diagnostic command. It reports both the core setup state and optional advanced items such as Semantic Scholar / Zotero API keys and Paper2Any sidecar readiness. Current setup guidance prefers MinerU first whenever a MinerU path is available.

Then start your agent in the repository root:

| Agent | What happens in this repo |
|-------|----------------------------|
| Claude Code | Reads `CLAUDE.md` and loads `.claude/skills/` |
| Codex / OpenClaw | Reads `AGENTS.md` and discovers `.agents/skills/` |
| Cline | Reads `.clinerules` and can use `.claude/skills/` |
| Qwen | Loads `.qwen/QWEN.md` and discovers `.qwen/skills/` |
| Cursor | Reads `.cursor/rules/scholaraio.mdc` as a Project Rule, then `AGENTS.md`; `.cursorrules` is kept as a legacy fallback |
| Windsurf | Reads `.windsurfrules` |
| GitHub Copilot | Reads `.github/copilot-instructions.md` |

This mode is best when you want the full project context, not just the ScholarAIO skills.

The project checkout does not register optional MCP servers by default. It does
not register Paper2Any; add that sidecar explicitly only for a Paper2Any request
or fixed-corpus evaluation. See [Paper2Any Integration](../guide/paper2any-integration.md)
for explicit sidecar registration.

The entry docs are intentionally layered:

- `AGENTS.md` / `CLAUDE.md` / `.qwen/QWEN.md`: short entry docs with durable project facts and hard constraints
- `.claude/skills/`: reusable workflows and procedures
- `docs/DESIGN.md`: repository knowledge map and documentation system of record
- `docs/guide/agent-reference.md`: deeper agent, runtime, and architecture reference

If an instruction starts turning into a long checklist, it probably belongs in a skill instead of an entry doc.

## Claude Code Plugin

Claude Code has the cleanest cross-project install path because ScholarAIO ships as a plugin and marketplace entry.

`scholaraio setup agent` prints the same plugin commands as manual actions, but it does not run them for you. Claude Code slash-commands must be entered inside Claude Code.

### Install into any project

Run these commands inside Claude Code as slash-commands, not in your system shell:

```text
/plugin marketplace add ZimoLiao/scholaraio
/plugin install scholaraio@scholaraio-marketplace
```

After installation, start a new Claude Code session in your target project. ScholarAIO skills will be available with the `/scholaraio:*` namespace, for example:

```text
/scholaraio:search
/scholaraio:show
/scholaraio:workspace
```

### What the plugin sets up

- Installs the `scholaraio` Python package on first session
- Creates `~/.scholaraio/config.yaml`
- Creates `~/.scholaraio/data/` and related workspace directories

This is the recommended way to make ScholarAIO available outside this repository.

## Automated Agent Registration

For cross-project use, ScholarAIO can preview and apply the parts that are safe to automate:

```bash
scholaraio setup agent
scholaraio setup agent --apply
scholaraio setup agent check
```

The command separates three layers:

- CLI runtime: `SCHOLARAIO_CONFIG` plus the installed `scholaraio` command path
- skill discovery: global or project-local pointers to `.claude/skills/`
- host instructions: plugin commands or wrapper files for agents without a global registry

By default, `scholaraio setup agent` is a preview and does not modify files. Add `--apply` to perform automatic actions. Restart your agent session after applying changes so newly registered skills are discovered.

Project-local wrappers created with `--target-project` contain absolute paths for this machine, such as the active ScholarAIO config and skills directory. Review those managed blocks before committing them to a shared repository.

Common scoped runs:

```bash
# Codex / OpenClaw global skill registration plus shell config
scholaraio setup agent --agent codex --apply

# Prepare project-local wrappers for supported hosts
scholaraio setup agent --all --target-project ~/repos/my-software-project --apply

# Inspect status in Chinese
scholaraio setup agent check --lang zh
```

### What Can Be Automated

| Target | Automatic action |
|--------|------------------|
| Codex / OpenClaw | Creates or verifies `~/.agents/skills/scholaraio -> <repo>/.claude/skills` |
| Shell runtime | Adds a managed block for `SCHOLARAIO_CONFIG` and the ScholarAIO command path |
| Qwen | Creates project-local `.qwen/QWEN.md` and `.qwen/skills` when `--target-project` is supplied |
| Cursor | Creates project-local `.cursor/rules/scholaraio.mdc` when `--target-project` is supplied |
| Cline | Adds a managed block to project-local `.clinerules` when `--target-project` is supplied |
| Windsurf | Adds a managed block to project-local `.windsurfrules` when `--target-project` is supplied |
| GitHub Copilot | Adds a managed block to project-local `.github/copilot-instructions.md` when `--target-project` is supplied |
| Claude Code | Prints plugin slash-commands; install still happens inside Claude Code |

### Manual Fallback

If you cannot let the setup command modify user files, use the same steps manually.

Codex-style agents can use ScholarAIO outside this repository through native skill discovery.

### One-time setup

Clone ScholarAIO somewhere stable:

```bash
git clone https://github.com/ZimoLiao/scholaraio.git ~/.codex/scholaraio
cd ~/.codex/scholaraio
pip install -e ".[full]"
scholaraio setup
```

Create a global skills symlink:

```bash
mkdir -p ~/.agents/skills
ln -s ~/.codex/scholaraio/.claude/skills ~/.agents/skills/scholaraio
```

Make config discovery explicit for cross-project use:

```bash
# Option A: keep ScholarAIO data rooted in the cloned repo
export SCHOLARAIO_CONFIG="$HOME/.codex/scholaraio/config.yaml"

# Option B: move/copy the config into the global fallback location
mkdir -p ~/.scholaraio
cp ~/.codex/scholaraio/config.yaml ~/.scholaraio/config.yaml
```

Without one of those two options, running `scholaraio` from another project may fall back to defaults rooted in that current project and create `data/` plus `workspace/` there.

Restart Codex or OpenClaw after creating the symlink.

### Windows

Clone the repo somewhere stable first, for example:

```powershell
git clone https://github.com/ZimoLiao/scholaraio.git "$env:USERPROFILE\.codex\scholaraio"
cd "$env:USERPROFILE\.codex\scholaraio"
pip install -e ".[full]"
scholaraio setup
```

Then use a junction instead of a symlink:

```powershell
$repoRoot = "$env:USERPROFILE\.codex\scholaraio"

New-Item -ItemType Directory -Force -Path "$env:USERPROFILE\.agents\skills"
cmd /c mklink /J "$env:USERPROFILE\.agents\skills\scholaraio" "$repoRoot\.claude\skills"
```

For cross-project use on Windows, either set `SCHOLARAIO_CONFIG` to `"$repoRoot\config.yaml"` or copy that config to `$env:USERPROFILE\.scholaraio\config.yaml`.

### What this gives you

- Global access to the ScholarAIO skill library
- Native discovery through `~/.agents/skills/`
- A setup path similar to other Codex skill packs

### Important limitation

This registers the skills, not the full repository instructions. If you want the agent to also read ScholarAIO's bundled project guidance, open this repository directly instead of only linking the skills.

## Which Path Should I Choose?

| Situation | Best choice |
|-----------|-------------|
| You are evaluating ScholarAIO itself | Open this repository directly |
| You want ScholarAIO in Claude Code across projects | Claude Code plugin |
| You want ScholarAIO in other coding-agent projects | `scholaraio setup agent --apply` |

## Verify the Setup

Use one of these checks after installation:

- In this repository: ask your agent to search or show a paper and confirm it can see ScholarAIO instructions or skills.
- In Claude Code plugin mode: verify `/scholaraio:search` appears.
- In Codex / OpenClaw: run `scholaraio setup agent check`, restart the agent, and ask it to use the `search` or `show` skill.

## Related Guides

- [Installation](installation.md)
- [Configuration](configuration.md)
- [Docs Home](../index.md)
