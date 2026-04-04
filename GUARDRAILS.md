# Commit Guardrails

Rules for keeping this repo clean, safe, and reproducible.

---

## Never commit these

| What | Why |
|------|-----|
| `agents.md` | AI-generated, user-specific output — already in `.gitignore` |
| `*.pptx` | Binary presentation files — large, personal, not source code |
| `.env`, `*.key`, `*.token` | Secrets and API tokens |
| `poetry.lock` | Lock file is machine-specific for a library — already in `.gitignore` |
| `dist/`, `build/` | Build artifacts — regenerated via `poetry build` |
| `__pycache__/`, `*.pyc` | Python bytecode — already in `.gitignore` |
| `.venv/`, `venv/` | Virtual environments — never belong in source control |

---

## AI-assisted commits

If a commit includes AI-generated or AI-assisted code:

- Review every line before committing — don't blindly commit AI output
- Do not commit AI-generated content that you don't understand
- The `agents.md` file is always AI-generated output — never commit it

---

## Pre-commit checks (enforced automatically)

Install the hooks once:

```bash
pip install pre-commit
pre-commit install
```

Hooks run automatically on every `git commit`:

- **ruff** — linting and formatting
- **no-secrets** — blocks accidental token/key commits
- **large-files** — blocks files over 1MB
- **pptx guard** — blocks `.pptx` files
- **agents.md guard** — blocks committing generated output

---

## Dependency changes

- Add dependencies via `poetry add <package>` only
- Never manually edit `[tool.poetry.dependencies]` without running `poetry install` after
- Optional dependencies (like `ollama`) must NOT be added to `pyproject.toml` — import them at runtime with a try/except

---

## Branch rules

| Branch | Purpose |
|--------|---------|
| `main` | Stable, published releases only |
| `feature/*` | New features |
| `fix/*` | Bug fixes |

Never push directly to `main`. Open a PR.