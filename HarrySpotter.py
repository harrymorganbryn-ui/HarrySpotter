import os
import glob
import subprocess
import datetime
import time
import sys
import threading
import csv
import shutil
import json
import re
import tkinter as tk
import tkinter.ttk as ttk
from tkinter import filedialog, messagebox, scrolledtext

try:
    from PIL import Image, ImageTk
except ImportError:
    print("CRITICAL: Pillow library not found. Please run 'python3 -m pip install Pillow' before starting.")
    sys.exit(1)

# ==========================================================================
# PERSISTENT SETTINGS
#
# Remembers, per working directory, every field the user filled in last
# time (input paths, executables, residue, contour, Drive source folder)
# so re-running on the same project is just "open app -> RUN", instead of
# re-Browsing to the same folders every session.
# ==========================================================================
IS_WINDOWS = sys.platform.startswith("win")
IS_MAC = sys.platform == "darwin"
IS_LINUX = not IS_WINDOWS and not IS_MAC
COMPUTER = "PC" if IS_WINDOWS else "Mac" if IS_MAC else "computer"
FILE_BROWSER = "File Explorer" if IS_WINDOWS else "Finder" if IS_MAC else "your file manager"
# Shell used to run CCP4/Phenix/Coot on macOS and Linux (many Linux systems have no zsh).
LOGIN_SHELL = ["/bin/zsh", "-l", "-c"] if IS_MAC else ["/bin/bash", "-l", "-c"]
# Hide the console window that would otherwise flash up for every
# Phenix/Dimple/Coot command the windowed .exe runs.
NO_WINDOW = {"creationflags": subprocess.CREATE_NO_WINDOW} if IS_WINDOWS else {}

if IS_WINDOWS:
    CONFIG_DIR = os.path.join(os.environ.get("APPDATA", os.path.expanduser("~")), "HarrySpotter")
elif IS_MAC:
    CONFIG_DIR = os.path.expanduser("~/Library/Application Support/HarrySpotter")
else:
    CONFIG_DIR = os.path.join(os.environ.get("XDG_CONFIG_HOME") or os.path.expanduser("~/.config"), "HarrySpotter")
# 3.x keeps its own settings file, so it starts fresh (like a new user) and
# never picks up paths remembered by the 2.x test builds, which use config.json.
CONFIG_FILE = os.path.join(CONFIG_DIR, "settings-v3.json")


def load_config():
    try:
        with open(CONFIG_FILE, "r") as f:
            return json.load(f)
    except Exception:
        return {}


def save_config(data):
    try:
        os.makedirs(CONFIG_DIR, exist_ok=True)
        with open(CONFIG_FILE, "w") as f:
            json.dump(data, f, indent=2)
    except Exception:
        pass


def app_project_dir():
    """The project folder this copy of the app belongs to: the folder holding
    dist/HarrySpotter.app when frozen, or the script's folder otherwise.
    Returns None if it can't be determined."""
    if getattr(sys, "frozen", False):
        path = os.path.abspath(sys.executable)
        while path != os.path.dirname(path):
            if os.path.basename(path) == "dist":
                return os.path.dirname(path)
            path = os.path.dirname(path)
        if IS_WINDOWS or IS_LINUX:
            # Shared as a zip / tar.gz: the folder holding the program is the
            # project, with input/ created beside it on first run.
            folder = os.path.dirname(os.path.abspath(sys.executable))
            try:
                os.makedirs(os.path.join(folder, "input", "mtz"), exist_ok=True)
                return folder
            except OSError:
                return None  # e.g. unzipped into Program Files - user picks a folder
        return None
    return os.path.dirname(os.path.abspath(__file__))


def google_drive_roots():
    """Account roots of Google Drive for Desktop on this computer.

    macOS: ~/Library/CloudStorage/GoogleDrive-<account>
    Windows: the virtual drive it mounts (G: by default, but any letter),
    or the user folder in "mirror" mode - whichever contains "My Drive"."""
    if IS_WINDOWS:
        import string
        roots = [f"{letter}:\\" for letter in string.ascii_uppercase[2:]
                 if os.path.isdir(f"{letter}:\\My Drive")]
        if os.path.isdir(os.path.join(os.path.expanduser("~"), "My Drive")):
            roots.append(os.path.expanduser("~"))
        return roots
    if IS_LINUX:
        # Google makes no Drive app for Linux; people mount Drive with rclone or
        # Insync. Look in the usual places (a mount point only counts if it isn't
        # empty, i.e. Drive is actually mounted there).
        home = os.path.expanduser("~")
        cands = sorted(glob.glob(os.path.join(home, "Insync", "*", "Google Drive"))) + \
                [os.path.join(home, n) for n in ("GoogleDrive", "Google Drive", "google-drive", "googledrive",
                                                 "gdrive", "GDrive", "Drive")]
        return [c for c in cands if os.path.isdir(c) and _listdir_safe(c)]
    return sorted(glob.glob(os.path.expanduser("~/Library/CloudStorage/GoogleDrive-*")))


def find_google_drive_mount():
    """Locate Google Drive for Desktop's "My Drive" folder (or the account
    root if there isn't one), so browse dialogs open somewhere useful."""
    roots = google_drive_roots()
    if not roots:
        return None
    my_drive = os.path.join(roots[0], "My Drive")
    return my_drive if os.path.isdir(my_drive) else roots[0]


VERSION_DIR_RE = re.compile(r'^v(\d+)$', re.IGNORECASE)
HALF_SETS = ("even", "odd")
SYNC_MANIFEST = ".harryspotter_sync.json"
DRIVE_DOWNLOAD_HINT = ("    Google Drive couldn't download this file. Check Drive for Desktop is running, "
                       "online and not paused, or right-click the visit folder in "
                       f"{FILE_BROWSER} → make it available offline, then sync again.")


def _listdir_safe(path):
    try:
        return sorted(os.listdir(path))
    except OSError:
        return []


def _subdirs(path):
    # os.path.isdir follows symlinks, which matters here: a Drive "shortcut"
    # to a shared visit folder shows up locally as a symlink.
    return [d for d in _listdir_safe(path)
            if not d.startswith(".") and os.path.isdir(os.path.join(path, d))]


def read_mtz_columns(path):
    """Return [(label, type), ...] from an MTZ file's header (pure Python,
    no CCP4/cctbx needed), or [] if it can't be read."""
    import struct
    try:
        with open(path, "rb") as f:
            head = f.read(24)
            if head[:4] != b"MTZ ":
                return []
            endian = "<" if (head[8] >> 4) == 4 else ">"
            ptr = struct.unpack(endian + "i", head[4:8])[0]
            offset = (struct.unpack(endian + "q", head[16:24])[0] if ptr == -1 else ptr) - 1
            f.seek(offset * 4)
            header = f.read()
    except (OSError, struct.error):
        return []
    cols = []
    for i in range(0, len(header) - 79, 80):
        rec = header[i:i + 80].decode("ascii", "replace")
        if rec.startswith("END"):
            break
        if rec.startswith("COLUMN"):
            parts = rec.split()
            if len(parts) >= 3:
                cols.append((parts[1], parts[2]))
    return cols


def choose_fobs_label(path):
    """Pick which observed-data array phenix.fobs_minus_fobs_map should use.

    xia2.ssx _all.mtz files carry the same intensities twice (Iobs and
    IMEAN), which makes Phenix stop with "Multiple equally suitable arrays
    of observed xray data found" unless a label is given. Preference:
    IMEAN, then Iobs/I, then amplitudes F/FP. Returns e.g. "IMEAN,SIGIMEAN",
    or None to let Phenix decide (e.g. only one array present)."""
    cols = dict(read_mtz_columns(path))
    for value, sigma, kind in (("IMEAN", "SIGIMEAN", "J"), ("Iobs", "SIGIobs", "J"), ("I", "SIGI", "J"),
                               ("F", "SIGF", "F"), ("FP", "SIGFP", "F"), ("Fobs", "SIGFobs", "F")):
        if cols.get(value) == kind and cols.get(sigma) == "Q":
            return f"{value},{sigma}"
    return None


COOT_RENDER_TIMEOUT = 300   # seconds; a normal render takes ~15-30 s


def coot_env():
    """Environment for launching Coot. On Windows, Coot 1 (GTK 4) tries Vulkan
    first when a Vulkan driver is present; in some setups (e.g. virtual
    machines with Microsoft's OpenCL/OpenGL/Vulkan Compatibility Pack) that
    fails and Coot quits at once. Skipping Vulkan makes GTK use OpenGL, as it
    does on ordinary PCs. A value the user has set themselves is kept."""
    env = dict(os.environ)
    if IS_WINDOWS:
        env.setdefault("GDK_DISABLE", "vulkan")
    return env


def kill_process_tree(proc):
    """Stop a Coot launch and everything it started (WinCoot runs via a .bat
    that starts coot.exe, so killing only the shell would leave Coot open)."""
    try:
        if IS_WINDOWS:
            subprocess.run(["taskkill", "/F", "/T", "/PID", str(proc.pid)], capture_output=True, **NO_WINDOW)
        else:
            import signal
            os.killpg(os.getpgid(proc.pid), signal.SIGKILL)
    except Exception:
        try:
            proc.kill()
        except Exception:
            pass
    try:
        proc.wait(timeout=10)
    except Exception:
        pass


def coot_opengl_failed(log_path):
    """If Coot's log shows it couldn't create an OpenGL context (so it can't
    draw anything), return a short reason; otherwise None. Coot's routine
    shader warnings don't count."""
    try:
        with open(log_path, errors="replace") as f:
            text = f.read()
    except OSError:
        return None
    if "libEGL not available" in text:
        return "libEGL not available"
    if "VK_ERROR_INITIALIZATION_FAILED" in text:
        return "Vulkan graphics failed to start"
    for pattern in ("gtk_gl_area_get_error() returned an error", "Unable to create a GL context",
                    "Failed to create OpenGL context", "No GL implementation is available",
                    "Could not create GL context"):
        if pattern in text:
            return "no OpenGL context"
    return None


# Map coefficient columns, in order of preference.
DIFF_MAP_COLUMNS = [("FoFo", "PHFc"), ("F_OBS_MINUS_F_OBS", "PHIF_OBS_MINUS_F_OBS"),
                    ("DELFWT", "PHDELWT"), ("FOFCWT", "PHFOFCWT")]
TWOFOFC_MAP_COLUMNS = [("FWT", "PHWT"), ("2FOFCWT", "PH2FOFCWT")]


def LINUX_SOFTWARE_BASES():
    """Folders where crystallography software is usually installed on Linux."""
    home = os.path.expanduser("~")
    return ["/opt/xtal", "/usr/local/xtal", "/opt", "/usr/local", home,
            os.path.join(home, "software"), os.path.join(home, "programs"), os.path.join(home, "opt")]


def ccp4_setup_scripts(dimple_path=""):
    """CCP4's environment script(s) (ccp4.setup-sh), sourced before running
    Dimple or Coot on macOS/Linux. Next to Dimple first, then usual places."""
    found = []
    if dimple_path and os.path.sep in dimple_path:
        cand = os.path.join(os.path.dirname(dimple_path), "ccp4.setup-sh")
        if os.path.isfile(cand):
            found.append(cand)
    if IS_MAC:
        found += sorted(glob.glob("/Applications/ccp4-*/bin/ccp4.setup-sh"))
    elif IS_LINUX:
        for base in LINUX_SOFTWARE_BASES():
            found += sorted(glob.glob(os.path.join(base, "ccp4*", "bin", "ccp4.setup-sh")))
    return list(dict.fromkeys(found))   # no duplicates, order kept


def find_gemmi(hints=()):
    """The gemmi command-line tool that comes with CCP4 (used to turn MTZ map
    coefficients into maps PyMOL can read). `hints` are other CCP4 program
    paths (e.g. Dimple) - gemmi lives in the same bin folder."""
    exe = "gemmi.exe" if IS_WINDOWS else "gemmi"
    for hint in hints:
        if hint and (os.path.sep in hint or "/" in hint):
            cand = os.path.join(os.path.dirname(hint), exe)
            if os.path.isfile(cand):
                return cand
    if shutil.which("gemmi"):
        return shutil.which("gemmi")
    if IS_WINDOWS:
        bases = [os.environ.get("SystemDrive", "C:") + "\\", os.path.expanduser("~")] + \
                [os.environ.get(v) for v in ("ProgramFiles", "ProgramFiles(x86)") if os.environ.get(v)]
        patterns = ["CCP4*\\bin\\gemmi.exe", "CCP4*\\*\\bin\\gemmi.exe"]
    elif IS_MAC:
        bases = ["/Applications", os.path.expanduser("~/Applications")]
        patterns = ["ccp4-*/bin/gemmi"]
    else:
        bases = LINUX_SOFTWARE_BASES()
        patterns = ["ccp4-*/bin/gemmi", "ccp4*/bin/gemmi"]
    for base in bases:
        for pattern in patterns:
            found = sorted(glob.glob(os.path.join(base, pattern)))
            if found:
                return found[-1]
    return None


def make_ccp4_maps(mtz, folder, name, gemmi_hints=()):
    """Turn an MTZ's map coefficients into CCP4 maps for PyMOL.

    Returns (maps, problem): maps is a list of (kind, path, f_col, phi_col)
    for kind "diff" (difference map) and "2fofc" (if present); problem is a
    message if a map couldn't be made (PyMOL is then asked to read the MTZ
    itself, which licensed PyMOL can do)."""
    cols = {c for c, _t in read_mtz_columns(mtz)}
    wanted = []
    for kind, pairs in (("diff", DIFF_MAP_COLUMNS), ("2fofc", TWOFOFC_MAP_COLUMNS)):
        for f_col, phi_col in pairs:
            if f_col in cols and phi_col in cols:
                wanted.append((kind, f_col, phi_col))
                break
    if not wanted:
        return [], "no map coefficients found in the MTZ"

    maps, problem = [], None
    try:
        import gemmi as gemmi_lib      # the Python library, if available
    except ImportError:
        gemmi_lib = None
    gemmi_exe = None if gemmi_lib else find_gemmi(gemmi_hints)

    for kind, f_col, phi_col in wanted:
        out = os.path.join(folder, f"{name}_{kind}.ccp4")
        if os.path.exists(out) and os.path.getmtime(out) >= os.path.getmtime(mtz):
            maps.append((kind, out, f_col, phi_col))
            continue
        try:
            if gemmi_lib:
                grid = gemmi_lib.read_mtz_file(mtz).transform_f_phi_to_map(f_col, phi_col, sample_rate=3)
                ccp4 = gemmi_lib.Ccp4Map()
                ccp4.grid = grid
                ccp4.update_ccp4_header()
                ccp4.write_ccp4_map(out)
            elif gemmi_exe:
                subprocess.run([gemmi_exe, "sf2map", "-f", f_col, "-p", phi_col, "-s", "3", mtz, out],
                               capture_output=True, timeout=120, check=True, **NO_WINDOW)
            else:
                raise FileNotFoundError("gemmi (part of CCP4) not found")
            maps.append((kind, out, f_col, phi_col))
        except Exception as e:
            problem = f"couldn't make a map file ({e})"
            maps.append((kind, None, f_col, phi_col))   # PyMOL will try the MTZ directly
    return maps, problem


def pymol_script(pdb, mtz, maps, name, chain, residue, contour):
    """Python script for PyMOL: model + maps around the target residue,
    difference density green (+) / red (-), 2mFo-DFc blue, black background."""
    target = f"{name} and chain {chain} and resi {residue}" if chain and residue else name
    lines = [
        "from pymol import cmd",
        "cmd.set('normalize_ccp4_maps', 1)   # map levels in sigma",
        f"cmd.load({pdb!r}, {name!r})",
    ]
    for kind, path, f_col, phi_col in maps:
        obj = f"{name}_{kind}"
        if path:
            lines.append(f"cmd.load({path!r}, {obj!r})")
        else:
            lines += ["try:",
                      f"    cmd.load_mtz({mtz!r}, {obj!r}, amplitudes={f_col!r}, phases={phi_col!r})",
                      "    for o in cmd.get_names('objects'):",
                      f"        if o.startswith({obj!r}) and o != {obj!r}: cmd.set_name(o, {obj!r})",
                      "except Exception as e:",
                      f"    print('Harry Spotter: could not load the {kind} map:', e)"]
        if kind == "diff":
            lines += [f"cmd.isomesh({obj + '_pos'!r}, {obj!r}, {contour}, {target!r}, 10)",
                      f"cmd.isomesh({obj + '_neg'!r}, {obj!r}, -{contour}, {target!r}, 10)",
                      f"cmd.color('green', {obj + '_pos'!r})",
                      f"cmd.color('red', {obj + '_neg'!r})"]
        else:
            lines += [f"cmd.isomesh({obj + '_mesh'!r}, {obj!r}, 1.0, {target!r}, 5)",
                      f"cmd.color('skyblue', {obj + '_mesh'!r})"]
    lines += [
        "cmd.bg_color('black')",
        "cmd.set('ray_opaque_background', 1)",
        f"cmd.hide('everything', {name!r})",
        f"cmd.show('cartoon', {name!r})",
        f"cmd.color('grey50', {name!r} + ' and elem C')",   # grey model so green/red density stands out
        f"cmd.set('cartoon_color', 'grey40', {name!r})",
        f"cmd.set('cartoon_transparency', 0.7, {name!r})",
        f"cmd.show('sticks', 'byres ((' + {target!r} + ') expand 6) and not name H*')",
        f"cmd.color('yellow', '({target}) and elem C')",
        f"cmd.label('({target}) and name CA', '\"%s%s\" % (resn, resi)')",
        "cmd.set('label_color', 'white')",
        f"cmd.zoom({target!r}, 10)",
    ]
    return "\n".join(lines) + "\n"


def copy_complete(src, dest):
    """copy2 via a temp file, so an interrupted Drive download never leaves a
    truncated MTZ/PDB where the pipeline would pick it up."""
    tmp = dest + ".partial"
    try:
        shutil.copy2(src, tmp)
        os.replace(tmp, dest)
    finally:
        if os.path.exists(tmp):
            os.remove(tmp)


def windows_registered_app(exe_names):
    """Program path recorded by its installer under Windows' "App Paths", or None."""
    if not IS_WINDOWS:
        return None
    try:
        import winreg
    except ImportError:
        return None
    for hive in (winreg.HKEY_CURRENT_USER, winreg.HKEY_LOCAL_MACHINE):
        for name in exe_names:
            try:
                with winreg.OpenKey(hive, r"SOFTWARE\Microsoft\Windows\CurrentVersion\App Paths" + "\\" + name) as key:
                    path = winreg.QueryValue(key, None).strip('"')
                    if path and os.path.isfile(path):
                        return path
            except OSError:
                continue
    return None


def resolve_windows_shortcut(lnk_path):
    """Target of a Windows .lnk shortcut, or None (uses Windows' own shortcut API)."""
    if not IS_WINDOWS:
        return None
    ps_path = lnk_path.replace("'", "''")
    try:
        out = subprocess.run(["powershell", "-NoProfile", "-NonInteractive", "-Command",
                              f"(New-Object -ComObject WScript.Shell).CreateShortcut('{ps_path}').TargetPath"],
                             capture_output=True, text=True, timeout=20, **NO_WINDOW)
        target = out.stdout.strip()
        return target if target and os.path.exists(target) else None
    except Exception:
        return None


def visit_lookalikes(drive_dir, visit, limit=8):
    """Names near drive_dir that start with the visit number (any extension) - shown
    in the log when the visit can't be opened, to make the cause obvious."""
    found = []
    for depth in (0, 1, 2):
        found += glob.glob(os.path.join(drive_dir, *(["*"] * depth), visit + "*"))
    return found[:limit]


def find_visit_dir(drive_dir, visit):
    """Resolve an MX visit number (e.g. "mx12345-1") to its local folder.

    Checks, in order: drive_dir itself, drive_dir/<visit>, the Drive account's
    shortcut targets (where Drive for Desktop puts folders shared with you),
    "Shared drives", and finally a shallow (3-level) search below drive_dir.
    Returns the path, or None if not found.
    """
    visit = visit.strip().strip("/")
    if not visit or not drive_dir:
        return None
    if os.path.basename(os.path.normpath(drive_dir)).lower() == visit.lower():
        return drive_dir

    def candidates():
        # Cheap, direct locations first; the shallow search below drive_dir
        # can be slow on a big Drive, so it only runs if nothing else hits.
        yield os.path.join(drive_dir, visit)
        for account in google_drive_roots():
            yield from glob.glob(os.path.join(account, ".shortcut-targets-by-id", "*", visit))
            yield from glob.glob(os.path.join(account, "Shared drives", "*", visit))
        for depth in (1, 2, 3):
            yield from glob.glob(os.path.join(drive_dir, *(["*"] * depth), visit))
        if IS_WINDOWS:
            # Google Drive for Desktop can show a Drive shortcut (e.g. a visit folder
            # shared with you) as a Windows shortcut file, "<visit>.lnk" - follow it.
            for depth in (0, 1, 2):
                for lnk in glob.glob(os.path.join(drive_dir, *(["*"] * depth), visit + ".lnk")):
                    target = resolve_windows_shortcut(lnk)
                    if target:
                        yield target

    fallback = None
    for c in candidates():
        if os.path.isdir(os.path.join(c, "stills_processing")):
            return c
        if fallback is None and os.path.isdir(c):
            fallback = c
    return fallback


def find_visit_reference_files(visit_dir):
    """Find the per-visit reference files kept in the top level of the visit
    folder (not searched recursively):

      - reference model: any *.pdb (e.g. kpc2_rt_esrf.pdb)
      - apo ground-state: a *.mtz with "apo" in its name
        (e.g. KPC2_apo_ground_state.mtz)

    If several match, the most recently modified wins. Returns
    (pdb_path or None, apo_mtz_path or None).
    """
    files = [os.path.join(visit_dir, f) for f in _listdir_safe(visit_dir)
             if not f.startswith(".") and os.path.isfile(os.path.join(visit_dir, f))]
    pdbs = [f for f in files if f.lower().endswith(".pdb")]
    apos = [f for f in files if f.lower().endswith(".mtz") and "apo" in os.path.basename(f).lower()]
    newest = lambda paths: max(paths, key=os.path.getmtime) if paths else None
    return newest(pdbs), newest(apos)


def default_input_file(input_dir, preferred, pattern):
    """Default for a first-time project: input/<preferred> if it exists,
    else the newest file in input/ matching pattern, else input/<preferred>."""
    path = os.path.join(input_dir, preferred)
    if os.path.exists(path):
        return path
    matches = glob.glob(os.path.join(input_dir, pattern))
    return max(matches, key=os.path.getmtime) if matches else path


def collect_visit_mtz_files(visit_dir, log=None):
    """Collect the merged MTZ for every dataset in an MX visit, following the
    xia2.ssx stills layout:

        <visit>/stills_processing/<protein+ligand>/<combination>/{even,odd}/vNNN/*_all.mtz

    For each combination directory (ij, ijk, ijkl, ...) and each of even/odd,
    the highest vNNN folder containing an *_all.mtz is used; the *_even.mtz /
    *_odd.mtz CC1/2 half-set files are ignored. If the newest version has no
    _all.mtz yet (still processing, or not synced down yet) the next newest
    one is used and a note is logged.

    Files keep their original *_all.mtz name. Returns a list of
    (source_path, destination_filename, dataset_key), where dataset_key is
    "<protein>/<combination>/<even|odd>" - used to replace an older vNNN's
    copy when a newer one (possibly with a different filename) appears.
    """
    log = log or (lambda msg: None)
    stills = os.path.join(visit_dir, "stills_processing")
    if not os.path.isdir(stills):
        log(f"  ! No stills_processing folder in {visit_dir}")
        return []

    results = []
    for protein in _subdirs(stills):
        protein_dir = os.path.join(stills, protein)
        for combo in _subdirs(protein_dir):
            combo_dir = os.path.join(protein_dir, combo)
            for half in _subdirs(combo_dir):
                if half.lower() not in HALF_SETS:
                    continue
                half_dir = os.path.join(combo_dir, half)
                versions = sorted(
                    ((int(m.group(1)), d) for d in _subdirs(half_dir)
                     for m in [VERSION_DIR_RE.match(d)] if m),
                    reverse=True)
                if not versions:
                    log(f"  ! {protein}/{combo}/{half}: no vNNN folders")
                    continue

                chosen = None
                for _num, vname in versions:
                    alls = [f for f in _listdir_safe(os.path.join(half_dir, vname))
                            if f.lower().endswith("_all.mtz")]
                    if alls:
                        chosen = (vname, os.path.join(half_dir, vname, alls[0]))
                        break
                if not chosen:
                    log(f"  ! {protein}/{combo}/{half}: no _all.mtz in any version")
                    continue
                if chosen[0] != versions[0][1]:
                    log(f"  ! {protein}/{combo}/{half}: {versions[0][1]} has no _all.mtz yet, using {chosen[0]}")

                results.append((chosen[1], os.path.basename(chosen[1]), f"{protein}/{combo}/{half.lower()}"))

    # Two datasets with the same _all.mtz filename would overwrite each
    # other locally; prefix those with their combination folder.
    names = [dest for _src, dest, _key in results]
    return [(src, f"{key.split('/')[1]}__{dest}" if names.count(dest) > 1 else dest, key)
            for src, dest, key in results]


# ==========================================================================
# LOOK & FEEL
# ==========================================================================
T = {
    "bg": "#f3f5f8", "card": "#ffffff", "border": "#e2e6ec", "text": "#1f2933",
    "muted": "#6b7785", "accent": "#0f766e", "accent_hover": "#115e59",
    "accent_soft": "#e6f4f2", "good": "#15803d", "bad": "#dc2626", "warn": "#b45309",
    "idle": "#a3acb8", "drive": "#1a73e8", "drive_hover": "#1558b0",
    "disabled_bg": "#dde2e8", "disabled_fg": "#8a94a0", "field": "#f8fafc",
    "seg_bg": "#e3e7ec", "log_bg": "#111827", "log_fg": "#e5e7eb",
}
FONT = "Segoe UI" if IS_WINDOWS else "Helvetica Neue" if IS_MAC else "DejaVu Sans"
MONO_FONT = ("Consolas", -14) if IS_WINDOWS else ("Menlo", 11) if IS_MAC else ("DejaVu Sans Mono", -14)


def F(size=11, weight="normal"):
    # Tk on Windows/Linux renders point sizes ~1.33x larger than on macOS;
    # pixel sizes (negative) keep the card layout identical everywhere.
    if not IS_MAC:
        return (FONT, -round(size * 1.25), weight)
    return (FONT, size, weight)


SOFTWARE_INFO = {
    # key: (display name, what it's used for, download page)
    "phenix": ("Phenix", "Fo-Fo difference maps", "https://phenix-online.org/download/"),
    "coot": ("Coot", "map rendering & inspection", "https://www2.mrc-lmb.cam.ac.uk/personal/pemsley/coot/"),
    "dimple": ("Dimple · CCP4", "apo screening", "https://www.ccp4.ac.uk/download/"),
    "pymol": ("PyMOL", "optional · view results", "https://pymol.org/"),
}
DRIVE_DOWNLOAD_URL = "https://www.google.com/drive/download/"
DRIVE_WEB_URL = "https://drive.google.com/"
RCLONE_DRIVE_URL = "https://rclone.org/drive/"


def tool_available(path):
    """True if path is an executable file, or a bare command on PATH."""
    path = (path or "").strip()
    if not path:
        return False
    if os.path.sep in path or "/" in path:
        return os.path.isfile(path) and os.access(path, os.X_OK)
    return shutil.which(path) is not None


def drive_account_name(mount):
    """'you@gmail.com' from ~/Library/CloudStorage/GoogleDrive-you@gmail.com/..."""
    for part in (mount or "").split(os.sep):
        if part.startswith("GoogleDrive-"):
            return part[len("GoogleDrive-"):]
    return None


def drive_app_installed():
    if IS_WINDOWS:
        return any(os.path.isdir(os.path.join(os.environ.get(v, ""), "Google", "Drive File Stream"))
                   for v in ("ProgramFiles", "ProgramW6432", "ProgramFiles(x86)"))
    if IS_LINUX:
        return bool(shutil.which("rclone") or shutil.which("insync"))
    return os.path.isdir("/Applications/Google Drive.app")


def open_google_drive_app():
    """Start Google Drive for Desktop so it can sign the user in."""
    if IS_WINDOWS:
        exes = []
        for v in ("ProgramFiles", "ProgramW6432", "ProgramFiles(x86)"):
            exes += glob.glob(os.path.join(os.environ.get(v, ""), "Google", "Drive File Stream", "*",
                                           "GoogleDriveFS.exe"))
        if exes:
            subprocess.Popen([max(exes, key=os.path.getmtime)])
        else:
            open_url(DRIVE_DOWNLOAD_URL)
    elif IS_MAC:
        subprocess.run(["open", "-a", "Google Drive"])
    else:
        open_url(RCLONE_DRIVE_URL)


def open_url(url):
    import webbrowser
    webbrowser.open(url)


class FlatButton(tk.Label):
    """Label-based button, since tk.Button ignores background colours on macOS."""
    STYLES = {
        "primary": (T["accent"], "white", T["accent_hover"]),
        "secondary": ("#e8ecf1", T["text"], "#dce1e7"),
        "drive": (T["drive"], "white", T["drive_hover"]),
        "ghost": (T["card"], T["accent"], T["accent_soft"]),
        "danger": ("#fdecec", T["bad"], "#f9d6d6"),
    }

    def __init__(self, master, text, command=None, style="secondary", size=11, padx=12, pady=6, **kw):
        super().__init__(master, text=text, font=F(size, "bold"), padx=padx, pady=pady, cursor="hand2", **kw)
        self.command = command
        self.set_style(style)
        self.bind("<Button-1>", self._click)
        self.bind("<Enter>", lambda e: self._enabled and self.config(bg=self._hover))
        self.bind("<Leave>", lambda e: self._enabled and self.config(bg=self._bg))

    def set_style(self, style):
        self._bg, self._fg, self._hover = self.STYLES[style]
        self._enabled = True
        self.config(bg=self._bg, fg=self._fg, cursor="hand2")

    def _click(self, _event):
        if self._enabled and self.command:
            self.command()

    def set_enabled(self, enabled, text=None):
        self._enabled = enabled
        if enabled:
            self.config(bg=self._bg, fg=self._fg, cursor="hand2")
        else:
            self.config(bg=T["disabled_bg"], fg=T["disabled_fg"], cursor="arrow")
        if text is not None:
            self.config(text=text)


class Collapsible(tk.Frame):
    """A '▸ Title' header that shows/hides its .body frame when clicked."""

    def __init__(self, master, title, collapsed=True, on_toggle=None, bg=None, size=10):
        bg = bg or T["card"]
        super().__init__(master, bg=bg)
        self.title = title
        self.on_toggle = on_toggle
        self.collapsed = collapsed
        self.header = tk.Label(self, font=F(size, "bold"), bg=bg, fg=T["muted"], cursor="hand2", anchor="w")
        self.header.pack(fill="x")
        self.header.bind("<Button-1>", lambda e: self.toggle())
        self.body = tk.Frame(self, bg=bg)
        self._render()

    def _render(self):
        self.header.config(text=f"{'▸' if self.collapsed else '▾'}  {self.title}")
        if self.collapsed:
            self.body.pack_forget()
        else:
            self.body.pack(fill="both", expand=True, pady=(6, 0))

    def toggle(self, collapsed=None):
        self.collapsed = (not self.collapsed) if collapsed is None else collapsed
        self._render()
        if self.on_toggle:
            self.on_toggle(self.collapsed)


class Card(tk.Frame):
    """White bento tile with a title row (right side free for actions)."""

    def __init__(self, master, title, subtitle=None):
        super().__init__(master, bg=T["card"], highlightbackground=T["border"], highlightthickness=1, bd=0)
        head = tk.Frame(self, bg=T["card"])
        head.pack(fill="x", padx=16, pady=(12, 8))
        titles = tk.Frame(head, bg=T["card"])
        titles.pack(side="left")
        tk.Label(titles, text=title, font=F(14, "bold"), bg=T["card"], fg=T["text"]).pack(anchor="w")
        if subtitle:
            tk.Label(titles, text=subtitle, font=F(10), bg=T["card"], fg=T["muted"]).pack(anchor="w")
        self.actions = tk.Frame(head, bg=T["card"])
        self.actions.pack(side="right")
        self.body = tk.Frame(self, bg=T["card"])
        self.body.pack(fill="both", expand=True, padx=16, pady=(0, 14))


STATUS_STYLE = {"ok": ("✓", "good"), "bad": ("✗", "bad"), "warn": ("!", "warn"), "idle": ("•", "idle")}


_PDB_RESIDUE_CACHE = {}


def pdb_residues(path):
    """{(chain, resnum): resname} for a PDB file, cached by mtime so the
    live status check can call it on every keystroke."""
    try:
        mtime = os.path.getmtime(path)
    except OSError:
        return {}
    cached = _PDB_RESIDUE_CACHE.get(path)
    if cached and cached[0] == mtime:
        return cached[1]
    residues = {}
    try:
        with open(path, "r", errors="replace") as f:
            for line in f:
                if line.startswith(("ATOM", "HETATM")) and len(line) > 26:
                    residues.setdefault((line[21].strip(), line[22:26].strip()), line[17:20].strip())
    except OSError:
        return {}
    _PDB_RESIDUE_CACHE[path] = (mtime, residues)
    return residues


TIMEPOINT_RE = re.compile(r'^\d+(\.\d+)?(ms|us|µs|ns|s|min|h)$', re.IGNORECASE)
MUTATION_RE = re.compile(r'^[A-Z]\d+[A-Z]$')


def describe_tokens(tokens):
    """Split name tokens into (protein, mutant, ligand, timepoint). Protein
    is the first token (e.g. KPC2), mutations look like K73A, timepoints like
    10s; the ligand is the first remaining token."""
    tokens = [t for t in tokens if t]
    if not tokens:
        return "", "", "", ""
    rest = tokens[1:]
    mutants = [t for t in rest if MUTATION_RE.match(t)]
    times = [t for t in rest if TIMEPOINT_RE.match(t)]
    others = [t for t in rest if not MUTATION_RE.match(t) and not TIMEPOINT_RE.match(t)]
    return tokens[0], "+".join(mutants), (others[0] if others else ""), (times[0] if times else "")


def dataset_groups(mtz_dir, base_names):
    """{base_name: {protein, mutant, ligand, timepoint, combination, half}}.

    Uses the Drive sync record (which stills_processing folder each file came
    from) because xia2 filenames aren't always right - e.g. the Tax datasets
    are named "..._Cef_...". Falls back to parsing the filename."""
    try:
        with open(os.path.join(mtz_dir, SYNC_MANIFEST)) as f:
            manifest = json.load(f)
    except Exception:
        manifest = {}
    by_name = {os.path.splitext(dest)[0]: key for key, dest in manifest.items()}

    groups = {}
    for name in base_names:
        key = by_name.get(name)
        if key and key.count("/") == 2:
            protein_dir, combo_dir, half = key.split("/")
            protein, mutant, ligand, timepoint = describe_tokens(protein_dir.split("_"))
            known = {t.lower() for t in protein_dir.split("_")}
            extra = [t for t in combo_dir.split("_") if t.lower() not in known]
            timepoint = timepoint or next((t for t in extra if TIMEPOINT_RE.match(t)), "")
            combination = "_".join(t for t in extra if not TIMEPOINT_RE.match(t))
        else:
            tokens = name.split("_")
            protein, mutant, ligand, timepoint = describe_tokens(tokens)
            half = next((t for t in tokens if t.lower() in HALF_SETS), "")
            combination = ""
        groups[name] = {"protein": protein, "mutant": mutant, "ligand": ligand, "timepoint": timepoint,
                        "combination": combination, "half": half}
    return groups


def group_sort_key(info, name):
    return (info["protein"].lower(), info["ligand"].lower(), info["mutant"].lower(), info["timepoint"],
            len(info["combination"]), info["combination"], info["half"], name)


APP_LOGO_NAMES = ["harryspotter_logo.png"]
LAB_LOGO_NAMES = ["lab_logo.png", "lab_logo", "lab_logo.jpeg", "lab_logo.jpg"]


def make_entry(parent, var, width=None, size=11):
    kw = {"width": width} if width else {}
    return tk.Entry(parent, textvariable=var, font=F(size), relief="flat", bg=T["field"], fg=T["text"],
                    highlightthickness=1, highlightbackground=T["border"], highlightcolor=T["accent"],
                    insertbackground=T["text"], **kw)


class AnimatedGifLabel(tk.Label):
    def __init__(self, master, path, *args, **kwargs):
        super().__init__(master, *args, **kwargs)
        self.path = path
        self.frames = []
        self.delay = 100
        self.idx = 0
        self.load_frames()
        if self.frames:
            self.config(image=self.frames[0])
            self.after(self.delay, self.next_frame)

    def load_frames(self):
        try:
            img = Image.open(self.path)
            for i in range(img.n_frames):
                img.seek(i)
                frame = img.copy()
                frame.thumbnail((320, 320))
                self.frames.append(ImageTk.PhotoImage(frame))
            self.delay = img.info.get('duration', 250)
        except Exception as e:
            print(f"Failed to load GIF frames: {e}")

    def next_frame(self):
        if self.frames:
            self.idx = (self.idx + 1) % len(self.frames)
            self.config(image=self.frames[self.idx])
            self.after(self.delay, self.next_frame)

class ApoInspectorGUI:
    def __init__(self, root):
        self.root = root
        self.root.withdraw() 
        
        self.is_windows = sys.platform.startswith('win')
        self.working_dir = ""
        self.prefix = ""
        self.first_run = not os.path.exists(CONFIG_FILE)
        self.app_config = load_config()

        self.startup_win = tk.Toplevel(self.root)
        self.startup_win.title("Harry Spotter — Open Project")
        self.startup_win.geometry("640x560")
        self.startup_win.minsize(600, 540)
        self.startup_win.configure(bg=T["bg"])
        self.startup_win.attributes("-topmost", True)

        card = tk.Frame(self.startup_win, bg=T["card"], highlightbackground=T["border"], highlightthickness=1)
        card.pack(fill="both", expand=True, padx=20, pady=20)
        inner = tk.Frame(card, bg=T["card"])
        inner.pack(fill="both", expand=True, padx=26, pady=20)

        brand = tk.Frame(inner, bg=T["card"])
        brand.pack(fill="x")
        self.startup_icon = self.load_image(APP_LOGO_NAMES, (72, 72))
        if self.startup_icon:
            tk.Label(brand, image=self.startup_icon, bg=T["card"]).pack(side="left", padx=(0, 14))
        names = tk.Frame(brand, bg=T["card"])
        names.pack(side="left")
        tk.Label(names, text="Harry Spotter", font=F(24, "bold"), bg=T["card"], fg=T["text"]).pack(anchor="w")
        tk.Label(names, text="Time-resolved & apo density inspector", font=F(11), bg=T["card"],
                 fg=T["muted"]).pack(anchor="w")
        self.startup_logo = self.load_image(LAB_LOGO_NAMES, (190, 64))
        if self.startup_logo:
            tk.Label(brand, image=self.startup_logo, bg=T["card"]).pack(side="right")
        tk.Frame(inner, bg=T["border"], height=1).pack(fill="x", pady=16)

        tk.Label(inner, text="Open a project", font=F(16, "bold"), bg=T["card"], fg=T["text"]).pack(anchor="w")
        tk.Label(inner, text="The project folder holds your input/ files and the results of each run.",
                 font=F(11), bg=T["card"], fg=T["muted"]).pack(anchor="w", pady=(2, 16))

        # Default to the project folder this app lives in, so a new version
        # never silently reopens an older version's project (and its data).
        # The last project is only used when the app isn't inside one.
        last_dir = self.app_config.get("last_working_dir", "")
        own_dir = app_project_dir()
        if own_dir and os.path.isdir(os.path.join(own_dir, "input")):
            default_dir = own_dir
        elif last_dir and os.path.isdir(last_dir):
            default_dir = last_dir
        else:
            default_dir = os.path.abspath(os.getcwd())
        self.var_work_dir = tk.StringVar(value=default_dir)

        tk.Label(inner, text="Project folder", font=F(11, "bold"), bg=T["card"], fg=T["text"]).pack(anchor="w")
        row_frame = tk.Frame(inner, bg=T["card"])
        row_frame.pack(fill="x", pady=(4, 2))
        make_entry(row_frame, self.var_work_dir).pack(side="left", fill="x", expand=True, ipady=4)
        FlatButton(row_frame, "Browse…", self.browse_working_dir, style="secondary", size=10).pack(side="right", padx=(8, 0))

        if default_dir == own_dir:
            hint = f"↻ This app's own project folder ({os.path.basename(own_dir)})."
        elif last_dir and os.path.isdir(last_dir):
            hint = f"↻ Your last project ({os.path.basename(last_dir)})."
        else:
            hint = ""
        if hint:
            tk.Label(inner, text=hint, font=F(10), bg=T["card"], fg=T["accent"]).pack(anchor="w")

        tk.Label(inner, text="Results folder prefix (optional)", font=F(11, "bold"), bg=T["card"],
                 fg=T["text"]).pack(anchor="w", pady=(14, 0))
        self.var_prefix = tk.StringVar(value=self.app_config.get("last_prefix", ""))
        make_entry(inner, self.var_prefix).pack(fill="x", pady=(4, 2), ipady=4)
        prefix_preview = tk.Label(inner, font=F(10), bg=T["card"], fg=T["muted"])
        prefix_preview.pack(anchor="w")

        def update_preview(*_):
            pre = self.var_prefix.get().strip()
            prefix_preview.config(text=f"Results will be saved in:  {pre + '_results' if pre else 'results'}/")
        self.var_prefix.trace_add("write", update_preview)
        update_preview()

        self.btn_confirm = FlatButton(inner, "Open Harry Spotter  →", self.confirm_working_dir, style="primary",
                                      size=13, pady=10)
        self.btn_confirm.pack(fill="x", side="bottom", pady=(16, 0))
        self.startup_win.bind("<Return>", lambda e: self.confirm_working_dir())

        self.startup_win.protocol("WM_DELETE_WINDOW", self.on_startup_close)

    def find_logo(self):
        return self.find_resource(LAB_LOGO_NAMES)

    def load_image(self, names, box):
        """PhotoImage of a bundled image scaled to fit `box`, or None."""
        try:
            img = Image.open(self.find_resource(names))
            img.load()
            img = img.convert("RGBA")
            img.thumbnail(box, Image.LANCZOS)
            return ImageTk.PhotoImage(img)
        except Exception:
            return None

    def find_resource(self, possible_names):
        possible_dirs = [os.path.dirname(os.path.abspath(__file__)), os.path.abspath(".")]
        
        if hasattr(sys, '_MEIPASS'):
            possible_dirs.append(sys._MEIPASS) 
            
        if getattr(sys, 'frozen', False):
            possible_dirs.append(os.path.dirname(sys.executable)) 
            if sys.platform == 'darwin':
                possible_dirs.append(os.path.abspath(os.path.join(os.path.dirname(sys.executable), '..', 'Resources')))
                
        for directory in possible_dirs:
            for name in possible_names:
                full_path = os.path.join(directory, name)
                if os.path.exists(full_path):
                    return full_path
                    
        raise FileNotFoundError(f"{possible_names[0]} not found in the app's resources")

    def browse_working_dir(self):
        path = filedialog.askdirectory(parent=self.startup_win, title="Select Project Working Directory")
        if path:
            self.var_work_dir.set(os.path.abspath(path))

    def confirm_working_dir(self):
        self.working_dir = self.var_work_dir.get().strip()
        self.prefix = self.var_prefix.get().strip()

        if not self.working_dir: return

        self.app_config["last_working_dir"] = self.working_dir
        self.app_config["last_prefix"] = self.prefix
        save_config(self.app_config)

        self.startup_win.destroy()
        self.setup_main_window()

    def on_startup_close(self):
        self.startup_win.destroy()
        self.root.destroy()
        sys.exit(0)

    def setup_main_window(self):
        self.root.deiconify()
        self.root.title("Harry Spotter — Time-Resolved & Apo Inspector")
        sw, sh = self.root.winfo_screenwidth(), self.root.winfo_screenheight()
        self.root.geometry(f"{min(1180, sw - 60)}x{min(1000, sh - 70)}")
        self.root.minsize(980, 720)
        self.root.configure(bg=T["bg"])
        
        default_coot = self.auto_find_software("coot")
        default_dimple = self.auto_find_software("dimple")
        default_phenix = self.auto_find_software("phenix")

        self.out_folder_name = f"{self.prefix}_results" if self.prefix else "results"

        # Per-project remembered settings (keyed by working_dir), so a
        # returning project needs zero Browse clicks to get back to where
        # it left off.
        self.proj_cfg = self.app_config.get("projects", {}).get(self.working_dir, {})

        # Strategy variables
        input_dir = os.path.abspath(os.path.join(self.working_dir, "input"))
        self.var_model = tk.StringVar(value=self.proj_cfg.get(
            "model", default_input_file(input_dir, "reference.pdb", "*.pdb")))
        self.var_mtz = tk.StringVar(value=self.proj_cfg.get(
            "mtz_dir", os.path.abspath(os.path.join(self.working_dir, "input", "mtz"))))
        self.var_apo_mtz = tk.StringVar(value=self.proj_cfg.get(
            "apo_mtz", default_input_file(input_dir, "apo_ground_state.mtz", "*apo*ground*state*.mtz")))

        self.var_out = tk.StringVar(value=self.proj_cfg.get(
            "out_dir", os.path.abspath(os.path.join(self.working_dir, self.out_folder_name))))
        self.var_dimple = tk.StringVar(value=self.proj_cfg.get("dimple_exe", default_dimple))
        self.var_phenix = tk.StringVar(value=self.proj_cfg.get("phenix_exe", default_phenix))
        self.var_coot = tk.StringVar(value=self.proj_cfg.get("coot_exe", default_coot))
        self.var_pymol = tk.StringVar(value=self.proj_cfg.get("pymol_exe") or self.auto_find_software("pymol"))
        self.var_residue = tk.StringVar(value=self.proj_cfg.get("residue", ""))
        self.var_chain = tk.StringVar(value=self.proj_cfg.get("chain", "A"))
        self.var_contour = tk.StringVar(value=self.proj_cfg.get("contour", "3.0"))

        # Google Drive sync
        self.var_drive_source = tk.StringVar(value=self.proj_cfg.get("drive_source", find_google_drive_mount() or ""))
        self.var_visit = tk.StringVar(value=self.proj_cfg.get("visit", ""))
        self.visit_dir_cache = self.proj_cfg.get("visit_dir", "")
        self.var_autosync = tk.BooleanVar(value=self.proj_cfg.get("autosync", True))
        self.var_dataset_count = tk.StringVar(value="")

        # UI state: pipeline mode (was the notebook tab) and which
        # collapsible sections are open, both remembered per project.
        self.var_mode = tk.StringVar(value=self.proj_cfg.get("mode", "phenix"))
        self.ui_collapsed = dict(self.proj_cfg.get("ui_collapsed", {}))
        self.current_issues = []
        self._refresh_job = None

        self.processed_datasets = []
        self.image_refs = []
        self.radio_vars = {}
        self.results_window = None

        self.create_widgets()
        self.root.protocol("WM_DELETE_WINDOW", self.on_main_close)

        # New users: walk them through connecting Google Drive.
        if self.first_run or (not find_google_drive_mount() and not self.app_config.get("drive_setup_dismissed")):
            self.root.after(700, lambda: self.show_drive_setup(auto=True))

        # Kick off a silent background sync immediately so, by the time the
        # user looks at the screen, any new Drive data is already local.
        if self.var_autosync.get() and self.var_drive_source.get().strip() and self.var_visit.get().strip():
            self.root.after(400, lambda: self.start_drive_sync(silent=True))

    def auto_find_linux(self, software_type):
        """Find a tool on Linux: PATH first, then the usual install folders
        (CCP4 under /opt/xtal, /usr/local, ~; Phenix; PyMOL incl. conda)."""
        on_path = {"coot": ["coot-1", "coot"], "dimple": ["dimple"],
                   "phenix": ["phenix.fobs_minus_fobs_map"], "pymol": ["pymol"]}[software_type]
        for name in on_path:
            if shutil.which(name):
                return shutil.which(name)
        patterns = {
            "coot": ["ccp4-*/bin/coot", "ccp4*/bin/coot", "coot*/bin/coot"],
            "dimple": ["ccp4-*/bin/dimple", "ccp4*/bin/dimple"],
            "phenix": ["phenix-*/phenix_bin/phenix.fobs_minus_fobs_map", "phenix-*/build/bin/phenix.fobs_minus_fobs_map",
                       "phenix-*/bin/phenix.fobs_minus_fobs_map"],
            "pymol": ["pymol/pymol", "pymol*/pymol", "pymol*/bin/pymol", "miniconda3/bin/pymol", "anaconda3/bin/pymol",
                      "miniforge3/bin/pymol", "mambaforge/bin/pymol"],
        }[software_type]
        for base in LINUX_SOFTWARE_BASES():
            for pattern in patterns:
                found = [f for f in sorted(glob.glob(os.path.join(base, pattern))) if tool_available(f)]
                if found:
                    return found[-1]  # newest version by name
        return on_path[-1]

    def auto_find_software(self, software_type):
        if self.is_windows:
            drives = [os.environ.get("SystemDrive", "C:") + "\\"]
            bases = drives + [os.environ.get(v, "") for v in ("ProgramFiles", "ProgramFiles(x86)", "LOCALAPPDATA")
                              if os.environ.get(v)] + [os.path.expanduser("~")]
            if software_type == "pymol":
                bases.append(os.environ.get("ProgramData", "C:\\ProgramData"))
            patterns = {
                "pymol": ["PyMOL*\\PyMOLWin.exe", "PyMOL*\\PyMOL.exe", "PyMOL*\\PyMOL*\\PyMOLWin.exe",
                          "Schrodinger\\PyMOL*\\PyMOLWin.exe", "Schrodinger\\PyMOL*\\PyMOL.exe",
                          "miniconda3\\Scripts\\pymol.exe", "anaconda3\\Scripts\\pymol.exe",
                          "miniforge3\\Scripts\\pymol.exe", "mambaforge\\Scripts\\pymol.exe"],
                "coot": ["WinCoot*\\wincoot.bat", "WinCoot*\\runwincoot.bat", "WinCoot*\\run_coot.bat",
                         "CCP4*\\WinCoot*\\wincoot.bat", "CCP4*\\*\\WinCoot*\\wincoot.bat",
                         "CCP4*\\bin\\wincoot.bat", "CCP4*\\*\\bin\\wincoot.bat",
                         "CCP4*\\WinCoot*\\runwincoot.bat", "CCP4*\\*\\WinCoot*\\runwincoot.bat"],
                "dimple": ["CCP4*\\bin\\dimple.bat", "CCP4*\\*\\bin\\dimple.bat",
                           "CCP4*\\bin\\dimple.exe", "CCP4*\\*\\bin\\dimple.exe"],
                "phenix": ["phenix*\\phenix_bin\\phenix.fobs_minus_fobs_map.bat",
                           "phenix*\\build\\bin\\phenix.fobs_minus_fobs_map.bat",
                           "phenix*\\*\\phenix.fobs_minus_fobs_map.bat"],
            }[software_type]
            on_path = {"coot": ["wincoot.bat", "runwincoot.bat", "run_coot.bat"], "dimple": ["dimple.bat", "dimple"],
                       "pymol": ["pymol.exe", "pymol", "PyMOLWin.exe"],
                       "phenix": ["phenix.fobs_minus_fobs_map.bat", "phenix.fobs_minus_fobs_map"]}[software_type]
            for name in on_path:
                if shutil.which(name):
                    return shutil.which(name)
            for base in bases:
                for pattern in patterns:
                    found = sorted(glob.glob(os.path.join(base, pattern)))
                    if found:
                        return found[-1]  # newest version by name
            if software_type == "pymol":
                found = windows_registered_app(["PyMOLWin.exe", "PyMOL.exe", "pymol.exe"])
                if found:
                    return found
                # Nearly every Windows install adds a Start Menu shortcut - follow it.
                menus = [os.path.join(os.environ.get(v, ""), "Microsoft", "Windows", "Start Menu", "Programs")
                         for v in ("ProgramData", "APPDATA") if os.environ.get(v)]
                for menu in menus:
                    for lnk in sorted(glob.glob(os.path.join(menu, "**", "*PyMOL*.lnk"), recursive=True)):
                        target = resolve_windows_shortcut(lnk)
                        if target and target.lower().endswith(".exe"):
                            return target
            return on_path[0]
        else:
            if IS_LINUX:
                return self.auto_find_linux(software_type)
            if software_type == "pymol":
                # Schrodinger (incentive) app bundles first, then open-source installs
                apps = sorted(glob.glob("/Applications/PyMOL*.app/Contents/MacOS/PyMOL") +
                              glob.glob(os.path.expanduser("~/Applications/PyMOL*.app/Contents/MacOS/PyMOL")))
                if apps: return apps[-1]
                if shutil.which("pymol"): return shutil.which("pymol")
                for path in ["/opt/homebrew/bin/pymol", "/usr/local/bin/pymol"] + [
                        os.path.expanduser(f"~/{d}/bin/pymol")
                        for d in ("miniconda3", "anaconda3", "miniforge3", "mambaforge")] + ["/opt/anaconda3/bin/pymol"]:
                    if os.path.exists(path): return path
                return "pymol"

            if software_type == "coot":
                for path in ["/opt/homebrew/bin/coot-1", "/opt/homebrew/bin/coot", "/usr/local/bin/coot-1", "/usr/local/bin/coot"]:
                    if os.path.exists(path): return path
                if shutil.which("coot-1"): return shutil.which("coot-1")
                if shutil.which("coot"): return shutil.which("coot")
                for path in glob.glob("/Applications/ccp4-*/bin/coot"):
                    if os.path.exists(path): return path
                return "coot-1"
                
            elif software_type == "dimple":
                if shutil.which("dimple"): return shutil.which("dimple")
                for path in glob.glob("/Applications/ccp4-*/bin/dimple") + ["/opt/homebrew/bin/dimple"]:
                    if os.path.exists(path): return path
                return "dimple"
                
            elif software_type == "phenix":
                if shutil.which("phenix.fobs_minus_fobs_map"): 
                    return shutil.which("phenix.fobs_minus_fobs_map")
                    
                paths = glob.glob(os.path.expanduser("~/Applications/phenix-*/phenix_bin/phenix.fobs_minus_fobs_map")) + \
                        glob.glob("/Applications/phenix-*/phenix_bin/phenix.fobs_minus_fobs_map") + \
                        glob.glob(os.path.expanduser("~/Applications/phenix-*/build/bin/phenix.fobs_minus_fobs_map")) + \
                        glob.glob("/Applications/phenix-*/build/bin/phenix.fobs_minus_fobs_map")
                
                for path in paths:
                    if os.path.exists(path): return path
                return "phenix.fobs_minus_fobs_map"

    def create_widgets(self):
        self.dots = {}
        self.path_entries = []

        outer = tk.Frame(self.root, bg=T["bg"])
        outer.pack(fill="both", expand=True, padx=20, pady=16)
        outer.columnconfigure(0, weight=3, uniform="bento")
        outer.columnconfigure(1, weight=2, uniform="bento")
        outer.rowconfigure(2, weight=1)

        # ---------------- HEADER ----------------
        header = tk.Frame(outer, bg=T["bg"])
        header.grid(row=0, column=0, columnspan=2, sticky="we", pady=(0, 12))
        self.header_icon = self.load_image(APP_LOGO_NAMES, (54, 54))
        if self.header_icon:
            tk.Label(header, image=self.header_icon, bg=T["bg"]).pack(side="left", padx=(0, 12))
        titles = tk.Frame(header, bg=T["bg"])
        titles.pack(side="left")
        tk.Label(titles, text="Harry Spotter", font=F(20, "bold"), bg=T["bg"], fg=T["text"]).pack(anchor="w")
        tk.Label(titles, text=f"Time-resolved & apo density inspector   ·   📁 {os.path.basename(self.working_dir)}"
                              f"   ·   results → {self.out_folder_name}/",
                 font=F(11), bg=T["bg"], fg=T["muted"]).pack(anchor="w")
        pill = tk.Frame(header, bg=T["border"], padx=1, pady=1)
        pill.pack(side="right")
        self.lbl_readiness = tk.Label(pill, font=F(11, "bold"), bg=T["card"], padx=14, pady=7, cursor="hand2")
        self.lbl_readiness.pack()
        self.lbl_readiness.bind("<Button-1>", lambda e: self.show_issues())
        self.header_logo = self.load_image(LAB_LOGO_NAMES, (150, 48))
        if self.header_logo:
            tk.Label(header, image=self.header_logo, bg=T["bg"]).pack(side="right", padx=(0, 16))

        # ---------------- MODE SWITCH ----------------
        mode_bar = tk.Frame(outer, bg=T["bg"])
        mode_bar.grid(row=1, column=0, columnspan=2, sticky="we", pady=(0, 12))
        seg = tk.Frame(mode_bar, bg=T["seg_bg"], padx=3, pady=3)
        seg.pack(side="left")
        self.mode_btns = {}
        for key, text in (("phenix", "⏱  Time-Resolved Fo-Fo  ·  Phenix"), ("dimple", "🧪  Apo Screening  ·  Dimple")):
            lbl = tk.Label(seg, text=text, font=F(11, "bold"), padx=16, pady=6, cursor="hand2")
            lbl.pack(side="left")
            lbl.bind("<Button-1>", lambda e, k=key: self.set_mode(k))
            self.mode_btns[key] = lbl
        self.lbl_mode_hint = tk.Label(mode_bar, font=F(10), bg=T["bg"], fg=T["muted"])
        self.lbl_mode_hint.pack(side="left", padx=14)

        # Cards on top, activity log below, with a draggable divider between.
        self.paned = tk.PanedWindow(outer, orient="vertical", bg=T["border"], sashwidth=7, bd=0,
                                    sashrelief="flat", showhandle=False, sashcursor="sb_v_double_arrow")
        self.paned.grid(row=2, column=0, columnspan=2, sticky="nsew")
        # The cards sit in a scrollable area, so the log can be dragged as
        # large as wanted; a scrollbar appears only when the cards don't fit.
        bento_wrap = tk.Frame(self.paned, bg=T["bg"])
        bento_canvas = tk.Canvas(bento_wrap, bg=T["bg"], highlightthickness=0, bd=0)
        bento_scroll = tk.Scrollbar(bento_wrap, orient="vertical", command=bento_canvas.yview)
        bento_canvas.configure(yscrollcommand=bento_scroll.set)
        bento_canvas.pack(side="left", fill="both", expand=True)
        bento = tk.Frame(bento_canvas, bg=T["bg"])
        bento_id = bento_canvas.create_window((0, 0), window=bento, anchor="nw")
        bento.columnconfigure(0, weight=3, uniform="bento")
        bento.columnconfigure(1, weight=2, uniform="bento")

        def update_bento_scroll(_event=None):
            bento_canvas.configure(scrollregion=(0, 0, bento.winfo_reqwidth(), bento.winfo_reqheight()))
            if bento.winfo_reqheight() > bento_canvas.winfo_height() + 2:
                bento_scroll.pack(side="right", fill="y")
            else:
                bento_scroll.pack_forget()
                bento_canvas.yview_moveto(0)
        bento.bind("<Configure>", update_bento_scroll)
        bento_canvas.bind("<Configure>", lambda e: (bento_canvas.itemconfigure(bento_id, width=e.width),
                                                    update_bento_scroll()))

        # Only scroll the cards while the pointer is over them (the log has its own scrolling).
        self.enable_wheel_scroll(self.root, bento_canvas, within=bento_wrap)
        self.bento = bento
        self.bento_wrap = bento_wrap

        # ---------------- BENTO: DRIVE ----------------
        drive = Card(bento, "☁  Data from Google Drive", "Latest _all.mtz for every dataset in the visit")
        drive.grid(row=0, column=0, sticky="nsew", padx=(0, 8), pady=(0, 12))
        self.btn_drive_setup = FlatButton(drive.actions, "Connect Google Drive…", self.show_drive_setup,
                                          style="ghost", size=10, padx=8, pady=3)
        b = drive.body
        status = tk.Frame(b, bg=T["card"])
        status.pack(fill="x", pady=(0, 10))
        self.dots["drive"] = tk.Label(status, font=F(13, "bold"), bg=T["card"], width=2)
        self.dots["drive"].pack(side="left")
        self.lbl_drive_status = tk.Label(status, font=F(11), bg=T["card"], fg=T["text"], anchor="w")
        self.lbl_drive_status.pack(side="left")

        visit_row = tk.Frame(b, bg=T["card"])
        visit_row.pack(fill="x")
        tk.Label(visit_row, text="MX visit", font=F(11, "bold"), bg=T["card"], fg=T["text"]).pack(side="left")
        visit_entry = make_entry(visit_row, self.var_visit, width=16, size=13)
        visit_entry.pack(side="left", padx=(10, 8), ipady=4)
        visit_entry.bind("<Return>", lambda e: self.start_drive_sync())
        self.btn_sync = FlatButton(visit_row, "⟳  Sync now", self.start_drive_sync, style="drive", size=11)
        self.btn_sync.pack(side="left")
        self.lbl_dataset_count = tk.Label(visit_row, textvariable=self.var_dataset_count, font=F(11, "bold"),
                                          bg=T["accent_soft"], fg=T["accent"], padx=10, pady=4)
        self.lbl_dataset_count.pack(side="right")
        tk.Label(b, text="e.g. mx12345-1  —  press Enter or Sync to pull new data", font=F(10),
                 bg=T["card"], fg=T["muted"]).pack(anchor="w", pady=(4, 6))

        opts = tk.Frame(b, bg=T["card"])
        opts.pack(fill="x")
        tk.Checkbutton(opts, text="Auto-sync when the app opens", variable=self.var_autosync, bg=T["card"],
                       fg=T["text"], font=F(10), command=self.persist_state).pack(side="left")
        FlatButton(opts, "📁  Open MTZ folder", lambda: self.open_in_finder(self.var_mtz.get().strip()),
                   style="ghost", size=10, padx=8, pady=3).pack(side="right")

        adv = self.make_collapsible(b, "drive_adv", "Folders")
        adv.pack(fill="x", pady=(8, 0))
        self.path_row(adv.body, 0, "drive_source", "Google Drive folder", self.var_drive_source, is_dir=True)
        self.path_row(adv.body, 1, "mtz_dir", "Local MTZ folder", self.var_mtz, is_dir=True)

        # ---------------- BENTO: SOFTWARE ----------------
        sw = Card(bento, "🧰  Software", f"Found automatically on this {COMPUTER}")
        sw.grid(row=0, column=1, sticky="nsew", padx=(8, 0), pady=(0, 12))
        FlatButton(sw.actions, "↻  Re-check", self.recheck_software, style="ghost", size=10, padx=8, pady=3).pack()
        self.sw_rows = {}
        for i, key in enumerate(("phenix", "coot", "dimple", "pymol")):
            name, purpose, url = SOFTWARE_INFO[key]
            row = tk.Frame(sw.body, bg=T["card"])
            row.pack(fill="x", pady=3)
            var = {"phenix": self.var_phenix, "coot": self.var_coot, "dimple": self.var_dimple,
                   "pymol": self.var_pymol}[key]
            # Buttons are packed first so they keep their space when the
            # status text is long.
            locate = FlatButton(row, "Locate…", lambda v=var: self.browse(v, False), style="ghost", size=10,
                                padx=6, pady=2)
            locate.pack(side="right")
            dot = tk.Label(row, font=F(13, "bold"), bg=T["card"], width=2)
            dot.pack(side="left")
            names = tk.Frame(row, bg=T["card"])
            names.pack(side="left")
            tk.Label(names, text=name, font=F(11, "bold"), bg=T["card"], fg=T["text"]).pack(anchor="w")
            state = tk.Label(names, font=F(10), bg=T["card"], fg=T["muted"])
            state.pack(anchor="w")
            download = FlatButton(row, "Download", lambda u=url: open_url(u), style="danger", size=10,
                                  padx=8, pady=2)
            self.dots[key] = dot
            self.sw_rows[key] = {"state": state, "download": download, "locate": locate, "purpose": purpose}
        sw_adv = self.make_collapsible(sw.body, "software_adv", "Executable paths")
        sw_adv.pack(fill="x", pady=(8, 0))
        self.path_row(sw_adv.body, 0, "phenix_path", "Phenix", self.var_phenix, is_dir=False)
        self.path_row(sw_adv.body, 1, "coot_path", "Coot", self.var_coot, is_dir=False)
        self.path_row(sw_adv.body, 2, "dimple_path", "Dimple", self.var_dimple, is_dir=False)
        self.path_row(sw_adv.body, 3, "pymol_path", "PyMOL", self.var_pymol, is_dir=False)

        # ---------------- BENTO: INPUTS ----------------
        inputs = Card(bento, "📄  Inputs", "Pulled from the visit folder when available")
        inputs.grid(row=1, column=0, sticky="nsew", padx=(0, 8), pady=(0, 12))
        self.path_row(inputs.body, 0, "model", "Reference PDB", self.var_model, is_dir=False)
        self.apo_row = self.path_row(inputs.body, 1, "apo", "Apo ground-state MTZ", self.var_apo_mtz, is_dir=False)
        self.path_row(inputs.body, 2, "out", "Results folder", self.var_out, is_dir=True, append_results=True)

        # ---------------- BENTO: RUN ----------------
        run = Card(bento, "🎯  Run")
        run.grid(row=1, column=1, sticky="nsew", padx=(8, 0), pady=(0, 12))
        fields = tk.Frame(run.body, bg=T["card"])
        fields.pack(fill="x")
        for col, (key, label, var, hint, weight) in enumerate((
                ("chain", "Chain", self.var_chain, "e.g. A", 1),
                ("residue", "Residue", self.var_residue, "number", 2),
                ("contour", "Contour", self.var_contour, "RMSD (σ)", 2))):
            f = tk.Frame(fields, bg=T["card"])
            f.grid(row=0, column=col, sticky="we", padx=(0, 10) if col < 2 else 0)
            fields.columnconfigure(col, weight=weight, uniform="runfields" if col else None,
                                   minsize=96 if col == 0 else 0)
            top = tk.Frame(f, bg=T["card"])
            top.pack(fill="x")
            self.dots[key] = tk.Label(top, font=F(12, "bold"), bg=T["card"], width=2)
            self.dots[key].pack(side="left")
            tk.Label(top, text=label, font=F(11, "bold"), bg=T["card"], fg=T["text"]).pack(side="left")
            make_entry(f, var, size=13, width=4 if key == "chain" else None).pack(fill="x", pady=(4, 0), ipady=4)
            tk.Label(f, text=hint, font=F(10), bg=T["card"], fg=T["muted"]).pack(anchor="w")
        self.lbl_target = tk.Label(run.body, font=F(11, "bold"), bg=T["accent_soft"], fg=T["accent"],
                                   padx=10, pady=4, anchor="w")
        self.lbl_target.pack(fill="x", pady=(8, 0))

        self.btn_run = FlatButton(run.body, "▶  Run pipeline", self.start_pipeline, style="primary", size=14, pady=10)
        self.btn_run.pack(fill="x", pady=(10, 8))
        row = tk.Frame(run.body, bg=T["card"])
        row.pack(fill="x")
        row.columnconfigure(0, weight=1, uniform="rb")
        row.columnconfigure(1, weight=1, uniform="rb")
        self.btn_load = FlatButton(row, "📂  Load previous", self.load_previous_run, style="secondary", size=11)
        self.btn_load.grid(row=0, column=0, sticky="we", padx=(0, 4))
        self.btn_view = FlatButton(row, "📊  View results", self.open_results, style="secondary", size=11)
        self.btn_view.grid(row=0, column=1, sticky="we", padx=(4, 0))
        self.btn_view.set_enabled(False)
        tk.Label(run.body, text=("⌘R" if IS_MAC else "Ctrl+R") + " runs the pipeline", font=F(10), bg=T["card"], fg=T["muted"]).pack(anchor="e", pady=(6, 0))

        # ---------------- ACTIVITY LOG ----------------
        self.outer = outer
        log_card = tk.Frame(self.paned, bg=T["card"], highlightbackground=T["border"], highlightthickness=1)
        self.log_card = log_card
        log_head = tk.Frame(log_card, bg=T["card"])
        log_head.pack(fill="x", padx=16, pady=10)
        self.log_header = tk.Label(log_head, font=F(12, "bold"), bg=T["card"], fg=T["text"], cursor="hand2")
        self.log_header.pack(side="left")
        self.log_header.bind("<Button-1>", lambda e: self.toggle_log())
        tk.Label(log_head, text="drag the bar above to resize", font=F(10), bg=T["card"],
                 fg=T["muted"]).pack(side="left", padx=12)
        FlatButton(log_head, "Clear", lambda: self.console.delete("1.0", tk.END), style="ghost", size=10,
                   padx=8, pady=2).pack(side="right")
        self.log_body = tk.Frame(log_card, bg=T["card"])
        self.console = scrolledtext.ScrolledText(self.log_body, height=4, bg=T["log_bg"], fg=T["log_fg"],
                                                 font=MONO_FONT, relief="flat", padx=10, pady=8,
                                                 insertbackground=T["log_fg"], highlightthickness=0)
        self.console.pack(fill="both", expand=True, padx=16, pady=(0, 14))
        for tag, colour in (("ok", "#86efac"), ("err", "#fca5a5"), ("warn", "#fcd34d"), ("head", "#93c5fd")):
            self.console.tag_config(tag, foreground=colour)

        # Top pane is a scrollable-free bento; give it its natural height as
        # a minimum so dragging the divider never hides a card.
        self.paned.add(bento_wrap, minsize=160, stretch="always")
        self.paned.add(log_card, minsize=48, stretch="never")
        self.paned.bind("<ButtonRelease-1>", lambda e: self._remember_log_height())
        self.log_height = int(self.proj_cfg.get("log_height", 320))
        self.log_collapsed = self.ui_collapsed.get("log", False)
        self.root.after(80, self._render_log)

        # ---------------- LIVE STATUS ----------------
        for var in (self.var_model, self.var_mtz, self.var_apo_mtz, self.var_out, self.var_phenix, self.var_coot,
                    self.var_dimple, self.var_residue, self.var_contour, self.var_drive_source, self.var_chain,
                    self.var_pymol):
            var.trace_add("write", lambda *a: self.schedule_refresh())
        self.root.bind_all("<Command-r>" if IS_MAC else "<Control-r>",
                           lambda e: self.start_pipeline() if self.btn_run._enabled else None)

        self.set_mode(self.var_mode.get(), persist=False)
        self.update_dataset_count()

    def toggle_log(self, collapsed=None):
        if not self.log_collapsed:
            self._remember_log_height()
        self.log_collapsed = (not self.log_collapsed) if collapsed is None else collapsed
        self.ui_collapsed["log"] = self.log_collapsed
        self._render_log()
        self.persist_state()

    def _log_header_height(self):
        return self.log_header.master.winfo_reqheight() + 4

    def _render_log(self):
        self.log_header.config(text=f"{'▸' if self.log_collapsed else '▾'}  Activity log")
        if self.log_collapsed:
            self.log_body.pack_forget()
        else:
            self.log_body.pack(fill="both", expand=True)
        self.root.update_idletasks()
        total = self.paned.winfo_height()
        if total <= 1:
            self.root.after(80, self._render_log)
            return
        # The log keeps the height the user last dragged it to; the cards
        # take the rest and scroll if they don't fit.
        want = self._log_header_height() if self.log_collapsed else max(self.log_height, 120)
        top = max(total - want, 160)
        self.paned.sash_place(0, 0, int(top))

    def _remember_log_height(self):
        if getattr(self, "log_collapsed", False):
            return
        try:
            total = self.paned.winfo_height()
            sash_y = self.paned.sash_coord(0)[1]
        except tk.TclError:
            return
        if total > 1 and total - sash_y > self._log_header_height() + 20:
            self.log_height = total - sash_y
            self.persist_state()

    # ----------------------------------------------------------------
    # UI HELPERS
    # ----------------------------------------------------------------
    def make_collapsible(self, parent, key, title, default_collapsed=True, size=10):
        def on_toggle(collapsed):
            self.ui_collapsed[key] = collapsed
            self.persist_state()
        return Collapsible(parent, title, collapsed=self.ui_collapsed.get(key, default_collapsed),
                           on_toggle=on_toggle, size=size)

    def path_row(self, parent, row, key, label, var, is_dir, append_results=False):
        """Status dot | label | path entry | Browse. Returns the widgets so a
        row can be hidden (e.g. the apo MTZ in Dimple mode)."""
        parent.columnconfigure(2, weight=1)
        dot = tk.Label(parent, font=F(12, "bold"), bg=T["card"], width=2)
        dot.grid(row=row, column=0, sticky="w")
        lbl = tk.Label(parent, text=label, font=F(11, "bold"), bg=T["card"], fg=T["text"], anchor="w")
        lbl.grid(row=row, column=1, sticky="w", padx=(0, 10))
        ent = make_entry(parent, var, size=11)
        ent.grid(row=row, column=2, sticky="we", pady=4, ipady=3)
        btn = FlatButton(parent, "Browse…", lambda: self.browse(var, is_dir, append_results), style="ghost",
                         size=10, padx=8, pady=3)
        btn.grid(row=row, column=3, padx=(8, 0))
        self.dots[key] = dot
        self.path_entries.append(ent)
        return (dot, lbl, ent, btn)

    def set_dot(self, key, state):
        if key in self.dots:
            symbol, colour = STATUS_STYLE[state]
            self.dots[key].config(text=symbol, fg=T[colour])

    def set_mode(self, mode, persist=True):
        self.var_mode.set(mode)
        for key, lbl in self.mode_btns.items():
            if key == mode:
                lbl.config(bg=T["card"], fg=T["accent"])
            else:
                lbl.config(bg=T["seg_bg"], fg=T["muted"])
        self.lbl_mode_hint.config(text="Target − apo Fo-Fo difference maps with Phenix" if mode == "phenix"
                                  else "Dimple refinement against the reference model")
        for w in self.apo_row:
            if mode == "phenix":
                w.grid()
            else:
                w.grid_remove()
        self.refresh_status()
        if persist:
            self.persist_state()

    def schedule_refresh(self):
        if self._refresh_job:
            self.root.after_cancel(self._refresh_job)
        self._refresh_job = self.root.after(250, self.refresh_status)

    def refresh_status(self):
        """Re-validate every input and update the ✓/✗ marks and the header
        readiness pill. Cheap (a few stat calls), so it runs on every edit."""
        self._refresh_job = None
        mode = self.var_mode.get()
        issues = []

        def check(key, ok, problem, needed=True):
            self.set_dot(key, "ok" if ok else ("bad" if needed else "idle"))
            if needed and not ok:
                issues.append(problem)

        check("model", os.path.isfile(self.var_model.get().strip()), "Reference PDB not found")
        check("apo", os.path.isfile(self.var_apo_mtz.get().strip()), "Apo ground-state MTZ not found",
              needed=(mode == "phenix"))
        mtz_dir = self.var_mtz.get().strip()
        n_mtz = len(glob.glob(os.path.join(mtz_dir, "*.mtz"))) if os.path.isdir(mtz_dir) else 0
        check("mtz_dir", n_mtz > 0, "No MTZ datasets yet — enter the MX visit and Sync, or choose an MTZ folder")
        check("out", bool(self.var_out.get().strip()), "Results folder not set")
        chain = self.var_chain.get().strip()
        residue = self.var_residue.get().strip()
        check("chain", bool(chain) and len(chain) <= 4 and chain.isalnum(), "Chain not set (e.g. A)")
        check("residue", bool(residue), "Target residue not set")
        model = self.var_model.get().strip()
        if chain and residue and os.path.isfile(model):
            resname = pdb_residues(model).get((chain, residue))
            if resname:
                self.lbl_target.config(text=f"✓  Target:  {resname} {chain}{residue}  in {os.path.basename(model)}",
                                       bg=T["accent_soft"], fg=T["accent"])
            else:
                self.lbl_target.config(text=f"!  {chain}{residue} not found in {os.path.basename(model)}",
                                       bg="#fdf3e3", fg=T["warn"])
                issues.append(f"Residue {chain}{residue} isn't in the reference PDB — check the chain and number")
                self.set_dot("residue", "warn")
        else:
            self.lbl_target.config(text="Set a chain and residue to centre the maps on",
                                   bg=T["field"], fg=T["muted"])
        try:
            float(self.var_contour.get().strip())
            contour_ok = True
        except ValueError:
            contour_ok = False
        check("contour", contour_ok, "Contour level must be a number")

        # Google Drive (optional - data can also be placed in the MTZ folder by hand)
        mount = self.var_drive_source.get().strip()
        if mount and os.path.isdir(mount):
            self.set_dot("drive", "ok")
            self.set_dot("drive_source", "ok")
            account = drive_account_name(mount)
            self.lbl_drive_status.config(text=f"Connected{'  ·  ' + account if account else ''}", fg=T["text"])
            self.btn_drive_setup.pack_forget()
        else:
            self.set_dot("drive", "warn")
            self.set_dot("drive_source", "warn")
            if IS_LINUX:
                status = "No Google Drive folder found - mount it with rclone or Insync"
            elif drive_app_installed():
                status = "Google Drive installed but not signed in"
            else:
                status = "Google Drive for Desktop not set up"
            self.lbl_drive_status.config(text=status, fg=T["warn"])
            self.btn_drive_setup.pack()

        # Software
        for key, var in (("phenix", self.var_phenix), ("coot", self.var_coot), ("dimple", self.var_dimple),
                         ("pymol", self.var_pymol)):
            needed = key == "coot" or key == mode   # PyMOL is optional: never blocks a run
            found = tool_available(var.get())
            row = self.sw_rows[key]
            if found:
                self.set_dot(key, "ok")
                row["state"].config(text=f"Installed  ·  {row['purpose']}", fg=T["good"])
                row["download"].pack_forget()
            else:
                self.set_dot(key, "bad" if needed else "idle")
                row["state"].config(text="Not installed — download needed" if needed
                                    else "Not installed  ·  optional, for viewing results" if key == "pymol"
                                    else "Not installed  ·  not needed in this mode",
                                    fg=T["bad"] if needed else T["muted"])
                if needed or key == "pymol":
                    row["download"].pack(side="right", padx=(6, 0), before=row["locate"])
                else:
                    row["download"].pack_forget()
                if needed:
                    issues.append(f"{SOFTWARE_INFO[key][0]} is not installed (or not found) — "
                                  f"use Download, then Re-check")
            self.set_dot(f"{key}_path", "ok" if found else ("bad" if needed else "idle"))

        for ent in self.path_entries:
            if self.root.focus_get() is not ent:
                ent.xview_moveto(1.0)  # show the file name end of long paths

        self.current_issues = issues
        if issues:
            self.lbl_readiness.config(text=f"●  {len(issues)} thing{'s' if len(issues) != 1 else ''} to fix  ›",
                                      fg=T["warn"])
        else:
            self.lbl_readiness.config(text="●  Ready to run", fg=T["good"])

    def show_issues(self):
        self.refresh_status()
        if self.current_issues:
            messagebox.showwarning("Not ready yet", "Before running:\n\n• " + "\n• ".join(self.current_issues))
        else:
            messagebox.showinfo("Ready", "Everything needed for this mode is in place.")

    def recheck_software(self):
        """Re-detect any tool that isn't found (e.g. just installed)."""
        for key, var in (("phenix", self.var_phenix), ("coot", self.var_coot), ("dimple", self.var_dimple),
                         ("pymol", self.var_pymol)):
            if not tool_available(var.get()):
                found = self.auto_find_software(key)
                if tool_available(found):
                    var.set(found)
                    self.log(f"✅ Found {SOFTWARE_INFO[key][0]}: {found}")
        self.refresh_status()
        self.persist_state()

    def on_main_close(self):
        self.persist_state()
        self.root.destroy()

    # ----------------------------------------------------------------
    # GOOGLE DRIVE SETUP (first run)
    #
    # HarrySpotter never handles Google passwords itself: Google Drive for
    # Desktop does the sign-in, then mirrors Drive to a local folder. This
    # window walks a new user through that and notices when it's done.
    # ----------------------------------------------------------------
    def show_drive_setup(self, auto=False):
        if getattr(self, "drive_win", None) is not None and self.drive_win.winfo_exists():
            self.drive_win.lift()
            return
        win = self.drive_win = tk.Toplevel(self.root)
        win.title("Connect Google Drive")
        win.configure(bg=T["bg"])
        win.resizable(False, False)
        win.transient(self.root)

        card = tk.Frame(win, bg=T["card"], highlightbackground=T["border"], highlightthickness=1)
        card.pack(fill="both", expand=True, padx=18, pady=18)
        inner = tk.Frame(card, bg=T["card"])
        inner.pack(fill="both", expand=True, padx=24, pady=20)

        tk.Label(inner, text="☁  Connect Google Drive", font=F(18, "bold"), bg=T["card"], fg=T["text"]).pack(anchor="w")
        if IS_LINUX:
            intro = ("Harry Spotter reads beamtime data from your Google Drive. Google doesn't make a Drive app\n"
                     "for Linux, so mount Drive as a folder with rclone (free) or Insync, then point Harry Spotter\n"
                     "at it. Your Google password goes only to Google — Harry Spotter never sees it.")
        else:
            intro = ("Harry Spotter reads beamtime data straight from your Google Drive. Sign in once with\n"
                     f"Google Drive for Desktop and your visit folders appear on this {COMPUTER} like any other\n"
                     "folder. Your Google password goes only to Google — Harry Spotter never sees it.")
        tk.Label(inner, text=intro, font=F(11), bg=T["card"], fg=T["muted"], justify="left").pack(anchor="w", pady=(4, 16))

        def choose_drive_folder():
            path = filedialog.askdirectory(parent=win, title="Choose your mounted Google Drive folder")
            if path:
                self.var_drive_source.set(os.path.abspath(path))
                self.persist_state()

        linux_steps = [
            ("install", "Install rclone (or Insync)", "rclone is free - e.g.  sudo apt install rclone", "rclone guide",
             lambda: open_url(RCLONE_DRIVE_URL)),
            ("signin", "Connect and mount your Drive",
             "rclone config  (choose Google Drive), then\nrclone mount gdrive: ~/GoogleDrive --daemon",
             "Choose folder…", choose_drive_folder),
        ]
        steps = linux_steps if IS_LINUX else [
            ("install", "Install Google Drive for Desktop", "Free download from Google.",
             "Download", lambda: open_url(DRIVE_DOWNLOAD_URL)),
            ("signin", "Sign in with your Google account", "Opens Google Drive, which signs you in via your browser.",
             "Open Google Drive", open_google_drive_app),
        ]
        steps += [
            ("shortcut", "Add the beamtime folder to My Drive",
             "If the visit folder was shared with you: on drive.google.com right-click it →\n"
             "Organise → Add shortcut to Drive.", "Open drive.google.com", lambda: open_url(DRIVE_WEB_URL)),
        ]
        step_dots = {}
        for i, (key, title, desc, btn_text, cmd) in enumerate(steps, 1):
            row = tk.Frame(inner, bg=T["card"])
            row.pack(fill="x", pady=6)
            dot = tk.Label(row, text=str(i), font=F(12, "bold"), bg=T["seg_bg"], fg=T["muted"], width=3, pady=4)
            dot.pack(side="left", anchor="n")
            txt = tk.Frame(row, bg=T["card"])
            txt.pack(side="left", padx=12, fill="x", expand=True)
            tk.Label(txt, text=title, font=F(12, "bold"), bg=T["card"], fg=T["text"]).pack(anchor="w")
            tk.Label(txt, text=desc, font=F(10), bg=T["card"], fg=T["muted"], justify="left").pack(anchor="w")
            FlatButton(row, btn_text, cmd, style="drive" if i < 3 else "ghost", size=10, padx=10,
                       pady=4).pack(side="right", anchor="n")
            step_dots[key] = dot

        status = tk.Label(inner, font=F(11, "bold"), bg=T["accent_soft"], fg=T["accent"], padx=12, pady=8, anchor="w")
        status.pack(fill="x", pady=(14, 10))

        bottom = tk.Frame(inner, bg=T["card"])
        bottom.pack(fill="x")
        dont_show = tk.BooleanVar(value=False)
        if auto:
            tk.Checkbutton(bottom, text="Don't show this again", variable=dont_show, bg=T["card"], fg=T["text"],
                           font=F(10)).pack(side="left")

        def close():
            if dont_show.get():
                cfg = load_config()
                cfg["drive_setup_dismissed"] = True
                save_config(cfg)
                self.app_config = cfg
            win.destroy()
        done_btn = FlatButton(bottom, "Done", close, style="primary", size=11)
        done_btn.pack(side="right")
        FlatButton(bottom, "Skip for now", close, style="secondary", size=11).pack(side="right", padx=(0, 8))
        win.protocol("WM_DELETE_WINDOW", close)

        def mark(key, ok):
            step_dots[key].config(text="✓" if ok else str(list(step_dots).index(key) + 1),
                                  bg=T["good"] if ok else T["seg_bg"], fg="white" if ok else T["muted"])

        def poll():
            if not win.winfo_exists():
                return
            mount = find_google_drive_mount()
            chosen = self.var_drive_source.get().strip()
            if not mount and IS_LINUX and os.path.isdir(chosen) and _listdir_safe(chosen):
                mount = chosen
            mark("install", drive_app_installed() or bool(mount))
            mark("signin", bool(mount))
            if mount:
                account = drive_account_name(mount)
                status.config(text=f"✓  Connected{' as ' + account if account else ''} — you're all set.",
                              bg="#e8f6ec", fg=T["good"])
                done_btn.set_enabled(True)
                if not os.path.isdir(self.var_drive_source.get().strip()):
                    self.var_drive_source.set(mount)
                    self.persist_state()
            else:
                status.config(text="⏳  Waiting for Google Drive to finish signing in…", bg=T["accent_soft"],
                              fg=T["accent"])
                done_btn.set_enabled(False)
            win.after(2000, poll)
        poll()

    # ----------------------------------------------------------------
    # PERSISTENCE
    # ----------------------------------------------------------------
    def persist_state(self):
        try:
            cfg = load_config()
            cfg.setdefault("projects", {})
            cfg["projects"][self.working_dir] = {
                "model": self.var_model.get().strip(),
                "mtz_dir": self.var_mtz.get().strip(),
                "apo_mtz": self.var_apo_mtz.get().strip(),
                "out_dir": self.var_out.get().strip(),
                "dimple_exe": self.var_dimple.get().strip(),
                "phenix_exe": self.var_phenix.get().strip(),
                "coot_exe": self.var_coot.get().strip(),
                "pymol_exe": self.var_pymol.get().strip(),
                "residue": self.var_residue.get().strip(),
                "chain": self.var_chain.get().strip(),
                "log_height": getattr(self, "log_height", 320),
                "contour": self.var_contour.get().strip(),
                "drive_source": self.var_drive_source.get().strip(),
                "visit": self.var_visit.get().strip(),
                "visit_dir": self.visit_dir_cache,
                "autosync": bool(self.var_autosync.get()),
                "mode": self.var_mode.get(),
                "ui_collapsed": self.ui_collapsed,
            }
            cfg["last_working_dir"] = self.working_dir
            cfg["last_prefix"] = self.prefix
            save_config(cfg)
            self.app_config = cfg
        except Exception:
            pass

    # ----------------------------------------------------------------
    # GOOGLE DRIVE SYNC
    #
    # Google Drive for Desktop mirrors the user's Drive to a normal local
    # folder (~/Library/CloudStorage/GoogleDrive-*), so no browser download
    # step is needed at all. This just needs to notice new .mtz files that
    # have appeared there and copy them into the pipeline's Target MTZ
    # Directory - one click, or automatic on launch via "Auto-sync".
    # ----------------------------------------------------------------
    def update_dataset_count(self):
        mtz_dir = self.var_mtz.get().strip()
        try:
            count = len(glob.glob(os.path.join(mtz_dir, "*.mtz")))
            self.var_dataset_count.set(f"{count} dataset{'s' if count != 1 else ''} ready")
        except Exception:
            self.var_dataset_count.set("")
        self.schedule_refresh()

    def open_in_finder(self, path):
        if not path:
            return
        try:
            if not os.path.exists(path):
                os.makedirs(path, exist_ok=True)
            if self.is_windows:
                subprocess.run(["explorer", path])
            elif IS_MAC:
                subprocess.run(["open", path])
            else:
                subprocess.Popen(["xdg-open", path])
        except Exception as e:
            messagebox.showerror("Error", f"Could not open folder:\n{e}")

    def start_drive_sync(self, silent=False):
        drive_dir = self.var_drive_source.get().strip()
        if not drive_dir or not os.path.isdir(drive_dir):
            if not silent:
                messagebox.showwarning(
                    "Google Drive Not Found",
                    "Set a valid Google Drive Source Folder first.\n\n" + (
                    "On Linux, mount your Google Drive as a folder (e.g. with rclone or Insync), then choose "
                    "that folder under Data → Folders → Google Drive folder." if IS_LINUX else
                    "If Google Drive for Desktop isn't installed and signed in yet, "
                    "install it from Google and sign in - your Drive files then "
                    "appear on this computer as a normal folder, with no manual downloading required.")
                )
            return

        visit = self.var_visit.get().strip()
        if not visit:
            if not silent:
                messagebox.showwarning("MX Visit Needed",
                                       "Enter the MX visit number (e.g. mx12345-1) so the app knows "
                                       "which visit's stills_processing folder to pull data from.")
            return

        target_dir = self.var_mtz.get().strip()
        if not target_dir:
            return
        try:
            os.makedirs(target_dir, exist_ok=True)
        except Exception as e:
            if not silent:
                messagebox.showerror("Error", f"Cannot create target MTZ directory: {e}")
            return

        self.btn_sync.set_enabled(False, "⏳  Syncing…")
        threading.Thread(target=self.run_drive_sync_logic, args=(drive_dir, visit, target_dir, silent), daemon=True).start()

    def run_drive_sync_logic(self, drive_dir, visit, target_dir, silent):
        copied = 0
        skipped = 0
        error = None
        reference_updates = []
        try:
            # Reuse the last resolved location for this visit if it's still
            # there; otherwise search the Drive for it (can take a while).
            visit_dir = self.visit_dir_cache
            if not (visit_dir and os.path.basename(os.path.normpath(visit_dir)).lower() == visit.lower()
                    and os.path.isdir(visit_dir)):
                self.log(f"🔎 Looking for visit {visit} in Google Drive...")
                visit_dir = find_visit_dir(drive_dir, visit)
            if not visit_dir:
                error = f"Could not find the visit folder '{visit}' in Google Drive."
                self.log(f"❌ Could not find visit folder '{visit}' under {drive_dir} "
                         f"(or in folders shared with you). Check the visit number, or point "
                         f"Google Drive Source at the folder containing it.")
                looks = visit_lookalikes(drive_dir, visit)
                if looks:
                    self.log("  Found these with that name, but couldn't open them as the visit folder: "
                             + "; ".join(looks))
                self.log(f"  Searched: {drive_dir} (3 levels down)"
                         + "".join(f"; {r}.shortcut-targets-by-id; {r}Shared drives"
                                   if r.endswith(os.sep) else f"; {os.path.join(r, '.shortcut-targets-by-id')}"
                                   for r in google_drive_roots()))
                return
            self.visit_dir_cache = visit_dir

            self.log(f"🔄 Scanning {visit}/stills_processing for new data: {visit_dir}")
            found_mtz = collect_visit_mtz_files(visit_dir, self.log)
            self.log(f"  Found {len(found_mtz)} dataset(s) (latest vNNN _all.mtz for each even/odd).")

            # Remembers which local file came from which dataset folder, so a
            # newer vNNN replaces the old copy even if its filename differs.
            manifest_path = os.path.join(target_dir, SYNC_MANIFEST)
            try:
                with open(manifest_path) as f:
                    manifest = json.load(f)
            except Exception:
                manifest = {}

            download_failed = False
            for src, dest_name, key in found_mtz:
                dest = os.path.join(target_dir, dest_name)
                old_name = manifest.get(key)
                if old_name and old_name != dest_name and os.path.exists(os.path.join(target_dir, old_name)):
                    try:
                        os.remove(os.path.join(target_dir, old_name))
                        self.log(f"  - Removed older version {old_name}")
                    except OSError as e:
                        self.log(f"  ! Could not remove older version {old_name}: {e}")
                try:
                    # A newer vNNN has the same dest name, so compare size and
                    # mtime (copy2 preserves mtime) to catch replacements.
                    if (os.path.exists(dest) and os.path.getsize(dest) == os.path.getsize(src)
                            and int(os.path.getmtime(dest)) == int(os.path.getmtime(src))):
                        skipped += 1
                        continue
                    updating = os.path.exists(dest)
                    copy_complete(src, dest)
                    manifest[key] = dest_name
                    copied += 1
                    rel = os.path.relpath(src, os.path.join(visit_dir, "stills_processing"))
                    self.log(f"  {'↻ Updated' if updating else '+ Copied'} {dest_name}  ←  {rel}")
                except Exception as e:
                    self.log(f"  ! Skipped {dest_name}: {e}")
                    download_failed = True
            if download_failed:
                self.log(DRIVE_DOWNLOAD_HINT)
            for _src, dest_name, key in found_mtz:
                if os.path.exists(os.path.join(target_dir, dest_name)):
                    manifest[key] = dest_name
            try:
                with open(manifest_path, "w") as f:
                    json.dump(manifest, f, indent=1)
            except OSError:
                pass

            # Per-visit reference files live in the top of the visit folder
            # (e.g. kpc2_rt_esrf.pdb, KPC2_apo_ground_state.mtz). When present
            # they're copied into input/ and become the Reference PDB / Apo
            # MTZ, so each visit is processed against its own references.
            input_dir = os.path.join(self.working_dir, "input")
            ref_pdb, ref_apo = find_visit_reference_files(visit_dir)
            for src, label, var in ((ref_pdb, "reference model", self.var_model),
                                    (ref_apo, "apo ground-state MTZ", self.var_apo_mtz)):
                if not src:
                    self.log(f"  (No {label} in the visit folder - keeping {os.path.basename(var.get().strip()) or 'current setting'})")
                    continue
                dest = os.path.join(input_dir, os.path.basename(src))
                try:
                    os.makedirs(input_dir, exist_ok=True)
                    if not (os.path.exists(dest) and os.path.getsize(dest) == os.path.getsize(src)
                            and int(os.path.getmtime(dest)) == int(os.path.getmtime(src))):
                        copy_complete(src, dest)
                        copied += 1
                        self.log(f"  + Copied visit {label}: {os.path.basename(src)}")
                    reference_updates.append((var, dest, label))
                except Exception as e:
                    self.log(f"  ! Could not copy visit {label} {os.path.basename(src)}: {e}")
                    self.log(DRIVE_DOWNLOAD_HINT)

            self.log(f"✅ Drive sync complete: {copied} new/updated file(s) copied, {skipped} already up to date.")
        except Exception as e:
            error = str(e)
            self.log(f"Drive sync error: {e}")
        finally:
            self.root.after(0, lambda: self.on_drive_sync_done(copied, silent, error, reference_updates))

    def on_drive_sync_done(self, copied, silent, error=None, reference_updates=()):
        # Tk variables must be set on the main thread, hence done here.
        for var, path, label in reference_updates:
            if var.get().strip() != path:
                var.set(path)
                self.log(f"  → Now using visit {label}: {os.path.basename(path)}")
        self.btn_sync.set_enabled(True, "⟳  Sync now")
        self.update_dataset_count()
        if not silent and error:
            messagebox.showerror("Drive Sync", error)
        elif not silent and copied == 0:
            messagebox.showinfo("Drive Sync", "No new files found - everything is already up to date.")
        self.persist_state()

    def set_gui_state(self, is_running):
        if is_running:
            self.btn_run.set_enabled(False, "⏳  Running… please wait")
            self.btn_load.set_enabled(False)
            self.btn_view.set_enabled(False)
        else:
            self.btn_run.set_enabled(True, "▶  Run pipeline")
            self.btn_load.set_enabled(True)
            self.btn_view.set_enabled(bool(self.processed_datasets))

    def browse(self, string_var, is_dir, append_results=False):
        current_val = string_var.get().strip()
        start_dir = self.working_dir
        if current_val and os.path.exists(current_val):
            start_dir = os.path.dirname(current_val) if not os.path.isdir(current_val) else current_val

        if is_dir:
            path = filedialog.askdirectory(parent=self.root, initialdir=start_dir)
        else:
            path = filedialog.askopenfilename(parent=self.root, initialdir=start_dir)
            
        if path:
            abs_path = os.path.abspath(path)
            if append_results:
                if os.path.basename(abs_path) != self.out_folder_name:
                    abs_path = os.path.join(abs_path, self.out_folder_name)
            string_var.set(abs_path)
            self.update_dataset_count()
            self.persist_state()

    def log(self, message):
        timestamp = datetime.datetime.now().strftime("%H:%M:%S")
        msg = f"[{timestamp}] {message}\n"
        self.root.after(0, self._append_log, msg)
        try:
            log_file = os.path.join(self.var_out.get(), "pipeline_run.log")
            with open(log_file, "a", encoding="utf-8") as f: f.write(msg)
        except: pass

    def _append_log(self, msg):
        if any(k in msg for k in ("❌", "Error", "CRITICAL", "error:", "Phenix says")):
            tag = "err"
        elif any(k in msg for k in ("✅", "+ Copied", "↻ Updated", "→ Now using")):
            tag = "ok"
        elif any(k in msg for k in (" ! ", "⚠", "Skipped", "(No ")):
            tag = "warn"
        elif any(k in msg for k in ("===", ">>>", "🔄", "🔎")):
            tag = "head"
        else:
            tag = None
        self.console.insert(tk.END, msg, tag)
        self.console.see(tk.END)
        if tag == "err" and self.log_collapsed:
            self.toggle_log(False)  # never hide a problem

    def get_target_coords(self, pdb_path, target_res, target_chain="A"):
        best_coords = None
        try:
            with open(pdb_path, 'r') as f:
                for line in f:
                    if line.startswith("ATOM") or line.startswith("HETATM"):
                        if len(line) < 54: continue
                        if line[16] not in [' ', 'A']: continue
                        chain, res_num, atom_name = line[21], line[22:26].strip(), line[12:16].strip()
                        if chain == target_chain and str(res_num) == str(target_res):
                            coords = (float(line[30:38]), float(line[38:46]), float(line[46:54]))
                            if atom_name == 'CA': return coords
                            if not best_coords: best_coords = coords
        except: pass
        return best_coords

    def open_results(self):
        if self.processed_datasets:
            self.show_results_window(self.processed_datasets)

    def load_previous_run(self):
        out_dir = filedialog.askdirectory(parent=self.root, title="Select Previous Output Directory", initialdir=self.working_dir)
        if not out_dir: return

        expected_folder = f"{self.prefix}_results" if self.prefix else "results"
        if os.path.basename(out_dir) != expected_folder and os.path.exists(os.path.join(out_dir, expected_folder)):
            out_dir = os.path.join(out_dir, expected_folder)
        elif os.path.basename(out_dir) != "results" and os.path.exists(os.path.join(out_dir, "results")):
            out_dir = os.path.join(out_dir, "results")

        run_dirs = glob.glob(os.path.join(out_dir, "dimple_*")) + glob.glob(os.path.join(out_dir, "phenix_*"))
        if not run_dirs:
            messagebox.showinfo("No Results", f"No runs found in:\n{out_dir}")
            return

        self.processed_datasets = []
        self.radio_vars.clear()

        no_map = []
        for d_dir in run_dirs:
            if not os.path.isdir(d_dir): continue
            
            base_name = os.path.basename(d_dir).replace("dimple_", "").replace("phenix_", "")
            if not (os.path.exists(os.path.join(d_dir, "final.mtz")) and os.path.exists(os.path.join(d_dir, "final.pdb"))):
                no_map.append(base_name)   # Phenix/Dimple failed for this one: nothing to show or open
                continue
            
            # --- FIXED: Corrected the filename search to successfully find "_spin.gif" instead of ".gif" ---
            gif_path = os.path.join(out_dir, f"{base_name}_spin.gif")
            
            self.processed_datasets.append({
                "base_name": base_name,
                "pdb": os.path.join(d_dir, "final.pdb"),
                "mtz": os.path.join(d_dir, "final.mtz"),
                "gif": gif_path if os.path.exists(gif_path) else None,
                "contour": self.var_contour.get()
            })
        
        self.processed_datasets.sort(key=lambda x: x["base_name"])
        if no_map:
            self.log(f"  {len(no_map)} dataset folder(s) have no map (Phenix/Dimple failed for them, "
                     f"e.g. non-isomorphous) and are not shown: " + ", ".join(sorted(no_map)))
        if not self.processed_datasets:
            messagebox.showinfo("No Results", f"No completed datasets found in:\n{out_dir}")
            return
        self.var_out.set(out_dir)
        self.log(f"📂 Successfully loaded {len(self.processed_datasets)} datasets from {os.path.basename(out_dir)}.")
        
        self.set_gui_state(False)
        self.open_results()

    def start_pipeline(self):
        self.refresh_status()
        if self.current_issues:
            messagebox.showwarning("Not ready yet", "Fix these before running:\n\n• " + "\n• ".join(self.current_issues))
            return
        self.run_strategy = self.var_mode.get()

        self.persist_state()
        self.set_gui_state(True)
        self.processed_datasets = []
        self.radio_vars.clear()
        
        if not os.path.exists(self.var_out.get()):
            try: os.makedirs(self.var_out.get())
            except Exception as e:
                messagebox.showerror("Error", f"Cannot create output directory: {e}")
                self.set_gui_state(False)
                return

        threading.Thread(target=self.run_pipeline_logic, daemon=True).start()

    def run_pipeline_logic(self):
        try:
            self.log("=== PIPELINE INITIATED ===")
            
            strategy = self.run_strategy
            
            abs_model = self.var_model.get().strip()
            abs_mtz_dir = self.var_mtz.get().strip()
            abs_out_dir = self.var_out.get().strip()
            target_res = self.var_residue.get().strip()
            target_chain = self.var_chain.get().strip() or "A"
            coot_exe = self.var_coot.get().strip()
            contour_val = self.var_contour.get().strip()

            if not os.path.exists(abs_model):
                raise FileNotFoundError(f"Reference PDB '{abs_model}' not found!")

            mtz_files = glob.glob(os.path.join(abs_mtz_dir, "*.mtz"))
            if not mtz_files:
                raise FileNotFoundError(f"No .mtz files found in '{abs_mtz_dir}'!")

            local_processed_datasets = []
            
            # ==========================================
            # PHASE 1: COMPUTE
            # ==========================================
            if strategy == "phenix":
                self.log("\n>>> PHASE 1: PHENIX Fo-Fo MAP GENERATION <<<")
                abs_apo_mtz = self.var_apo_mtz.get().strip()
                phenix_exe = self.var_phenix.get().strip()
                
                if phenix_exe.endswith("/phenix") or phenix_exe.endswith("\\phenix") or phenix_exe.endswith("phenix.exe") or phenix_exe.endswith("phenix.bat"):
                    self.log("Auto-correcting Phenix executable path to map generation tool...")
                    phenix_exe = phenix_exe.replace("phenix.exe", "phenix.fobs_minus_fobs_map.bat")\
                                           .replace("phenix.bat", "phenix.fobs_minus_fobs_map.bat")\
                                           .replace("phenix", "phenix.fobs_minus_fobs_map")
                
                if not os.path.exists(abs_apo_mtz):
                    raise FileNotFoundError(f"Apo MTZ '{abs_apo_mtz}' not found!")
                    
                for mtz in mtz_files:
                    base_name = os.path.basename(mtz).replace(".mtz", "")
                    phenix_out = os.path.join(abs_out_dir, f"phenix_{base_name}")
                    os.makedirs(phenix_out, exist_ok=True)
                    phenix_log = os.path.join(phenix_out, f"phenix_{base_name}.log")
                    
                    self.log(f"Processing {base_name}...")
                    
                    # Fobs1=Target, Fobs2=Apo for standard target-apo subtraction
                    label_1 = choose_fobs_label(mtz)
                    label_2 = choose_fobs_label(abs_apo_mtz)
                    cmd = (f'"{phenix_exe}" f_obs_1_file_name="{mtz}" f_obs_2_file_name="{abs_apo_mtz}" '
                           + (f'f_obs_1_label="{label_1}" ' if label_1 else '')
                           + (f'f_obs_2_label="{label_2}" ' if label_2 else '')
                           + f'phase_source="{abs_model}" '
                           f'ignore_non_isomorphous_unit_cells=False')
                    
                    with open(phenix_log, "w") as p_log:
                        if self.is_windows:
                            subprocess.run(cmd, stdout=p_log, stderr=subprocess.STDOUT, shell=True, cwd=phenix_out, **NO_WINDOW)
                        else:
                            mac_cmd = f'{cmd}'
                            subprocess.run(LOGIN_SHELL + [mac_cmd], stdout=p_log, stderr=subprocess.STDOUT, cwd=phenix_out)
                            
                    raw_mtz_1 = os.path.join(phenix_out, "FoFoPHFc.mtz")
                    raw_mtz_2 = os.path.join(phenix_out, "fobs_minus_fobs_map.mtz")
                    
                    raw_mtz = raw_mtz_1 if os.path.exists(raw_mtz_1) else (raw_mtz_2 if os.path.exists(raw_mtz_2) else None)
                    abs_final_mtz = os.path.join(phenix_out, "final.mtz")
                    abs_final_pdb = os.path.join(phenix_out, "final.pdb")
                    
                    success = False
                        
                    if raw_mtz:
                        shutil.copy(raw_mtz, abs_final_mtz)
                        
                        if os.path.exists(abs_final_mtz):
                            success = True
                            shutil.copy(abs_model, abs_final_pdb) 
                        
                    if success:
                        local_processed_datasets.append({
                            "base_name": base_name, 
                            "pdb": abs_final_pdb, 
                            "mtz": abs_final_mtz, 
                            "png_prefix": os.path.join(abs_out_dir, f"{base_name}_spin"),
                            "contour": contour_val
                        })
                    else:
                        self.log(f"  Error: Phenix failed to output the difference map for {base_name}.")
                        try:
                            with open(phenix_log) as p_log:
                                reasons = [l.strip() for l in p_log if l.startswith(("Sorry", "Error", "Traceback"))]
                            if reasons:
                                self.log(f"    Phenix says: {reasons[-1]}")
                        except OSError:
                            pass

            else:
                self.log("\n>>> PHASE 1: APO DIMPLE REFINEMENT <<<")
                dimple_exe = self.var_dimple.get().strip()
                ccp4_setup_path = ""
                if not self.is_windows:
                    potential_setups = ccp4_setup_scripts(self.var_dimple.get().strip())
                    if potential_setups: ccp4_setup_path = potential_setups[0]
                
                for mtz in mtz_files:
                    base_name = os.path.basename(mtz).replace(".mtz", "")
                    dimple_out = os.path.join(abs_out_dir, f"dimple_{base_name}")
                    dimple_log = os.path.join(abs_out_dir, f"dimple_{base_name}.log")
                    self.log(f"Processing {base_name}...")
                    
                    with open(dimple_log, "w") as d_log:
                        if self.is_windows:
                            win_cmd = f'"{dimple_exe}" "{mtz}" "{abs_model}" "{dimple_out}"'
                            subprocess.run(win_cmd, stdout=d_log, stderr=subprocess.STDOUT, shell=True, **NO_WINDOW)
                        else:
                            source_cmd = f"source '{ccp4_setup_path}' >/dev/null 2>&1; " if ccp4_setup_path else ""
                            mac_cmd = f"{source_cmd}'{dimple_exe}' '{mtz}' '{abs_model}' '{dimple_out}'"
                            subprocess.run(LOGIN_SHELL + [mac_cmd], stdout=d_log, stderr=subprocess.STDOUT)
                    
                    abs_final_pdb = os.path.join(dimple_out, "final.pdb")
                    abs_final_mtz = os.path.join(dimple_out, "final.mtz")
                    
                    if os.path.exists(abs_final_pdb):
                        local_processed_datasets.append({
                            "base_name": base_name, 
                            "pdb": abs_final_pdb, 
                            "mtz": abs_final_mtz, 
                            "png_prefix": os.path.join(abs_out_dir, f"{base_name}_spin"),
                            "contour": contour_val
                        })
                    else:
                        self.log(f"  Error: Dimple failed to produce final.pdb for {base_name}.")

            if not local_processed_datasets:
                raise Exception("No datasets successfully processed in Phase 1!")

            # ==========================================
            # PHASE 2: SEQUENTIAL RENDERING (Coot)
            # ==========================================
            self.log("\n>>> PHASE 2: GRAPHICAL RENDERING (360° SPIN) <<<")
            
            is_fofo_str = "True" if strategy == "phenix" else "False"
            
            for d in local_processed_datasets:
                coot_log = os.path.join(abs_out_dir, f"coot_{d['base_name']}.log")
                self.log(f"Rendering {d['base_name']}...")
                
                coords = self.get_target_coords(d['pdb'], target_res, target_chain)
                cx, cy, cz = coords if coords else (0, 0, 0)
                coords_flag = "True" if coords else "False"

                safe_pdb = d['pdb'].replace('\\', '/')
                safe_mtz = d['mtz'].replace('\\', '/')
                safe_png_prefix = d['png_prefix'].replace('\\', '/')

                coot_script = f"""
from coot import *
import time
import math

try:
    set_smooth_scroll_flag(0)
    set_smooth_scroll_steps(0)
    set_smooth_scroll_limit(0.0)
except: pass

try: set_draw_go_to_atom_path(0)
except: pass
try: set_draw_crosshairs(0)
except: pass
try: set_show_environment_distances(0)
except: pass
try: set_environment_distances_distance_limits(0.0, 0.01)
except: pass

try: set_background_colour(0.0, 0.0, 0.0)
except: pass

def flush_graphics():
    # GTK 3 Coot only. Deliberately not re-entering the GLib main loop here:
    # this script runs inside it, and re-entering crashes Coot 1.x. Frame
    # capture below is scheduled on the main loop instead.
    try:
        from gi.repository import Gtk
        while Gtk.events_pending(): Gtk.main_iteration()
    except Exception:
        pass

try:
    imol_pdb = read_pdb(r'{safe_pdb}')
    map_imol = -1
    is_fofo_map = {is_fofo_str}
    
    if is_fofo_map:
        try:
            map_imol = make_and_draw_map(r'{safe_mtz}', "FoFo", "PHFc", "", 0, 1)
        except Exception as e:
            print("make_and_draw_map with FoFo/PHFc failed:", e)
            map_imol = -1
        
        if map_imol is None or map_imol < 0:
            for f_col, phi_col in [("F_OBS_MINUS_F_OBS", "PHIF_OBS_MINUS_F_OBS"), ("DELFWT", "PHDELWT")]:
                try:
                    map_imol = make_and_draw_map(r'{safe_mtz}', f_col, phi_col, "", 0, 1)
                    if map_imol is not None and map_imol >= 0: break
                except: pass
    else:
        res = auto_read_make_and_draw_maps(r'{safe_mtz}')
        
        if isinstance(res, list) and len(res) > 0: map_imol = res[0]
        elif isinstance(res, int) and res >= 0: map_imol = res
        elif res is not None:
            try: map_imol = list(res)[0]
            except: pass
        
    flush_graphics()
    
    if map_imol is None or map_imol < 0:
        try:
            all_imols = molecule_number_list()
            for i in all_imols:
                if i != imol_pdb:
                    map_imol = i
                    break
        except: pass

    if map_imol is not None and map_imol >= 0:
        try: set_contour_level_in_sigma(map_imol, {contour_val})
        except Exception as e: print("Failed to set difference map contour:", e)

    try: add_atom_label(imol_pdb, "{target_chain}", {target_res}, "", " CA ")
    except: pass
    
    target_x, target_y, target_z = {cx}, {cy}, {cz}
    
    if {coords_flag} and map_imol is not None and map_imol >= 0:
        try:
            peaks = []
            try: peaks = map_peaks(map_imol, {contour_val})
            except:
                try: peaks = find_peaks(map_imol, {contour_val})
                except: pass
                
            best_peak, min_dist = None, 8.0 
            for p in peaks:
                try: px, py, pz = p[0], p[1], p[2]
                except: px, py, pz = p.x, p.y, p.z
                dist = ((px - {cx})**2 + (py - {cy})**2 + (pz - {cz})**2)**0.5
                if dist < min_dist:
                    min_dist, best_peak = dist, (px, py, pz)
                    
            if best_peak:
                target_x, target_y, target_z = best_peak[0], best_peak[1], best_peak[2]
        except: pass
    
    set_rotation_centre(target_x, target_y, target_z)
    
    try: set_map_radius(20.0)
    except: pass
    
    try: set_view_quaternion(0.0, 0.0, 0.0, 1.0)
    except: pass
    set_zoom(20) 
    set_draw_axes(0)
    
    SETUP_OK = True
except Exception as e: 
    SETUP_OK = False
    print("CRITICAL COOT SCRIPT ERROR:", e)
    import traceback
    traceback.print_exc()

# 24 frames of 15 degrees = smooth 360 degree GIF rotation.
# Frames are captured from Coot's own event loop: set the view, give the main
# loop time to actually draw it, then take the screenshot. (time.sleep() here
# would freeze drawing, which gives black or garbage frames on some systems.)
N_FRAMES = 24
WARMUP_MS = 1000    # let Coot show its window and draw the maps once
FRAME_MS = 80       # per frame: time to redraw before the screenshot
                    # (screenshots take ~10 ms; HS_TIMING lines in the Coot log show the real cost)
frame_no = [0]
T_START = time.time()
import sys
print("HS_TIMING script started")
sys.stdout.flush()

def set_frame_view(i):
    angle = math.radians(i * 15)
    try: set_view_quaternion(0.0, math.sin(angle / 2.0), 0.0, math.cos(angle / 2.0))
    except: pass
    try: graphics_draw()
    except: pass

def capture_frame():
    try:
        i = frame_no[0]
        frame_path = r'{safe_png_prefix}' + "_%d.png" % i
        t_shot = time.time()
        try: screendump_image(frame_path)
        except Exception as e: print("Screendump failed:", e)
        print("HS_TIMING frame %d: screenshot %.0f ms, %.1f s since script start"
              % (i, (time.time() - t_shot) * 1000, time.time() - T_START))
        sys.stdout.flush()
        frame_no[0] = i + 1
        if frame_no[0] >= N_FRAMES:
            coot_real_exit(0)
            return False
        set_frame_view(frame_no[0])
        return True           # run again after FRAME_MS
    except Exception as e:
        print("CAPTURE ERROR:", e)
        coot_real_exit(0)
        return False

def start_capture():
    GLib.timeout_add(FRAME_MS, capture_frame)
    return False

if not SETUP_OK:
    coot_real_exit(0)
else:
    try:
        from gi.repository import GLib
        set_frame_view(0)
        GLib.timeout_add(WARMUP_MS, start_capture)
        GLib.timeout_add_seconds(180, lambda: coot_real_exit(0))   # never hang the pipeline
    except ImportError:
        # No GLib bindings: fall back to the old sequential capture.
        for _ in range(20):
            flush_graphics()
            time.sleep(0.1)
        for i in range(N_FRAMES):
            set_frame_view(i)
            for _ in range(5):
                flush_graphics()
                time.sleep(0.08)
            frame_path = r'{safe_png_prefix}' + "_%d.png" % i
            try: screendump_image(frame_path)
            except Exception as e: print("Screendump failed:", e)
        coot_real_exit(0)
"""
                temp_py = os.path.join(abs_out_dir, "temp_render.py")
                with open(temp_py, "w") as f:
                    f.write(coot_script)
                    
                timed_out = False
                started = time.time()
                with open(coot_log, "w") as c_log:
                    if self.is_windows:
                        win_cmd = f'"{coot_exe}" --no-state-script --script "{temp_py}"'
                        proc = subprocess.Popen(win_cmd, stdout=c_log, stderr=subprocess.STDOUT, shell=True,
                                                env=coot_env(), **NO_WINDOW)
                    else:
                        ccp4_setup_path = ""
                        potential_setups = ccp4_setup_scripts(self.var_dimple.get().strip())
                        if potential_setups: ccp4_setup_path = potential_setups[0]
                        source_cmd = f"source '{ccp4_setup_path}' >/dev/null 2>&1; " if ccp4_setup_path else ""
                        mac_cmd = f"{source_cmd}'{coot_exe}' --no-state-script --script '{temp_py}'"
                        proc = subprocess.Popen(LOGIN_SHELL + [mac_cmd], stdout=c_log,
                                                stderr=subprocess.STDOUT, start_new_session=True)
                    # Coot's own script can't enforce a time limit if Coot never gets far
                    # enough to run it (e.g. no OpenGL), so the app enforces one.
                    try:
                        proc.wait(timeout=COOT_RENDER_TIMEOUT)
                    except subprocess.TimeoutExpired:
                        timed_out = True
                        kill_process_tree(proc)

                if os.path.exists(temp_py): os.remove(temp_py)

                gl_problem = coot_opengl_failed(coot_log)
                if (not gl_problem and not timed_out and time.time() - started < 20
                        and not glob.glob(d['png_prefix'] + "_*")):
                    gl_problem = "Coot closed within seconds of starting, without drawing anything"
                if gl_problem == "Vulkan graphics failed to start" and glob.glob(d['png_prefix'] + "_*"):
                    gl_problem = None  # just a warning: Coot fell back and still rendered
                if timed_out:
                    self.log(f"  ⚠ Coot didn't finish within {COOT_RENDER_TIMEOUT // 60} minutes, so it was closed.")
                if gl_problem:
                    self.log(f"  ❌ Coot couldn't render on this computer ({gl_problem}), so no spin GIFs can be made "
                             f"here. This is usually a graphics (OpenGL) problem, common in virtual machines. "
                             f"The difference maps are still in the results folder - review them in the Results "
                             f"window with Open in Coot on a computer with working graphics, or set the Coot "
                             f"path to a Coot that can draw here (e.g. WinCoot 0.9).")
                    self.log("  Skipping the remaining renders.")
                    for rest in local_processed_datasets[local_processed_datasets.index(d):]:
                        rest.setdefault('gif', None)
                    break

                # Assembly Phase: Combine 24 Coot frames into a single smooth animated GIF
                frames, frame_files, blank = [], [], 0
                for i in range(24):
                    tga_path = d['png_prefix'] + f"_{i}.png.tga"
                    png_path = d['png_prefix'] + f"_{i}.png"

                    actual_path = tga_path if os.path.exists(tga_path) else (png_path if os.path.exists(png_path) else None)

                    if actual_path:
                        try:
                            img = Image.open(actual_path)
                            frame = img.convert("RGB")
                            img.close()
                            frame_files.append(actual_path)
                            if frame.convert("L").getextrema()[1] < 12:
                                blank += 1  # all black: Coot hadn't drawn anything
                            else:
                                frames.append(frame)
                        except: pass

                if blank or len(frame_files) < 24:
                    # Keep the raw frames and say so, rather than silently making a bad GIF.
                    keep_dir = os.path.join(abs_out_dir, f"coot_frames_{d['base_name']}")
                    os.makedirs(keep_dir, exist_ok=True)
                    for fpath in frame_files:
                        shutil.move(fpath, os.path.join(keep_dir, os.path.basename(fpath)))
                    self.log(f"  ⚠ {len(frame_files)} of 24 frames captured, {blank} blank for {d['base_name']}. "
                             f"Raw frames kept in {os.path.basename(keep_dir)}/ - see coot_{d['base_name']}.log")
                else:
                    for fpath in frame_files:
                        try: os.remove(fpath)
                        except OSError: pass

                if frames:
                    gif_path = d['png_prefix'] + ".gif"
                    frames[0].save(gif_path, save_all=True, append_images=frames[1:], duration=250, loop=0)
                    d['gif'] = gif_path
                else:
                    d['gif'] = None

            self.processed_datasets = local_processed_datasets
            self.log("\n✅ PIPELINE COMPLETE! Opening results window...")
            self.root.after(0, self.on_pipeline_complete)
            
        except Exception as e:
            self.log(f"CRITICAL PIPELINE FAILURE: {e}")
            self.root.after(0, self.on_pipeline_failed)

    def on_pipeline_complete(self):
        self.set_gui_state(False)
        if self.processed_datasets:
            self.open_results()

    def on_pipeline_failed(self):
        self.set_gui_state(False)

    def _on_mousewheel(self, event, canvas):
        direction = -1 if event.delta > 0 else 1
        if sys.platform == "darwin":
            canvas.yview_scroll(direction, "units")
        elif event.num == 4:
            canvas.yview_scroll(-1, "units")
        elif event.num == 5:
            canvas.yview_scroll(1, "units")
        else:
            canvas.yview_scroll(direction, "units")

    def enable_wheel_scroll(self, toplevel, canvas, within=None):
        """Scroll `canvas` with a mouse wheel *and* a trackpad.

        Tk 9 (used by this build) reports two-finger trackpad scrolling as
        <TouchpadScroll>, not <MouseWheel> - which is why scrolling did
        nothing in the results window. Bound once on the toplevel, so it
        covers every widget inside it; with `within`, only scrolls while the
        pointer is over that widget (so the activity log keeps its own)."""
        canvas.configure(yscrollincrement=1)  # 1 unit = 1 pixel

        def targeted(event):
            if within is None:
                return True
            w = toplevel.winfo_containing(event.x_root, event.y_root)
            return w is not None and str(w).startswith(str(within))

        def scrollable():
            first, last = canvas.yview()
            return first > 0 or last < 1

        def on_wheel(event):
            if targeted(event) and scrollable() and event.delta:
                canvas.yview_scroll(-40 if event.delta > 0 else 40, "units")

        def on_touchpad(event):
            if not (targeted(event) and scrollable()):
                return
            try:
                _dx, dy = toplevel.tk.call("tk::PreciseScrollDeltas", event.delta)
            except tk.TclError:
                return
            if dy:
                canvas.yview_scroll(-int(dy), "units")

        toplevel.bind("<MouseWheel>", on_wheel, add="+")
        if IS_LINUX:
            # X11 reports wheel movement as button 4 (up) / 5 (down)
            def on_button(event, direction):
                if targeted(event) and scrollable():
                    canvas.yview_scroll(direction * 40, "units")
            toplevel.bind("<Button-4>", lambda e: on_button(e, -1), add="+")
            toplevel.bind("<Button-5>", lambda e: on_button(e, 1), add="+")
        try:
            toplevel.bind("<TouchpadScroll>", on_touchpad, add="+")
        except tk.TclError:
            pass  # Tk 8.6 has no separate trackpad event

    def _bind_scroll_recursive(self, widget, canvas):
        widget.bind("<MouseWheel>", lambda e: self._on_mousewheel(e, canvas))
        widget.bind("<Button-4>", lambda e: self._on_mousewheel(e, canvas))
        widget.bind("<Button-5>", lambda e: self._on_mousewheel(e, canvas))
        for child in widget.winfo_children():
            self._bind_scroll_recursive(child, canvas)

    def save_gif_copy(self, src_path, base_name):
        dest_path = filedialog.asksaveasfilename(
            parent=self.results_window,
            defaultextension=".gif",
            filetypes=[("GIF files", "*.gif")],
            initialfile=f"{base_name}.gif"
        )
        if dest_path:
            try:
                shutil.copy(src_path, dest_path)
                messagebox.showinfo("Success", f"GIF saved to:\n{dest_path}")
            except Exception as e:
                messagebox.showerror("Error", f"Could not save GIF:\n{e}")

    def open_in_pymol(self, d):
        """Open a dataset's model and maps in PyMOL, centred on the target residue."""
        pymol_exe = self.var_pymol.get().strip()
        if not tool_available(pymol_exe):
            found = self.auto_find_software("pymol")
            if tool_available(found):
                self.var_pymol.set(found)
                pymol_exe = found
                self.persist_state()
            else:
                messagebox.showinfo("PyMOL not found",
                                    "Harry Spotter couldn't find PyMOL on this computer.\n\n"
                                    "Install it from pymol.org, or if it's already installed, set its location in "
                                    "the Software card (Locate… next to PyMOL).",
                                    parent=self.results_window or self.root)
                return
        if not (os.path.exists(d['pdb']) and os.path.exists(d['mtz'])):
            messagebox.showerror("Files missing", f"Can't find this dataset's model and map files:\n"
                                                  f"{d['pdb']}\n{d['mtz']}", parent=self.results_window or self.root)
            return

        folder = os.path.dirname(d['pdb'])
        name = re.sub(r"\W", "_", d['base_name'])[:40].strip("_") or "dataset"
        if name[0].isdigit():
            name = "d_" + name
        maps, problem = make_ccp4_maps(d['mtz'], folder, name,
                                       gemmi_hints=(self.var_dimple.get().strip(), self.var_coot.get().strip()))
        script = pymol_script(d['pdb'], d['mtz'], maps, name, self.var_chain.get().strip(),
                              self.var_residue.get().strip(), d.get('contour', self.var_contour.get()) or "3.0")
        script_path = os.path.join(folder, "open_in_pymol.py")
        with open(script_path, "w", encoding="utf-8") as f:
            f.write(script)
        try:
            subprocess.Popen([pymol_exe, script_path], cwd=folder)
        except Exception as e:
            messagebox.showerror("PyMOL", f"Couldn't start PyMOL:\n{e}", parent=self.results_window or self.root)
            return
        self.log(f"🔬 Opening {d['base_name']} in PyMOL" +
                 (f" - note: {problem}; asking PyMOL to read the MTZ directly" if problem else ""))

    def open_in_coot(self, d):
        coot_exe = self.var_coot.get().strip()
        target_res = self.var_residue.get().strip()
        target_chain = self.var_chain.get().strip() or "A"
        contour_val = d.get('contour', '3.0')
        
        # Infer strategy from the output path created by the pipeline
        is_fofo_str = "True" if "phenix_" in d['pdb'].replace('\\', '/') else "False"

        safe_pdb = d['pdb'].replace('\\', '/')
        safe_mtz = d['mtz'].replace('\\', '/')
        
        # Write an interactive script to open this specific dataset seamlessly
        script_path = os.path.join(os.path.dirname(d['pdb']), "open_interactive.py")
        
        coot_script = f"""
from coot import *
import time

try: set_background_colour(0.0, 0.0, 0.0)
except: pass

try:
    imol_pdb = read_pdb(r'{safe_pdb}')
    map_imol = -1
    is_fofo_map = {is_fofo_str}
    
    if is_fofo_map:
        try:
            map_imol = make_and_draw_map(r'{safe_mtz}', "FoFo", "PHFc", "", 0, 1)
        except Exception as e:
            print("make_and_draw_map with FoFo/PHFc failed:", e)
            map_imol = -1
        
        if map_imol is None or map_imol < 0:
            for f_col, phi_col in [("F_OBS_MINUS_F_OBS", "PHIF_OBS_MINUS_F_OBS"), ("DELFWT", "PHDELWT")]:
                try:
                    map_imol = make_and_draw_map(r'{safe_mtz}', f_col, phi_col, "", 0, 1)
                    if map_imol is not None and map_imol >= 0: break
                except: pass
    else:
        res = auto_read_make_and_draw_maps(r'{safe_mtz}')
        
        if isinstance(res, list) and len(res) > 0: map_imol = res[0]
        elif isinstance(res, int) and res >= 0: map_imol = res
        elif res is not None:
            try: map_imol = list(res)[0]
            except: pass

    if map_imol is not None and map_imol >= 0:
        try: set_contour_level_in_sigma(map_imol, {contour_val})
        except Exception as e: print("Failed to set difference map contour:", e)

    if "{target_res}" != "":
        try: 
            set_go_to_atom_chain_residue_atom_name("{target_chain}", int("{target_res}"), "CA")
        except: pass
        
except Exception as e: 
    print("CRITICAL COOT SCRIPT ERROR:", e)
    import traceback
    traceback.print_exc()
"""
        with open(script_path, "w") as f:
            f.write(coot_script)
            
        # Spawn Coot as a separate, non-blocking process so the GUI remains interactive
        if self.is_windows:
            # WinCoot expects forward slashes even in command-line arguments
            safe_script_path = script_path.replace('\\', '/')
            win_cmd = f'"{coot_exe}" --script "{safe_script_path}"'
            subprocess.Popen(win_cmd, shell=True, env=coot_env())
        else:
            ccp4_setup_path = ""
            potential_setups = ccp4_setup_scripts(self.var_dimple.get().strip())
            if potential_setups: ccp4_setup_path = potential_setups[0]
            source_cmd = f"source '{ccp4_setup_path}' >/dev/null 2>&1; " if ccp4_setup_path else ""
            mac_cmd = f"{source_cmd}'{coot_exe}' --script '{script_path}'"
            subprocess.Popen(LOGIN_SHELL + [mac_cmd])

    ASSESSMENTS = {
        # value: (button text, colour key, soft background)
        "Ligand present": ("✓  Ligand present", "good", "#e8f6ec"),
        "No ligand": ("✗  No ligand", "bad", "#fdecec"),
    }

    def show_results_window(self, datasets):
        if self.results_window is not None and self.results_window.winfo_exists():
            self.results_window.lift()
            return

        win = self.results_window = tk.Toplevel(self.root)
        win.title("Harry Spotter — Results")
        sw, sh = self.root.winfo_screenwidth(), self.root.winfo_screenheight()
        win.geometry(f"{min(1260, sw - 60)}x{min(940, sh - 70)}")
        win.minsize(760, 560)
        win.configure(bg=T["bg"])

        for d in datasets:
            if d['base_name'] not in self.radio_vars:
                self.radio_vars[d['base_name']] = tk.StringVar(self.root, value="Unreviewed")

        outer = tk.Frame(win, bg=T["bg"])
        outer.pack(fill="both", expand=True, padx=20, pady=16)

        # ---------------- HEADER ----------------
        header = tk.Frame(outer, bg=T["bg"])
        header.pack(fill="x", pady=(0, 12))
        titles = tk.Frame(header, bg=T["bg"])
        titles.pack(side="left")
        tk.Label(titles, text="Review ligand density", font=F(20, "bold"), bg=T["bg"], fg=T["text"]).pack(anchor="w")
        chain = self.var_chain.get().strip() or "A"
        residue = self.var_residue.get().strip()
        contour = datasets[0].get('contour', self.var_contour.get()) if datasets else self.var_contour.get()
        tk.Label(titles, text=f"{len(datasets)} dataset{'s' if len(datasets) != 1 else ''}   ·   "
                              f"target {chain}{residue}   ·   contour {contour} σ   ·   📁 {os.path.basename(self.var_out.get())}",
                 font=F(11), bg=T["bg"], fg=T["muted"]).pack(anchor="w")
        FlatButton(header, "💾  Export CSV", lambda: self.export_csv(datasets), style="primary",
                   size=12, pady=8).pack(side="right")

        # ---------------- SUMMARY + FILTER ----------------
        bar = tk.Frame(outer, bg=T["bg"])
        bar.pack(fill="x", pady=(0, 12))
        seg = tk.Frame(bar, bg=T["seg_bg"], padx=3, pady=3)
        seg.pack(side="left")
        self.results_filter = tk.StringVar(value="All")
        filter_btns = {}
        for key in ("All", "Unreviewed", "Ligand present", "No ligand"):
            lbl = tk.Label(seg, font=F(11, "bold"), padx=14, pady=6, cursor="hand2")
            lbl.pack(side="left")
            lbl.bind("<Button-1>", lambda e, k=key: set_filter(k))
            filter_btns[key] = lbl
        progress = tk.Label(bar, font=F(11), bg=T["bg"], fg=T["muted"])
        progress.pack(side="right")

        # ---------------- CARD GRID ----------------
        grid_frame = tk.Frame(outer, bg=T["bg"])
        grid_frame.pack(fill="both", expand=True)
        canvas = tk.Canvas(grid_frame, bg=T["bg"], highlightthickness=0)
        scrollbar = tk.Scrollbar(grid_frame, orient="vertical", command=canvas.yview)
        inner = tk.Frame(canvas, bg=T["bg"])
        inner_id = canvas.create_window((0, 0), window=inner, anchor="nw")
        canvas.configure(yscrollcommand=scrollbar.set)
        canvas.pack(side="left", fill="both", expand=True)
        scrollbar.pack(side="right", fill="y")
        inner.bind("<Configure>", lambda e: canvas.configure(scrollregion=canvas.bbox("all")))

        self.image_refs.clear()
        self.result_groups = dataset_groups(self.var_mtz.get().strip(), [d['base_name'] for d in datasets])
        datasets = sorted(datasets, key=lambda d: group_sort_key(self.result_groups[d['base_name']], d['base_name']))
        cards = []
        for d in datasets:
            cards.append((d, self._make_result_card(inner, d, lambda: refresh())))

        state = {"cols": 0}

        def layout(force=False):
            width = canvas.winfo_width()
            cols = max(1, width // 600)
            canvas.itemconfigure(inner_id, width=width)
            if cols == state["cols"] and not force:
                return
            state["cols"] = cols
            for c in range(4):
                inner.columnconfigure(c, weight=1 if c < cols else 0, uniform="res" if c < cols else None)
            wanted = self.results_filter.get()
            i = 0
            for d, card in cards:
                value = self.radio_vars[d['base_name']].get()
                if wanted == "All" or value == wanted:
                    card.grid(row=i // cols, column=i % cols, sticky="nsew", padx=6, pady=6)
                    i += 1
                else:
                    card.grid_remove()
            canvas.yview_moveto(0)

        def refresh():
            counts = {"Ligand present": 0, "No ligand": 0, "Unreviewed": 0}
            for d in datasets:
                v = self.radio_vars[d['base_name']].get()
                counts[v if v in counts else "Unreviewed"] += 1
            reviewed = len(datasets) - counts["Unreviewed"]
            progress.config(text=f"{reviewed} of {len(datasets)} reviewed   ·   "
                                 f"✓ {counts['Ligand present']} present   ·   ✗ {counts['No ligand']} no ligand")
            labels = {"All": f"All  {len(datasets)}", "Unreviewed": f"Unreviewed  {counts['Unreviewed']}",
                      "Ligand present": f"✓ Present  {counts['Ligand present']}",
                      "No ligand": f"✗ No ligand  {counts['No ligand']}"}
            for key, lbl in filter_btns.items():
                sel = key == self.results_filter.get()
                lbl.config(text=labels[key], bg=T["card"] if sel else T["seg_bg"],
                           fg=T["accent"] if sel else T["muted"])

        def set_filter(key):
            self.results_filter.set(key)
            refresh()
            layout(force=True)

        canvas.bind("<Configure>", lambda e: layout())
        refresh()
        win.after(50, lambda: layout(force=True))
        self.enable_wheel_scroll(win, canvas)

    def _make_result_card(self, parent, d, on_change):
        name = d['base_name']
        var = self.radio_vars[name]
        card = tk.Frame(parent, bg=T["card"], highlightthickness=2, highlightbackground=T["border"])
        body = tk.Frame(card, bg=T["card"])
        body.pack(fill="both", expand=True, padx=14, pady=12)

        tk.Label(body, text=name, font=F(12, "bold"), bg=T["card"], fg=T["text"], anchor="w", justify="left",
                 wraplength=540).pack(fill="x")
        info = getattr(self, "result_groups", {}).get(name, {})
        meta = [" ".join(x for x in (info.get("protein"), info.get("mutant")) if x), info.get("ligand"),
                " ".join(x for x in (info.get("timepoint"), info.get("combination")) if x), info.get("half"),
                f"contour {d.get('contour', '3.0')} σ"]
        tk.Label(body, text="   ·   ".join(m for m in meta if m), font=F(10), bg=T["card"],
                 fg=T["muted"], anchor="w").pack(fill="x", pady=(0, 8))

        row = tk.Frame(body, bg=T["card"])
        row.pack(fill="x")
        if d.get('gif') and os.path.exists(d['gif']):
            gif_lbl = AnimatedGifLabel(row, d['gif'], bg="black", bd=0)
            gif_lbl.pack(side="left")
            self.image_refs.append(gif_lbl)
        else:
            tk.Label(row, text="📸\nNo render", width=22, height=11, bg=T["field"], fg=T["muted"],
                     font=F(11, "bold")).pack(side="left")

        side = tk.Frame(row, bg=T["card"])
        side.pack(side="left", fill="both", expand=True, padx=(14, 0))
        tk.Label(side, text="Ligand density", font=F(11, "bold"), bg=T["card"], fg=T["text"]).pack(anchor="w")
        choice_btns = {}
        for value, (text, colour, soft) in self.ASSESSMENTS.items():
            b = tk.Label(side, text=text, font=F(11, "bold"), padx=10, pady=7, cursor="hand2", anchor="w")
            b.pack(fill="x", pady=(6, 0))
            b.bind("<Button-1>", lambda e, v=value: choose(v))
            choice_btns[value] = b
        tk.Frame(side, bg=T["card"]).pack(fill="both", expand=True)
        FlatButton(side, "🐸  Open in Coot", lambda: self.open_in_coot(d), style="secondary", size=10,
                   pady=5).pack(fill="x", pady=(0, 6))
        FlatButton(side, "🔬  Open in PyMOL", lambda: self.open_in_pymol(d), style="secondary", size=10,
                   pady=5).pack(fill="x", pady=(0, 6))
        if d.get('gif') and os.path.exists(d['gif']):
            FlatButton(side, "💾  Save GIF", lambda: self.save_gif_copy(d['gif'], name), style="ghost",
                       size=10, pady=4).pack(fill="x")

        def render():
            current = var.get()
            for value, b in choice_btns.items():
                text, colour, soft = self.ASSESSMENTS[value]
                if value == current:
                    b.config(bg=T[colour], fg="white")
                else:
                    b.config(bg=T["field"], fg=T["muted"])
            card.config(highlightbackground=T[self.ASSESSMENTS[current][1]] if current in self.ASSESSMENTS
                        else T["border"])

        def choose(value):
            # Clicking the current choice again clears it back to Unreviewed.
            var.set("Unreviewed" if var.get() == value else value)
            render()
            on_change()

        render()
        return card

    def export_csv(self, datasets):
        file_path = filedialog.asksaveasfilename(
            parent=self.results_window,
            defaultextension=".csv",
            filetypes=[("CSV files", "*.csv")],
            initialfile="ligand_assessment.csv"
        )
        if not file_path: return
        try:
            n_groups = self.write_assessment_csv(file_path, datasets)
            messagebox.showinfo("Success", f"Results exported, grouped into {n_groups} protein/ligand "
                                           f"group{'s' if n_groups != 1 else ''}:\n{file_path}")
        except Exception as e:
            messagebox.showerror("Export Error", f"Failed to save CSV:\n{e}")

    def write_assessment_csv(self, file_path, datasets):
        """Rows grouped by protein and ligand (then mutant, timepoint,
        combination, even/odd), with a blank row between groups.
        Returns the number of groups."""
        target = f"{self.var_chain.get().strip() or 'A'}{self.var_residue.get().strip()}"
        names = [d['base_name'] for d in datasets]
        groups = dataset_groups(self.var_mtz.get().strip(), names)
        ordered = sorted(datasets, key=lambda d: group_sort_key(groups[d['base_name']], d['base_name']))
        with open(file_path, mode='w', newline='') as f:
            writer = csv.writer(f)
            writer.writerow(["Protein", "Mutant", "Ligand", "Timepoint", "Combination", "Half",
                             "Ligand_Assessment", "Dataset", "Target", "Contour_sigma"])
            previous, n_groups = None, 0
            for d in ordered:
                name = d['base_name']
                g = groups[name]
                group = (g["protein"], g["ligand"])
                if group != previous:
                    if previous is not None:
                        writer.writerow([])
                    previous, n_groups = group, n_groups + 1
                val = self.radio_vars.get(name).get() if name in self.radio_vars else "Unreviewed"
                writer.writerow([g["protein"], g["mutant"], g["ligand"], g["timepoint"], g["combination"],
                                 g["half"], val, name, target, d.get('contour', '')])
        return n_groups

if __name__ == "__main__":
    root = tk.Tk()
    if IS_WINDOWS:
        base = getattr(sys, "_MEIPASS", os.path.dirname(os.path.abspath(__file__)))
        try:
            root.iconbitmap(default=os.path.join(base, "logo.ico"))
        except tk.TclError:
            pass
    try:
        base = getattr(sys, "_MEIPASS", os.path.dirname(os.path.abspath(__file__)))
        icon = Image.open(os.path.join(base, "harryspotter_logo.png"))
        icon.thumbnail((256, 256))
        root._app_icon = ImageTk.PhotoImage(icon)
        root.iconphoto(True, root._app_icon)
    except Exception:
        pass
    app = ApoInspectorGUI(root)
    root.mainloop()