---
name: paper2any
description: Use when turning an existing ScholarAIO paper into Paper2Any figures, technical route diagrams, or presentation slides through an external Paper2Any checkout.
---

# Paper2Any Handoff

Use this skill when the user wants Paper2Any output from a paper already managed by ScholarAIO.

Paper2Any is kept as an external tool. ScholarAIO prepares a handoff bundle with the paper input, a manifest, and a runner script; the generated script then calls the upstream Paper2Any CLI from a separate checkout.

## Workflow

1. Resolve the target paper with normal ScholarAIO identifiers.
2. Prepare a bundle:

```bash
scholaraio paper2any prepare <paper-id> --task figure --graph-type tech_route
```

3. Point the generated runner at Paper2Any and pass normal upstream CLI/API options:

```bash
PAPER2ANY_ROOT=<Paper2Any checkout> workspace/_system/paper2any/<paper-id>/figure/run-paper2any.sh --api-key <key>
```

If the Paper2Any checkout location is stable, bake it into the runner:

```bash
scholaraio paper2any prepare <paper-id> --task ppt --paper2any-root <Paper2Any checkout> --page-count 12 --language en
workspace/_system/paper2any/<paper-id>/ppt/run-paper2any.sh --api-key <key>
```

## Task Selection

| Need | Command |
|------|---------|
| Scientific figure or technical route diagram | `scholaraio paper2any prepare <paper-id> --task figure --graph-type model_arch` |
| Presentation from a paper | `scholaraio paper2any prepare <paper-id> --task ppt --page-count 12` |
| Editable PPT from a PDF slide/report source | `scholaraio paper2any prepare <paper-id> --task pdf2ppt` |

`figure` supports `--graph-type model_arch`, `tech_route`, and `exp_data`.

## Input Rules

- Default input is `auto`: use `paper.pdf` when present, otherwise use `paper.md` as text for Paper2Any figure/PPT workflows.
- Use `--input pdf` when Paper2Any must see the original PDF.
- Use `--input markdown` only for `figure` or `ppt`; `pdf2ppt` requires a PDF.

## Verification

Do not stop after bundle creation. Actually run the generated `run-paper2any.sh` when the Paper2Any checkout and credentials are available, then inspect the files under the bundle `outputs/` directory.
