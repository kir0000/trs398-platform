# TRS-398 Rev.1: a platform for the determination of absolute dose

*Русская версия: [DESIGN.md](DESIGN.md)*

The transfer of two xlsm worksheets (photons HE v2.0, electrons HE v2.0) into Docker + PostgreSQL with trends.
Status: implemented (see the [README](../README.en.md)); this document keeps the analysis of the source worksheets and the decisions taken.

## 1. What the macros actually do

The TRS-398 calculation in the worksheets is done by **sheet formulas and named ranges**, not by VBA.
The macros do three things, and only the third one is needed by the platform as logic.

### 1.1 The worksheet interface (not needed in the platform)
- About 25 `CheckBox*_Click` handlers switch modes: SSD/SAD, pulsed/scanned beam,
  polarity, the way TPR is obtained, FFF/WFF. They change the hidden sheet “Черновик” (Draft), show and
  hide objects, colour and lock cells (`Locked`, `Interior.ColorIndex`).
- `Worksheet_Change` (sheet “Расчёт” = Calculation): a warning if |RHo − RH| ≥ 30 (humidity
  at the measurement and at the calibration); re-locking PDD20 when the filter changes (I8).
- `Workbook_Open`: shows the sheets, sets the protection. `Workbook_BeforeClose`: the save dialog.
- `modFixRU2.Fix_Formatting_Rev1`: fixes the Russian captions and the superscripts/subscripts.
- In the platform this is replaced by an ordinary form with validation and conditional fields.

### 1.2 Protection (replaced by real roles in the platform)
- The structure of the workbook and the sheets are protected by passwords that are **hard-coded** (`heslo`, `WB_PASSWORD`).
  This protects against accidental damage, not against access: the code can be read from the xlsm without a password.
- Consequence: the passwords of the worksheets are not transferred to the platform, authentication and roles are made anew (section 3).

### 1.3 The journal and trends (`LogDose`, its logic must be transferred)
- `AddToLog`: takes the current calculation (row 3 of the “Журнал” = Journal sheet) and appends a record to the table
  `ЖурналТбл`: date, chamber, MQ, Dw(zref), Dw(zmax), kTP, kelec, kpol, ks, kvol, kQ, ND,w, TPR20,10
  plus a note (the performer, the protocol number). It warns about a duplicate (the same date and the same Dw).
- `DeleteJournalRows`: deletes the selected records after confirmation (irreversible).
  After the deletion all formulas are rebuilt (`RebuildAllFormulas`).
- Most of the `LogDose` code works around the peculiarities of Excel: self-growing ranges
  damaged neighbouring rows, so the formulas are written as text. **The database has no such problem.**

The journal formulas that have to be kept:

| Quantity | Formula |
|---|---|
| Deviation from 1 cGy/MU, % | `(Dw_zmax − 0.01) / 0.01 · 100` |
| Deviation from the previous one, % | `(Dw − Dw_prev) / Dw_prev · 100` |
| MR (moving range) | `abs(dev_i − dev_{i−1})` |
| CL | the mean of the deviations (over all records) |
| σ | `MR̄ / 1.128` |
| ±2σ, ±3σ | `CL ± 2σ`, `CL ± 3σ` |
| UCL(MR) | `3.267 · MR̄` |
| SPC signal | a point beyond 3σ; 2 of the last 3 beyond 2σ on one side; 8 in a row on one side of CL |
| CUSUM | `k = 0.5σ`, `H = 5σ`; `C+_i = max(0, C+_{i−1} + (x−CL) − k)`, `C−_i = min(0, C−_{i−1} + (x−CL) + k)` |
| Status | `\|dev\| > 2 %` action; `> 1 %` watch |
| Trend, %/month | `SLOPE(dev, date) · 30.4375` |
| Forecast of exceeding ±2 % | the crossing of the trend line with ±2 % |
| kelec trend | the kelec values of the records over time (calibrations) |

Subtleties to be decided consciously (they are implicit in the xlsm):
- CL and σ are computed over **all** records and move with every new point. For SPC a baseline period is usually fixed.
  In the platform: `spc_baseline` with start and end dates, recalculated on request.
- The 2-of-3 and 8-in-a-row signals are tied to the record number, not to the date. In the database the order by date is used.

## 2. Calculation formulas (on the sheets, not in VBA)

### Photons (section 6 of Rev.1)
- `kTP = (P0/P) · (273.2 + T)/(273.2 + T0)`
- `kpol = (|M+| + |M−|) / (2·M)`; if Q ≠ Q0: `kpol / kpol_Q0`
- `ks = a0 + a1·(M1/M2) + a2·(M1/M2)²`, the coefficients `a0..a2` by linear interpolation over V1/V2 from Table 10
  (separate sets for pulsed and scanned beams)
- `kvol` (FFF only): `1 + (0.0062·TPR20,10 − 0.0036)·(100/SDD)²·L²`, `SDD = SSD + zref`, L from the chamber data sheet
- Beam quality:
  - WFF: `TPR20,10 = 1.2661·(PDD20/PDD10) − 0.0595`
  - FFF: `TPR20,10 = −0.7898 + 0.0329·PDD10 − 0.000166·PDD10²`
  - the allowed range of Table 16: 0.56–0.82 (outside it kQ is not defined)
- `kQ` from Table 16 (26 chambers, 12 TPR nodes from 0.56 to 0.82), **linear interpolation** (VBA `Interpolate`)
- `M_corr = M1 · kTP · kelec · kpol · ks · kvol`; `Dw,Q(zref) = M_corr · ND,w · kQ,Q0`
- `Dw(zmax)`: SSD `= 100·Dw(zref)/PDD(zref)`; SAD `= Dw(zref)/TMR(zref)`
- The “1 cGy/MU” check: `Dw(zmax)·100`, the correction in %, the value at 200 MU

### Electrons (section 7 of Rev.1)
- measured `R50`; `Q (R50,w) = factor · R50 · 1.029 − 0.06` (sheet Temp)
- `zref = 0.6·R50 − 0.1`
- `kQ` from Tables 20 (calibration in 60Co) and 21 (calibration in an electron beam), 16 chambers, an R50 grid of 14 nodes
  (1.0 … 10 g/cm²), **a natural cubic spline** (checked against scipy in `modRev1kQ`, the difference is < 1e-15)
- `Dw` by the same k factors (kTP, kpol, ks, kelec)

### Uncertainty
A separate sheet “Неопределённость” (Uncertainty) in both files. In the first version of the platform it is shown in the report as it is,
the calculation was transferred in the second stage (see the plan).

## 3. Roles and access

Two layers: the application roles (what a person may do) and the database roles (what a service may do).

### 3.1 Application roles (RBAC)

| Role | Who | Rights |
|---|---|---|
| `viewer` | any employee of the department | view measurements, trends, reports |
| `physicist` | a medical physicist | everything of `viewer`, plus create and edit **own drafts**, submit for review |
| `reviewer` | a senior physicist / a second reviewer | everything of `viewer`, plus approve or return records. **Cannot approve their own record** |
| `admin` | the person responsible for the system | users and roles, reference tables (chambers, kQ tables), linacs, the SPC baseline period, alarm thresholds |

Rules:
- Record statuses: `draft → submitted → approved` (or `returned → draft`). Only **approved** records go into the trend and SPC.
- An approved record is immutable. A correction creates a new record that refers to the old one
  (`supersedes_id`), the old one gets the status `superseded` with a mandatory reason. There is no physical deletion,
  this replaces the macro “Delete records”.
- The two-person principle: `approved_by ≠ created_by` (a CHECK in the database).
- Reference tables (kQ, ND,w, chambers) are versioned: every calculation stores the version of the tables and of the formulas,
  so that the result can be reproduced.
- The audit log (`audit_log`) is append-only (UPDATE and DELETE are forbidden by a trigger).

### 3.2 PostgreSQL roles
| DB role | Purpose | Rights |
|---|---|---|
| `trs_owner` | migrations | owner of the schema, DDL |
| `trs_app` | the application | `SELECT/INSERT/UPDATE` on the working tables, only `INSERT` into `audit_log`, no `DELETE` |
| `trs_readonly` | Grafana, analytics | `SELECT` on the views (`v_trend`, `v_spc`), no access to users and password hashes |

The passwords of the DB roles come from `.env` (not stored in the repository). The passwords of the application users are stored
only as hashes (argon2/bcrypt).

## 4. The data model (briefly)

Reference tables: `chambers`, `chamber_kq_photon`, `chamber_kq_electron`, `electrometers`, `linacs`, `beams`.
Equipment and calibrations: `chamber_units` (SN), `calibrations` (ND,w, kelec, laboratory, date).
Measurements: `measurement_sessions` (input data), `results` (all k factors, Dw, deviation, versions).
Quality control: `spc_baseline`, the views `v_trend`, `v_spc`.
Service: `users`, `audit_log`, `protocol_counters`.

The schema is in `db/init/001_schema.sql` (migrations 002–008 next to it).

## 5. The work plan (as it was)

1. **The calculation core** (pure Python) with tests: photons, then electrons. The reference: your xlsm files
   (photons 6 FFF: kQ = 0.99726616; ks = 1.00299564; kvol = 1.00124046; kTP = 1.01031742; Dw(zmax) = 0.0100012639 Gy/MU).
2. **The database and roles**: the schema, migrations, import of the reference tables and journals from xlsm.
3. **The web application**: entering a measurement, the calculation, submitting for review, approval.
4. **Trends**: SPC on the database data (the rules of section 1.3), Grafana on `v_trend`.
5. **PDF reports and uncertainty.**

## 6. Open questions (at the design stage)
- The SPC baseline period: fix after N points or manually?
- Is an integration with LDAP/Active Directory needed, or are local accounts enough?
- Should the source xlsm files be stored as attachments to a record?
- The approval rules: always a second person or only for certain types of measurements?

## 7. Verification results (Oct 2026)

- The photon and electron core matches the values stored in the xlsm (tests `tests/test_photon.py`, `tests/test_electron.py`).
- SPC (`core/spc.py`): CL, the trend slope and the last deviation agreed with the “Тренд” (Trend) sheet.
- **In the photon xlsm the SPC columns of the journal are not calculated.** The formulas “record No.”, “previous Dw”, “previous dev.” are in
  columns I, J, K, while the formulas MR, “SPC signal” and CUSUM refer to J, K, L (a shift by one column after a column
  was deleted). Because of this MR is empty, σ in “Trend” is empty, the ±2σ/±3σ limits and CUSUM give `#N/A`,
  and “SPC signal: no” is always shown. The Python calculation finds a “beyond 3σ” signal at record 14 (2024-12-14,
  +0.82 %), and a manual note about a “beyond 3σ” signal is attached to exactly that record in the journal.
- The electron journal (25 records) is marked “Demo data”: it was imported with the flag `is_demo` and does not go into the trends.
- The historical journals contain only totals (no readings), so they are kept in `legacy_journal`.

## 8. Uncertainty and interactive charts

- `core/uncertainty.py`: a budget per TRS-398 Rev.1 (Table 17 for photons, Tables 24/25 for electrons, section 7.10),
  Type A = the journal σ (MR̄/1.128), combination in quadrature, U = 2·uc, the contributions of the components, the recalibration decision
  (a verdict by the tolerance and U_rel = 2·√2·σ, the trend, months to the levels, the recommended date). The numbers of the sheets are reproduced
  to the last digit (`tests/test_uncertainty.py`).
- The pages `/trends` (a Plotly chart with a fallback server-side SVG) and `/uncertainty` (a Plotly contribution chart).
- Findings in the source xlsm:
  - photons: the total cells of the “Неопределённость” sheet (`uc`, `U`) show `#VALUE!`, because Type A is taken from
    “Trend” (D5), which is empty because of the column shift of the journal (see section 7);
  - electrons: the condition “R50 of the current beam” uses the named range `R_50`, which points to an empty cell
    (R50 of the calibration beam), so for a plane-parallel chamber the value for R50 < 2 g/cm² (0.8 %) is always taken.
    The platform uses the R50 of the measured beam (0.7 % at R50 ≥ 2 g/cm²); this difference from the sheet is deliberate.

## 9. The protocol and the appendix “Uncertainty estimate”

- The protocol (`app/protocol.py`, `app/templates/protocol.html`) reproduces the “Расчёт” (Calculation) sheet (cell colours, formulas, check boxes,
  the block “Note: 1cGy=1MU check”, footnotes a–f) on A4; in Excel the same sheet falls apart into 6 pages across its width.
- The appendix to the protocol follows the “Неопределённость” sheet of the electron file together with its comments:
  the configuration, stages 1 and 2 (Type B, yellow cells), Type A (the journal σ at the date of the measurement), uc and U (k = 2), the reference value
  of TRS-398, the GUM definitions, the notes (a)–(e) for electrons and (a)–(d) for photons, the block “Recalibration decision”.
  The texts are in `core/uncertainty_text.py`, the calculation in `core/uncertainty.py`, the data of the block in `protocol.uncertainty_block()`.
- The appendix is a **one-page summary by default**; the full one is available with `?unc=full`, none with `?unc=none`.
- The history for Type A and the trend: the approved and imported records of the beam up to the measurement date plus the record itself if it is not
  approved yet; if an SPC baseline period is set for the beam, it is used.
- The check against the stored values of the electron sheet: the trend 0.142 %/month, the deviation by the trend line 0.554 %, U_rel 1.44 %,
  σ 0.51 % agree; uc differs deliberately (see section 8, the `R_50` reference in the source sheet).
- `tools/render_sample.py` draws sample protocols (synthetic data) inside the container for a visual check.

## 10. Demo data and equipment

- `tools/seed_demo.py` (tested on a separate database, `tests/test_seed_demo.py`): 2 linacs with a model and a serial number
  (TrueBeam 2480, Versa HD 7213), photons 6, 6 FFF, 10 FFF, 15 MV and electrons 6, 9, 12, 15 MeV; each linac has its own chambers and electrometer
  (TrueBeam follows the 2.0 templates), each working chamber has two calibrations, and two reserve chambers are registered;
  24 monthly records per beam with real readings from which the core computes the results. Two scenarios are set explicitly: an excursion out of tolerance with an adjustment
  and a drift without a jump.
- The register of what was created is kept in the audit log (`seed_demo`); `--remove` deletes only it and the records with `extra.demo`.

## 11. Equipment parameters and reference readings

- The parameters of sections 1–3 of the sheet are set once in “Equipment” and are not changed on the calculation sheet: for the linac (model, serial No.,
  city), for the beam (dose rate, field size or applicator, phantom, window, cpl, hpl, zmax), for the calibration (ND,w, Q0 and R50,w, depth,
  P0, T0, humidity, V1, polarity at calibration and “with correction”, polarity at the user, laboratory, dates, the electrometer
  with a serial number and a range, the box “calibrated separately” with kelec, the laboratory and the date).
- The calculation takes these values only from the equipment (`app/main.py: equipment_values`), what the browser sent is replaced; a snapshot
  of the values is stored in the record (`extra.form`), so later edits of the equipment do not change old protocols.
- **kelec**: the value from the certificate (for example VNIIFTRI) is used only with the box “calibrated separately from the chamber”,
  otherwise kelec = 1 (TRS-398 Rev.1, note c).
- **The readings (iii) and (iv)** (M+, M−, M at the user's polarity, M1 at V1, M2, V1, V2, beam type) are determined once for a
  beam and chamber: the form fills them in from the first approved record of the beam, any value can be changed. kpol and ks are calculated from
  these series (`PhotonInput.m_pol`, `m1_ks`), so they do not depend on the size of the current reading M1. M at the user's polarity is
  set from M+ or M− according to the polarity in Equipment and is stored with the record.
- A calibration that has already been used in measurements cannot be edited (the protocols refer to it): a new calibration is added.
  A chamber whose calibration has expired cannot be chosen for a new measurement.

## 12. Energy comparison

`core/compare.py` and the page `/compare`: the series of all beams of a linac are brought together by calendar months (the mean per month). A common shift:
in a month at least 3 beams with data and at least 70 % of them deviated to one side by at least 0.3 %, with a mean of at least 0.3 %
(a common cause: the monitor, the environment, dosimetry). The Pearson correlation of the monthly deviations with at least 6 common months. The hints
are worded for the physicist and do not replace decisions. The demo data of TrueBeam contain a common-shift scenario (March–April 2026).

## 13. Later additions

- **Protocol number** (`protocol_no`, migration 008): `YYYY-NNNN`, assigned by a database trigger at the creation of a record, sequential per year of the measurement,
  not editable, never reused.
- **Backups and restoring**: `db/backup.sh`, `db/restore.sh`, `restore.bat`, the “Backups” page; a safety copy of the current database is made before every restore.
- **First start**: the first administrator is created in the browser (`/setup`), no password is kept in `.env`.
- **Network access** (`lan-on.bat`, optional HTTPS through Caddy) and the **two languages** (`app/i18n.py`, the phrase catalog `app/i18n/en.json`).
- **Guards against typos**: the dates of calibrations and measurements cannot lie in the future, an expired calibration cannot be chosen, ND,w is checked against
  the typical range of the chamber type (a soft hint).
