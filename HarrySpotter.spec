# -*- mode: python ; coding: utf-8 -*-


a = Analysis(
    ['HarrySpotter.py'],
    pathex=[],
    binaries=[],
    datas=[('lab_logo.png', '.'), ('harryspotter_logo.png', '.'), ('logo.icns', '.')],
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
    upx=True,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=['logo.icns'],
)
coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name='HarrySpotter',
)
app = BUNDLE(
    coll,
    name='HarrySpotter.app',
    icon='logo.icns',
    bundle_identifier=None,
)
