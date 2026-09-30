"""Write THIRD_PARTY_LICENSES.txt for the packaged app.

The standalone downloads bundle Python, Tcl/Tk and Pillow (and PyInstaller's
start-up program). Their licences allow redistribution but ask for the notices
to be included, so this collects the actual licence texts from the Python used
for the build. Run it before PyInstaller (the build scripts do).

Harry Spotter does NOT bundle Phenix, CCP4, Dimple, Coot, gemmi or PyMOL -
it runs the copies the user has installed and licensed.
"""
import glob
import importlib.metadata
import os
import platform
import sys
import sysconfig

OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "THIRD_PARTY_LICENSES.txt")
parts = []


def first_existing(paths):
    for p in paths:
        if p and os.path.isfile(p):
            return p
    return None


def section(title, text, source):
    parts.append("=" * 78 + f"\n{title}\n" + (f"(from {source})\n" if source else "") + "=" * 78
                 + "\n\n" + text.strip() + "\n\n")


# ---------------------------------------------------------------- Python
stdlib = sysconfig.get_paths()["stdlib"]
ver = f"{sys.version_info.major}.{sys.version_info.minor}"
py_lic = first_existing([os.path.join(stdlib, "LICENSE.txt"), os.path.join(sys.base_prefix, "LICENSE.txt"),
                         os.path.join(sys.base_prefix, "LICENSE"), f"/usr/share/doc/python{ver}/copyright",
                         "/usr/share/doc/python3/copyright"])
section(f"Python {platform.python_version()}  -  Python Software Foundation License",
        open(py_lic, errors="replace").read() if py_lic else
        "See https://docs.python.org/3/license.html", py_lic)

# ---------------------------------------------------------------- Tcl/Tk
try:
    import tkinter
    tcl = tkinter.Tcl()
    tcl_ver, tk_ver = tcl.eval("info patchlevel"), str(tkinter.TkVersion)
    libdir = tcl.eval("info library")
    tk_lic = None
    text = None
    for cand in (os.path.join(libdir, "license.terms"), os.path.join(os.path.dirname(libdir), "license.terms")):
        if os.path.isfile(cand):
            tk_lic, text = cand, open(cand, errors="replace").read()
            break
    if text is None:
        try:   # Tcl 9 keeps its files inside the library (zipfs)
            text = tcl.eval(f"set f [open {{{libdir}/license.terms}}]; set t [read $f]; close $f; set t")
            tk_lic = libdir + "/license.terms"
        except Exception:
            pass
    section(f"Tcl {tcl_ver} / Tk {tk_ver}  -  Tcl/Tk License (BSD-style)",
            text or "See https://www.tcl.tk/software/tcltk/license.html", tk_lic)
except Exception as e:
    section("Tcl/Tk  -  Tcl/Tk License (BSD-style)", f"See https://www.tcl.tk/software/tcltk/license.html ({e})", None)

# ---------------------------------------------------------------- Pillow (its licence file also covers the
# image libraries its wheels bundle, e.g. libjpeg, zlib, libpng, libtiff, freetype, libwebp)
try:
    dist = importlib.metadata.distribution("pillow")
    lic_files = [f for f in (dist.files or []) if "LICENSE" in f.name.upper() or "COPYING" in f.name.upper()]
    texts = [open(dist.locate_file(f), errors="replace").read() for f in lic_files
             if os.path.isfile(dist.locate_file(f))]
    section(f"Pillow {dist.version}  -  MIT-CMU (HPND) License, including bundled image libraries",
            "\n\n".join(texts) or "See https://github.com/python-pillow/Pillow/blob/main/LICENSE",
            ", ".join(str(f) for f in lic_files) or None)
except importlib.metadata.PackageNotFoundError:
    pass

# ---------------------------------------------------------------- PyInstaller start-up program
try:
    pyi = importlib.metadata.distribution("pyinstaller")
    pyi_version = pyi.version
except importlib.metadata.PackageNotFoundError:
    pyi_version = "?"
section(f"PyInstaller {pyi_version} bootloader  -  GPL 2.0 with the PyInstaller bootloader exception",
        "The app's start-up program comes from PyInstaller. It is licensed under the GNU GPL v2 with an\n"
        "exception that allows it to be distributed with programs under any licence.\n"
        "See https://github.com/pyinstaller/pyinstaller/blob/develop/COPYING.txt", None)

header = f"""Harry Spotter - third-party licences
====================================

Harry Spotter itself is released under the MIT License (see LICENSE in the source
repository: https://github.com/harrymorganbryn-ui/HarrySpotter).

This download bundles the open-source components below, whose licences allow
redistribution provided these notices are included.

Harry Spotter does NOT include or distribute Phenix, CCP4, Dimple, Coot, gemmi or
PyMOL. It runs the copies installed on your computer; each must be obtained and
licensed from its developers.

Built with Python {platform.python_version()} on {platform.system()} {platform.machine()}.

"""
with open(OUT, "w", encoding="utf-8") as f:
    f.write(header + "".join(parts))
print(f"wrote {OUT} ({len(parts)} sections)")
