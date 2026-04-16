<div align="center">

<!-- TODO: Replace with actual logo when available -->
<!-- <img src="docs/assets/logo.png" width="200" alt="ScholarAIO Logo"> -->

# ScholarAIO

**Scholar All-In-One — A research infrastructure for AI agents.**

[English](README.md) | [中文](README_CN.md)

[![GitHub stars](https://img.shields.io/github/stars/ZimoLiao/scholaraio?style=social)](https://github.com/ZimoLiao/scholaraio/stargazers)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)
[![Python 3.10+](https://img.shields.io/badge/Python-3.10%2B-blue.svg)](https://www.python.org/)
[![Claude Code Skills](https://img.shields.io/badge/Claude_Code_Skills-ScholarAIO-purple.svg)](.claude/skills/)

</div>

---

Your coding agent already reads code, writes code, and runs experiments. ScholarAIO adds a structured research workspace on top, so the same agent can search literature, cross-check results against papers, use scientific software more accurately, and carry the whole research workflow from one terminal.

- Your paper library becomes a reusable knowledge base for the same agent.
- When scientific software questions come up, the agent can consult official documentation at runtime instead of guessing from prompts.
- The system is built to keep expanding as new tools and workflows become worth supporting.

<div align="center">
  <img src="docs/assets/scholaraio.gif" width="900" alt="ScholarAIO natural-language research workflow">
</div>

ScholarAIO offers more than search. It gives an AI coding agent a research workspace that supports natural-language interaction, papers and notes, more reliable use of scientific software, writing and running code, checking results against the literature, and structured academic writing.

<div align="center">
  <img src="docs/assets/scholaraio-architecture-v1.3.0.png" width="900" alt="ScholarAIO architecture: human, agent, scientific context, tool layer, and compute/outputs">
</div>

## Quick Start

The default and recommended way to use ScholarAIO is simple: install it, configure it once, and open this repository directly with your coding agent.

```bash
git clone https://github.com/ZimoLiao/scholaraio.git
cd scholaraio
pip install -e ".[full]"
scholaraio setup
```

Then open the repository in Codex, Claude Code, or another supported agent. In this setup, the agent gets the fullest experience: bundled instructions, local skills, the CLI, and the complete codebase context are all available directly. For Claude Code plugins, Codex/OpenClaw skill registration, and other setup paths, see [`docs/getting-started/agent-setup.md`](docs/getting-started/agent-setup.md).

## What It Does

|  | Feature | Details |
|--|---------|---------|
| **PDF Parsing** | Deep structure extraction | Convert PDFs into structured Markdown while preserving formulas, figures, and layout as much as possible |
| **Not Just Papers** | More than papers | Journal articles, theses, patents, technical reports, standards, and lecture notes — four inbox categories with tailored metadata handling |
| **Hybrid Search** | Keyword + semantic fusion | Combine full-text and vector retrieval for stronger search results |
| **Topic Discovery** | See what your library is about | Automatically group papers into research themes and use interactive views to grasp the overall structure quickly |
| **Literature Exploration** | Multi-dimensional discovery | Explore a research direction through journal, topic, author, institution, keyword, year, citation impact, and more |
| **Citation Graph** | References & impact | Forward citations, backward citations, and shared-reference analysis |
| **Layered Reading** | Read on demand | Start with metadata or the abstract, then move into conclusions or full text only when you need to |
| **Multi-Source Import** | Connect your existing library | Import directly from reference managers, PDFs, and Markdown without rebuilding your library from scratch |
| **Workspaces** | Organize by project | Manage paper subsets with scoped search and BibTeX export |
| **Multi-Format Export** | BibTeX, RIS, Markdown, DOCX | Export your full library or a workspace for Zotero, Endnote, submission, or sharing |
| **Metadata Scrub** | Incremental cleanup after enrich | Review and repair low-quality titles, authors, and years for non-standard documents, then mark reviewed records to skip future passes |
| **Persistent Notes** | Cross-session memory | Keep analysis notes for each paper so future sessions can reuse them instead of starting over |
| **Research Insights** | Reading behavior analytics | Search hot keywords, most-read papers, reading trends, and semantic neighbor recommendations for papers you haven't read yet |
| **Federated Discovery** | Cross-library search | Search your main library, exploration libraries, and arXiv from one entry point instead of hopping across tools |
| **Remote Backup** | Rsync-based sync | Back up the ScholarAIO `data/` workspace to configured remote targets through named rsync plans |
| **AI-for-Science Runtime** | Use scientific software more accurately | Use scientific software against official documentation at runtime instead of guessing commands and parameters |
| **Extensible Tool Onboarding** | Keep adding the tools that matter | As new scientific tools and workflows become important, the system can keep expanding |
| **Academic Writing** | AI-assisted writing | Router-first workflows for literature review, guided single-paper reading, paper sections, citation check, rebuttal, gap analysis, poster packages, and technical reports — with every citation traceable to your own library |

For writing tasks, start with the router-style writing entry when the deliverable is clear but the workflow is not. The current writing stack is organized around:

- `academic-writing`: route by deliverable and writing stage
- `literature-review`: long-form review and survey writing
- `paper-guided-reading`: guided deep reading of a single paper from fuzzy search to full-text analysis
- `paper-writing`: manuscript sections and paper-focused drafting
- `review-response`: rebuttal and response-letter workflows
- `research-gap`: gap analysis and open-question reports
- `technical-report`: technical briefings and topic reports
- `poster`: poster-oriented content packaging
- `document`: final DOCX / PPTX packaging

See [`docs/guide/writing.md`](docs/guide/writing.md) for the full writing map.

## Works With Your Agent

ScholarAIO is designed to be **agent-agnostic**, but different agents expose different integration paths. Some work best when you open this repository directly; others are easier to use through plugins.

| Agent / IDE | Open this repo directly | Reuse from another project |
|-------------|-------------------------|-----------------------------|
| [Claude Code](https://docs.anthropic.com/en/docs/claude-code) | `CLAUDE.md` + `.claude/skills/` | Claude plugin marketplace |
| [Codex](https://openai.com/codex) / OpenClaw | `AGENTS.md` + `.agents/skills/` | Symlink skills into `~/.agents/skills/` |
| [Cline](https://github.com/cline/cline) | `.clinerules` + `.claude/skills/` | CLI + skills |
| [Qwen](https://qwen.ai/) | `.qwen/QWEN.md` + `.qwen/skills/` | CLI + skills |
| [Cursor](https://cursor.sh) | `.cursor/rules/scholaraio.mdc` + `AGENTS.md` (`.cursorrules` legacy fallback) | CLI + skills |
| [Windsurf](https://codeium.com/windsurf) | `.windsurfrules` | CLI + skills |
| [GitHub Copilot](https://github.com/features/copilot) | `.github/copilot-instructions.md` | CLI + skills |

Skills follow the open [AgentSkills.io](https://agentskills.io) standard, and `.agents/skills/` and `.qwen/skills/` are symlinks to `.claude/skills/` so different agents can discover and reuse the same skills. Qwen-specific project context lives in `.qwen/QWEN.md`.

**Migrating from existing tools?** Import directly from Endnote (XML/RIS) and Zotero (Web API or local SQLite), with PDFs, metadata, and references brought over together. More import sources are on the roadmap.

## Configuration

> Start by opening `scholaraio` with your agent and let it walk you through the setup. The notes below are only a basic overview.

ScholarAIO works with a minimal setup and can be expanded as needed.

- `scholaraio setup` walks you through the basics.
- An LLM API key is optional but recommended for more robust metadata extraction and content completion.
- A MinerU token is optional but recommended, and free. You can also deploy MinerU or Docling locally for PDF parsing.
- `scholaraio setup check` shows what is installed, what is optional, and what is missing.

Full setup and configuration details → [`docs/getting-started/agent-setup.md`](docs/getting-started/agent-setup.md), [`config.yaml`](config.yaml)

## Agent First, CLI Available

ScholarAIO works best through an AI coding agent, but it also provides a CLI for scripting, debugging, and quick queries. For a current command reference aligned with the code, see [`docs/guide/cli-reference.md`](docs/guide/cli-reference.md).

## Project Structure

```
scholaraio/             # Python package — CLI and all core modules
  ingest/               #   PDF parsing + metadata extraction pipeline
  sources/              #   External source adapters (arXiv / Endnote / Zotero)

.claude/skills/         # Agent skills (AgentSkills.io format)
.agents/skills/         # ↑ symlink for cross-agent discovery
.qwen/QWEN.md           # ↑ project context for Qwen Code
.qwen/skills/           # ↑ symlink for Qwen agent skill discovery
data/papers/            # Your paper library (gitignored)
data/proceedings/       # Proceedings library (gitignored)
data/inbox/             # Drop PDFs here for ingestion
data/inbox-proceedings/ # Drop proceedings volumes here for dedicated ingest
```

Full module reference → [`CLAUDE.md`](CLAUDE.md) or [`AGENTS.md`](AGENTS.md)

## Citation

If you use ScholarAIO in your research, please cite:

```bibtex
@software{scholaraio,
  author = {Liao, Zi-Mo},
  title = {ScholarAIO: AI-Native Research Terminal},
  year = {2026},
  url = {https://github.com/ZimoLiao/scholaraio},
  license = {MIT}
}
```

## License

[MIT](LICENSE) © 2026 Zi-Mo Liao
