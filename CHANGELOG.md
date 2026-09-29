# Changelog

## 3.2 (2026-09-29)
- **Open in PyMOL** from the results window: the model and maps open centred on the
  target residue (difference map green/red at the chosen contour, 2mFo-DFc blue for
  Dimple, black background). MTZ map coefficients are converted with CCP4's `gemmi`.
  PyMOL is found automatically on macOS and Windows and shown (as optional) in the
  Software card.
- Spin GIFs: frames are captured from Coot's event loop so each view is fully drawn
  before the screenshot (fixes black / noisy frames with Coot 1.x on Windows).
  Blank renders are reported, with the raw frames and Coot log kept for diagnosis.
  Capture is fast: ~4 s per dataset with Coot on screen (was ~15 s); the Coot log
  records each screenshot's time (`HS_TIMING` lines).
- Load previous skips datasets that have no map (Phenix/Dimple failed, e.g.
  non-isomorphous) and says which in the log, instead of showing empty cards.
- Coot opens with a black background (renders and "Open in Coot").
- Each Coot render has a 5-minute time limit (Coot and its helper processes are
  closed if it hangs), and if Coot can't create an OpenGL context (e.g. in some
  virtual machines) the app says so and skips the remaining renders.
- On Windows, Coot 1 is launched with Vulkan disabled (`GDK_DISABLE=vulkan`), so it starts
  where a Vulkan driver is present but broken (e.g. virtual machines).
- If Coot closes within seconds without drawing anything (e.g. crashes on start-up),
  the app says so and skips the remaining renders.
- `pipeline_run.log` is written as UTF-8; on Windows, lines containing symbols such as
  ✅ ⚠ ❌ were previously dropped from the file.
- Coot scripts avoid Python 3-only syntax, so older WinCoot 0.9 builds can run them.
- Windows build script detects being run from inside a zip.
- Windows: a visit folder that Google Drive shows as a Windows shortcut (`.lnk`) is
  followed; if a visit can't be found, the log lists look-alike names and where it searched.
- Windows: PyMOL is also found via the registry and Start Menu shortcuts.
- Harry Spotter and Tooke lab logos in the start and main windows; app logo as the
  window/taskbar icon.

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
