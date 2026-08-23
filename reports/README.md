# Run reports

`python ontology.py SOURCE GRAPH --report` writes a verbose Markdown report to
`reports/runs/` and keeps the terminal silent on a successful run.

The report separates the full graph skeleton used by context selection from the
exact system and user messages ultimately sent to the extraction LLM.

Each file is named with the local run time and source name. Reports contain
stable phase headings, the parsed extraction, validation diagnostics, merge
decisions and reason codes, and the final graph changes. This makes them useful
for both human review and later AI analysis.

Generated reports are intentionally ignored by Git because they can be large
and may contain source-derived information.
