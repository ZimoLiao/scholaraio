# Installation

## Requirements

- Python 3.10+
- Git

## Install from PyPI

```bash
# Core installation
pip install scholaraio

# Full installation (embed + topics + import + pdf + office + draw)
pip install "scholaraio[full]"
```

Then run:

```bash
scholaraio setup
```

## Install from Source

```bash
git clone https://github.com/zimoliao/scholaraio.git
cd scholaraio

# Core only (search, export, audit)
pip install -e .

# Full installation (embed + topics + import + pdf + office + draw)
pip install -e ".[full]"
```

Use the source install path when you want to inspect the codebase, edit the package locally, or contribute changes upstream.

## Optional Dependencies

| Extra | What it adds |
|-------|-------------|
| `embed` | Semantic search (sentence-transformers + FAISS) |
| `topics` | BERTopic topic modeling |
| `pdf` | PyMuPDF-based PDF fallback and long-PDF utilities |
| `import` | Endnote / Zotero import |
| `office` | DOCX / PPTX / XLSX ingest and inspection |
| `draw` | Python helpers for Mermaid and custom SVG drawing; Graphviz `dot` and Inkscape are system tools checked by `setup check` |
| `full` | Core research workflow extras: embed + topics + import + pdf + office + draw |
| `dev` | Development tools (pytest, ruff, mypy) |

## Setup Wizard

Run the interactive setup wizard to configure API keys and directories:

```bash
scholaraio setup
```

Or check what's already configured:

```bash
scholaraio setup check
```

`setup check` is the most complete initial diagnostic surface. It covers:

- core setup items: dependency groups, `config.yaml`, LLM key, MinerU / Docling availability, parser recommendation, Graphviz `dot`, Inkscape, `contact_email`, and directory state
- optional advanced items: Semantic Scholar API key and Zotero API key

Current setup guidance prefers **MinerU first** whenever a MinerU path is available (local service or `mineru-open-api` + token). `Docling` and then PyMuPDF remain the fallback chain when MinerU is not usable or when the user explicitly prefers a lighter parser path.

Cost transparency:

- `LLM API key`: usually billed separately by the chosen provider
- `MINERU_TOKEN`: free to apply
- `contact_email`: free
- `Semantic Scholar API key`: optional; most endpoints work anonymously, but some require a key
- `Zotero API key`: optional; ScholarAIO's current Web API import path expects it, while local `zotero.sqlite` import does not

## Agent Setup

If you want to know which path to use for Claude Code, Codex, OpenClaw, Cursor, or other agents, see:

- [Agent Setup](agent-setup.md)

That guide separates:

- opening this repository directly
- registering ScholarAIO for use from another project
- choosing between native skills and plugins

## Embedding Model

The embedding model (Qwen3-Embedding-0.6B, ~1.2 GB) downloads automatically on first use. For users outside China, set `embed.source: huggingface` in `config.yaml`.
