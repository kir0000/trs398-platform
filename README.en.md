# TRS-398 Rev.1: absolute dose determination

*Русская версия: [README.md](README.md)*

A program for calculating the absorbed dose to water by TRS-398 Rev.1 (high-energy photons and electrons): a single-file database,
roles, approval by a second person, output trends (control charts, CUSUM) and a PDF protocol in the form of the "Расчёт" worksheet.
It runs on an ordinary Windows laptop, **without Docker and without installing a database**. The interface is in **Russian and English** (RU / EN switch at the top).

> Educational and research use. The program is not a certified medical device: every result must be checked independently. See [NOTICE.md](NOTICE.md).

## Installation (Windows 10/11)

1. From the **Releases** page download `TRS398-setup-….exe` and run it (no administrator rights needed). Without installing: `TRS398-portable-….zip`, unpack into any folder.
2. Start **TRS-398**. An icon appears in the tray (near the clock) and `http://localhost:8000` opens in the browser.
3. At the first start the program asks for the login and password of the administrator (choose your own). Then: "Users" (physicists and reviewers), "Equipment" (machine, beams, chamber and calibration), "Measurements".

Windows may show a "SmartScreen" warning (the program has no paid digital signature): "More info → Run anyway".
Details: [docs/INSTALL.en.md](docs/INSTALL.en.md), Russian: [docs/INSTALL.md](docs/INSTALL.md).

Tray icon menu: open the program; make a backup; data folder; restore from a backup; error log; start with Windows;
allow connections from other computers; exit. Closing the browser window does not stop the program, "Exit" does.

**Several physicists.** The program runs on the laptop of one of them; the others open `http://laptop-name:8000` in a browser
(switch on "Allow connections from other computers", [docs/NETWORK.en.md](docs/NETWORK.en.md)). Data and users are shared and kept on that laptop.
A guide for physicists: [docs/USER_GUIDE.en.md](docs/USER_GUIDE.en.md) (also inside the program, item "Help").

**Where the data are.** Installed version: `%LOCALAPPDATA%\TRS398\data` ("Data folder" in the icon menu). Portable version: the folder `data` next to the program.
The whole database is one file `trs398.db`; backups are in `backups` beside it.

### Backups and restoring

The program makes a backup at start and then every day after 02:00 (the computer's time) while it is running, and keeps them for 30 days
(the page “Settings” or the `BACKUP_HOUR`, `BACKUP_KEEP_DAYS` environment variables). Every backup is checked at once (unpacked, `integrity_check`, the number of measurements): a backup that cannot be read is removed and the error is shown in the log and on the “Backups” page; the database file itself is checked at the start and once a day, damage is shown by a red banner on every page. If the data folder lies in a synchronised cloud folder (Yandex.Disk, OneDrive, Dropbox, Google Drive…), the program warns about it: synchronisation can damage the database file. The files `backups\trs398_YYYY-MM-DD_HHMMSS.db.gz` contain user data and password hashes, keep the folder closed.
A backup at any moment: the icon menu or the button "Make a backup now" on the **Backups** page. **Important:** by default the backups lie on the same laptop. Set a **second folder** on the “Backups” page (another disk, a USB stick, a network folder or a cloud folder): every new backup is written there too, and a failure is shown as a warning on the “Backups” page and in “About”.

**Restore:** the icon menu item "Restore from a backup…" (or the Start menu shortcut), choose the number of the backup, type `YES`.
The program closes, **the current database is saved in `backups\keep` first**, then replaced by the backup. Start the program again.

**Move to another laptop:** install the program, put the backup file into `backups`, restore it. Passwords move with the backup. Faster: on the laptop with the data `python tools/make_transfer.py` (or the icon menu → “Make a backup”) makes a file `trs398_….db.gz`; on the other laptop put it next to `TRS398.exe` (or into the folder `transfer`) and double-click **`load-test-db.bat`** of the portable version (a file can also be dragged onto the script): the database of that copy of the program is replaced, the old one is kept in `backups\keep`, and only the program of the same folder is closed.

**A new empty database:** exit the program, rename or delete `trs398.db` in the data folder (make a backup first), start the program: it offers to create the administrator.

To check a backup: the Start menu shortcut "Check a backup". To check that all stored results reproduce from the raw data: `python tools/recompute_check.py` (from the sources).

### Moving from version 1.x (Docker, PostgreSQL)

The data are moved once by the script `tools/pg_to_sqlite.py` (needs Python and the running 1.x container; the database is only read; the script verifies every value and the trend view).
Version 1.x stays available in the branch `v1.x` of the repository.

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
- **Exporting a trend** to Excel (three sheets) and CSV: the points with limits and signals, the summary, the baseline periods. The **energy comparison** of a linac is exported the same way (five Excel sheets or a CSV).
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

Administrator: menu "Clearing the database". It needs a scope, a reason, the password and the word `DELETE` (in the Russian interface `УДАЛИТЬ`). Measurements/results and/or historical journals are deleted.
Users, equipment, reference data and the audit log stay; the clearing itself is written to the audit log. The audit log is cleared separately and only in a controlled way: “Audit” → “Clear the log…” (a reason, the password and the word CLEAR; before the deletion the whole log is saved as CSV in `backups/audit_archive`, a safety copy of the database is made in `backups/keep`, the records of earlier clearings are never deleted, the clearing itself stays in the log). Ordinary requests of the program cannot delete history (the database triggers protect it);
it is possible only through the maintenance operations in `app/dbops.py` for an active administrator. Make a backup before clearing.

## Demo data

`python tools/seed_demo.py` fills the database with 3 years of monthly data (`--years N` or `--months N` change the length, `--independent` removes the links between the energies; the energies of one linac share a common part (seasonal swing of the monitor, drift) and group events: all photons after a target service, all electrons after a scattering foil change, electrons from 9 MeV together, 6 MV with and without the filter): **2 linacs** (TrueBeam, Versa HD) and **15 beams**: photons 6, 6 FFF, 10 FFF, 15 MV and electrons 6, 9, 12, 15 MeV (360 approved records).
Chambers and calibrations (illustrative values): TrueBeam follows the 2.0 templates (SNC600c Farmer, ND,w = 0.05138 Gy/nC; PTW 34001 Roos, ND,w = 0.5791 Gy/nC),
Versa HD has its own (PTW 30013 Farmer and IBA NACP-02, the IBA Dose1 electrometer), plus two reserve chambers with a valid calibration (IBA FC65-G Farmer, a second PTW 34001 Roos).
Each working chamber has two calibrations: a past one (expired, not available in the form) and the current one. The records are marked DEMO, made by the “Demo physicist” and approved by the “Demo reviewer”
(disabled accounts, nobody can sign in as them). The data have something to show: an excursion out of tolerance and a re-adjustment (Versa HD 6 MV), a slow drift (TrueBeam 12 MeV),
a common shift of several energies in one month (TrueBeam). Beams with your real data are skipped. To remove only what was added: `python tools/seed_demo.py --remove`.
Make a backup before running it. The script works with the database in the data folder (`TRS_DATA`); close the program meanwhile.

## Development

```
python -m venv .venv && .venv\Scripts\pip install -r requirements-dev.txt
.venv\Scripts\python -m pytest -q tests
python run.py            # the server without the tray icon, http://localhost:8000
python tools/build_windows.py [--installer]   # build: needs pystray, pillow, pyinstaller, and Inno Setup 6 for the installer
```

`scipy` is not needed for the build (the kQ cubic spline is our own, `core/electron.py`; the comparison with scipy runs in the tests, it is in requirements-dev). The tests use a temporary SQLite database. The PDF is printed by the installed Edge or Chrome in headless mode (`app/pdf.py`; the test is skipped if there is none).
Release: a tag `v2…` starts the build of the installer and the zip in GitHub Actions. Released migrations `app/migrations/NNN_*.sql` are never edited (`tests/test_migrations.py` checks their hashes): any schema change is a new file with the next number; before applying it to a database with data the program makes a copy in `backups/keep`.

### Languages

Russian is the source language of the interface, English comes from the phrase catalog `app/i18n/en.json` (`app/i18n.py` translates the finished page).
After changing any Russian text of the interface: `python tools/i18n_extract.py` lists the phrases without English, `--todo file.json` exports them for translation, `--merge file.json` loads the translations, `--stale` lists the catalog entries that are no longer in the templates.
The automatic checks (`tests/test_i18n.py`, `tests/test_i18n_lint.py`: phrase boundaries, a clean catalog, Russian words glued to variables in the templates, every status of a record on every page for every role in English) fail if a phrase has no English text or Russian remains on a page in English mode. The default language is set by `TRS_LANG` (`ru` or `en`).

## Structure

- `core/`: calculation (photons, electrons, SPC), reference tables in `core/data/`
- `app/`: the web application (FastAPI, Jinja2, HTMX); `app/main.py` creates the application and includes the parts of `app/routes/` (sign-in pages, measurements, trends, uncertainty, equipment, administration), the common parts are in `app/web.py` and `app/common.py`; `app/db.py` and `app/migrations/` (SQLite), `app/protocol.py` assembles the protocol data
- `tray.py`, `run.py`, `trs398.spec`, `installer/`: start, tray icon, build
- `importers/`: moving tables and journals from xlsm (read only)
- `docs/DESIGN.en.md`: analysis of the source worksheets, formulas, data model (Russian: `docs/DESIGN.md`)

## Licence

The code is under the [MIT](LICENSE) licence. The IAEA reference tables in `core/data/` are not covered by the project licence, see [NOTICE.md](NOTICE.md).
