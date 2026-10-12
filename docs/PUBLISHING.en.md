# Before making the repository public

The owner's decision: the IAEA tables (`core/data/photon_tables.json`, `core/data/electron_tables.json`) stay in the repository.
While the repository is private this is not an issue. Before opening it:

1. Check the terms of use of TRS-398 Rev.1 (https://doi.org/10.61092/iaea.ve7q-y94k) with regard to
   redistributing the kQ tables (16, 20, 21) and the ks table (10). If redistribution is not allowed, delete the two JSON files
   (including from the git history) and keep the `importers/` scripts: the tables are built from the user's own worksheets.
2. Make sure there are no real data in the git history: `.env`, `backups/`, `tests/data/*.json`, `docs/sample_*.pdf`
   are ignored; check `git log --stat` for stray files.
3. Replace the repository address and the contacts in the README, keep the medical disclaimer from `NOTICE.md`.
4. Run `pytest`, `tools/recompute_check.py` and CI.
5. Only after that: Settings → General → Change visibility.

# Releasing versions and delivering them to computers without the Internet

The computers of a hospital often have neither GitHub nor the Internet. So every version is released as a package that is carried by a USB stick
or a network folder; GitHub is only needed by you to get the finished package.

## How to release a version

1. Make sure the tests pass (`.venv\Scripts\python -m pytest -q tests`) and everything is committed.
2. Set a tag: `git tag v1.0.0` and `git push origin v1.0.0`. GitHub Actions builds the image (it goes to `ghcr.io/kir0000/trs398-app:1.0.0`)
   and attaches two files to the release page (Releases):
   - `TRS398-1.0.0-offline.zip`: everything with the Docker images inside (about 0.5–0.7 GB), for computers without the Internet;
   - `TRS398-1.0.0-installer.zip`: the same without the images (small), the images are pulled at the start (needs the Internet and a public package in ghcr.io).
3. The same can be made on your own computer without GitHub: `python tools/make_bundle.py 1.0.0` (needs Docker); the packages appear in the folder `dist/`.
4. The version is shown in the program (at the bottom of a page, `/healthz`) and in the name of the image; the number comes from the tag or from the file `VERSION`.

## Installing on a computer without the Internet

1. Install Docker Desktop from the installer that your IT department gives you (it is not part of the package: it has its own licence) and WSL 2
   (on closed networks the IT department installs it beforehand). In detail: `INSTALL.en.md`.
2. Copy `TRS398-<version>-offline.zip` to the computer and unpack it into a folder without Russian letters, for example `C:\trs398`.
3. Check the integrity (optional): `certutil -hashfile TRS398-<version>-offline.zip SHA256` and compare with the sum on the release page.
4. Run `start.bat`: the images are loaded from the package (a few minutes, once), then the browser opens. Further as in `INSTALL.en.md`.

## Updating to a new version

1. Unpack the new `TRS398-<version>-offline.zip` over the old folder: the file `.env` and the folders `backups` and `certs` are not in the package, they stay.
2. Run `update.bat`: it makes a backup, loads the images of the new version, restarts the program and applies the changes of the database schema.
3. If something goes wrong, restore the backup (`restore.bat`) and run the previous version.

## What is published (open code)

The image and the repository hold the code of the program, the documentation and the reference tables. They hold no patient data, no passwords and none of your measurements:
`.env`, `backups/` and the databases stay on your computer. The image in ghcr.io is private by default; to let anybody download it without signing in,
open after the first publication: profile → Packages → trs398-app → Package settings → Change visibility → Public.
Before opening the repository go through the checklist above (at the start of this file).
