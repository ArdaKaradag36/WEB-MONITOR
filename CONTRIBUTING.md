## Contributing to WatchDog

Thanks for considering contributing to WatchDog! This document explains how to set up
your development environment, run tests, and what we expect from pull requests.

---

## Development setup

1. **Clone the repository**

```bash
git clone <repo-url> WEB-MONITOR
cd WEB-MONITOR
```

2. **Create and activate a virtualenv**

```bash
python -m venv .venv
source .venv/bin/activate           # Windows: .venv\Scripts\activate
```

3. **Install dependencies**

```bash
pip install -r watchdog/requirements.txt
```

For editable/package mode:

```bash
pip install -e ./watchdog
```

---

## Running tests

We expect all tests to pass before a PR is merged:

```bash
pytest watchdog
```

Optionally, you can also run a quick syntax check:

```bash
python -m compileall watchdog/src
```

---

## Code style

- Prefer idiomatic, type-annotated Python.
- If you use formatters/linters locally, we recommend:
  - `black` for formatting (default 88 columns),
  - `isort` for import ordering,
  - `ruff` or `flake8` for linting.
- The CI currently focuses on tests and basic syntax checks; a dedicated linting
  workflow can be added later.

When in doubt, follow the existing style of the module you are editing.

---

## Pull request guidelines

- **Tests**: New features and bug fixes should come with tests where reasonable.
- **Documentation**:
  - Update `README.md` when you add or change user-visible behavior (CLI flags,
    config fields, Docker usage, etc.).
  - Update or add examples under `watchdog/config` if you introduce new config
    patterns that users are expected to follow.
- **Scope**:
  - Prefer small, focused PRs over large, multi-purpose ones.
  - If you need to refactor existing code, try to keep refactors and feature work
    in separate commits.
- **CI**: Ensure the GitHub Actions CI pipeline is green (tests passing).

Thank you for helping improve WatchDog!

