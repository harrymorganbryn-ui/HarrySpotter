"""Diagnostic: which screenshot routes work in this Coot? (CI only)

Lists Coot's Python functions to do with screenshots/framebuffers, then tries
a screenshot with framebuffers on and (if possible) off, and reports whether
each image has any content.
"""
import os
import subprocess
import sys

data = sys.argv[1]
out = sys.argv[2]
os.makedirs(out, exist_ok=True)
script = os.path.join(out, "probe.py")
open(script, "w").write(f'''
import coot, time, sys
names = sorted(n for n in dir(coot) if any(k in n.lower() for k in ("framebuffer", "screendump", "screenshot", "image", "offscreen")))
print("PROBE_NAMES", names); sys.stdout.flush()
read_pdb({os.path.join(data, "phenix", "final.pdb")!r})
make_and_draw_map({os.path.join(data, "phenix", "final.mtz")!r}, "FoFo", "PHFc", "", 0, 0)
from gi.repository import GLib
def shots():
    try:
        screendump_image({os.path.join(out, "fb_on.png")!r}); print("PROBE_SHOT fb_on done")
    except Exception as e: print("PROBE_SHOT fb_on failed", e)
    for fn in ("set_use_framebuffers", "set_use_framebuffers_for_screendump", "set_framebuffer_scale_factor"):
        if hasattr(coot, fn):
            try:
                getattr(coot, fn)(0 if "scale" not in fn else 1); print("PROBE_SET", fn)
            except Exception as e: print("PROBE_SET failed", fn, e)
    try:
        graphics_draw()
    except Exception: pass
    GLib.timeout_add(500, second)
    return False
def second():
    try:
        screendump_image({os.path.join(out, "fb_off.png")!r}); print("PROBE_SHOT fb_off done")
    except Exception as e: print("PROBE_SHOT fb_off failed", e)
    sys.stdout.flush()
    coot_real_exit(0)
    return False
GLib.timeout_add(1500, shots)
''')
r = subprocess.run(["coot", "--no-state-script", "--script", script], capture_output=True, text=True, timeout=180)
log = r.stdout + r.stderr
open(os.path.join(out, "probe.log"), "w").write(log)
for line in log.splitlines():
    if line.startswith("PROBE_") or "glnamedreadbuffer" in line or "use_framebuffers" in line:
        print(line[:400])
from PIL import Image
for name in ("fb_on", "fb_off"):
    for ext in (".png.tga", ".png"):
        p = os.path.join(out, name + ext)
        if os.path.exists(p):
            print(f"RESULT {name}: max brightness {Image.open(p).convert('L').getextrema()[1]}")
            break
    else:
        print(f"RESULT {name}: no file")
