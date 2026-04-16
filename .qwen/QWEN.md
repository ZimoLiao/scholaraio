# ScholarAIO for Qwen Code

Use this file as the Qwen Code project context for ScholarAIO.

## What This Project Is

ScholarAIO is a research infrastructure for AI agents. It helps users search papers, read and analyze literature, inspect figures and formulas, run academic workflows, and support scientific writing from one terminal workspace.

The Python package is `scholaraio`. The repository also contains reusable agent skills under `.claude/skills/`, exposed to Qwen Code through `.qwen/skills/`.

## How To Work In This Repo

- Prefer project skills in `.qwen/skills/` when the user request clearly matches one.
- Use the `scholaraio` CLI to do real work instead of describing what should be done.
- Load information progressively. Prefer metadata/abstract first, then conclusion/full text only when needed.
- Treat paper conclusions as claims, not facts. Compare evidence, point out limitations, and distinguish author opinion from supported results.
- Keep responses concise and evidence-driven.

## Skill-First Workflow

When a user request matches a ScholarAIO capability, check the corresponding skill in `.qwen/skills/` first.

Common skills:

- `search`: find papers, authors, and topics
- `show`: read metadata, abstract, conclusion, or full text
- `ingest`: process inbox items into the library
- `workspace`: manage paper subsets for a project
- `audit`: inspect data quality, missing fields, duplicates, and repair candidates
- `scrub`: incrementally review and repair low-quality metadata after enrich
- `literature-review`: organize a review narrative
- `paper-writing`: draft concrete manuscript sections
- `citation-check`: verify whether citations are real and correctly matched
- `draw`: generate diagrams and figures
- `document`: generate or inspect Office documents
- `scientific-runtime`: serve scientific CLI tasks with safer runtime grounding

## Common CLI Entry Points

Use these directly when needed:

- `scholaraio --help`
- `scholaraio search --help`
- `scholaraio show --help`
- `scholaraio audit --help`
- `scholaraio refetch --help`
- `scholaraio ingest --help`
- `scholaraio ws --help`
- `scholaraio arxiv --help`
- `scholaraio toolref --help`

## Notes for Qwen Code

- Qwen Code should rely on `.qwen/skills/` for project skills in this repository.
- Do not assume `AGENTS.md` or `CLAUDE.md` is auto-loaded.
- If more complete project guidance is needed, read `AGENTS.md` manually.

## Research Attitude

- Do not over-trust highly cited papers or prestigious venues.
- Cross-check contradictory papers and explain possible reasons for disagreement.
- Help the user get closer to scientific truth through argument and evidence, not citation count alone.
