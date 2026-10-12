# TRS-398 Rev.1: determination of absolute dose

*Русская версия: [README.md](README.md)*

A web platform for calculating absorbed dose to water according to TRS-398 Rev.1 (high-energy photons and electrons):
a PostgreSQL database, roles, approval by a second person, output trends (control charts, CUSUM) and printing of the
protocol as a PDF in the form of the “Calculation” worksheet. The interface and the start scripts work in **English and Russian**
(the language switch EN / RU is in the top bar of the program).

> For educational and research use. The program is not a certified medical device: every result must be checked
> independently. See [NOTICE.md](NOTICE.md).

## Installation in three steps (Windows)

1. Install [Docker Desktop](https://www.docker.com/products/docker-desktop/) and start it (details with settings: [docs/INSTALL.en.md](docs/INSTALL.en.md)).
2. Download the project (on GitHub: **Code → Download ZIP**, unpack into a convenient folder, for example `C:\trs398`) or `git clone`.
3. Double-click **`start.bat`**. It checks the computer, asks for the language (English or Russian), and the first start takes a few minutes
   (the application is built); then http://localhost:8000 opens by itself and asks **which login and password the administrator should have**:
   choose your own. Then: “Users” (add physicists and reviewers), “Equipment” (linac, beams, chamber and calibration), “Measurements”.

Linux/macOS: `cp .env.example .env`, set the three database passwords and `SESSION_SECRET`, then `docker compose up -d --build`.

| File | What it does |
|---|---|
| `start.bat` / `stop.bat` | start / stop (the data are kept) |
| `lan-on.bat` / `lan-off.bat`, `https-on.bat` / `https-off.bat` (HTTPS) | open the program to the other computers of the network / close it ([docs/NETWORK.en.md](docs/NETWORK.en.md)) |
| `backup-now.bat` | a database backup right now |
| `restore.bat` | replace the database with a backup (see below) |
| `update.bat` | update the program to a new version (makes a backup first) |
| `language.bat` | choose the language of the scripts and of the program (English / Русский) |

One server computer, many workplaces: on the server run `lan-on.bat`, the others open `http://computer-name:8000` in the browser.
Details and optional HTTPS: [docs/NETWORK.en.md](docs/NETWORK.en.md). A guide for physicists: [docs/USER_GUIDE.en.md](docs/USER_GUIDE.en.md) (also available inside the program under “Help”).

The data are stored in the Docker volume `trs398_pgdata`, the database backups are in the project's `backups` folder.

### Backups and restoring

The `backup` service (container `trs398_backup`) makes a backup at start-up and then every day at 02:00 (container time, UTC),
keeps them for 30 days (`BACKUP_HOUR`, `BACKUP_KEEP_DAYS` in `.env`). Files: `backups/trs398_YYYY-MM-DD_HHMMSS.sql.gz`;
they contain the users' data and password hashes, keep the folder private (it is not committed to git). A backup at any moment:
the “Make a backup now” button on the **“Backups”** page (administrator menu) or `backup-now.bat`.

**Restore:** run `restore.bat` (Linux/macOS: `./restore.sh`), choose the number of the backup and type `YES`.
The program stops, **the current database is first saved to `backups/keep`** (a wrong choice can be undone the same way),
the database is replaced by the backup, the program starts again.

**Move to another computer or reinstall:** install the program (`start.bat`), put the backup file into the `backups` folder,
run `restore.bat file_name`. The users' passwords are transferred with the backup.

**A new empty database:** stop the program (`stop.bat`), run `docker compose down -v` (deletes the data volume;
first `backup-now.bat` and copy the file somewhere), then `start.bat`: the browser offers to create the administrator again.

To check that the latest backup is readable (it is loaded into a temporary database and compared with the working one, the working one is only read):
`python tools/verify_backup.py`. To check that all stored results can be reproduced from the input data:
`docker exec -i trs398_app python - < tools/recompute_check.py` (PowerShell: `Get-Content tools/recompute_check.py -Raw | docker exec -i trs398_app python -`).

## What it can do

- Photons and electrons: kTP, kpol, ks (two-voltage method), kvol (FFF), kQ (Tables 16, 20, 21), Dw(zref), Dw(zmax).
- Workflow: draft → under review → approved (or returned). The author cannot approve their own record.
  An approved record cannot be changed, only superseded with a reason. The protocol number (YYYY-NNNN) is assigned by the database.
- **Protocol**: a print page and a PDF (buttons “Print” and “Download PDF”) in the form of the “Calculation” worksheet (yellow, blue and green cells, formulas, check boxes), plus the appendix “Uncertainty estimate”
  (a one-page summary by default; the full one with stages 1–2, Type A from the journal, uc and U, notes and the recalibration decision is available with `?unc=full`).
- **Energy comparison**: all energies of one linac together: the state of each, overlaid series, an “energy × month” map, a search for a common shift of several energies in one month and the correlations between the energies.
- Tables are sorted by clicking a header, the top bar and the table headers are pinned.
- The parameters of sections 1–3 of the worksheet (linac, beam, chamber, calibration, polarities, electrometer) are set in “Equipment”; on the calculation sheet they are only displayed. The readings (iii) and (iv) are filled in from the first record of the beam and can be changed.
- Trends: control limits ±2σ/±3σ, signal rules, CUSUM, a forecast of exceeding ±2 %, a fixed baseline period.
- The administrator: users, equipment, the audit log, backups, clearing the database.
- Two languages (Russian, English) for the interface, the protocol/PDF, the help and the start scripts.

## Roles

| Role | Rights |
|---|---|
| viewer | view measurements and trends |
| physicist | enter measurements, submit for review, chamber calibrations |
| reviewer | approve and return records of others, supersede approved ones |
| administrator | everything above, users, linacs and beams, the SPC baseline period, the audit log, backups, clearing the database |

## Clearing the database

The administrator: the menu item “Clear database”. A scope, a reason, the password and the word `УДАЛИТЬ` (or `DELETE` in the English interface) are needed. Measurements/results and/or historical journals
are deleted. Users, equipment, reference tables and the audit log are kept, the clearing itself is written to the audit log. The application role has no `DELETE` right: deletion is possible only through the
protected function `admin_purge()` and only for an active administrator. Make a backup before clearing.

## Demo data

`python tools/seed_demo.py` fills the database with 2 years of monthly data: **2 linacs** (TrueBeam, Versa HD) and **15 beams**: photons 6, 6 FFF, 10 FFF, 15 MV and electrons 6, 9, 12, 15 MeV (360 approved records).
Chambers and calibrations (illustrative values): TrueBeam follows the 2.0 templates (SNC600c Farmer, ND,w = 0.05138 Gy/nC; PTW 34001 Roos, ND,w = 0.5791 Gy/nC),
Versa HD has its own (PTW 30013 Farmer and IBA NACP-02, the IBA Dose1 electrometer), plus two reserve chambers with a valid calibration (IBA FC65-G Farmer, a second PTW 34001 Roos).
Each working chamber has two calibrations: a past one (expired, not available in the form) and the current one. The records are marked DEMO, made by the “Demo physicist” and approved by the “Demo reviewer”
(disabled accounts, nobody can sign in as them). The data have something to show: an excursion out of tolerance and a re-adjustment (Versa HD 6 MV), a slow drift (TrueBeam 12 MeV),
a common shift of several energies in one month (TrueBeam). Beams with your real data are skipped. To remove only what was added: `python tools/seed_demo.py --remove`.
Make a backup before running it (`backup-now.bat`). The script needs `.env` with the database owner's password and a running program.

## Development

```
python -m venv .venv && .venv\Scripts\pip install -r requirements-dev.txt
.venv\Scripts\python -m pytest -q tests
```

The end-to-end tests use a separate database `trs398_test` on the running container `trs398_db` (port 5433) and do not touch the working
data; without the database they are skipped. The PDF is produced by WeasyPrint, which is part of the Docker image.

### Languages

Russian is the source language of the interface; English comes from the phrase catalog `app/i18n/en.json` (`app/i18n.py` translates the finished page).
After changing any Russian text of the interface: `python tools/i18n_extract.py` lists the phrases without an English text, `--todo file.json` writes them for translating,
`--merge file.json` takes the translations in. The test `tests/test_i18n.py` fails if a phrase has no English text or a page still contains Russian in English mode.
The scripts take the language from `TRS_LANG` in `.env` (messages in `tools/msg.en.bat` and `tools/msg.ru.bat`, checks in `tools/preflight.ps1`).

## Structure

- `core/`: calculation (photons, electrons, SPC), reference tables in `core/data/`
- `app/`: the web application (FastAPI, Jinja2, HTMX), `app/protocol.py` assembles the protocol data, `app/i18n.py` the translation
- `db/init/`: schema, roles, migrations
- `importers/`: transfer of tables and journals from xlsm (read-only)
- `docs/DESIGN.en.md`: analysis of the source worksheets, formulas, the data model (Russian: `docs/DESIGN.md`)

## Licence

The code is distributed under the [MIT](LICENSE) licence. The IAEA reference tables in `core/data/` are not covered by the project's
licence, see [NOTICE.md](NOTICE.md).
