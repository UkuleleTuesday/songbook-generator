# Agent Guidance

## Prose (Issues, PR descriptions, comments)

- Stay concise and to the point
- Any prose beyond 250 words on a single issue, description or comment has to be seriously earned.

### Pull requests

- Focus on the why behind a change instead of the how.
- Do not re-state or list what changes.

## Code

- Keep changes focused and follow established patterns in nearby code.
- For behavior changes, add or update tests and run `uv run pytest`.
- Before committing, run `uvx --from 'pre-commit<5' pre-commit run --all-files`.
- Refer to `README.md` for the project overview, setup, CLI, configuration,
  and deployment documentation; avoid duplicating those details here.
