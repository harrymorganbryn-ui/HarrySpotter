# Harry Spotter

[![DOI](https://zenodo.org/badge/DOI/10.5281/zenodo.23020039.svg)](https://doi.org/10.5281/zenodo.23020039)
[![Latest release](https://img.shields.io/github/v/release/harrymorganbryn-ui/HarrySpotter)](https://github.com/harrymorganbryn-ui/HarrySpotter/releases/latest)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)

A desktop app for quickly checking crystallographic datasets for ligand density
around a target residue, for time-resolved serial crystallography and apo screening.

Harry Spotter pulls the latest merged data for a beamtime visit from Google Drive,
computes a difference map for every dataset, renders a 360° spin GIF of the density
around your target residue in Coot, and lets you review them all side by side,
marking each one **Ligand present** or **No ligand**, with a grouped CSV export.

It runs on **macOS**, **Windows** and **Linux**.

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
  open any dataset in Coot or PyMOL (centred on your target residue), and a CSV
  grouped by protein and ligand.
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
| [PyMOL](https://pymol.org/) (optional) | "Open in PyMOL" from the results — maps are converted with CCP4's `gemmi`. Schrödinger's PyMOL needs an active licence to load files; free open-source PyMOL also works (`conda install -c conda-forge pymol-open-source`) |

Harry Spotter does **not** include or distribute Phenix, CCP4, Dimple, Coot, gemmi or
PyMOL. It runs the copies installed on your computer, so each must be obtained and
licensed from its developers. Harry Spotter is an independent tool and is not affiliated
with or endorsed by them; their names are used only to describe what it works with.

To **build** it from source: Python 3.12+ with Tkinter, plus the packages in
`requirements.txt`.

## Installing

Download a ready-built app from the
[**latest release**](https://github.com/harrymorganbryn-ui/HarrySpotter/releases/latest)
(under **Assets**) — no Python needed.

### macOS (Apple Silicon — M1 or later)

1. Download `HarrySpotter-<version>-macOS-AppleSilicon.zip` and unzip it
   (Safari usually does this automatically).
2. Drag `HarrySpotter.app` into **Applications**.
3. Open it. The first time, macOS will say it can't verify the developer (the app
   isn't notarised): go to **System Settings → Privacy & Security** and click
   **Open Anyway** — or right-click the app → **Open** → **Open**.
4. On the start screen, click **Browse…** and choose (or create) a project folder,
   e.g. `Documents/HarrySpotter`. Your inputs and results are kept there, and it's
   remembered next time.

On an Intel Mac, [build from source](#building).

### Windows 10/11

1. Download `HarrySpotter-<version>-Windows-x64.zip` — or `-Windows-ARM64.zip` for an ARM-based
   PC (e.g. Snapdragon / Copilot+; check **Settings → System → About → System type**).
2. Right-click it → **Extract All…** into a folder you can write to, such as
   Documents (not Program Files).
3. Open the extracted folder and double-click `HarrySpotter.exe`. If
   **"Windows protected your PC"** appears, click **More info → Run anyway**
   (first time only).
4. Keep the folder together — it's the app's project folder, and results are saved
   inside it.

Spin GIFs are drawn by Coot, so Coot needs working OpenGL graphics — normal PCs have
this, but most virtual machines don't (the app says so if Coot can't draw). WinCoot 1
is recommended: WinCoot 0.9 opens every screenshot it takes in an image viewer.

### After installing

Install the tools listed under [Requirements](#requirements). The app's
**Software** card shows a tick for each one it finds, with a download link if not,
and **Locate…** if one is installed somewhere unusual. The first launch also walks
you through connecting Google Drive.

### Linux (x86-64)

1. Download `HarrySpotter-<version>-Linux-x86_64.tar.gz` and extract it where you can
   write, e.g. `tar -xzf HarrySpotter-*-Linux-x86_64.tar.gz` in your home folder.
2. Run `./HarrySpotter` from the extracted folder. Optionally run `./install.sh` to add
   Harry Spotter to your applications menu.
3. Google doesn't make a Drive app for Linux: mount Drive as a folder with
   [rclone](https://rclone.org/drive/) or Insync (`~/GoogleDrive` is found automatically;
   any other folder can be chosen in the app). See `README_FIRST.txt` in the download.

Built on Ubuntu 22.04, so it runs on 22.04 and newer and other recent distributions.

## Building

### macOS

```bash
python3 -m pip install -r requirements.txt
./build_mac.sh
```

The app is written to `dist/HarrySpotter.app`.

### Linux

```bash
sudo apt install python3-tk          # or your distribution's equivalent
python3 -m pip install -r requirements.txt
VERSION=3.3 ./build_linux.sh         # -> HarrySpotter-3.3-Linux-x86_64.tar.gz
```

### Windows

Double-click `build_windows.bat` (it installs the build tools, makes the icon and
builds). The app is written to `dist\HarrySpotter\HarrySpotter.exe`.
Then run `package_windows.bat` to make a shareable `HarrySpotter-3.3-Windows.zip`
(see `README_FIRST.txt`, which goes inside the zip).

### Running from source

```bash
python3 -m pip install Pillow
python3 HarrySpotter.py
```

## Using it

1. **Open a project** — a folder that will hold `input/` (reference PDB, apo MTZ,
   `input/mtz/` datasets) and the results. The Windows app defaults to its own
   folder; on a Mac, pick one with **Browse…** the first time.
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
| `HarrySpotter.py` | the application (single file, macOS, Windows and Linux) |
| `HarrySpotter.spec`, `build_mac.sh` | macOS build |
| `HarrySpotter-windows.spec`, `build_windows.bat`, `make_icon.py` | Windows build |
| `package_windows.bat`, `README_FIRST.txt` | Windows shareable zip |
| `HarrySpotter-linux.spec`, `build_linux.sh`, `linux/` | Linux build, menu entry and notes |
| `ci/`, `.github/workflows/build.yml` | Linux and Windows (x64, ARM64) builds and automated tests (GitHub Actions) |
| `collect_licenses.py` | writes `THIRD_PARTY_LICENSES.txt` (notices for the bundled Python, Tcl/Tk, Pillow) at build time |
| `harryspotter_logo.png`, `lab_logo.png`, `logo.icns` | artwork |

## Citing

If you use Harry Spotter in your research, please cite it:

> Morgan, H. *Harry Spotter* (software). Zenodo. https://doi.org/10.5281/zenodo.23020039

This DOI always points to the latest version. To cite a specific release, use its
own DOI from [Zenodo](https://doi.org/10.5281/zenodo.23020039) (e.g. v3.2:
[10.5281/zenodo.23047881](https://doi.org/10.5281/zenodo.23047881)). GitHub's
**"Cite this repository"** button gives APA and BibTeX formats.

Harry Spotter runs other programs to do the science, so please **also cite the ones
your results used** (check each program's website for its current recommended
citation):

- **Phenix** (Fo-Fo maps) — Liebschner, D. *et al.* (2019). *Acta Cryst.* D**75**, 861–877.
- **CCP4** — Agirre, J. *et al.* (2023). *Acta Cryst.* D**79**, 449–461.
- **Dimple** (apo screening) — Wojdyr, M., Keegan, R., Winter, G. & Ashton, A. (2013). *Acta Cryst.* A**69**, s299.
- **Coot** (map rendering) — Emsley, P., Lohkamp, B., Scott, W. G. & Cowtan, K. (2010). *Acta Cryst.* D**66**, 486–501.
- **gemmi** (map conversion for PyMOL) — Wojdyr, M. (2022). *J. Open Source Softw.* **7**(73), 4200.
- **PyMOL** — The PyMOL Molecular Graphics System, Schrödinger, LLC.

## Licence

MIT — see [LICENSE](LICENSE). © 2026 Harry Morgan.

The standalone downloads also bundle Python, Tcl/Tk and Pillow; their licence notices are
in `THIRD_PARTY_LICENSES.txt` inside each download.
