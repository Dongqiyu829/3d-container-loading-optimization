# -*- mode: python ; coding: utf-8 -*-

import os
from pathlib import Path

from PyInstaller.utils.hooks import collect_dynamic_libs


ROOT = Path(SPECPATH).parents[1]
CONSOLE_MODE = os.environ.get("PYINSTALLER_DIAGNOSTIC_CONSOLE") == "1"
GREEDY_EXECUTABLE = ROOT / "build" / "windows" / "Bin_packing_3D.exe"
if not GREEDY_EXECUTABLE.is_file():
    raise FileNotFoundError(
        f"Compile the Windows Greedy backend before freezing: {GREEDY_EXECUTABLE}"
    )

normal_example_files = sorted((ROOT / "benchmarks" / "instances").glob("*.json"))
datas = [
    (str(ROOT / "benchmarks" / "suite.json"), "benchmarks"),
] + [(str(path), "benchmarks/instances") for path in normal_example_files]

binaries = [
    (str(GREEDY_EXECUTABLE), "backend"),
] + collect_dynamic_libs("ortools")

hiddenimports = [
    "ortools.sat.cp_model_pb2",
    "ortools.sat.sat_parameters_pb2",
    "ortools.sat.python.cp_model",
    "ortools.sat.python.cp_model_helper",
    "matplotlib.backends.backend_qtagg",
    "mpl_toolkits.mplot3d.art3d",
]

a = Analysis(
    [str(ROOT / "packaging" / "windows" / "pyinstaller_entry.py")],
    pathex=[str(ROOT)],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
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
    name="3DContainerLoading",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=CONSOLE_MODE,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch="x86_64",
    codesign_identity=None,
    entitlements_file=None,
    version=str(ROOT / "packaging" / "windows" / "version_info.txt"),
    uac_admin=False,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name="3DContainerLoading",
)
