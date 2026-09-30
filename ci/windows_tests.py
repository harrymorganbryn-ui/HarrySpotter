"""Windows checks for Harry Spotter, run on GitHub's Windows machines (x64 and ARM64).

Usage: python ci/windows_tests.py <path to packaged HarrySpotter.exe> <expected arch: x64|arm64>
Checks the packaged program's architecture, then the Windows-specific code
from source (settings location, clean tool environment, Coot's Vulkan
setting, following a Google Drive shortcut (.lnk) to a visit folder).
Writes ci-out/summary-windows-<arch>.md; exits non-zero if any check fails.
"""
import os
import runpy
import struct
import subprocess
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
exe, arch = sys.argv[1], sys.argv[2]
OUT = os.path.join(ROOT, "ci-out")
os.makedirs(OUT, exist_ok=True)
results = []


def check(name, ok, detail=""):
    results.append((name, bool(ok), str(detail)))
    print(f"[{'PASS' if ok else 'FAIL'}] {name}  {detail}", flush=True)


# ------------------------------------------------------------------ packaged program type
with open(exe, "rb") as f:
    data = f.read(4096)
pe = struct.unpack_from("<I", data, 0x3C)[0]
machine = struct.unpack_from("<H", data, pe + 4)[0]
kind = {0x8664: "x64", 0xAA64: "arm64", 0x14C: "x86"}.get(machine, hex(machine))
check(f"HarrySpotter.exe is a native {arch} program", kind == arch, kind)

# ------------------------------------------------------------------ Windows code paths (from source)
os.chdir(ROOT)
ns = runpy.run_path(os.path.join(ROOT, "HarrySpotter.py"), run_name="ci")
check("Detected as Windows", ns["IS_WINDOWS"] and not ns["IS_MAC"] and not ns["IS_LINUX"])
check("Settings in %APPDATA%", ns["CONFIG_DIR"].startswith(os.environ["APPDATA"]), ns["CONFIG_DIR"])
check("Coot launched with Vulkan disabled", ns["coot_env"]().get("GDK_DISABLE") == "vulkan")

# the packaged app's own settings must not reach Phenix/Coot/Dimple
bundle = os.path.dirname(exe)
saved = dict(os.environ)
os.environ.update({"TCL_LIBRARY": os.path.join(bundle, "_tcl_data"), "_PYI_APPLICATION_HOME_DIR": bundle,
                   "PATH": bundle + os.pathsep + saved.get("PATH", "")})
sys.frozen, sys._MEIPASS = True, bundle
env = ns["tool_env"]()
del sys.frozen, sys._MEIPASS
os.environ.clear()
os.environ.update(saved)
clean = ("TCL_LIBRARY" not in env and "_PYI_APPLICATION_HOME_DIR" not in env
         and not any(p.startswith(bundle) for p in env["PATH"].split(os.pathsep)))
check("Tools get a clean environment (no packaged-app settings)", clean)

# a visit folder that Google Drive shows as a Windows shortcut (.lnk)
tmp = tempfile.mkdtemp()
real = os.path.join(tmp, "shared", "mx12345-1")
os.makedirs(os.path.join(real, "stills_processing"))
drive = os.path.join(tmp, "My Drive", "Lab")
os.makedirs(drive)
lnk = os.path.join(drive, "mx12345-1.lnk")
ps = (f"$s=(New-Object -ComObject WScript.Shell).CreateShortcut('{lnk}'); "
      f"$s.TargetPath='{real}'; $s.Save()")
subprocess.run(["powershell", "-NoProfile", "-Command", ps], check=True)
found = ns["find_visit_dir"](os.path.join(tmp, "My Drive"), "mx12345-1")
check("Visit found through a Drive shortcut (.lnk)", found and os.path.samefile(found, real), found)


class Stub:
    is_windows = True


for tool in ("coot", "dimple", "phenix", "pymol"):
    found = ns["ApoInspectorGUI"].auto_find_software(Stub(), tool)
    check(f"Search for {tool} runs (not installed on CI)", isinstance(found, str) and found, found)

failed = [r for r in results if not r[1]]
with open(os.path.join(OUT, f"summary-windows-{arch}.md"), "w") as f:
    f.write(f"# Harry Spotter Windows {arch} checks: {len(results) - len(failed)}/{len(results)} passed\n\n")
    for name, ok, detail in results:
        f.write(f"- {'PASS' if ok else 'FAIL'} - {name} - {detail}\n")
print(f"\n{len(results) - len(failed)}/{len(results)} checks passed")
sys.exit(1 if failed else 0)
