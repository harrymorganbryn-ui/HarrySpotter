# Harry Spotter

A desktop app for quickly checking crystallographic datasets for ligand density
around a target residue, for time-resolved serial crystallography and apo screening.

Harry Spotter pulls the latest merged data for a beamtime visit from Google Drive,
computes a difference map for every dataset, renders a 360° spin GIF of the density
around your target residue in Coot, and lets you review them all side by side,
marking each one **Ligand present** or **No ligand**, with a grouped CSV export.

It runs on **macOS** and **Windows**.

## Features

- **Two modes**
  - **Time-resolved Fo-Fo** — `phenix.fobs_minus_fobs_map` (target − apo ground state)
  - **Apo screening** — Dimple refinement against a reference model
- **Google Drive sync by MX visit number** — finds the visit (including folders shared
  with you) and, for every dataset in
  `<visit>/stills_processing/<protein+ligand>/<combination>/{even,odd}/vNNN/`,
  copies the `*_all.mtz` from the newest `vNNN` (never the CC½ half-sets).
  The visit's reference PDB (and an `*apo*.mtz`, if present) are pulled from the
  top of the visit folder.
- **Automatic Phenix column choice** for xia2.ssx files that carry duplicate
  intensity arrays (`IMEAN`/`Iobs`).
- **Chain + residue targeting**, checked live against the reference PDB.
- **Review window** — animated spin GIFs, Ligand present / No ligand calls, filters,
  open any dataset in Coot, and a CSV grouped by protein and ligand.
- **Setup checks** — shows which of Phenix, Coot and Dimple were found (with download
  links if not), and guides new users through connecting Google Drive for Desktop.

## Requirements

To **run** the app:

| | Needed for |
|---|---|
| [Google Drive for Desktop](https://www.google.com/drive/download/) | syncing beamtime data (optional — MTZs can also be put in `input/mtz` by hand) |
| [Phenix](https://phenix-online.org/download/) | time-resolved Fo-Fo maps |
| [CCP4](https://www.ccp4.ac.uk/download/) (Dimple) | apo screening |
| [Coot](https://www2.mrc-lmb.cam.ac.uk/personal/pemsley/coot/) / WinCoot | rendering and inspection |

To **build** it from source: Python 3.12+ with Tkinter, plus the packages in
`requirements.txt`.

## Building

### macOS

```bash
python3 -m pip install -r requirements.txt
./build_mac.sh
```

The app is written to `dist/HarrySpotter.app`.

### Windows

Double-click `build_windows.bat` (it installs the build tools, makes the icon and
builds). The app is written to `dist\HarrySpotter\HarrySpotter.exe`.
Then run `package_windows.bat` to make a shareable `HarrySpotter-3.1-Windows.zip`
(see `README_FIRST.txt`, which goes inside the zip).

### Running from source

```bash
python3 -m pip install Pillow
python3 HarrySpotter.py
```

## Using it

1. **Open a project** — a folder that will hold `input/` (reference PDB, apo MTZ,
   `input/mtz/` datasets) and the results. A built app defaults to its own folder.
2. **Enter the MX visit** (e.g. `mx12345-1`) and click **Sync now**.
3. Check the **Inputs** (reference PDB, apo ground-state MTZ) and **Software** cards.
4. Set the **chain**, **residue** and **contour level**, choose the mode, and
   **Run pipeline** (⌘R / Ctrl+R).
5. Review the spin GIFs, mark each dataset, and **Export CSV**.

Settings are remembered per project in
`~/Library/Application Support/HarrySpotter/settings-v3.json` (macOS) or
`%APPDATA%\HarrySpotter\settings-v3.json` (Windows).

## Repository layout

| File | Purpose |
|---|---|
| `HarrySpotter.py` | the application (single file, macOS + Windows) |
| `HarrySpotter.spec`, `build_mac.sh` | macOS build |
| `HarrySpotter-windows.spec`, `build_windows.bat`, `make_icon.py` | Windows build |
| `package_windows.bat`, `README_FIRST.txt` | Windows shareable zip |
| `lab_logo.png`, `logo.icns` | artwork |

## Licence

MIT — see [LICENSE](LICENSE). © 2026 Harry Morgan.
