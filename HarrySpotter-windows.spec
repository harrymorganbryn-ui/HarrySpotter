# -*- mode: python ; coding: utf-8 -*-
# PyInstaller build for Windows: produces dist\HarrySpotter\HarrySpotter.exe


a = Analysis(
    ['HarrySpotter.py'],
    pathex=[],
    binaries=[],
    datas=[('lab_logo.png', '.'), ('harryspotter_logo.png', '.'), ('logo.ico', '.'), ('THIRD_PARTY_LICENSES.txt', '.')],
    hiddenimports=[],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name='HarrySpotter',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,
    disable_windowed_traceback=False,
    icon='logo.ico',
)
coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name='HarrySpotter',
)
