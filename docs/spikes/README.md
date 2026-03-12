# Spikes

This folder contains time-boxed research and analysis documents produced before
committing to an implementation approach.

## When to write a spike

Write a spike when you need to reduce uncertainty about a design decision,
an unfamiliar API, or a significant refactor before writing production code.

## File naming convention

```
<github-issue-number>-<short-kebab-case-description>.md
```

Examples:

```
281-metadata-storage-analysis.md
312-gcs-signed-url-approach.md
```

- **Prefix with the GitHub issue number** so the spike can be traced back to its
  motivating issue.
- **Use kebab-case** for the rest of the name; keep it short (3–5 words).

## What to include

A spike document should cover:

1. **Problem statement** – what question the spike is answering.
2. **Findings** – observed behaviour, relevant code references, constraints.
3. **Options** – candidate approaches with pros and cons.

Spikes are reference documents; they do not need to be kept up to date after the
work is complete.
