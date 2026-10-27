---
name: ai-check
description: Give any material an AI score — how likely it is that a large language model wrote or polished it. Works on documents, papers, proposals, theses, essays, reports, emails, web pages and pasted text, in English or Chinese, from DOCX, PDF, LaTeX/Overleaf, Markdown, HTML or plain text. Produces fragment-level scores with reasons and an HTML/PDF report, and after explicit user confirmation helps revise the flagged passages. Use when the user asks for an AI score, AI-writing check, AI rate, "does this read as AI-written", or wants to reduce AI-writing style.
license: MIT
compatibility: Requires Python 3.10+ with python-docx>=1.1 and reportlab>=4; PDF input also needs pypdf. No LibreOffice, Word automation or network access needed.
---

# AI-check

AI-check gives any piece of writing an **AI score**: a 0–100% estimate of how much of it reads as
written or polished by a large language model. The assistant judges each fragment; the bundled scripts
extract text, collect deterministic evidence signals and render the report.

## Core Rules

- Assistant-judged: you (the assistant) set each fragment's `aiScore`, `verdict`, reason and signals in
  the visible conversation. The scripts only read and write files and compute deterministic text signals;
  they never call a model or output a probability.
- The score is a reference judgement. Never claim it matches Turnitin, GPTZero, CNKI or any other closed
  detector, and say so when you report it.
- The score measures AI-writing style. It says nothing about the quality or correctness of the material.
- Never modify the source in place. Reports and rewritten files go beside the source or into a
  user-provided output directory.
- Ask for confirmation before applying any revision.
- Revisions preserve facts, terminology, numbers, formulas, citation markers and the direction of every
  conclusion.

## Inputs

`scripts/ai_check.py scan` reads:

| Input | How it is read |
| --- | --- |
| `.docx` | Body paragraphs in document order (content controls included). |
| `.pdf` | Page text via `pypdf`; soft line wraps and hyphenation are joined. Scanned PDFs without a text layer yield nothing. |
| `.tex` file or LaTeX/Overleaf project directory | The file with `\documentclass` (preferring `main.tex`), with `\input`/`\include` followed. `\section`-like commands (including custom wrappers such as `\tsection`), `\paragraph{..}` and leading `\textbf{Label.}` become headings; citations become `[n]`; comments, floats, display math, the bibliography and `\todo{..}` notes are dropped. |
| `.md` / `.markdown` / `.qmd` / `.rmd` | `#` headings become sections; front matter, fenced code and HTML comments are dropped; links keep their text. |
| `.html` / `.htm` | Visible text; `script`, `style`, `nav`, `footer` and `head` are dropped; `h1`–`h6` become sections. |
| any other file | Plain UTF-8 text; blank lines separate paragraphs. |
| `-` or `--text "..."` | Pasted material from stdin or the command line. |

Tables are skipped by default; add `--include-tables` when the user wants table text judged.

## Workflow

0. Use a Python 3.10+ interpreter (for example `python3.11` when the default `python3` is older).
   Install missing dependencies with `<python> -m pip install --user "python-docx>=1.1" "reportlab>=4" pypdf`.
   Run the scripts without `-I` when the dependencies live in user site-packages: `-I` hides them.
1. Extract fragments:

   ```bash
   <python> scripts/ai_check.py scan <source> --out <scan.json> [--title "..."] [--include-tables]
   <python> scripts/ai_check.py scan --text "pasted material" --title "Email draft" --out <scan.json>
   ```

   For pasted material, write it to a file in a scratch directory or pass it with `--text`/stdin.
2. Judge the chunks in order. Read each chunk's `traceFeatures.riskSignals` and
   `traceFeatures.mitigatingSignals` as evidence; they are inputs to your judgement, never a score.
   `traceFeatures.clarityIssues` lists ambiguous pronouns and bare demonstratives. They leave the
   AI score unchanged and go on the revision list.
3. Save a results JSON with one entry per judged chunk:

   ```json
   {"results": [{"chunkId": "chunk-0001", "sensitivity": "medium", "aiScore": 0.62,
                 "verdict": "suspicious", "reason": "Trend opener and a stated goal repeated twice.",
                 "signals": ["trend opener", "repeated goal"]}]}
   ```

   `aiScore` is 0–1 (0–100 is also accepted), `verdict` is `ai` / `suspicious` / `human`,
   `sensitivity` is `low` / `medium` / `high`. Write reasons in the language the user writes in.
4. Render the report:

   ```bash
   <python> scripts/ai_check.py report <scan.json> <results.json> --out-dir <dir>
   ```

   It writes an HTML report, a selectable-text A4 PDF and a summary JSON. The summary's `aiScore` is the
   headline number: flagged characters weighted by their fragment scores, over all characters.
   `flaggedShare` is the share of characters in fragments scored 0.30 or higher.
5. Tell the user the AI score, the few fragments that drive it (with the concrete signals), any
   clarity issues worth fixing, and the report path. Ask whether they want revisions.

## Revising after confirmation

- **DOCX**: build a replacements JSON, check it, then write a new file as Word tracked changes.

  ```json
  {"replacements": [{"chunkId": "chunk-0001", "sourceText": "a sentence copied verbatim from the chunk",
                     "replacementText": "the revised sentence", "reason": "remove the trend opener"}]}
  ```

  Run `scripts/ai_rewrite_docx.py dry-run <docx> <replacements.json>` and fix every item whose
  `willApply` is false (not found, ambiguous, dropped citation or number). Add `"occurrence": N` when the
  same text appears more than once. Then run
  `scripts/ai_rewrite_docx.py apply <docx> <replacements.json> --out <new.docx> --track-changes`.
  Formatting, superscript citations, equations, images and fields outside the changed characters are kept.
- **Every other format** (LaTeX, Markdown, HTML, plain text, PDF, pasted text): give each revision as
  location (`file:line` where a file exists) + original sentence + revised sentence. Edit the source files
  only when the user asks for that, and rescan afterwards to report the new score.

## Detection Guidance

- Start at `medium` sensitivity.
- Leave out titles, headings, keywords, tables of contents, references, cover pages, signatures, code
  and short metadata-like lines.
- 0.30 is the rewrite line: a fragment at 0.30 or above already reads as AI-written to a careful reader.
  Below 0.30 it is recorded and stays out of the flagged list; 0.30–0.59 is medium risk, 0.60 and above
  high risk.
- A high score needs concrete, revisable risks: trend openers, template transitions, contribution-list
  structure, uniformly smooth sentence rhythm, dense connectors, generic value claims, LLM-favoured
  vocabulary ("delve", "pivotal", "underscore", "seamless"), stacked dashes, the same goal stated twice,
  over-defense, or claims with no source-specific evidence.
- Over-defense is a risk signal in its own right: writing that argues against an imagined objection.
  It shows up as negation contrasts ("rather than", "instead of", "not X but Y"), guard clauses
  ("only when", "under the original assumptions", "provided that"), disclaimers ("we do not claim",
  "note that"), stacked hedges, several qualifiers pinned onto one detail ("the original property on the
  full RTL under the original assumptions"), and the same guard phrase repeated across paragraphs.
  Restating a condition the reader already assumes ("proved only when every proof holds") is
  over-defense. Unbounded defense of a specific detail is one of the most irritating AI-writing habits;
  score it like any other template.
- Formal, technical, citation-heavy or well-organised writing is no evidence of AI on its own. Citations,
  named methods, metrics, statistics, experiment details, data and author-specific detail are mitigating
  signals. A limitation counts as mitigating when it is concrete and stated once ("the team was already
  experienced with asynchronous tools"); boundaries inside an over-defended passage are part of the risk.
- For `aiScore >= 0.70`, name at least two risk signals and explain why the mitigating signals do not
  offset them.
- Match the genre: an email, a grant proposal and a novel chapter each have their own normal register.
  Judge against what a human writer of that genre would produce.

## Revision Guidance

- The goal of a revision is every fragment below 0.30. Rescan after rewriting and report the new scores.
- Turn each fragment's reason and signals into rewrite goals.
- Remove the actual risk signals. Making text smoother, more balanced or more formal keeps or raises the
  AI style.
- Lower the tone of generic value claims by replacing them with what the source actually did or measured.
- Break contribution-list structure by varying sentence rhythm and tying claims to local context.
- Cut obvious connectors and let sentence length vary naturally.
- Repeat the noun when a pronoun could point to more than one earlier noun: "a formal check validates
  the contract", never "a formal check validates it" after "an LLM proposes each contract". Give every
  "This"/"These" a noun ("This bottleneck…"). A rewrite never introduces such a pronoun.
- For over-defense, delete guards the reader already assumes, state each necessary condition once and
  positively, and write the claim as a plain fact. A rewrite never adds caveats, contrasts or disclaimers.
- When the source lacks evidence, shrink the claim to what the source supports; never invent evidence.
- Keep every citation marker and every number. The DOCX rewrite script skips replacements that drop a
  citation such as `[4]` or a number such as `2.1`; set `"allowNumberChange": true` on an item only when
  the user explicitly approved changing that number.

## References

- `references/ai_score_signals.md`: the shared risk and mitigating signal vocabulary.
- `references/report_format.md`: what the report must contain; read it before changing report output.
