# Academic Writing

ScholarAIO's writing support is organized as a small set of specialized skills plus one routing skill. These work best through an agent host that can load ScholarAIO skills; the examples below use Claude Code-style slash-skill names.

## Start Here

### Academic Writing Router (`/academic-writing`)

Use this first when the user knows the deliverable they want, but not which writing workflow to use. It routes by outcome, writing stage, and document type, then points to the right specialized skill or skill combination.

## Choose By Deliverable

| Deliverable | Recommended skill path |
|-------------|------------------------|
| Long-form literature review / survey | `/academic-writing` -> `/literature-review` |
| Guided deep reading of a single paper | `/academic-writing` -> `/paper-guided-reading` |
| Paper section draft (Introduction, Method, Results, Discussion, Conclusion) | `/academic-writing` -> `/paper-writing` |
| Response letter / rebuttal | `/academic-writing` -> `/review-response` |
| Research-gap memo / topic scouting | `/academic-writing` -> `/research-gap` |
| Final prose cleanup / de-AI-fication / style transfer | `/academic-writing` -> `/writing-polish` |
| Reference validation | `/citation-check` |
| Formal Word report | `/academic-writing` -> writing skill + `/document` |
| Presentation deck / advisor update slides | `/academic-writing` -> writing skill + `/document` |
| Poster content package | `/academic-writing` -> `/poster` |
| Technical or special-topic report | `/academic-writing` -> `/technical-report` |

## Choose By Writing Stage

| Stage | Recommended skill |
|-------|-------------------|
| Define scope and output format | `/academic-writing` |
| Collect and organize papers | `/workspace` |
| Read and summarize evidence | `/show` |
| Guided deep reading of a paper | `/paper-guided-reading` |
| Draft review narrative | `/literature-review` |
| Draft manuscript sections | `/paper-writing` |
| Identify open questions | `/research-gap` |
| Build a technical report or briefing | `/technical-report` |
| Build a poster-ready content package | `/poster` |
| Respond to reviewers | `/review-response` |
| Polish wording and match journal tone | `/writing-polish` |
| Verify citations before delivery | `/citation-check` |
| Turn Markdown/content into DOCX or PPTX | `/document` |

## Current Writing Skills

### Literature Review (`/literature-review`)

Generates a structured literature review from papers in a workspace. Organizes by topic, builds narrative, identifies gaps, and exports BibTeX.

### Paper Guided Reading (`/paper-guided-reading`)

Starts from a fuzzy keyword or research interest, searches the local library, confirms the target paper with the user, then loads full text for structured deep reading using a 20-point analytical framework. Outputs conversational insights rather than long reports.

### Paper Writing (`/paper-writing`)

Assists with drafting specific paper sections: Introduction, Related Work, Method, Results, Discussion, Conclusion. Uses workspace papers for citations.

### Writing Polish (`/writing-polish`)

Polishes academic prose, removes AI-generated patterns, and adapts writing to a target style. Supports English and Chinese.

### Review Response (`/review-response`)

Drafts point-by-point responses to peer reviewer comments, locating evidence from workspace papers and the manuscript.

### Research Gap (`/research-gap`)

Identifies unexplored areas and open questions by analyzing literature in a workspace through topic clustering, citation analysis, and cross-paper comparison.

### Citation Check (`/citation-check`)

Verifies citations in AI-generated or human-written text against the knowledge base. Catches hallucinated references and wrong metadata.

### Technical Report (`/technical-report`)

Builds report-oriented workflows for technical investigations, topic reports, and recommendation-style briefings. It chooses the right analysis backbone, then organizes the result into a report structure.

### Poster (`/poster`)

Builds poster-oriented workflows for conference posters and visual one-page summaries. It keeps the focus on sections, message hierarchy, and figure-to-text balance rather than paper-style prose.

### Document (`/document`)

Generates and inspects Office deliverables such as DOCX and PPTX. Use it with the writing skills above when the user wants a polished report, slide deck, or poster-style package rather than just Markdown text.

## Deliverable Notes

- ScholarAIO's current first-class document outputs are `DOCX`, `PPTX`, and `XLSX` through `/document`.
- Requests for `Beamer` or academic posters should currently be handled as content-and-structure workflows first: plan the sections, write the content, generate figures if needed, then package the result as `PPTX`/`DOCX` or another explicitly requested format.
- Technical reports and special-topic reports should usually start with `/technical-report`, which then routes to the right analysis layer and packaging steps.
- Poster requests should usually start with `/poster`, which then routes to the right content and asset workflows.

## Typical Workflow

1. Create a workspace with `/workspace` to organize relevant papers.
2. Start with `/academic-writing` if the target output is not yet mapped to a specific workflow.
3. Use the specialized writing skill for the content work.
4. Run `/citation-check` before final delivery if the output contains citations.
5. Use `/document` when the user wants a formal DOCX or PPTX deliverable.
6. Save outputs in `workspace/<name>/`.
