# Berlin Werkstudent Job Radar

Persönlicher Job-Finder für öffentliche Stellenangebote in Berlin. Der Radar entdeckt Angebote, normalisiert sie, dedupliziert sie, bewertet sie transparent und verlinkt ausschließlich auf die Originalanzeige.

## Wichtige Betriebsregel

Das Projekt versucht **nicht**, CAPTCHA, Login, robots.txt/technische Zugriffsbeschränkungen, Anti-Bot-Schutz oder Sperren zu umgehen. StepStone und Indeed werden standardmäßig über öffentliche Suchmaschinen-Discovery adressiert; wenn Discovery nicht funktioniert, bleibt die Quelle einfach ohne Treffer. Es gibt keine automatischen Bewerbungen.

## Features

- FastAPI + SQLAlchemy + SQLite/PostgreSQL
- Dependency-free asyncio scheduler
- Responsive Dashboard mit Score-Ranking
- Suchprofil persistent in DB
- Dynamische Suchqueries
- StepStone / Indeed / Generic Discovery
- HTTP Timeout, Connection Pooling, Concurrency-Limit
- URL-Canonicalization und Fingerprint-Deduplizierung
- Transparenter 0–100 Match-Score
- Pagination bis 50 Jobs pro Seite
- Hintergrund-Scan und 60-Minuten-Scheduler
- Docker + Render Blueprint
- Pytest

## Installation

Python 3.12+:

```bash
python -m venv .venv
# Windows:
.venv\Scripts\activate
# macOS/Linux:
source .venv/bin/activate

pip install -r requirements.txt
copy .env.example .env  # Windows
# oder: cp .env.example .env
python run.py
```

Dashboard: `http://127.0.0.1:8000`

## Tests

```bash
pytest -q
```

## Docker

```bash
cp .env.example .env
docker compose up --build
```

## Environment Variables

| Variable | Default | Zweck |
|---|---:|---|
| DATABASE_URL | SQLite lokal | PostgreSQL auf Render einsetzen |
| SCAN_INTERVAL_MINUTES | 60 | Scheduler |
| REQUEST_TIMEOUT | 20 | HTTP Timeout |
| MAX_CONCURRENT_REQUESTS | 3 | kontrollierte Parallelität |
| REQUEST_RATE_PER_SECOND | 1 | Rate-Limit-Konfiguration |
| DEFAULT_LOCATION | Berlin | Suchort |
| DEFAULT_RADIUS_KM | 20 | Radius |
| MIN_MATCH_SCORE | 70 | UI-/Profil-Schwelle |
| DISCOVERY_MAX_RESULTS | 10 | Treffer je Discovery-Query |
| USER_AGENT | BerlinJobRadar/... | Identifikation |

Keine Secrets hardcoden.

## Render

Für dauerhafte Speicherung auf Render eine PostgreSQL-Datenbank anbinden und `DATABASE_URL` als Environment Variable setzen. SQLite bleibt für lokale Entwicklung geeignet; das lokale Render-Dateisystem ist nicht als dauerhafte Produktionsablage gedacht.

## GitHub

Repository anlegen, Dateien committen und pushen:

```bash
git init
git add .
git commit -m "Initial Berlin Job Radar"
git branch -M main
git remote add origin <YOUR_GITHUB_REPO>
git push -u origin main
```

## API

- `GET /api/jobs`
- `GET /api/jobs/{id}`
- `GET /api/jobs/{id}/sources`
- `POST /api/jobs/{id}/save`
- `POST /api/jobs/{id}/status`
- `POST /api/scan`
- `GET /api/scan/status`
- `GET /api/settings`
- `POST /api/settings`

## Matching

Die Basisgewichtung folgt dem definierten Profil: Werkstudent +25, Berlin +20, Fachbereich +15, Stunden +10, Remote/Hybrid +10, Skills +10, Gehalt +5, frisch +5. Negative Faktoren reduzieren den Score. Der finale Wert wird immer auf 0–100 begrenzt.

## Troubleshooting

**Keine StepStone/Indeed-Treffer:** Öffentliche Discovery kann temporär blockiert oder verändert sein. Das System beendet den Scan nicht, sondern meldet die Quelle als leer/partiell.

**Render zeigt keine alten Jobs:** Bei SQLite ist das erwartbar, weil die Dateispeicherung nicht dauerhaft garantiert ist. PostgreSQL verwenden.

**Scan läuft nicht:** `/health` prüfen, danach `/api/scan/status`. Logs zeigen Collector-Fehler.

## Architektur

`Discovery → Parsing/Normalisierung → Deduplication → Matching → Ranking → Dashboard`

Die Anwendung speichert keine Bewerberdaten und öffnet beim Bewerben ausschließlich den Original-Link in einem neuen Browser-Tab.
