"""Centralized source-tree and frozen-application resource resolution."""

from __future__ import annotations

import sys
from dataclasses import dataclass
from pathlib import Path


SOURCE_ROOT = Path(__file__).resolve().parents[1]


class RuntimeResourceError(RuntimeError):
    """Raised when a required application resource is unavailable."""


def is_frozen_application() -> bool:
    return bool(getattr(sys, "frozen", False))


def runtime_root(
    *,
    frozen: bool | None = None,
    bundle_root: str | Path | None = None,
) -> Path:
    """Return the source root or PyInstaller's extracted/bundled resource root."""

    packaged = is_frozen_application() if frozen is None else frozen
    if not packaged:
        return SOURCE_ROOT
    if bundle_root is not None:
        return Path(bundle_root).resolve()
    pyinstaller_root = getattr(sys, "_MEIPASS", None)
    if pyinstaller_root is None:
        return Path(sys.executable).resolve().parent
    return Path(pyinstaller_root).resolve()


def resolve_runtime_resource(
    relative_path: str | Path,
    *,
    frozen: bool | None = None,
    bundle_root: str | Path | None = None,
    required: bool = True,
) -> Path:
    """Resolve one application resource without assuming a repository checkout."""

    relative = Path(relative_path)
    if relative.is_absolute() or ".." in relative.parts:
        raise ValueError("runtime resource paths must be safe relative paths")
    root = runtime_root(frozen=frozen, bundle_root=bundle_root)
    resolved = (root / relative).resolve()
    if root != resolved and root not in resolved.parents:
        raise ValueError("runtime resource path escapes the application root")
    if required and not resolved.exists():
        mode = "packaged" if (is_frozen_application() if frozen is None else frozen) else "source"
        raise RuntimeResourceError(
            f"required {mode} application resource is missing: {resolved}"
        )
    return resolved


@dataclass(frozen=True)
class GreedyExecutableResolution:
    path: Path
    requires_compilation: bool
    mode: str


def resolve_greedy_executable(
    development_target: str | Path | None,
    *,
    frozen: bool | None = None,
    bundle_root: str | Path | None = None,
) -> GreedyExecutableResolution:
    """Select compile-on-demand source behavior or the bundled Windows backend."""

    packaged = is_frozen_application() if frozen is None else frozen
    if packaged:
        executable = resolve_runtime_resource(
            Path("backend") / "Bin_packing_3D.exe",
            frozen=True,
            bundle_root=bundle_root,
        )
        if not executable.is_file():
            raise RuntimeResourceError(
                f"bundled Greedy backend is not a file: {executable}"
            )
        return GreedyExecutableResolution(executable, False, "packaged")
    if development_target is None:
        raise ValueError("source mode requires a Greedy build target")
    return GreedyExecutableResolution(
        Path(development_target).resolve(), True, "source"
    )

