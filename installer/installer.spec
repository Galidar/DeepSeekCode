# -*- mode: python ; coding: utf-8 -*-
import os
_installer_dir = SPECPATH if 'SPECPATH' in dir() else os.path.dirname(os.path.abspath(__file__))

a = Analysis(
    [os.path.join(_installer_dir, 'installer_app.py')],
    pathex=[],
    binaries=[],
    datas=[(os.path.join(_installer_dir, 'payload'), 'payload')],
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
    a.binaries,
    a.datas,
    [],
    name='DeepSeekCode_Setup',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)
