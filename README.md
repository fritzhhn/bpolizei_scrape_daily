# Polizeimeldungen Berlin – Scraper & Dashboard

Sammelt [Polizeimeldungen der Polizei Berlin](https://www.berlin.de/polizei/polizeimeldungen/) (aktuelle Meldungen + [Archiv ab 2014](https://www.berlin.de/polizei/polizeimeldungen/archiv/)) in einer SQLite-Datenbank und zeigt sie in einem lokalen Web-Dashboard.

## Voraussetzungen

- Python 3.11+
- Netzwerkzugriff auf berlin.de

## Installation

```bash
cd "/Users/fritz/polizei scrape"
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

## Scraper

### Einmalig: komplettes Archiv (2014–heute)

Dauert je nach Verbindung **mehrere Stunden** (~20.000+ Meldungen). Der Scraper wartet zwischen Anfragen (~0,35 s), um den Server nicht zu belasten.

```bash
export PYTHONPATH="."
python -m scraper.scrape --mode full -v
```

Fortsetzen nach Abbruch (überspringt bereits gespeicherte Artikel):

```bash
python -m scraper.scrape --mode full --skip-existing -v
```

### Aktuell: letzte ~2 Wochen

```bash
python -m scraper.scrape --mode current
```

### Täglich: neue Meldungen

Prüft die [aktuelle Übersicht](https://www.berlin.de/polizei/polizeimeldungen/) und das laufende Archiv-Jahr.

```bash
python -m scraper.scrape --mode daily --skip-existing
```

## Gespeicherte Felder pro Meldung

| Feld | Quelle |
|------|--------|
| `id` | Artikel-ID aus URL (`pressemitteilung.XXXXX`) |
| `url` | Link zur Originalmeldung |
| `title` | Überschrift |
| `published_at` | Veröffentlichungszeit (Liste) |
| `meldung_date` | „Polizeimeldung vom …“ |
| `district` | Ereignisort / Bezirk |
| `summary` | Meta-Description (Kurztext) |
| `tags` | Kategorien aus Meta-Keywords (z. B. Kriminalität, Verkehr) |
| `case_number` | Aktenzeichen „Nr. XXXX“ aus dem Text |
| `body_text` | Volltext der Pressemeldung (ohne Kontakt-Sidebar) |
| `images` | Bild-URLs + Alt-Text (falls vorhanden) |
| `source_year` | Jahr im URL-Pfad |
| `first_seen_at` / `last_scraped_at` | Scraper-Zeitstempel |

Nicht gespeichert: Pressekontakt-Sidebar, Seiten-Navigation, Boilerplate.

### Automatisierung (macOS)

```bash
chmod +x scripts/run_daily.sh scripts/install_launchd.sh
./scripts/install_launchd.sh
```

Alternativ per cron (z. B. 6:00):

```cron
0 6 * * * /bin/bash "/Users/fritz/polizei scrape/scripts/run_daily.sh"
```

## Dashboard

```bash
export PYTHONPATH="."
python dashboard/app.py
```

Öffnen: [http://127.0.0.1:5050](http://127.0.0.1:5050)

Funktionen: Suche im Volltext, Filter nach Bezirk/Jahr, Statistik, Detailansicht mit Link zum Original.

## Daten

- SQLite: `data/meldungen.db` (wird im Git-Repo mit aktualisiert)
- Logs: `data/logs/` (lokal, nicht versioniert)

Fortschritt eines laufenden Full-Scrapes:

```bash
./scripts/scrape_status.sh
```

## GitHub & täglicher Scrape

Das Repo enthält einen [GitHub Actions](https://docs.github.com/en/actions) Workflow (`.github/workflows/scrape.yml`):

- **Automatisch:** täglich um 05:00 UTC (`--mode daily --skip-existing`)
- **Manuell:** unter *Actions → Polizeimeldungen scrapen → Run workflow* (Modus `daily`, `current` oder `full`)

Nach jedem Lauf wird `data/meldungen.db` bei Änderungen ins Repo gepusht.

### Repo anlegen und pushen

```bash
cd "/Users/fritz/polizei scrape"
git init
git add .
git commit -m "Initial commit: Polizeimeldungen Scraper & Dashboard"
# Auf GitHub leeres Repo erstellen, dann:
git remote add origin https://github.com/fritzhhn/bpolizei_scrape_daily.git
git branch -M main
git push -u origin main
```

Unter *Settings → Actions → General* „Read and write permissions“ für Workflows erlauben, damit die DB committet werden kann.

**Erster Full-Scrape:** lokal starten (dauert ~1,5–2,5 h), danach DB mitpushen — oder einmalig Actions mit Modus `full` ausführen.

## Hinweise

- Daten stammen von öffentlichen Pressemeldungen; Nutzung nur zu Recherche/Archivierung.
- Bitte `robots.txt` und faire Abfrageraten beachten (im Scraper eingebaut).
- Kein Ersatz für offizielle Meldungen – immer das [Original auf berlin.de](https://www.berlin.de/polizei/polizeimeldungen/) prüfen.
