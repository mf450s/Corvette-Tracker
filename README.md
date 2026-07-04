# Corvette Tracker

Ein wöchentlicher Angebots-Tracker für Chevrolet Corvettes. Ziel ist ein aggregierter Feed aus mehreren Fahrzeugbörsen/Quellen, der neue und geänderte Angebote erkennt, relevante Metadaten extrahiert, Dubletten zusammenführt und die Fahrzeuge vergleichbar macht.

## Ziel

Der Tracker soll einmal pro Woche nach neuen Corvette-Angeboten suchen und pro Fahrzeug strukturierte Daten sammeln:

- Modell / Generation
- Preis
- Motor
- Kilometerstand
- Außenfarbe
- Innenfarbe
- Angebotslink
- Schaden / Mängel
- TÜV / HU
- Erstzulassung
- Unfallstatus
- Leistung / PS
- Standort
- Herkunft / Landeshistorie
- weitere kaufrelevante Informationen

Am Ende entsteht ein aggregierter Feed, der neue, geänderte und interessante Angebote übersichtlich ausgibt.

---

## Warum das Ding sinnvoll ist

Corvette-Angebote sind oft schlecht vergleichbar:

- gleiche Fahrzeuge tauchen auf mehreren Plattformen auf
- Händlertexte sind unstrukturiert
- Importfahrzeuge haben relevante Historienrisiken
- Unfall, Schaden, TÜV, Motor und Ausstattung stehen oft irgendwo im Freitext
- Preise ändern sich, ohne dass man es merkt
- gute Angebote verschwinden schnell

Der Tracker soll nicht nur Links sammeln, sondern die Angebote kaufentscheidungsfähig machen.

---

## Scope v1

### Muss können

1. Wöchentlich laufen
2. Angebote aus definierten Quellen abrufen
3. Corvette-Angebote erkennen
4. Metadaten extrahieren
5. Rohdaten speichern
6. Strukturierte Angebotsdaten speichern
7. Neue Angebote erkennen
8. Geänderte Angebote erkennen, besonders Preisänderungen
9. Dubletten über Plattformen hinweg möglichst zusammenführen
10. Einen aggregierten Feed erzeugen

### Nicht in v1

- Kein automatischer Kaufentscheid
- Kein Login-Scraping hinter Accounts
- Kein aggressives Scraping gegen Schutzmechanismen
- Keine perfekte Fahrzeughistorie ohne externe kostenpflichtige Datenquellen
- Kein ML-Klassifikator, solange einfache Regeln reichen

---

## Mögliche Datenquellen

Start pragmatisch mit öffentlich zugänglichen Quellen.

### Fahrzeugbörsen

- mobile.de
- AutoScout24
- Kleinanzeigen
- AutoUncle
- Classic Trader, falls ältere Corvettes relevant sind
- Händler-Websites mit Corvette-Bestand

### Ergänzende Quellen

- Hersteller-/Modell-Datenbanken für Generation, Motoren und Leistungsdaten
- TÜV-/HU-Angaben aus Inseratstexten
- VIN-Decoder, falls VIN im Inserat steht
- Google Maps / Geocoding für Standortnormalisierung, optional

### Quellen-Strategie

Pro Quelle wird ein eigener Connector gebaut:

```text
source connector -> raw listing -> parser -> normalized listing -> feed
```

Jede Quelle darf anders sein. Das gemeinsame Datenmodell sitzt erst nach dem Parsing.

---

## Kern-Datenmodell

### Pflichtfelder

| Feld | Typ | Beschreibung |
|---|---:|---|
| `id` | string | Interne stabile ID |
| `source` | string | Quelle, z. B. `mobile.de` |
| `source_listing_id` | string/null | ID der Anzeige auf der Plattform, falls verfügbar |
| `url` | string | Link zum Angebot |
| `title` | string | Originaltitel der Anzeige |
| `model` | string/null | Modellbezeichnung, z. B. `Corvette C6` |
| `generation` | string/null | C1, C2, C3, C4, C5, C6, C7, C8 |
| `price_eur` | number/null | Preis in EUR |
| `engine` | string/null | Motor, z. B. `LS3`, `LT1`, `6.2 V8` |
| `mileage_km` | number/null | Kilometerstand |
| `exterior_color` | string/null | Außenfarbe |
| `interior_color` | string/null | Innenfarbe |
| `damage` | string/null | Erkannter Schaden/Mängeltext |
| `has_damage` | boolean/null | Strukturierte Schadenserkennung |
| `accident_status` | string/null | `unfallfrei`, `unfall`, `unbekannt` |
| `first_registration` | string/null | Erstzulassung, ideal `YYYY-MM` |
| `tuv_until` | string/null | TÜV/HU bis, ideal `YYYY-MM` |
| `power_hp` | number/null | Leistung in PS |
| `location_raw` | string/null | Standort wie im Inserat |
| `location_country` | string/null | Aktuelles Angebotsland |
| `origin_country` | string/null | Herkunft/Landeshistorie, falls erkennbar |
| `seller_type` | string/null | Händler oder privat |
| `created_at` | datetime | Ersterfassung durch Tracker |
| `updated_at` | datetime | Letzte Aktualisierung durch Tracker |
| `seen_at` | datetime | Zuletzt gesehen |

### Sinnvolle Zusatzfelder

Diese Felder würde ich direkt mitplanen, auch wenn nicht alle Quellen sie sauber liefern.

| Feld | Warum relevant |
|---|---|
| `vin` | Ermöglicht Dubletten-Erkennung, Ausstattung und Historienchecks |
| `transmission` | Schalter/Automatik ist bei Corvettes preisrelevant |
| `body_style` | Coupe, Cabrio, Targa, Z06, Grand Sport etc. |
| `trim` | Stingray, Z06, ZR1, Grand Sport, Collector Edition etc. |
| `fuel_type` | Meist Benzin, aber für Vollständigkeit |
| `emission_class` | Relevant für Zulassung/Umweltzonen |
| `owners_count` | Anzahl Vorbesitzer ist kaufrelevant |
| `service_history` | Scheckheft, Rechnungen, Wartungsnachweise |
| `import_status` | EU-Fahrzeug, US-Import, Japan-Import etc. |
| `registration_country_history` | Länderhistorie, sofern aus Text/Kennzeichen erkennbar |
| `license_plate_hint` | Nur grob/optional speichern, keine unnötigen personenbezogenen Daten |
| `availability_status` | verfügbar, reserviert, verkauft, unbekannt |
| `days_online` | Hilft beim Einschätzen von Preis/Attraktivität |
| `price_history` | Preisänderungen sind oft das wichtigste Signal |
| `image_urls` | Bilder für Wiedererkennung und spätere manuelle Prüfung |
| `main_image_hash` | Hilft bei Dubletten über mehrere Plattformen |
| `description_text` | Originalbeschreibung für spätere Extraktion/Debugging |
| `equipment` | Ausstattung: Magnetic Ride, HUD, Keramikbremsen, Competition Seats etc. |
| `modifications` | Tuning, Auspuff, Felgen, Software, Umbauten |
| `known_issues` | Erkannte Problemsignale aus Freitext |
| `warranty` | Händlergarantie/Gewährleistung |
| `vat_deductible` | MwSt. ausweisbar, für Gewerbe relevant |
| `financing_available` | Optional, eher Händlerfeld |
| `crawl_confidence` | Vertrauen in die extrahierten Daten |

---

## Corvette-spezifische Felder

Corvettes haben ein paar Dinge, die bei normalen Auto-Trackern oft fehlen.

### Generation

- C1: 1953–1962
- C2: 1963–1967
- C3: 1968–1982
- C4: 1984–1996
- C5: 1997–2004
- C6: 2005–2013
- C7: 2014–2019
- C8: ab 2020

### Varianten / Trims

- Base / Stingray
- Grand Sport
- Z06
- ZR1
- Convertible
- Coupe / Targa
- Collector Edition / Sondermodelle

### Motoren / Codes

Beispiele:

- LS1
- LS2
- LS3
- LS6
- LS7
- LS9
- LT1
- LT2
- LT4
- LT5

Der Tracker sollte sowohl Freitext wie `6.2 V8` als auch Motorcodes erkennen.

---

## Schaden, Unfall und Risiko-Erkennung

### Separat behandeln

`Schaden` und `Unfall` sind nicht dasselbe.

- `damage`: aktueller oder beschriebener Schaden/Mangel
- `accident_status`: ob das Fahrzeug als unfallfrei/unfallbehaftet beschrieben wird
- `risk_flags`: Warnsignale aus Text und Metadaten

### Beispiele für Risk Flags

| Flag | Auslöser |
|---|---|
| `accident_reported` | `Unfallwagen`, `nicht unfallfrei`, `reparierter Unfallschaden` |
| `damage_reported` | `Frontschaden`, `Seitenschaden`, `Motorschaden`, `Getriebeschaden` |
| `salvage_import_possible` | US-Import + auffällig niedriger Preis + Schadensbegriffe |
| `mileage_unclear` | `Tacho in Meilen`, `abgelesen`, `laut Vorbesitzer` |
| `no_tuv` | `ohne TÜV`, `HU abgelaufen`, `nicht fahrbereit` |
| `registration_problem` | `keine deutschen Papiere`, `Zulassung schwierig` |
| `modified_heavily` | Kompressorumbau, Software, Rennstrecke, Tracktool |
| `sold_or_reserved` | `verkauft`, `reserviert` |

---

## Herkunft / Landeshistorie

Herkunft ist wichtig, aber nicht immer sicher bestimmbar. Deshalb immer mit Confidence speichern.

### Mögliche Hinweise

- Text: `US Import`, `Japan Import`, `EU Fahrzeug`, `deutsche Erstauslieferung`
- Kennzeichen auf Bildern, falls man später Bildanalyse einbauen will
- Meilentacho / mph-Angaben
- Carfax-Erwähnungen
- Title-Begriffe: `salvage`, `rebuilt`, `clean title`
- Standort und Erstzulassungsland
- Sprache/Format der Dokumente im Beschreibungstext

### Datenmodell dafür

```json
{
  "origin_country": "US",
  "origin_confidence": 0.8,
  "origin_evidence": [
    "description contains 'US Import'",
    "mileage listed in miles"
  ]
}
```

Keine falsche Sicherheit: Wenn es nur geraten ist, bleibt es `unknown` oder niedrige Confidence.

---

## Aggregierter Feed

Der Feed soll nicht einfach alle Listings dumpen, sondern relevante Änderungen hervorheben.

### Feed-Typen

1. **Neue Angebote**
2. **Preisänderungen**
3. **Wieder aufgetauchte Angebote**
4. **Vermutlich gleiche Fahrzeuge auf anderer Plattform**
5. **Interessante Angebote nach Score**
6. **Risky Deals / Warnungen**
7. **Nicht mehr verfügbare Angebote**

### Beispiel-Ausgabe Markdown

```markdown
## Neue Corvette-Angebote — KW 12/2026

### 1. Corvette C7 Grand Sport — 67.900 €

- Motor: LT1 6.2 V8
- PS: 466
- Kilometer: 42.000 km
- EZ: 05/2018
- TÜV/HU: 06/2027
- Außen: Admiral Blue
- Innen: Schwarz
- Standort: München, DE
- Herkunft: EU-Fahrzeug, Confidence 0.7
- Unfall: unfallfrei laut Inserat
- Schaden: keine Angabe
- Verkäufer: Händler
- Preisänderung: neu
- Risiko-Flags: keine
- Link: https://...

Kurzbewertung: Sauberer Datensatz, marktüblicher Preis, guter Kandidat für manuelle Prüfung.
```

### Feed-Formate

Für v1 reichen:

- `feed/latest.md` für Menschen
- `feed/latest.json` für Maschinen
- optional `feed/latest.csv` für Tabellen

Später möglich:

- RSS/Atom
- Matrix/Telegram/ntfy Push
- kleine Weboberfläche
- GitHub Pages / statischer Report

---

## Scoring

Ein einfacher Score hilft, viele Angebote zu sortieren.

### Beispiel-Score

```text
score = base
  + generation_preference
  + trim_bonus
  + low_mileage_bonus
  + good_price_bonus
  + clean_history_bonus
  - accident_penalty
  - damage_penalty
  - unclear_import_penalty
  - missing_tuv_penalty
```

### Konfigurierbare Präferenzen

Später in `config.yaml`:

```yaml
preferences:
  generations: ["C6", "C7"]
  trims: ["Grand Sport", "Z06", "ZR1"]
  max_price_eur: 90000
  max_mileage_km: 80000
  countries: ["DE", "NL", "BE"]
  require_tuv: false
  avoid_accident_cars: true
  avoid_salvage_imports: true
```

---

## Dubletten-Erkennung

Gleiches Auto kann auf mehreren Plattformen stehen. Dubletten-Erkennung sollte mehrere schwache Signale kombinieren.

### Harte Signale

- gleiche VIN
- gleiche Plattform-ID
- identische URL

### Weiche Signale

- gleicher Titel
- gleicher Preis
- gleicher Kilometerstand
- gleicher Standort
- gleiche Farbe innen/außen
- gleiche Bilder oder ähnlicher Bild-Hash
- gleiche Telefonnummer/Händlername, falls öffentlich im Inserat
- gleiche Beschreibungspassagen

### Ergebnis

Listings bleiben als einzelne Quellen erhalten, werden aber einem `vehicle_cluster_id` zugeordnet.

```text
vehicle_cluster
  ├── mobile.de listing
  ├── autoscout24 listing
  └── händler-website listing
```

---

## Speicherung

### Vorschlag v1

SQLite reicht.

```text
data/
  corvette_tracker.sqlite
  raw/
    mobile_de/
    autoscout24/
  exports/
    latest.json
    latest.csv
feed/
  latest.md
  archive/
    2026-03-23.md
```

### Tabellen

- `sources`
- `raw_listings`
- `listings`
- `listing_snapshots`
- `vehicle_clusters`
- `price_history`
- `feed_runs`

### Warum Snapshots?

Weil Preis, Text, Kilometerstand und Verfügbarkeit sich ändern. Ohne Snapshots sieht man nur den letzten Zustand.

---

## Wöchentlicher Lauf

### Ablauf

1. Config laden
2. Pro Quelle Suchergebnisse abrufen
3. Rohdaten speichern
4. Parser ausführen
5. Daten normalisieren
6. Dubletten erkennen
7. Änderungen gegenüber letztem Snapshot berechnen
8. Score und Risk Flags berechnen
9. Feed generieren
10. Ergebnisse speichern
11. Optional Benachrichtigung senden

### Scheduling

Optionen:

- Cronjob auf dem Server
- GitHub Actions Schedule
- Hermes Cronjob, wenn der Feed direkt durch Hermes zugestellt werden soll

Für dieses Projekt pragmatisch:

```text
Sonntag morgens laufen lassen, Feed erzeugen, dann manuell prüfen.
```

---

## Technischer Vorschlag

### Sprache

Python ist sinnvoll:

- gute Scraping-/Parsing-Libraries
- SQLite einfach
- Tests einfach
- Feed-Generierung simpel

### Mögliche Dependencies

- `httpx` für HTTP
- `selectolax` oder `beautifulsoup4` für HTML Parsing
- `pydantic` für Datenmodelle
- `sqlmodel` oder `sqlite-utils` / direkt `sqlite3`
- `pytest` für Tests
- `python-dateutil` für Datumsparsing
- `rapidfuzz` für Dubletten-Erkennung
- `typer` für CLI

### Projektstruktur

```text
corvetteTracker/
  README.md
  pyproject.toml
  config.example.yaml
  src/
    corvette_tracker/
      __init__.py
      cli.py
      config.py
      models.py
      database.py
      normalize.py
      scoring.py
      feed.py
      dedupe.py
      sources/
        __init__.py
        base.py
        mobile_de.py
        autoscout24.py
  tests/
    test_normalize.py
    test_scoring.py
    test_dedupe.py
    test_feed.py
  data/
    .gitkeep
  feed/
    .gitkeep
```

---

## CLI-Idee

```bash
corvette-tracker run --config config.yaml
corvette-tracker crawl --source mobile_de
corvette-tracker parse --source mobile_de
corvette-tracker feed --format markdown
corvette-tracker export --format json
```

---

## Datenqualität

Jedes extrahierte Feld sollte eine Quelle und Confidence haben können.

Beispiel:

```json
{
  "engine": {
    "value": "LS3 6.2 V8",
    "confidence": 0.9,
    "evidence": "title contains 'LS3' and description contains '6.2 V8'"
  }
}
```

Für die Datenbank kann v1 trotzdem flache Spalten nutzen. Evidence kann als JSON-Feld gespeichert werden.

---

## Datenschutz / Rechtliches

- Keine privaten Kontaktdaten unnötig speichern
- Keine Kennzeichen dauerhaft speichern, außer als grober Herkunftshinweis und nur wenn wirklich nötig
- Robots.txt und Nutzungsbedingungen der Quellen prüfen
- Rate Limits einhalten
- User-Agent sauber setzen
- Rohdaten nur lokal speichern
- Keine Captcha-/Bot-Schutz-Umgehung als Kernfeature einplanen

---

## Offene Entscheidungen

1. Welche Generationen sind interessant? Alle oder Fokus auf C5–C8?
2. Preislimit?
3. Länder: nur Deutschland oder EU-weit?
4. Privat + Händler oder nur Händler?
5. Sollen Unfallwagen komplett ausgeschlossen oder nur markiert werden?
6. Soll der Feed per Datei reichen oder direkt per ntfy/Matrix/Telegram kommen?
7. Wie wichtig sind Bilder/Bildvergleich in v1?
8. Sollen US-Importe ausgeschlossen oder nur riskanter bewertet werden?

---

## Umsetzung in Phasen

### Phase 1: Grundgerüst

- Python-Projekt anlegen
- Config laden
- Datenmodell definieren
- SQLite initialisieren
- CLI bauen
- Tests für Normalisierung und Feed schreiben

### Phase 2: Manuelle / Mock-Daten

- Beispiel-Listings als Fixtures speichern
- Parser gegen gespeicherte HTML/JSON-Beispiele testen
- Feed aus Mock-Daten generieren
- Scoring und Risk Flags verifizieren

### Phase 3: Erste echte Quelle

- Einen Source-Connector bauen
- Suchergebnisse abrufen
- Detailseiten abrufen, falls erlaubt und nötig
- Rohdaten speichern
- Parser stabilisieren

### Phase 4: Aggregation

- Snapshots speichern
- neue/geänderte/verschwundene Listings erkennen
- Preisverlauf speichern
- Dubletten-Heuristik einbauen

### Phase 5: Wöchentlicher Betrieb

- Cron/Scheduler einrichten
- Feed archivieren
- Optional Benachrichtigung versenden
- Logs und Fehlerreporting ergänzen

### Phase 6: Komfort

- CSV/JSON Export
- kleine HTML-Seite
- Filter nach Generation, Preis, Land, Unfallstatus
- manuelle Watchlist / Favoriten

---

## Akzeptanzkriterien für v1

v1 ist fertig, wenn:

- `corvette-tracker run` einen kompletten Lauf ausführt
- mindestens eine echte Quelle angebunden ist
- neue Angebote erkannt werden
- Preisänderungen erkannt werden
- strukturierte Felder für Preis, Modell, Kilometerstand, Standort und Link zuverlässig befüllt werden
- Freitextfelder wie Schaden, Unfall, TÜV/HU und Herkunft als best-effort extrahiert werden
- `feed/latest.md` erzeugt wird
- `data/exports/latest.json` erzeugt wird
- Tests für Normalisierung, Dedupe, Scoring und Feed bestehen

---

## Beispiel `latest.json`

```json
{
  "generated_at": "2026-03-23T08:00:00Z",
  "summary": {
    "new_listings": 4,
    "changed_listings": 2,
    "removed_listings": 1,
    "total_active": 38
  },
  "listings": [
    {
      "id": "mobile_de_123456",
      "cluster_id": "vehicle_abc123",
      "source": "mobile.de",
      "url": "https://example.com/listing/123456",
      "model": "Corvette C7 Grand Sport",
      "generation": "C7",
      "price_eur": 67900,
      "engine": "LT1 6.2 V8",
      "mileage_km": 42000,
      "exterior_color": "Admiral Blue",
      "interior_color": "Black",
      "damage": null,
      "has_damage": false,
      "accident_status": "unfallfrei",
      "first_registration": "2018-05",
      "tuv_until": "2027-06",
      "power_hp": 466,
      "location_raw": "München",
      "location_country": "DE",
      "origin_country": "EU",
      "origin_confidence": 0.7,
      "seller_type": "dealer",
      "risk_flags": [],
      "score": 82,
      "change_type": "new"
    }
  ]
}
```

---

## Erste konkrete Implementierungsaufgaben

1. `pyproject.toml` mit Python-Projekt und CLI anlegen
2. Pydantic-Modelle für `Listing`, `ListingSnapshot`, `FeedItem` erstellen
3. Normalizer für Preis, Kilometer, Datum, PS, Farben schreiben
4. Risk-Flag-Erkennung aus Freitext bauen
5. Markdown-Feed aus strukturierten Listings generieren
6. SQLite-Speicher einbauen
7. Dedupe-Heuristik über VIN/URL/Titel/Preis/km/Standort bauen
8. Erste Quelle anbinden
9. Wöchentlichen Scheduler konfigurieren

---

## Grundsatz

Erst robuste Datenpipeline, dann schöne Oberfläche. Wenn die Extraktion und Historie stimmen, kann der Feed später beliebig hübsch werden.
