# Graphviz DOT/SVG Diagram Workflow

This guide covers the Graphviz path used by ScholarAIO's `diagram` command and
the `/draw` skill. It is a workflow guide, not a full Graphviz reference: the
current renderer emits DOT source and compiles SVG through the `dot` command.

Use this path when you want version-controlled scientific figures that can be
inserted into Markdown, LaTeX, or Beamer without rasterization blur.

## When To Use Graphviz

| Need | Recommended output | Why |
|------|--------------------|-----|
| Paper or Beamer architecture figure | `svg` | Vector output, stable scaling, reusable in LaTeX |
| Reviewable diagram source | `dot` | Plain text, easy to diff and manually tune |
| Collaborative manual editing | `drawio` | Import into diagrams.net and adjust layout by hand |
| Fast Markdown preview | `mermaid` | No Graphviz dependency, easy inline rendering |

Choose Graphviz when layout should be mostly automatic, labels are concise, and
the final artifact should remain editable as text. Choose `drawio` when exact
manual placement matters more than reproducible source.

## Prerequisites

Install Graphviz so the `dot` executable is available. If you plan to insert
SVGs into Beamer with `\includesvg`, install Inkscape at the same time:

```bash
# Ubuntu/Debian
sudo apt-get install graphviz inkscape

# macOS
brew install graphviz
brew install --cask inkscape

# Conda, useful when you only need dot/SVG rendering inside an env
conda install -c conda-forge graphviz

# Verify the commands that ScholarAIO and Beamer depend on
dot -V
inkscape --version
```

`scholaraio setup check` also reports `Graphviz dot` and `Inkscape` so agents can
diagnose missing renderer tools before running a diagram workflow. For Beamer
SVG insertion, compile LaTeX with `-shell-escape`. See the
[Academic Beamer Guide](academic-beamer-guide.md) for the surrounding
slide-production rules.

## Generate DOT Or SVG

From a paper record:

```bash
python -m scholaraio.cli diagram <paper-id> --type model_arch --format svg
```

From a plain text description:

```bash
python -m scholaraio.cli diagram \
  --from-text "Input data flows into encoder, decoder, and prediction head" \
  --type model_arch \
  --format svg
```

To keep only the intermediate representation:

```bash
python -m scholaraio.cli diagram <paper-id> --type model_arch --dump-ir
```

To render an existing IR file into DOT or SVG:

```bash
python -m scholaraio.cli diagram \
  --from-ir workspace/_system/figures/diagram_example.ir.json \
  --format dot

python -m scholaraio.cli diagram \
  --from-ir workspace/_system/figures/diagram_example.ir.json \
  --format svg
```

By default, generated figures are written through `workspace_figures_dir`,
usually `workspace/_system/figures/`. SVG rendering also preserves a `.dot`
sidecar with the same base filename.

## Current Renderer Mapping

ScholarAIO converts IR fields into DOT with a deliberately small mapping:

| IR field | DOT behavior |
|----------|--------------|
| `title` | Graph label at the top |
| `layout_hint: horizontal` or `bipartite` | `rankdir=LR` |
| Other `layout_hint` values | `rankdir=TB` |
| `layer` | Nodes are grouped into invisible layer clusters |
| `type: data` | Ellipse with pale green fill |
| `type: operation` | Rounded box with pale orange fill |
| `type: decision` | Diamond with pale pink fill |
| Other node types | Rounded box with pale blue fill |
| edge `label` | DOT edge label |
| edge `style` | DOT edge style such as `solid`, `dashed`, or `bold` |

The current implementation does not automatically switch to `neato`, `fdp`,
`sfdp`, `twopi`, or `circo`. If you need those engines, export DOT first and run
Graphviz manually.

```bash
dot -Tsvg workspace/_system/figures/diagram_example.dot \
  -o workspace/_system/figures/diagram_example.svg
```

## Manual DOT Tuning

The generated `.dot` file is meant to be safe to inspect and adjust. Common
tuning moves:

```dot
// Keep related nodes on the same rank.
{ rank=same; "encoder"; "decoder"; }

// Encourage ordering without drawing a visible connector.
"input" -> "encoder" [style=invis, weight=10];

// Let an auxiliary edge avoid forcing layout.
"metadata" -> "prediction" [style=dashed, constraint=false];
```

Keep labels short. For dense academic figures, prefer explicit line breaks over
long horizontal labels:

```dot
"encoder" [label="Encoder\nmulti-scale features"];
```

For Chinese labels or mixed-language figures, set a font available on the target
machine:

```dot
graph [fontname="Noto Sans CJK SC"];
node [fontname="Noto Sans CJK SC"];
edge [fontname="Noto Sans CJK SC"];
```

## Beamer Insertion

For Beamer, insert the generated SVG directly:

```latex
\usepackage{svg}

\begin{frame}
\centering
\includesvg[width=0.8\columnwidth]{workspace/_system/figures/diagram_example.svg}
\end{frame}
```

Compile with `xelatex` or `lualatex` plus `-shell-escape`, and make sure
Inkscape is installed. If the deck is archived or moved, copy the SVG and DOT
source into the deck's local `images/` or `figures/` directory and update the
path accordingly.

## Troubleshooting

| Symptom | Fix |
|---------|-----|
| `Graphviz dot command was not found` | Install Graphviz and confirm `dot -V` works |
| SVG generation fails but DOT exists | Run `dot -Tsvg <file.dot> -o <file.svg>` to see the native Graphviz error |
| Layout is too wide | Re-render from edited IR with `layout_hint: vertical`, or edit DOT to add ranks |
| Layout is too tall | Use `layout_hint: horizontal`, or add same-rank groups in DOT |
| CJK labels render as boxes | Set `fontname` to an installed CJK font in the DOT file |
| Beamer cannot include SVG | Use `\usepackage{svg}`, compile with `-shell-escape`, and install Inkscape |
| Exact placement is still poor | Export `drawio` and manually refine in diagrams.net |

## Quality Checklist

- [ ] The diagram answers one visual question, not an entire paper.
- [ ] Node labels are short enough to read at slide or paper scale.
- [ ] Edge labels are used only when they add information.
- [ ] The `.dot` sidecar is kept with the exported `.svg`.
- [ ] The SVG is inspected at the final target size.
- [ ] Beamer decks compile with `-shell-escape` before delivery.

## Related References

- [CLI Reference](../guide/cli-reference.md) for `scholaraio diagram` options.
- [Academic Beamer Guide](academic-beamer-guide.md) for slide layout and SVG insertion rules.
- `/draw` skill for agent-side routing between Graphviz, Mermaid, drawio, and custom SVG workflows.
