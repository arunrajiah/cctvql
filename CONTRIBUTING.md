# Contributing to cctvQL

Thank you for considering a contribution! cctvQL grows through the community — especially through **new adapters** for CCTV systems.

---

## Table of Contents

- [Ways to Contribute](#ways-to-contribute)
- [Development Setup](#development-setup)
- [Writing an Adapter](#writing-an-adapter)
- [Code Style](#code-style)
- [Pull Request Guidelines](#pull-request-guidelines)
- [Reporting Bugs](#reporting-bugs)
- [Requesting Features](#requesting-features)

---

## Ways to Contribute

| Contribution | Impact | Difficulty |
|---|---|---|
| Write a new CCTV adapter | ⭐⭐⭐⭐⭐ | Medium |
| Fix a bug | ⭐⭐⭐ | Low–Medium |
| Improve NLP prompts | ⭐⭐⭐ | Low |
| Add tests | ⭐⭐ | Low |
| Improve documentation | ⭐⭐ | Low |
| Translate docs | ⭐⭐ | Low |

---

## Development Setup

```bash
# Fork and clone
git clone https://github.com/YOUR_USERNAME/cctvql.git
cd cctvql

# Create a virtual environment
python -m venv .venv
source .venv/bin/activate      # Windows: .venv\Scripts\activate

# Install in editable mode with dev extras
pip install -e ".[dev,mqtt,onvif]"

# Verify everything works
pytest tests/ -v
```

---

## Writing an Adapter

The single highest-impact contribution. See the full guide: **[docs/adapters.md](docs/adapters.md)**

Quick checklist:
- [ ] Create `cctvql/adapters/your_system.py`
- [ ] Subclass `BaseAdapter` and implement all abstract methods
- [ ] Register in `cctvql/_bootstrap.py`
- [ ] Add to `cctvql/adapters/__init__.py`
- [ ] Write tests in `tests/test_your_system_adapter.py`
- [ ] Add to compatibility table in `README.md`
- [ ] Add config example to `config/example.yaml`

---

## Code Style

We use [Ruff](https://docs.astral.sh/ruff/) for linting and formatting.

```bash
# Check linting
ruff check cctvql/

# Auto-fix
ruff check --fix cctvql/

# Type checking
mypy cctvql/
```

Key conventions:
- All public methods need docstrings
- Use `Optional[X]` not `X | None` for Python 3.10 compat
- Async methods for all I/O operations
- Never raise exceptions from adapter methods — log and return `None` or `[]`
- Add `metadata: dict` to all schema objects for adapter-specific extra data

---

## Pull Request Guidelines

1. **One PR per feature or fix** — keep them focused and easy to review
2. **Tests are required** for new adapters and bug fixes
3. **Update docs** if you change behavior or add config options
4. **Run the full test suite** before opening a PR: `pytest tests/ -v`
5. **Use a descriptive PR title**: `feat: add Hikvision adapter` or `fix: correct Frigate timestamp parsing`

### Commit message format

```
type: short description

Optional longer description.

Fixes #123
```

Types: `feat`, `fix`, `docs`, `test`, `refactor`, `chore`

---

## Reporting Bugs

Please use the [Bug Report template](https://github.com/arunrajiah/cctvql/issues/new?template=bug_report.md).

Include:
- cctvQL version and Python version
- Your config (redact passwords/API keys)
- Full error output with `logging.level: DEBUG`
- Steps to reproduce

---

## Requesting Features

Use the [Feature Request template](https://github.com/arunrajiah/cctvql/issues/new?template=feature_request.md).

Please describe:
- What you want to do and why
- Any API docs for the system you want supported

---

## Code of Conduct

Be respectful and constructive. We're all here to build something useful for the community. Harassment, discrimination, or toxic behavior will not be tolerated.

---

## Questions?

Open a [Discussion](https://github.com/arunrajiah/cctvql/discussions) — we're happy to help you get started.
