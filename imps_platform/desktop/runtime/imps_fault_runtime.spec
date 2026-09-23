# -*- mode: python ; coding: utf-8 -*-
from pathlib import Path


runtime_root = Path(SPECPATH).resolve()
vendor_root = runtime_root / "vendor"

a = Analysis(
    [str(runtime_root / "imps_fault_runtime.py")],
    pathex=[str(runtime_root), str(vendor_root)],
    binaries=[],
    datas=[],
    hiddenimports=[
        "capture",
        "job_service",
        "worker",
        "detection_policy",
        "core.schema",
        "core.detector_base",
        "core.feature_tracker",
        "core.iso15118",
        "core.iso_features",
        "core.iso15118_3",
        "core.slac_features",
        "models.agentic_ai",
        "models.fast_infer",
        "models.nn_tools",
        "models.slac_rules",
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=["torch", "sklearn", "scipy", "pandas", "matplotlib"],
    noarchive=False,
    optimize=1,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="imps-fault-runtime",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=True,
    disable_windowed_traceback=False,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    name="imps-fault-runtime",
)
