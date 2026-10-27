---
name: ai-check
description: Generate reference AI-writing-rate reports for Word/DOCX files or LaTeX/Overleaf projects (Chinese or English academic writing) and, after explicit user confirmation, apply AI-assisted revisions to a new DOCX, optionally as Word tracked changes. Use when the user asks to check a paper's AI-writing rate (AI率/AIGC率), create an AI-rate PDF/HTML report, or reduce AI-writing style (降AI率) based on that report.
license: MIT
compatibility: Requires Python 3.10+ with python-docx>=1.1 and reportlab>=4. No LibreOffice, Word automation or network access needed.
---

# AI-check

AI-check turns a DOCX or a LaTeX source (a `.tex` file or an Overleaf project directory) into a
reference AI-writing-rate report, then optionally helps revise suspicious passages after the user confirms.

## Core Rules

- Assistant-judged: you (the assistant) judge `aigcValue`, `verdict`, reasons, and rewrites in the
  visible conversation. Bundled Python scripts only read/write DOCX, JSON, HTML/PDF, and
  deterministic text signals; they never call a model or output a probability.
- Independent document pipeline: do not use LibreOffice, `soffice`, Office automation, DOCX-to-PDF
  rendering, or screenshot-based document rendering for AI-check reports. DOCX is read through
  `python-docx`; PDF is produced directly with `reportlab` as selectable text.
- Never claim alignment with CNKI, VIP, Turnitin, or any closed detector. Say the report is for
  reference.
- Do not modify the original DOCX in place. Write reports and rewritten DOCX files beside the source
  or under a user-provided output directory (`ai_rewrite_docx.py` refuses `--out` equal to the source).
- Ask for confirmation before applying revisions to Word.
- Preserve facts, terminology, numbers, formulas, citation markers, and conclusion direction.

## Workflow

0. Use a Python 3.10+ interpreter (for example `python3.11` when the default `python3` is older).
   If `python-docx` or `reportlab` is missing, run `<python> -m pip install --user "python-docx>=1.1" "reportlab>=4"`.
   Do not run the scripts with `python -I` when the deps are in user site-packages: `-I` hides them.
1. Run `scripts/ai_check.py scan <source> --out <scan.json>` to extract chunks in document order.
   `<source>` is a `.docx`, a `.tex` file, or a LaTeX project directory. Feed LaTeX directly, with no
   conversion to DOCX: the scanner picks the file with `\documentclass` (preferring `main.tex`),
   follows `\input`/`\include`, uses `\section`-like commands (including custom wrappers such as
   `\tsection`), `\paragraph{..}` and leading `\textbf{Label.}` as headings, numbers citations as
   `[n]`, and drops comments, floats, display math, the bibliography and `\todo{..}` notes.
   Tables are skipped by default; add `--include-tables` only if the user wants table text judged.
2. Judge chunks in order. Use each chunk's `traceFeatures.riskSignals` and
   `traceFeatures.mitigatingSignals` as evidence, but do not treat them as a score.
3. Save a results JSON (one entry per judged chunk):

   ```json
   {"results": [{"chunkId": "chunk-0001", "sensitivity": "medium", "aigcValue": 0.62,
                 "verdict": "suspicious", "reason": "模板化收束，缺少方法边界", "signals": ["模板表达", "泛化套话"]}]}
   ```

   `aigcValue` is 0–1, `verdict` is `ai` / `suspicious` / `human`, `sensitivity` is `low` / `medium` / `high`.
4. Run `scripts/ai_check.py report <scan.json> <results.json> --out-dir <dir>` to generate an
   HTML report and a polished selectable-text PDF (A4, summary cards, distribution chart, repeated
   table headers, page numbers).
5. Show the report path and summary. Ask whether to revise the Word document.
   For a LaTeX source, steps 6–8 do not apply: the rewrite script only writes DOCX. After the user
   confirms, give each revision as `file:line` + original sentence + revised sentence, locating the
   sentence in the `.tex` with grep. Edit the `.tex` files only when the user asks for that.
6. If the user confirms a DOCX revision, prepare a replacements JSON from the report and source chunks:

   ```json
   {"replacements": [{"chunkId": "chunk-0001", "sourceText": "原文中的一句或一段（逐字复制）",
                      "replacementText": "改写后的文字", "reason": "去掉模板化收束"}]}
   ```

   `sourceText` must be copied verbatim from the chunk text (whitespace differences are tolerated).
   Add `"occurrence": N` when the same text appears in several paragraphs.
7. Run `scripts/ai_rewrite_docx.py dry-run <docx> <replacements.json>` and fix every item whose
   `willApply` is false (not found, ambiguous, missing citation marks or missing numbers).
8. Run `scripts/ai_rewrite_docx.py apply <docx> <replacements.json> --out <new.docx> --track-changes`
   so the user can accept or reject each edit in Word. Omit `--track-changes` only if the user wants
   a clean copy. Only the changed characters are rewritten; formatting, superscript citations,
   equations, images and fields elsewhere in the paragraph are preserved.

## Detection Guidance

- Initial sensitivity is `medium`.
- Do not include titles, keywords, table-of-contents entries, references, cover pages, declarations,
  or short metadata-like text in the final report.
- `aigcValue < 0.30` is recorded but not shown as a suspicious report fragment.
- High scores require concrete, revisable risks: template phrases, contribution-list style,
  uniformly smooth rhythm, dense connectors, generic value claims or buzzwords (赋能/助力/至关重要,
  "pivotal", "underscore", "delve"), stacked dashes, missing boundaries, or weak source-specific
  evidence.
- Do not score high only because the writing is academic, technical, citation-heavy, or structurally
  orderly. Citations, model names, metrics, statistics, experiments, data, limitations, and concrete
  method details are mitigating signals.
- For `aigcValue >= 0.70`, include at least two risk signals and explain why mitigating signals do
  not fully offset them.

## Revision Guidance

- Read the report reason/signals and convert them into rewrite goals.
- Medium rewriting should remove the actual risk signals rather than making text smoother and more
  templated.
- For generic value claims, lower the tone and add boundaries from the source context.
- For contribution-list style, vary sentence rhythm and integrate claims into local context.
- For dense connectors or uniform rhythm, reduce obvious connectors and allow natural variation.
- If the source lacks evidence, do not invent evidence. Use limitation, scope, or author-choice
  language instead.
- Keep every citation marker and every number. The rewrite script skips replacements that drop a
  citation such as `[4]` or a number such as `2.1`; set `"allowNumberChange": true` on an item only
  when the user explicitly approved changing that number.

## References

- Read `references/ai_rate_signals.md` for the shared risk/mitigation signal vocabulary.
- Read `references/report_format.md` when changing report output expectations.
