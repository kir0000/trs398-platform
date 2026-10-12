# Notice: third-party material and medical disclaimer

## Medical disclaimer

This software calculates absorbed dose to water following the formalism of IAEA TRS-398 Rev.1 (2024).
It is provided for educational and research use. It is **not** a certified medical device. Every result must be
checked independently (for example against the IAEA worksheets or a second dosimetrist) before it is used in
clinical practice. The authors accept no responsibility for clinical decisions based on its output.

## IAEA TRS-398 Rev.1 data

The files `core/data/photon_tables.json` and `core/data/electron_tables.json` contain numerical data that
originates from IAEA Technical Reports Series No. 398 (Rev.1, 2024): the kQ tables (Tables 16, 20, 21) and the
ks coefficients (Table 10). That material belongs to the IAEA and is **not** covered by this project's MIT
license. Before redistributing it, check the IAEA's terms of use for the publication
(https://doi.org/10.61092/iaea.ve7q-y94k). If redistribution is not permitted, remove those two files and
regenerate them locally from your own worksheets with the scripts in `importers/`.

Chamber wall thickness and cavity length values come from the same worksheets and manufacturer data sheets.

## Software dependencies

FastAPI, Starlette, Jinja2, psycopg, SciPy, argon2-cffi, WeasyPrint and HTMX are used under their own
licenses (BSD/MIT/LGPL and similar). The container image also installs the Liberation and DejaVu fonts.

The browser libraries are bundled in `app/static/` so that the program works without internet access: HTMX 1.9.12 (BSD 2-Clause) and Plotly.js 2.35.2 (MIT).
