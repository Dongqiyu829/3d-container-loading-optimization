# Windows Distribution and Acceptance Plan

This document covers the v1.1.0 Windows x64 application build. It does not change the canonical instance or solution format version, solver mathematics, or benchmark semantics.

## Runtime dependency audit

The source GUI imports the following production runtime layers:

- Python modules: `gui`, `baseline_common`, `validate_solution`, `greedy_baseline`, `greedy_portfolio`, `cpsat_baseline`, and `hybrid_optimizer`.
- CP-SAT: OR-Tools and its native extension libraries, plus its declared Python dependencies.
- GUI: PySide6, Qt libraries, and the Qt platform/plugin resources collected by PyInstaller's PySide6 hooks.
- Visualization: Matplotlib, NumPy, Pillow, font/data resources, and the QtAgg backend.
- Fast/Optimize/Compare: `Bin_packing_3D.exe`, invoked through the existing line-oriented machine protocol.
- Normal application data: `benchmarks/suite.json` and the 28 committed internal example JSON files referenced by that suite.

The independent validator is Python code and does not read the JSON Schema files during normal GUI execution. The frozen application therefore does not need to bundle the schemas. It also does not bundle research notebooks, generated results, learning outputs, distributional benchmark campaigns, or the 700 OR-Library BR source instances.

No suitable application icon currently exists in `assets/`: the available PNG files are packing/research illustrations rather than a Windows product icon. The first build therefore uses the PyInstaller/Inno default executable icon. A reviewed `.ico` asset can be added separately without changing solver behavior.

## Source and packaged backend resolution

`gui.resources` is the single boundary for source-tree versus frozen resources.

- Source mode resolves resources from the repository root. GUI Fast/Optimize/Compare retain compile-on-demand behavior and therefore require a C++17 `g++` compiler.
- Packaged mode resolves data from PyInstaller's application resource root and selects `backend/Bin_packing_3D.exe`. It never calls the compiler.

The bundled Greedy executable is built from the unchanged `Bin_packing_3D.cpp`. Its machine protocol, orientation mapping, Portfolio selection, and Hybrid orchestration are unchanged. Windows child-process flags prevent the console-subsystem backend from opening a terminal window behind the windowed GUI.

## Reproducible build inputs

- Runtime: Python 3.12 x64 and `requirements-gui.txt`.
- Freeze: `requirements-packaging.txt` pins PyInstaller separately from normal runtime requirements.
- Greedy: MinGW-w64 C++17, linked with static GCC runtime options.
- Freeze definition: `packaging/windows/3DContainerLoading.spec`.
- Installer definition: `packaging/windows/installer.iss` using Inno Setup 6.
- Orchestration: `packaging/windows/build.ps1`.

From a configured Windows build environment:

```powershell
python -m pip install -r requirements-packaging.txt
./packaging/windows/build.ps1 -Python python -Cxx g++
```

The build writes ignored intermediate files under `build/` and `dist/`, then stable release candidates under `artifacts/`:

- `3DContainerLoading-Windows-x64-Setup.exe`
- `3DContainerLoading-Windows-x64-Portable.zip`
- `SHA256SUMS.txt`

The PyInstaller application is `--onedir`/windowed. The installer uses a non-admin per-user default under `%LOCALAPPDATA%\Programs`, creates a Start Menu shortcut, offers an optional desktop shortcut, and registers uninstall support. It does not edit `PATH`.

## Automated packaged-application smoke

The build launches `dist/3DContainerLoading/3DContainerLoading.exe` with Python removed from `PATH` and runs a hidden packaging self-test. That self-test exercises:

- Fast through the bundled Greedy executable;
- Optimize;
- Compare;
- standalone CP-SAT volume and count;
- standalone CP-SAT weight and count-plus-weight;
- committed example loading;
- canonical instance output;
- canonical solution and metadata output;
- Matplotlib/Qt 3D visualization rendering.

Every emitted solution must pass the same independent validator used by source mode. The self-test records its result in `build/windows/packaged-smoke/summary.json`. This automated smoke does not replace visible human testing.

## Clean Windows 10/11 x64 acceptance test

Use a machine or VM that does not rely on Python, Conda, pip, Git, `g++`, OR-Tools, PySide6, or Matplotlib being installed.

1. Download `3DContainerLoading-Windows-x64-Setup.exe` and `SHA256SUMS.txt` from the same workflow artifact or draft release.
2. Verify the installer's SHA-256 value.
3. Run the installer without administrator elevation.
4. Confirm the normal wizard, per-user destination, Start Menu shortcut, optional desktop shortcut, and absence of any `PATH` prompt.
5. Launch **3D Container Loading Optimizer** from the Start Menu and confirm no terminal window appears.
6. Load a committed example and verify the six human-readable orientation controls reproduce its allowed subset.
7. Run Fast and confirm a valid visualized result and Details output.
8. Run Optimize with a short budget and confirm a valid final result.
9. Run Compare and confirm both validated rows are shown.
10. Run standalone CP-SAT with packed-volume and packed-box-count objectives.
11. Enable total-weight capacity, enter weights, and run CP-SAT for both objectives.
12. Save a canonical instance, reload it, and confirm orientations and optional weights are unchanged.
13. Save a solution and metadata sidecar, then independently inspect the files.
14. Pan/rotate the 3D visualization and switch displayed Compare results.
15. Close and relaunch the application.
16. Uninstall from Windows Settings and confirm the application directory and shortcuts are removed.

Repeat a shorter check with `3DContainerLoading-Windows-x64-Portable.zip`: extract it to a new directory and double-click `3DContainerLoading.exe`. Fast, CP-SAT, visualization, and save operations must work without installation.

## Signing and SmartScreen

The current workflow does not code-sign binaries. Windows may show an unsigned-publisher or Microsoft Defender SmartScreen warning. Testers should verify the published SHA-256 checksum before choosing the documented Windows option to continue. Do not describe these artifacts as signed unless a later release workflow performs and verifies real code signing.

## Release boundary

The Windows workflow uploads review artifacts only. It does not create a tag or GitHub Release. After clean-machine acceptance, the stable filenames can be attached to a human-reviewed `v1.1.0` release and the currently inactive README latest-download URLs can be made clickable.

