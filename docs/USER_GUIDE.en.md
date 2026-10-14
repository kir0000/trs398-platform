# User guide

A platform for the determination of absolute dose according to IAEA TRS-398 Rev.1 (photons and electrons). Address: `http://localhost:8000` on the computer with the program, from other computers of the network: the address shown by the tray icon menu (see “Network access” in the README).

## Roles

| Role | What it can do |
|---|---|
| Viewer | View measurements, trends, uncertainty and the energy comparison, print protocols |
| Physicist | The same, and also enter measurements, submit them for review, supersede an approved record, save the reference values of a beam |
| Reviewer | Approve or return the measurements of others (one's own cannot be approved) |
| Administrator | Equipment, users, the audit log, backups, clearing the database |

## 1. Once: the “Equipment” section

The equipment is changed by the administrator; a physicist and a reviewer see and use it. The section has three tabs:

- **Linacs and beams.** On the left the list of linacs, on the right the chosen linac: its data and the tables of beams “Photons” and “Electrons” (one row per beam, one “Save” button).
  Every beam has a readiness indicator: “missing” (without *z*<sub>max</sub> or *PDD*(*z*<sub>ref</sub>) the sheet cannot be filled), “not everything is filled in” or “✓ ready”.
  The reference point at SAD and the window of the electron phantom are in a collapsible block under the beam row.
- **A beam entered by mistake.** A beam without data is deleted with the “Delete” button. If the beam already has records, the “⋯” menu of its row offers two options:
  “To the archive” (the beam disappears from the choices of a new measurement, its records and trends stay; “Restore from the archive” undoes it) and, only if all records of the beam are drafts or returned ones,
  “Delete the beam and its drafts” (imported journal rows are deleted only with a separate tick). Approved, superseded and annulled records are history and cannot be deleted;
  annul a wrong approved record first (section 4) and send the beam to the archive.
- **Dosimetry.** Chambers (type and serial number) with the history of calibrations, the validity is highlighted (expires within the next 3 months, expired); such chambers are also reminded about by a red or yellow banner at the top of the “Measurements” page (by the newest calibration of each chamber), electrometers, the “New calibration” form.
- **Reference values.** The sets saved with the button “Make these values the reference” on the measurement sheet: for each pair “beam + chamber” you see who saved them and when and what they contain; the administrator can delete a set.

All parameters of sections 1–3 of the worksheet (chamber, *N*<sub>D,w</sub>, *Q*<sub>0</sub>, calibration conditions, electrometer, *k*<sub>elec</sub>,
polarity at the laboratory and at the user, “with correction”, “calibrated separately from the chamber”) are set **only here**.
On the calculation sheet they are filled in automatically and are not changed.

1. Add a linac (several are possible) and its beams (photons or electrons, energy, FFF).
2. Add a chamber and an electrometer, then a calibration (*N*<sub>D,w</sub>, date, “valid until”, laboratory, voltage, *k*<sub>elec</sub>).
   Compare *N*<sub>D,w</sub> with the certificate: for Farmer-type chambers it is usually about 0.05 Gy/nC, for plane-parallel ones about 0.5.
3. For electrons give the material and the thickness of the water phantom window, the plastic phantom and the factors *c*<sub>pl</sub>, *h*<sub>pl</sub>.
4. If *k*<sub>elec</sub> is calibrated separately from the chamber (for example at VNIIFTRI), tick the box and give the laboratory and the date.
5. For every beam enter *PDD*(*z*<sub>ref</sub>) and *TMR*(*z*<sub>ref</sub>), the MU at calibration and, for SAD, the expected dose at the reference point (see section 6).

## 2. New measurement

1. “Measurements” → “New measurement”: choose the beam type, the linac and the energy. Chambers whose calibration has expired are not available in the list
   (grey, “expired”); the server also rejects such a record. The calibration and measurement dates cannot be later than today.
2. **Beam quality *Q*.** Enter the measured TPR<sub>20,10</sub> directly (sec. 6.3 of TRS-398 Rev.1) or leave it empty and enter PDD:
   PDD(10) and PDD(20) for a beam with a filter, only PDD(10) for a flattening-filter-free (FFF) beam; the PDD(20) field is disabled.
   Next to *Q* the source is shown: “entered manually”, “calculated from PDD”, or a warning if the entered value
   differs from the calculated one by more than 0.003. The entered value is always the one used in the calculation.
3. **Geometry.** For SSD, *PDD*(*z*<sub>ref</sub>) is entered; for SAD, *TMR*(*z*<sub>ref</sub>) is entered or the expected dose from “Equipment” is used; the field that does not apply is disabled.
4. **Conditions.** The pressure *P* and the temperature *T* are accepted within 80–110 kPa and 10–35 °C. The humidity defaults to 50 %; between 20 and 80 % its influence
   on the readings can be neglected (per TRS-398), outside this range a warning appears.
5. **Readings.** Enter the series separated by spaces. Next to each series the mean and the drift are shown: the slope of the trend line over the series
   in % of the mean (green up to 0.2 %, yellow up to 0.5 %, red above). Use a series without drift in one direction.
6. **Corrections (iii) and (iv).** Two series are needed for polarity (*M*₊ at +*V*₁ and *M*₋ at −*V*₁) and two for recombination
   (*M*₁ at *V*₁ and *M*₂ at *V*₂). *M* in the formula for *k*<sub>pol</sub> is taken from *M*₊ or *M*₋ according to the user's polarity set in “Equipment”.
   For a new measurement the reference readings of the beam and chamber are filled in (if saved), otherwise the initial ones (the first approved record);
   any value can be changed. Buttons above the block: “Fill in the initial readings of the beam”, “Fill in the reference readings” and
   “Make these values the reference”. The last one saves the values of the open sheet (beam quality *Q*, the series *M* and MU, readings (iii) and (iv))
   as the reference of the selected beam and chamber (available to a physicist or the administrator; the action is written to the audit log).
7. The **result** is pinned to the bottom of the screen and updates as you type. Colour by the deviation from 1 cGy/MU (at SAD from the expected dose): green up to 1 %,
   yellow 1–2 %, red above 2 %.
8. The “?” sign next to a field opens an explanation. Save the record as a draft, then press “Submit for review”.
   The **protocol number** (like `2026-0042`, numbered per year of the measurement) is assigned by the database when saving; you do not type it.
   It is shown in the list, on the record page and on the printed protocol and never changes. Use the “Note” field for a comment only.

## 3. Review

A second person opens the record from the “under review” list, checks the data and presses “Approve” or “Return”.
The author cannot approve their own record (this is enforced both in the application and in the database).
An approved record is immutable; a correction is made by superseding (a new record, the old one gets the status “superseded”).

## 4. Deleting and annulling a record

- **Draft or “returned”.** The record page has a “Delete” button (the author or an administrator). The record disappears, its protocol
  number is not reused, and the audit log keeps who deleted which number and when.
- **Approved record.** It cannot be deleted. An administrator presses “Annul” and gives a reason (at least 5 characters). The record stays in the
  database with the status “annulled”, leaves the trends, the energy comparison and the uncertainty budget, and the protocol is printed with the
  mark “ANNULLED”. If a correcting copy (a replacement) is annulled, the record it replaced becomes valid again.
- **A corrected record is needed, not just a cancellation.** Use “Supersede”.

## 5. Printing the protocol

Open the record and press “Print” (page) or “PDF”. The form repeats the worksheet. The “Uncertainty estimate” appendix is a summary by default
(one page: components, *u*<sub>c</sub>, *U*, verdict); on the print screen you can choose “full” (all tables, the distribution and the formula of every component,
notes, the recalibration decision) or “no appendix”. The protocol is printed in the interface language; for another language add `?lang=ru` or `?lang=en` to the address.

## 6. Trends and analysis

- **Trends.** A Shewhart chart (I-MR), the Western Electric rules, CUSUM and a forecast of exceeding the tolerance for the chosen beam.
  For SAD the dose is determined at the reference point (isocentre at the reference depth) without recalculation to *z*<sub>max</sub>. In “Equipment” the beam gets
  the expected dose at the reference point (cGy/MU, from the planning system), the depth of that point and the source of the value, as well as the MU at calibration
  (filled into a new sheet). At SAD the deviation is taken from the expected dose. Every set of reference conditions (SSD; SAD with a given depth, field and
  expected dose) forms a separate trend series with its own limits and CUSUM; the series is chosen from a list on the “Trends” page, and values from different conditions are not mixed.
  If the expected dose or the depth is changed, new records go into a new series and the old ones stay in the previous one.
- **Baseline periods** (administrator). Each period starts its own segment of the statistics: the limits and the CUSUM sums are calculated anew from its first record
  (for example, after an adjustment). Records before the first period are shown grey, without limits and signals.
- **Uncertainty.** A budget per TRS-398 (tables 17/24/25), Type A from the journal, *u*<sub>c</sub>, *U* (*k* = 2), a recalibration recommendation.
  The Type B values can be changed to the conditions of the institution and the accreditation of the laboratory (the fields of the table, the “Save the values” button; “Restore the default values” undoes the changes),
  and your own lines can be added, including ready-made ones from the literature (TG-51 Addendum, McDermott 2024). Changed and added values are marked and go into the appendix to the protocol;
  physicists and the administrator can change them, and the changes are written to the audit log. At the bottom of the page there is a table comparing with published budgets.
  The budget tables give for every component the shape of the distribution (normal, uniform, triangular, U-shaped) and the formula by which its value is obtained from the source data
  (*u* = *U*/*k*, *a*/√3 etc.). The general formulas and the sensitivity rules for different energies are in the card “How the standard uncertainty is obtained”,
  and the distributions of the input data of McDermott 2024 are under the comparison table. In your own line you can enter the distribution, the parameter (*a*, σ or *U* with *k*) and the sensitivity *c*:
  the value of *u* is calculated automatically.
- **Energy comparison.** All beams of one linac on one chart, a month-by-month heat map, correlations, a search for a common shift. The charts follow the filters of the table of the state of each energy.

Tables are sorted by clicking a header; the page header is pinned.

### Exporting a trend to Excel and CSV

On the “Trends” page above the chart there are the buttons **“Download Excel”** and **“Download CSV”** (available to every role). The file belongs to the chosen beam and series (reference conditions). The Excel file has three sheets: “Data” (the date, the deviation, MR, the signals of the rules and of CUSUM, CL and the ±3σ limits of every point, the number of the baseline period, the source: a measurement or an imported journal, the protocol number, Dw(zmax)), “Summary” (CL, σ, status, trend, forecast, thresholds) and “Baseline periods”. The values are exact, not rounded to the screen. In the Russian interface the CSV uses “;” and the decimal comma (the Russian Excel reads it correctly), in the English one the comma and the point. Every export is written to the audit log.

### How to read CUSUM

CUSUM accumulates small deviations from the centre line CL, so it notices a slow drift or a small constant shift earlier than
the Shewhart chart. Each record adds its deviation from CL, reduced by the allowance *k* = 0.5σ, to the sum; C⁺ grows when the output is above CL,
C⁻ falls when it is below, and neither crosses zero. A signal is raised when C⁺ exceeds *H* = 5σ (shift up) or C⁻ falls below −*H* (shift down).

- **Example.** With σ = 0.3 % and the output 0.3 % above CL, the threshold is crossed at about the 10th record, while a chart with limits ±0.9 % does not see such a shift.
- **Repeated signals.** The sum is not reset after a signal, so consecutive signals belong to one shift; the shift began where the sum started to rise.
- **What to do.** A signal is a reason to check the measurement conditions (pressure, temperature, chamber, electrometer, monitor, accelerator output), not a verdict of a fault.
- **Limitations.** The limits are calculated from the journal itself: if it already contains a shifted series, set a baseline period to a stable time.
  The decision to recalibrate is made from the deviation from 1 cGy/MU and from the uncertainty, not from CUSUM.

The same note is on the “Trends” page (the “How to read CUSUM” block).

## 7. Interface language

The **EN / RU** switch is in the top bar (on the sign-in page at the top right). The choice is remembered in the browser; the default language is set by the `TRS_LANG` variable (`ru` or `en`).

The interface language, the encoding and the decimal separator do not depend on the language or the regional settings of Windows. Pages are always UTF-8; Russian pages show a comma in numbers (`2,5`), English pages a point (`2.5`),
and either can be typed. Only the look of the standard browser fields (for example, the date picker: dd.mm.yyyy or mm/dd/yyyy) depends on the region of the computer.

## 8. For the administrator

- “Users”: creating accounts and roles.
- “Audit”: the log of actions (records can only be appended, never changed or deleted). Each record shows the time, the user, the **address of the computer**, a readable name of the action, the object (a link to the protocol) and the details: reasons and comments, and for edits **“was → became”** (beam parameters, calibrations, measurement records, user roles). The log also holds the sign-in and sign-out, opening of the printed form and of the PDF of a protocol, the start of the program, the automatic backups and their failures, updates of the database structure and restoring from a backup. There are filters (dates, user, section, action, a search by text and address), pages of 100 records and an export **to CSV** (opens in Excel) with the same filters. The texts typed by people stay as written, also in English.
- “Backups”: the state of the backups, the “Make a backup now” button, instructions for restoring (the “Restore from a backup…” item of the icon menu).
- “Clear database”: deleting data (first check the backup freshness banner; the confirmation word is УДАЛИТЬ or DELETE).
- Backups: daily into the `backups/` folder, kept for 30 days. To check that a backup restores:

```bash
python tools/verify_backup.py
```

## 9. Glossary: terms and abbreviations

### Protocol and physics

| Term | Meaning |
|---|---|
| IAEA TRS-398 Rev.1 | The IAEA protocol (Technical Reports Series No. 398, revision 1) for the determination of absorbed dose to water in external beam radiotherapy |
| TG-51, TG-142 | AAPM recommendations: TG-51 on beam calibration, TG-142 on quality assurance of accelerators (tolerances) |
| SSD (source–surface distance) | The distance from the source to the phantom surface; the usual measurement geometry, 100 cm |
| SAD (source–axis distance) | The distance from the source to the axis of rotation (isocentre), 100 cm; the chamber at a given depth in the isocentre |
| SCD | The source–chamber distance: SCD = SSD + *z*<sub>ref</sub> |
| FFF (flattening filter free) | A beam without a flattening filter; a beam with a filter (WFF) needs PDD(10) and PDD(20), an FFF beam only PDD(10) |
| MU (monitor unit) | The monitor unit of the accelerator |
| *z*<sub>ref</sub> | The reference depth of the chamber (photons usually 10 g/cm²; electrons 0.6·*R*<sub>50</sub> − 0.1) |
| *z*<sub>max</sub> | The depth of the dose maximum |
| PDD(*z*) | The percentage depth dose at the depth *z*; PDD(10), PDD(20) at SSD 100 cm |
| TMR | The tissue–maximum ratio, for SAD |
| TPR<sub>20,10</sub> | The ratio of the readings at the depths 20 and 10 cm at a constant source–chamber distance: the quality index of a photon beam |
| *R*<sub>50</sub> | The depth at which the dose is 50 % of the maximum; the quality index of an electron beam |
| *Q*, *Q*<sub>0</sub> | The beam quality of the user and the reference quality of the calibration (usually ⁶⁰Co) |
| *N*<sub>D,w</sub> | The calibration coefficient of the chamber in terms of absorbed dose to water, Gy/nC |
| *M*, *M*<sub>+</sub>, *M*<sub>−</sub>, *M*<sub>1</sub>, *M*<sub>2</sub> | The electrometer readings, nC: at the polarity of the user, at the positive and negative polarity, at the voltages *V*<sub>1</sub> and *V*<sub>2</sub> |
| *V*<sub>1</sub>, *V*<sub>2</sub> | The working and the reduced chamber voltages, V (the two-voltage method) |
| *k*<sub>TP</sub> | The correction for air pressure and temperature |
| *k*<sub>pol</sub> | The polarity correction |
| *k*<sub>s</sub> | The correction for incomplete charge collection (recombination) |
| *k*<sub>vol</sub> | The volume effect correction (for FFF beams) |
| *k*<sub>elec</sub> | The electrometer calibration factor |
| *k*<sub>Q,Q0</sub> | The beam quality correction factor |
| *c*<sub>pl</sub>, *h*<sub>pl</sub> | The corrections for a plastic phantom (depth and fluence), electrons |
| *D*<sub>w</sub>(*z*<sub>ref</sub>), *D*<sub>w</sub>(*z*<sub>max</sub>) | The absorbed dose to water at the reference depth and at the depth of the maximum, Gy/MU |
| PSDL, SSDL | The primary and secondary standards dosimetry laboratories that issue the calibration certificate |
| VNIIFTRI | The Russian metrology institute that calibrates electrometers and chambers |

### Uncertainty and statistics

| Term | Meaning |
|---|---|
| GUM | The Guide to the expression of uncertainty in measurement (JCGM 100) |
| Type A, Type B | Type A: an estimate from a series of measurements; Type B: from specifications, tolerances and certificates |
| *u*, *u*<sub>c</sub>, *U*, *k* | The standard, the combined and the expanded uncertainty; the coverage factor (*k* = 2, about 95 %) |
| I-MR | The control chart of individual values and moving ranges |
| CL | The centre line of the chart (the mean of the deviations) |
| σ | The standard deviation, here σ = MR̄ / 1.128 |
| MR̄ | The mean moving range (the difference of two neighbouring values) |
| Western Electric | A set of rules that find signals on a chart (beyond 3σ, 2 of 3 beyond 2σ, 8 in a row on one side) |
| CUSUM | The cumulative sum of the deviations: it finds a small constant shift (*k* = 0.5σ, *H* = 5σ) |
| SPC | Statistical process control |

### Terms of the program

| Term | Meaning |
|---|---|
| Record | One measurement with its result; statuses: draft, under review, approved, returned, superseded, annulled |
| Reference values | The readings of a beam and chamber saved to be filled into new measurements |
| Baseline period | The interval of dates from which the limits of the chart are calculated; it starts its own segment of the statistics |
| Trend series | The records of one beam obtained under the same reference conditions |
| Expected dose | The dose per 1 MU at the reference point according to the planning system, for SAD (cGy/MU) |
| Beam readiness | The indicator in “Equipment”: whether the data of a beam suffice for the calculation sheet |

## Important

The calculations are intended for clinical use only after independent verification and comparison with your own worksheets.
The user is responsible for the result.
