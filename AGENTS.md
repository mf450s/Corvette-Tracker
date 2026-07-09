# Repository Guidelines

## Project shape
- Python package under `src/corvette_tracker`; CLI entrypoint is `corvette_tracker.cli:main` and the installed script is `corvette-tracker`.
- This is a C6 Corvette listing tracker: source connectors fetch/parse public marketplace pages, normalize into `Listing`, dedupe clusters, persist SQLite snapshots, then render Markdown/JSON/CSV/HTML exports.
- Main flow in `src/corvette_tracker/cli.py`: `collect_live`/fixture parsing -> `assign_clusters` -> optional AI enrichment -> `TrackerStore.upsert_listings` -> `write_exports` -> copy `site/index.html` to root `index.html`.
- Source connectors live in `src/corvette_tracker/sources/`: AutoScout24, Kleinanzeigen, AutoUncle, Classic Trader, mobile.de.
- Database design notes are in `database/schema.dbml`; runtime storage currently creates its SQLite tables from `src/corvette_tracker/storage.py`.

## Setup and commands
- Create env/install dev deps:
  ```bash
  python3 -m venv .venv
  .venv/bin/python -m pip install -e '.[dev]'
  cp config.example.yaml config.yaml
  ```
- Prefer `rtk` wrappers where available to keep tool output compact. Known-good wrappers here: `rtk pytest`, `rtk git`, `rtk gh`, and `rtk diff`. Fall back to raw commands only when an `rtk` wrapper is missing, changes behavior, hides needed detail, or fails in a way the raw command does not.
- Run tests with compact output when the venv is on PATH:
  ```bash
  PATH="$PWD/.venv/bin:$PATH" rtk pytest -q
  ```
  Note: this project has a provider-loading test that imports `tests.test_ai_enrichment:FakeProvider`; if `rtk pytest` fails there while the raw command passes, treat it as an `rtk` wrapper/import-path limitation and verify with the CI-equivalent raw command below.
- CI-equivalent raw command, useful when verifying exact CI behavior or debugging wrapper issues:
  ```bash
  .venv/bin/python -m pytest -q
  ```
- Run one focused test:
  ```bash
  PATH="$PWD/.venv/bin:$PATH" rtk pytest tests/test_cli.py -q
  ```
- Run with live sources:
  ```bash
  .venv/bin/python -m corvette_tracker.cli run --config config.yaml --output-dir .
  ```
- Run without live network using an AutoScout24-like fixture:
  ```bash
  .venv/bin/python -m corvette_tracker.cli run --fixture path/to/fixture.html --output-dir /tmp/corvette-run
  ```

## Generated files and git hygiene
- Runtime outputs are intentionally local artifacts: `site/`, root `index.html`, `feed/latest.md`, `data/exports/*.json`, `data/exports/*.csv`, and `data/corvette_tracker.sqlite`.
- `.gitignore` already excludes the SQLite DB, `site/`, feed/export artifacts, caches, `.venv/`, and egg-info. Do not commit generated run output unless explicitly asked.
- CI runs on push/PR to `development` with Python 3.13 and only installs `.[dev]` before `python -m pytest -q`.
- Branch from `development`; PRs target `development`. Do not push directly to `main` or release branches.
- After implementing and verifying changes, commit and push the feature/fix branch without waiting for explicit prompting unless the user says not to. Use Conventional Commits. Prefer `rtk git status`, `rtk git diff`, `rtk git add`, `rtk git commit`, `rtk git push`, and `rtk gh ...` where possible; fall back to raw `git`/`gh` if the wrapper lacks needed behavior.

## Source/network gotchas
- No login/CAPTCHA/private contact scraping. Public pages only.
- AutoUncle and mobile.de can return HTTP 403 from server/CI IP ranges; the CLI should keep going and surface source warnings instead of failing the whole run.
- Classic Trader often returns zero C6 listings; keep the connector/tests valid for listings when present.
- Kleinanzeigen list pages may only expose one image; the connector loads detail pages to extract gallery images and normalizes them to `?rule=$_59.AUTO`.
- AutoScout24 thumbnail URLs like `/250x188.webp` are normalized to `/1920x1080.webp` when possible.

## Domain rules worth preserving
- The project deliberately targets Corvette C6 (2005-2013). Filter C7/C8 false positives: `Z06`, `ZR1`, and `Grand Sport` alone are not proof of C6.
- `engine` is only for explicit motor evidence (`LS2`, `LS3`, `LS7`, `LS9`). If inferred from horsepower, use `probable_engine`, `engine_confidence`, and `engine_note` instead.
- AI enrichment is optional and provider-pluggable via `module:ClassName`; it must not overwrite explicit parser/source values, only fill missing scalar fields and merge list fields.
- Risk flags and origin/import hints are heuristics; do not present them as verified facts.

## Testing notes
- Tests rely on inline HTML fixtures and `tmp_path`; prefer adding small representative fixtures inside tests over live network calls.
- `tests/conftest.py` injects `src` into `sys.path`; editable install is still the expected local/CI setup.
- For CLI behavior, assert generated files in a temporary output directory instead of writing into the repo root.
