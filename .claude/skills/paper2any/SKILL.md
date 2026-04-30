---
name: paper2any
description: Use when turning an existing ScholarAIO paper or related local asset into Paper2Any figures, diagrams, slide decks, poster/video bundles, PDF/Image-to-PPT conversions, PPT polishing, citation/rebuttal/KB workflows, or the full Paper2Any API through the managed external runtime.
---

# Paper2Any Handoff

Use this skill when the user wants Paper2Any output from a paper already managed by ScholarAIO, from a related local image/PPTX asset that should be copied into a ScholarAIO handoff bundle, or from an upstream Paper2Any web/API workflow.

Paper2Any is kept as an external runtime, not vendored into ScholarAIO. ScholarAIO can install or update the full upstream checkout under `data/runtime/extensions/paper2any/Paper2Any`. For standalone CLI workflows, it prepares a handoff bundle with the input, a manifest, and a runner script, then calls the real upstream Paper2Any CLI from that managed checkout. For web/API-only workflows, it starts the real upstream FastAPI backend through the same managed venv. Setup installs the Python runtime and frontend export dependencies used by editable PPT output.

## Workflow

1. Resolve the target paper with normal ScholarAIO identifiers.
2. Check the managed runtime, and install it when missing:

```bash
scholaraio paper2any status || scholaraio paper2any setup
```

3. Prepare a bundle:

```bash
scholaraio paper2any prepare <paper-id> --task figure --graph-type tech_route
```

4. Run the generated script with normal upstream CLI/API options:

```bash
workspace/_system/paper2any/<paper-id>/figure/run-paper2any.sh --api-key <key>
```

For upstream capabilities that are exposed as service routes rather than standalone scripts, list the capabilities and start the backend:

```bash
scholaraio paper2any capabilities
scholaraio paper2any serve --port 9999
```

If the runtime lives outside the managed default, configure it once instead of repeating paths:

```bash
scholaraio paper2any setup --root <Paper2Any checkout>
scholaraio paper2any prepare <paper-id> --task ppt --page-count 12 --language en
workspace/_system/paper2any/<paper-id>/ppt/run-paper2any.sh --api-key <key>
```

## Standalone Task Selection

| Need | Command |
|------|---------|
| Scientific figure or technical route diagram | `scholaraio paper2any prepare <paper-id> --task figure --graph-type model_arch` |
| Editable presentation from a paper | `scholaraio paper2any prepare <paper-id> --task ppt --page-count 12` |
| Classic Paper2PPT upstream path | `scholaraio paper2any prepare <paper-id> --task ppt-classic --page-count 12` |
| Editable PPT from a PDF slide/report source | `scholaraio paper2any prepare <paper-id> --task pdf2ppt` |
| Image or screenshot to PPT | `scholaraio paper2any prepare <paper-id> --task image2ppt --source-file path/to/image.png` |
| Polish an existing PPT/PPTX | `scholaraio paper2any prepare <paper-id> --task ppt2polish --source-file path/to/deck.pptx` |
| Academic poster from paper PDF | `scholaraio paper2any prepare <paper-id> --task poster` |
| Video script/narration assets from paper PDF | `scholaraio paper2any prepare <paper-id> --task video --language en` |

`figure` supports `--graph-type model_arch`, `tech_route`, and `exp_data`.
`ppt` uses Paper2Any's frontend editable CLI by default and exports `frontend_slides.json`, `frontend_theme.json`, `frontend_summary.json`, and `paper2ppt_frontend_editable.pptx`. The default path does not require a separate image-generation model; pass upstream frontend CLI options to the generated runner only when needed.
`ppt-classic` uses upstream `script/run_paper2ppt_cli.py`; it may require an image-generation-capable model depending on upstream options.

## API Workflow Selection

Use `scholaraio paper2any serve` for Paper2Any features that are implemented as FastAPI/web workflows rather than standalone CLI scripts:

| Need | Upstream surface |
|------|------------------|
| Paper/text or image to draw.io diagrams | `/api/v1/paper2drawio/*`, `/api/v1/image2drawio/*` |
| Rebuttal and revision-response drafting | `/api/v1/paper2rebuttal/*` |
| Citation exploration | `/api/v1/paper2citation/*` |
| Image model playground | `/api/v1/image-playground/*` |
| Mind maps | `/api/v1/mindmap/*` |
| Knowledge-base upload/search/chat/PPT/podcast/report | `/api/v1/kb/*` |

Use `scholaraio paper2any capabilities` before choosing a path when the request is broad or the user asks what Paper2Any can do.

## Input Rules

- Default input is `auto`: use `paper.pdf` when present, otherwise use `paper.md` as text for Paper2Any figure/PPT workflows.
- Use `--input pdf` when Paper2Any must see the original PDF.
- Use `--input markdown` only for `figure`, `ppt`, or `ppt-classic`.
- `pdf2ppt`, `poster`, and `video` require `paper.pdf`.
- `image2ppt` and `ppt2polish` require `--source-file`; ScholarAIO copies that local asset into the bundle.
- Upstream Paper2Any also contains FastAPI/KB/router workflows such as citation, technical report, rebuttal, DrawIO, mindmap, podcast, and deep research. Use `paper2any serve` for those instead of `paper2any prepare`.

## Verification

Do not stop after bundle creation. Actually run the generated `run-paper2any.sh` when the Paper2Any checkout and credentials are available, then inspect the files under the bundle `outputs/` directory.
