# -*- mode: python ; coding: utf-8 -*-
"""
PyInstaller spec file for ueye-timelapse.

Build with:
    pyinstaller ueye_timelapse.spec

Or use the build script:
    python build_exe.py

The resulting executable will be in dist/ueye-timelapse/
"""

import sys
from pathlib import Path

block_cipher = None

# Path to the source package
src_path = Path("src")

a = Analysis(
    [str(src_path / "ueye_timelapse" / "__main__.py")],
    pathex=[str(src_path)],
    binaries=[],
    datas=[],
    hiddenimports=[
        # PyQt5 plugins that PyInstaller sometimes misses
        "PyQt5.sip",
        # OpenCV may need these
        "cv2",
        # Ensure pyueye is bundled if available
        "pyueye",
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        # Exclude unnecessary large packages to reduce size
        "matplotlib",
        "scipy",
        "pandas",
        "tkinter",
        "_tkinter",
        "unittest",
        "test",
        "xmlrpc",
    ],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="ueye-timelapse",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=False,  # No console window (GUI app)
    icon="ueyetimelapse_icon.ico",
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name="ueye-timelapse",
)
