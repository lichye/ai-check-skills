# Report Format

The report must stand alone: a reader who has never used AI-check should understand it.

Required visible fields:

- Report title: `AI-check Report`
- Check time
- Material title (`--title`, document metadata, the first title-like line, or the file name)
- Author when available
- Check type: `AI-writing assessment`
- Scope: the model families the assessment targets
- AI score, flagged share, human share
- Flagged character count and total character count
- Flagged fragment distribution
- A table with `Text` and `AI score` columns
- Each flagged row shows `AI score: 0.xxx` in a stable text format and a risk label (low/medium/high)
- The reason appears below the fragment text and never replaces it
- Notes stating that the score is a reference judgement, unrelated to text quality, and not the output
  of any closed detector

The summary JSON carries `aiScore`, `flaggedShare`, `humanShare`, `flaggedChars`, `totalChars`,
`fragmentCount` and the report paths.

PDF output must contain selectable text. If the PDF backend is unavailable, write the HTML report and
state clearly that PDF generation was skipped.

PDF layout requirements:

- Generate the PDF directly with `reportlab`; never use LibreOffice, `soffice`, Word automation or
  DOCX-to-PDF rendering.
- Use Helvetica for Latin-only material and a CJK-capable font when the report contains CJK text.
- A4 pages with readable margins, a header card, metadata block, metric cards, a bounded distribution
  chart, repeated table headers across pages and a page-number footer.
- Body text for the report table flows in a table, never at absolute positions; long fragments wrap
  and split across pages without overlapping the score column or footer.
