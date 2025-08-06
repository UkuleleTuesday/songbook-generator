# CONVENTIONS
You MUST follow the following conventions:
* Use 80 max characters per line.
* Keep your changes small, clean and testable. Whenever possible, write unit tests first (TDD) to verify your assumptions.
* Follow usual ruff and ruff format defaults.
* NEVER include broad Exception catch-all clauses, as it will cause exceptions to be swallowed without understanding
  their root cause. Only catch expected exceptions.
* Be careful not to introduce any trailing spaces
