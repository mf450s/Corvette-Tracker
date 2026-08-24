# C6 Corvette Tracker

A Python-based marketplace tracker for **Chevrolet Corvette C6** listings. The tracker crawls public listing pages, normalizes vehicle data relevant to a purchase, detects changes through SQLite snapshots, and generates a static website with feed and export files.

The project deliberately focuses on **C6 (2005–2013)**. Other Corvette generations are filtered out on a best-effort basis.

## What the project currently does

- fetches public search results for C6 Corvette listings
- extracts structured vehicle data from listing HTML/JSON
- detects C6-relevant fields such as price, mileage, first registration, inspection status, engine, trim, transmission, and location
- flags risks such as accidents, damage, unclear mileage, missing inspection data, import or salvage hints, and heavy modifications
- derives a **probable engine** from horsepower when the listing does not contain an explicit engine code
- collects high-quality images, including detail galleries from Kleinanzeigen
- deduplicates obvious duplicate listings and creates clusters
- stores snapshots locally in SQLite to detect new listings and price changes
- generates Markdown, JSON, CSV, and HTML exports
- renders a static website with cards, images, and gallery thumbnails

## Sources

| Source | Status | Behavior |
|---|---:|---|
| AutoScout24 | active | Search HTML/`__NEXT_DATA__`; images are normalized to a large CDN variant (`1920x1080.webp`) |
| Kleinanzeigen | active | Search and detail pages; detail galleries are loaded and exported as multiple images |
| AutoUncle | active / sometimes blocked | Public search page; provides additional Corvette listings, can intermittently return HTTP 403 from server environments, and is then reported as a source warning |
| Classic Trader | active / often empty | JSON-LD/public search page; currently often returns 0 C6 listings, but the connector parses available C6 listings correctly |
| mobile.de | optional / often blocked | Connector is available, but mobile.de frequently returns `Access denied` / HTTP 403 from server and CI environments. The run continues and reports a source warning in JSON/HTML. |

No login or CAPTCHA bypassing. Private contact data is not intentionally stored.

## Data pipeline

```text
source connector
  -> raw public HTML/JSON
  -> parser
  -> normalized C6 Listing
  -> dedupe / cluster assignment
  -> SQLite snapshots
  -> feed + static website exports
```

## Setup

```bash
uv sync --locked
cp config.example.yaml config.yaml
```

## Live run

```bash
uv run corvette-tracker run --config config.yaml --output-dir .
```

A run without an explicit config also works:

```bash
uv run corvette-tracker run --output-dir .
```

## Docker / WebUI

The project can run as a combined frontend and backend container. The WebUI is available at `http://localhost:8096` and displays listings from the SQLite database. GET endpoints are readable. Mutating POST and PATCH endpoints require `CORVETTE_TRACKER_ADMIN_USER` and `CORVETTE_TRACKER_ADMIN_PASSWORD` through HTTP Basic Auth.

```bash
# Set credentials in the shell or a private env file first.
export CORVETTE_TRACKER_ADMIN_USER
export CORVETTE_TRACKER_ADMIN_PASSWORD

docker build -t corvette-tracker:local .
docker run --rm -p 8096:8096 \
  -v corvette-tracker-data:/app/runtime \
  -e CORVETTE_TRACKER_CRON_INTERVAL=6h \
  --env CORVETTE_TRACKER_ADMIN_USER \
  --env CORVETTE_TRACKER_ADMIN_PASSWORD \
  corvette-tracker:local
```

Important Docker environment variables:

| Variable | Default | Meaning |
|---|---|---|
| `CORVETTE_TRACKER_CRON_INTERVAL` | `6h` | Crawl interval: seconds (`300`), minutes (`15m`), hours (`2h`), days (`1d`), or `never`/`off` to disable |
| `CORVETTE_TRACKER_RUN_ON_START` | `true` | Starts a crawl immediately when the container starts |
| `CORVETTE_TRACKER_PORT` / `PORT` | `8096` | HTTP port inside the container |
| `CORVETTE_TRACKER_OUTPUT_DIR` | `/app/runtime` | Persistent runtime files, exports, and website |
| `CORVETTE_TRACKER_DATABASE` | `/app/runtime/data/corvette_tracker.sqlite` | SQLite database including snapshots and manual overrides |
| `CORVETTE_TRACKER_CONFIG` | `/app/config.yaml` | YAML configuration; can be replaced with a volume |
| `CORVETTE_TRACKER_ADMIN_USER` | unset | Username for mutating POST/PATCH requests |
| `CORVETTE_TRACKER_ADMIN_PASSWORD` | unset | Password for mutating POST/PATCH requests |

## Tests

```bash
uv run pytest -q
```

CI runs on pull requests and pushes to `development` and `main`.

## Generated files

```text
site/index.html                 # static website
index.html                      # website copy for root/GitHub Pages hosting
feed/latest.md                  # Markdown feed for humans
data/exports/latest.json        # complete JSON export
data/exports/latest.csv         # tabular CSV export
data/corvette_tracker.sqlite    # local history / snapshots
```

`data/corvette_tracker.sqlite`, `site/`, `feed/latest.md`, and `data/exports/*` are local runtime artifacts and are not permanently versioned.

## Static website

The application can serve the generated `site/` website separately. Deployment targets, internal paths, domains, and credentials belong in private operations documentation, not in this repository. Generated website and export files remain local runtime artifacts and are not versioned.

The website shows the following for each listing:

- image / gallery thumbnails
- source and listing link
- score
- price
- engine / probable engine
- horsepower
- mileage
- transmission, for example manual or automatic
- trim / variant
- body style, for example convertible, coupe, or targa
- first registration
- inspection status
- location
- risk warnings
- source warnings, for example when mobile.de blocks requests

## Scoring

The score is a preference heuristic from `0..100`. Current default:

```text
Score = base_score + fulfilled preferences - risk penalties
```

Default weights:

| Criterion | Meaning | Points |
|---|---|---:|
| Manual (`transmission: manual`) | very important | +30 |
| Not a convertible (`body_style` is not convertible) | important | +20 |
| Not an LS2 (`engine`/`probable_engine` is known and not LS2) | important | +20 |
| Preferred trim (`Grand Sport`, `Z06`, `ZR1`) | medium | +10 |

`base_score` defaults to `20`, so a listing fulfilling all preferences reaches `100`. Risk flags such as `damage_reported`, `no_tuv`, or `sold_or_reserved` are applied afterwards. The final value is limited to `0..100`.

Configure scoring in `config.yaml`:

```yaml
scoring:
  base_score: 20
  weights:
    manual_transmission: 30
    non_convertible: 20
    non_ls2: 20
    preferred_trim: 10
  preferred_trims: [Grand Sport, Z06, ZR1]
```

The WebUI also contains a **Configure scoring** section. Changes are written to the same `config.yaml` and immediately applied to exports and API output.

## JSON fields

The JSON export includes fields such as:

```json
{
  "id": "autoscout24_...",
  "source": "AutoScout24",
  "url": "https://...",
  "title": "Chevrolet Corvette C6",
  "generation": "C6",
  "price_eur": 41900,
  "price_label": null,
  "mileage_km": 61000,
  "engine": null,
  "probable_engine": "LS2",
  "engine_confidence": 0.86,
  "engine_note": "404 hp -> probable LS2",
  "power_hp": 404,
  "estimated_power_hp": null,
  "power_note": null,
  "body_style": "Coupé",
  "transmission": "automatic",
  "trim": "Base",
  "first_registration": "2010-03",
  "tuv_until": null,
  "location_raw": "80809 München",
  "image_urls": ["https://..."],
  "risk_flags": [],
  "score": 65,
  "change_type": "new",
  "cluster_id": "soft_..."
}
```

## Engine detection

The tracker distinguishes between a safely detected and a derived probable engine, as well as explicit and estimated power:

- `engine`: only when the listing contains an engine code or unambiguous displacement/trim evidence (`LS2`, `LS3`, `LS7`, `LS9`)
- `probable_engine`: when there is no certain engine code but the horsepower matches a C6 engine range
- `engine_confidence`: confidence of the derivation
- `engine_note`: explanation for the derivation
- `power_hp`: explicitly detected horsepower from the listing
- `estimated_power_hp`: estimated stock power from the detected engine when the listing contains no horsepower
- `power_note`: evidence for estimated power

Current heuristic:

| Horsepower range | Probable engine | Confidence |
|---:|---|---:|
| 395–410 hp | LS2 | 0.86 |
| 425–445 hp | LS3 | 0.86 |
| 500–520 hp | LS7 | 0.90 |
| 630–660 hp | LS9 | 0.92 |

The website explicitly labels this as `probable LSx`, not as a verified fact.

## Image handling

### AutoScout24

AutoScout24 often returns thumbnail URLs in search results such as:

```text
...jpg/250x188.webp
```

The connector normalizes them to larger CDN variants:

```text
...jpg/1920x1080.webp
```

### Kleinanzeigen

Kleinanzeigen usually exposes only one image in the search list. The connector therefore also loads the detail page and extracts the complete gallery. Image URLs are normalized to the larger variant:

```text
?rule=$_59.AUTO
```

If the detail page fails, the search-list image remains as a fallback.

## AI enrichment hook

The project contains a prepared extension layer for future image and text analysis by an AI provider. The tracker does not include a fixed provider or API key. Instead, a provider can be attached as a Python class.

The AI layer receives each listing's:

- title
- description text
- image URLs, limited by `max_images`
- known structured fields such as price, mileage, engine, trim, and risk flags

The provider returns an `EnrichmentResult`. The currently planned enrichment fields are:

- `exterior_color`
- `interior_color`
- `transmission`
- `eu_spec`
- `equipment`
- `visual_flags`
- additional `risk_flags`
- `notes`
- `evidence`

Important: AI results never overwrite values explicitly detected by a parser. They only fill missing fields and append deduplicated equipment and risk lists.

Configuration:

```yaml
ai_enrichment:
  enabled: true
  provider: "your_module:YourVisionProvider"
  max_images: 8
```

Alternatively through the CLI:

```bash
uv run corvette-tracker run \
  --config config.yaml \
  --ai-provider "your_module:YourVisionProvider" \
  --ai-max-images 8
```

A provider template is available at:

```text
examples/ai_provider_template.py
```

The website and Markdown output show AI equipment, visual hints, and AI notes. The JSON export additionally contains `ai_enrichment` with provider, confidence, notes, and evidence.

## Risk flags

Currently detected warning signals:

- `accident_reported`
- `damage_reported`
- `salvage_import_possible`
- `mileage_unclear`
- `no_tuv`
- `registration_problem`
- `modified_heavily`
- `sold_or_reserved`

The flags are heuristics and do not replace manual inspection.

## Snapshot and change logic

The tracker stores listings in SQLite. On the next run it can detect:

- new listing (`new`)
- price change (`price_change`)
- metadata change (`metadata_change`)
- unchanged listing (`unchanged`)

Repeated runs therefore build a local history.

## CLI

Currently implemented:

```bash
uv run corvette-tracker run [--config config.yaml] [--output-dir .] [--database data/corvette_tracker.sqlite]
```

For tests, a local fixture can be used instead of live crawling:

```bash
uv run corvette-tracker run --fixture tests-or-local-fixture.html --output-dir /tmp/corvette-run
```

## Development

Branch and PR convention for this repository:

- branch from `development`
- open PRs against `development`
- do not push directly to `main` or release branches

Useful commands:

```bash
# Tests
uv run pytest -q

# Live run with output in the current directory
uv run corvette-tracker run --output-dir .

# Compact Git status, if rtk is available
rtk git status --short --branch || git status --short --branch
```

## Known limitations

- AutoUncle and mobile.de can temporarily block server or CI IP ranges with HTTP 403; the tracker reports a source warning and continues with the remaining sources.
- Classic Trader often has no C6 matches at the moment; the connector remains active so listings appear when available.
- C7/C8 false positives are filtered out: `Z06`, `ZR1`, and `Grand Sport` alone are not proof of a C6 because these terms occur across multiple generations.
- Extraction is best-effort; listing text is unstructured and sometimes contradictory.
- Origin, accident status, and engine derivations are heuristic when they are not explicit in the listing.
- No paid history or VIN data sources are connected.
- No aggressive bot-protection or login bypassing.

## Project structure

```text
corvetteTracker/
  config.example.yaml
  database/schema.dbml
  examples/
    ai_provider_template.py
  src/corvette_tracker/
    ai_enrichment.py
    cli.py
    dedupe.py
    feed.py
    favicon.py
    health.py
    http.py
    models.py
    normalize.py
    storage.py
    sources/
      autoscout24.py
      autouncle.py
      classic_trader.py
      kleinanzeigen.py
      mobile_de.py
  tests/
    test_cli.py
    test_dedupe.py
    test_feed.py
    test_normalize.py
    test_sources.py
    test_storage.py
```
