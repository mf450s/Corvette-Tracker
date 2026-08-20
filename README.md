# C6 Corvette Tracker

Ein Python-basierter Angebots-Tracker für **Chevrolet Corvette C6**-Inserate. Der Tracker crawlt öffentliche Angebotsseiten, normalisiert kaufrelevante Fahrzeugdaten, erkennt Änderungen über SQLite-Snapshots und erzeugt eine statische Website mit Feed/Export-Dateien.

Der Fokus liegt bewusst auf **C6 (2005–2013)**. Andere Corvette-Generationen werden best-effort herausgefiltert.

## Was das Projekt aktuell macht

- ruft öffentliche Suchergebnisse für C6-Corvette-Angebote ab
- extrahiert strukturierte Fahrzeugdaten aus Inserats-HTML/JSON
- erkennt C6-relevante Felder wie Preis, Laufleistung, EZ, TÜV/HU, Motor, Trim, Getriebe und Standort
- markiert Risiken wie Unfall, Schaden, unklare Meilen/Kilometer, fehlender TÜV, Import-/Salvage-Hinweise und starke Modifikationen
- leitet einen **wahrscheinlichen Motor** aus PS ab, wenn kein expliziter Motorcode im Inserat steht
- sammelt Bilder in hoher Qualität, inklusive Detail-Galerien bei Kleinanzeigen
- dedupliziert offensichtliche gleiche Inserate und bildet Cluster
- speichert Snapshots lokal in SQLite, um neue Listings und Preisänderungen zu erkennen
- erzeugt Markdown-, JSON-, CSV- und HTML-Exporte
- rendert eine statische Website mit Cards, Bildern und Galerie-Thumbnails

## Quellen

| Quelle | Status | Verhalten |
|---|---:|---|
| AutoScout24 | aktiv | Such-HTML/`__NEXT_DATA__`, Bilder werden auf große CDN-Variante normalisiert (`1920x1080.webp`) |
| Kleinanzeigen | aktiv | Suchseite + Detailseiten; Detail-Galerien werden geladen und als mehrere Bilder exportiert |
| AutoUncle | aktiv / manchmal blockiert | Öffentliche Suchseite; liefert zusätzliche Corvette-Treffer, kann aus Server-Umgebungen intermittierend HTTP 403 werfen und wird dann als Quellen-Warnung behandelt |
| Classic Trader | aktiv / oft leer | JSON-LD/öffentliche Suchseite; aktuell häufig 0 C6-Angebote, aber der Connector parsed vorhandene C6-Listings sauber |
| mobile.de | optional / oft blockiert | Connector vorhanden, aber mobile.de liefert aus Server-/CI-Umgebungen häufig `Access denied` / HTTP 403. Der Lauf bricht dann nicht ab, sondern zeigt eine Quellen-Warnung in JSON/HTML. |

Keine Login-/Captcha-Umgehung. Keine privaten Kontaktdaten werden bewusst gespeichert.

## Datenpipeline

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

## Live-Lauf

```bash
uv run corvette-tracker run --config config.yaml --output-dir .
```

Ohne explizite Config geht auch:

```bash
uv run corvette-tracker run --output-dir .
```

## Docker / WebUI

Das Projekt kann direkt als kombinierter Frontend+Backend-Container laufen. Die WebUI ist danach unter `http://localhost:8096` erreichbar und zeigt die Listings aus der SQLite-Datenbank an. GET-Endpunkte sind lesbar. Mutierende POST- und PATCH-Endpunkte benötigen `CORVETTE_TRACKER_ADMIN_USER` und `CORVETTE_TRACKER_ADMIN_PASSWORD` über HTTP Basic Auth.

```bash
docker build -t corvette-tracker:local .
docker run --rm -p 8096:8096 \
  -v corvette-tracker-data:/app/runtime \
  -e CORVETTE_TRACKER_CRON_INTERVAL=6h \
  -e CORVETTE_TRACKER_ADMIN_USER=admin \
  -e CORVETTE_TRACKER_ADMIN_PASSWORD='set-a-local-secret' \
  corvette-tracker:local
```

Wichtige Docker-ENV-Variablen:

| Variable | Default | Bedeutung |
|---|---|---|
| `CORVETTE_TRACKER_CRON_INTERVAL` | `6h` | Crawl-Intervall: Sekunden (`300`), Minuten (`15m`), Stunden (`2h`), Tage (`1d`) oder `never`/`off` zum Deaktivieren |
| `CORVETTE_TRACKER_RUN_ON_START` | `true` | Führt beim Containerstart direkt einen Crawl aus |
| `CORVETTE_TRACKER_PORT` / `PORT` | `8096` | HTTP-Port im Container |
| `CORVETTE_TRACKER_OUTPUT_DIR` | `/app/runtime` | Persistente Runtime-Dateien, Exporte und Website |
| `CORVETTE_TRACKER_DATABASE` | `/app/runtime/data/corvette_tracker.sqlite` | SQLite-Datei inkl. Snapshots und manueller Overrides |
| `CORVETTE_TRACKER_CONFIG` | `/app/config.yaml` | YAML-Config; kann per Volume überschrieben werden |
| `CORVETTE_TRACKER_ADMIN_USER` | nicht gesetzt | Benutzername für mutierende POST-/PATCH-Requests |
| `CORVETTE_TRACKER_ADMIN_PASSWORD` | nicht gesetzt | Passwort für mutierende POST-/PATCH-Requests |

## Tests

```bash
uv run pytest -q
```

CI läuft auf Pull Requests und Pushes gegen `development`.

## Erzeugte Dateien

```text
site/index.html                 # statische Website
index.html                      # Kopie der Website für Root-/GitHub-Pages-Hosting
feed/latest.md                  # Markdown-Feed für Menschen
data/exports/latest.json        # vollständiger JSON-Export
data/exports/latest.csv         # tabellarischer CSV-Export
data/corvette_tracker.sqlite    # lokale Historie / Snapshots
```

`data/corvette_tracker.sqlite`, `site/`, `feed/latest.md` und `data/exports/*` sind lokale Lauf-Artefakte und werden nicht dauerhaft versioniert.

## Statische Website

Die Anwendung kann die generierte `site/`-Website separat ausliefern. Deployment-Ziele, interne Pfade, Domains und Zugangsdaten gehören in die private Betriebsdokumentation, nicht in dieses Repository. Generierte Website- und Exportdateien bleiben lokale Laufzeit-Artefakte und werden nicht versioniert.

Die Website zeigt pro Listing:

- Bild / Galerie-Thumbnails
- Quelle und Link zum Inserat
- Score
- Preis
- Motor / wahrscheinlicher Motor
- PS
- Laufleistung
- Getriebe, z. B. Schalter oder Automatik
- Trim / Variante
- Karosserie, z. B. Cabrio, Coupé oder Targa
- EZ
- TÜV/HU
- Standort
- Risiko-Hinweise
- Quellen-Warnungen, z. B. wenn mobile.de blockt

## Scoring

Der Score ist eine Preference-Heuristik von `0..100`. Aktueller Standard:

```text
Score = base_score + erfüllte Wunsch-Kriterien - Risiko-Abzüge
```

Default-Gewichtung:

| Kriterium | Bedeutung | Punkte |
|---|---|---:|
| Schalter (`transmission: manual`) | sehr wichtig | +30 |
| Kein Cabrio (`body_style` nicht Cabrio/Convertible) | wichtig | +20 |
| Kein LS2 (`engine`/`probable_engine` bekannt und nicht LS2) | wichtig | +20 |
| Bevorzugter Trim (`Grand Sport`, `Z06`, `ZR1`) | mittel | +10 |

`base_score` ist standardmäßig `20`, dadurch landet ein Listing, das alle Wunsch-Kriterien erfüllt, bei `100`. Risiko-Flags wie `damage_reported`, `no_tuv` oder `sold_or_reserved` ziehen danach Punkte ab. Der finale Wert wird auf `0..100` begrenzt.

Konfigurierbar in `config.yaml`:

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

Im WebUI gibt es zusätzlich den Bereich **Scoring konfigurieren**. Änderungen werden in dieselbe `config.yaml` geschrieben und bei Export/API-Ausgabe direkt neu angewendet.

## JSON-Felder

Der JSON-Export enthält u. a.:

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
  "engine_note": "Leistung 404 PS → wahrscheinlich LS2",
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

## Motor-Erkennung

Der Tracker unterscheidet zwischen sicher erkanntem und wahrscheinlich abgeleitetem Motor sowie sicherer und geschätzter Leistung:

- `engine`: nur wenn ein Motorcode oder eindeutiger Hubraum-/Trim-Hinweis im Inserat steht (`LS2`, `LS3`, `LS7`, `LS9`)
- `probable_engine`: wenn kein sicherer Motorcode vorhanden ist, aber die Leistung zur C6 passt
- `engine_confidence`: Confidence der Ableitung
- `engine_note`: Erklärung für die Ableitung
- `power_hp`: explizit erkannte PS-Angabe aus dem Inserat
- `estimated_power_hp`: geschätzte Serienleistung aus erkanntem Motor, wenn das Inserat keine PS nennt
- `power_note`: Hinweis/Evidence zur geschätzten Leistung

Aktuelle Heuristik:

| PS-Bereich | wahrscheinlicher Motor | Confidence |
|---:|---|---:|
| 395–410 PS | LS2 | 0.86 |
| 425–445 PS | LS3 | 0.86 |
| 500–520 PS | LS7 | 0.90 |
| 630–660 PS | LS9 | 0.92 |

Die Website zeigt das explizit als `wahrscheinlich LSx`, nicht als sichere Angabe.

## Bild-Handling

### AutoScout24

AutoScout liefert in Suchergebnissen oft Thumbnail-URLs wie:

```text
...jpg/250x188.webp
```

Der Connector normalisiert diese auf größere CDN-Varianten:

```text
...jpg/1920x1080.webp
```

### Kleinanzeigen

Kleinanzeigen zeigt in der Suchliste meist nur ein Bild. Der Connector lädt deshalb zusätzlich die Detailseite und extrahiert die komplette Galerie. Die Bild-URLs werden auf die größere Variante normalisiert:

```text
?rule=$_59.AUTO
```

Wenn die Detailseite fehlschlägt, bleibt das Suchlistenbild als Fallback erhalten.

## AI-Enrichment-Hook

Das Projekt enthält eine vorbereitete Erweiterungsschicht für spätere Bild+Text-Auswertung durch eine KI. Der Tracker selbst bringt keinen festen Provider und keinen API-Key mit. Stattdessen kann ein Provider als Python-Klasse angebunden werden.

Die AI-Schicht bekommt pro Listing:

- Titel
- Beschreibungstext
- Bild-URLs, begrenzt über `max_images`
- bereits bekannte strukturierte Felder wie Preis, km, Motor, Trim, Risiko-Flags

Der Provider gibt ein `EnrichmentResult` zurück. Aktuell vorgesehene Ergänzungsfelder:

- `exterior_color`
- `interior_color`
- `transmission`
- `eu_spec`
- `equipment`
- `visual_flags`
- zusätzliche `risk_flags`
- `notes`
- `evidence`

Wichtig: AI-Ergebnisse überschreiben keine bereits explizit vom Parser erkannten Werte. Sie füllen nur fehlende Felder und hängen Listen wie Ausstattung/Risiko-Hinweise dedupliziert an.

Konfiguration:

```yaml
ai_enrichment:
  enabled: true
  provider: "your_module:YourVisionProvider"
  max_images: 8
```

Alternativ per CLI:

```bash
.venv/bin/python -m corvette_tracker.cli run \
  --config config.yaml \
  --ai-provider "your_module:YourVisionProvider" \
  --ai-max-images 8
```

Ein Provider-Template liegt unter:

```text
examples/ai_provider_template.py
```

Die Website und Markdown-Ausgabe zeigen AI-Ausstattung, visuelle Hinweise und AI-Notizen sichtbar an. Der JSON-Export enthält zusätzlich `ai_enrichment` mit Provider, Confidence, Notes und Evidence.

## Risiko-Flags

Aktuell erkannte Warnsignale:

- `accident_reported`
- `damage_reported`
- `salvage_import_possible`
- `mileage_unclear`
- `no_tuv`
- `registration_problem`
- `modified_heavily`
- `sold_or_reserved`

Die Flags sind heuristisch und ersetzen keine manuelle Prüfung.

## Snapshot- und Änderungslogik

Der Tracker speichert Listings in SQLite. Beim nächsten Lauf kann er erkennen:

- neues Listing (`new`)
- Preisänderung (`price_change`)
- Metadatenänderung (`metadata_change`)
- unverändertes Listing (`unchanged`)

Damit lässt sich über wiederholte Läufe eine lokale Historie aufbauen.

## CLI

Aktuell implementiert:

```bash
.venv/bin/python -m corvette_tracker.cli run [--config config.yaml] [--output-dir .] [--database data/corvette_tracker.sqlite]
```

Für Tests kann ein lokales Fixture statt Live-Crawling genutzt werden:

```bash
.venv/bin/python -m corvette_tracker.cli run --fixture tests-or-local-fixture.html --output-dir /tmp/corvette-run
```

## Entwicklung

Branch-/PR-Konvention für dieses Repo:

- von `development` branchen
- PR gegen `development`
- kein direkter Push auf `main`/Release-Branches

Nützliche Befehle:

```bash
# Tests
.venv/bin/python -m pytest -q

# Live-Run + kompakte Ausgabe
.venv/bin/python -m corvette_tracker.cli run --output-dir .

# Git Status kompakt, falls rtk verfügbar
rtk git status --short --branch || git status --short --branch
```

## Bekannte Grenzen

- AutoUncle und mobile.de können Server-/CI-IP-Ranges zeitweise mit HTTP 403 blockieren; der Tracker behandelt das als Quellen-Warnung und nutzt die übrigen Quellen weiter.
- Classic Trader hat für C6 aktuell oft keine Treffer; der Connector ist trotzdem aktiv, damit Angebote auftauchen, sobald dort welche vorhanden sind.
- C7/C8-False-Positives werden herausgefiltert: `Z06`, `ZR1` und `Grand Sport` reichen alleine nicht als C6-Beleg, weil diese Begriffe über mehrere Generationen vorkommen.
- Extraktion ist best-effort; Inseratstexte sind unstrukturiert und teils widersprüchlich.
- Herkunft, Unfallstatus und Motor-Ableitungen sind heuristisch, wenn sie nicht explizit im Inserat stehen.
- Keine kostenpflichtigen Historien-/VIN-Datenquellen angebunden.
- Keine aggressive Bot-Schutz- oder Login-Umgehung.

## Projektstruktur

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
