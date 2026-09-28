# Changelog

## 3.1
- CSV export grouped by protein and ligand (from the Drive folder each dataset came
  from), with protein, mutant, ligand, timepoint, combination and half columns.
- Mouse-wheel and trackpad scrolling in the results window and main window.
- Windows support: Google Drive detection, WinCoot/CCP4/Phenix discovery,
  settings in `%APPDATA%`, build and packaging scripts.
- Fresh settings file (`settings-v3.json`); Google Drive setup shown on first launch.

## 3.0
- Chain field; target residue checked against the reference PDB.
- Resizable activity log.
- Results window redesigned; assessment is now Ligand present / No ligand.

## 2.9
- Redesigned main window (cards, mode switch, live readiness checks).
- Software detection with download links; Google Drive setup guide for new users.

## 2.8
- Synced files keep their original `*_all.mtz` names; newer `vNNN` replaces older copies.
- Explicit Phenix column labels for xia2.ssx MTZs (duplicate `IMEAN`/`Iobs` arrays).

## 2.6 – 2.7
- Sync by MX visit number from `stills_processing`, latest `vNNN`, `_all.mtz` only.
- Reference PDB / apo MTZ pulled from the visit folder.
- App opens its own project folder by default.

## 2.5
- Google Drive for Desktop sync.
