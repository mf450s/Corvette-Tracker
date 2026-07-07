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
python3 -m venv .venv
.venv/bin/python -m pip install -e '.[dev]'
cp config.example.yaml config.yaml
```

## Live-Lauf

```bash
.venv/bin/python -m corvette_tracker.cli run --config config.yaml --output-dir .
```

Ohne explizite Config geht auch:

```bash
.venv/bin/python -m corvette_tracker.cli run --output-dir .
```

## Tests

```bash
.venv/bin/python -m pytest -q
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

Die Website zeigt pro Listing:

- Bild / Galerie-Thumbnails
- Quelle und Link zum Inserat
- Score
- Preis
- Laufleistung
- Motor / wahrscheinlicher Motor
- Trim / Variante
- EZ
- TÜV/HU
- Standort
- Risiko-Hinweise
- Quellen-Warnungen, z. B. wenn mobile.de blockt

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
  "mileage_km": 61000,
  "engine": null,
  "probable_engine": "LS2",
  "engine_confidence": 0.86,
  "engine_note": "Leistung 404 PS → wahrscheinlich LS2",
  "power_hp": 404,
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

Der Tracker unterscheidet zwischen sicher erkanntem und wahrscheinlich abgeleitetem Motor:

- `engine`: nur wenn ein Motorcode oder eindeutiger Hubraum-/Trim-Hinweis im Inserat steht (`LS2`, `LS3`, `LS7`, `LS9`)
- `probable_engine`: wenn kein sicherer Motorcode vorhanden ist, aber die Leistung zur C6 passt
- `engine_confidence`: Confidence der Ableitung
- `engine_note`: Erklärung für die Ableitung

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

- mobile.de blockt Server-/CI-IP-Ranges häufig mit HTTP 403.
- Extraktion ist best-effort; Inseratstexte sind unstrukturiert und teils widersprüchlich.
- Herkunft, Unfallstatus und Motor-Ableitungen sind heuristisch, wenn sie nicht explizit im Inserat stehen.
- Keine kostenpflichtigen Historien-/VIN-Datenquellen angebunden.
- Keine aggressive Bot-Schutz- oder Login-Umgehung.

## Projektstruktur

```text
corvetteTracker/
  config.example.yaml
  database/schema.dbml
  src/corvette_tracker/
    cli.py
    dedupe.py
    feed.py
    http.py
    models.py
    normalize.py
    storage.py
    sources/
      autoscout24.py
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
