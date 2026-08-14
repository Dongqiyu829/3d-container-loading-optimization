import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app_version import __version__  # noqa: E402
from gui.packaging_smoke import run_packaging_self_test  # noqa: E402
from gui.resources import (  # noqa: E402
    RuntimeResourceError,
    resolve_greedy_executable,
    resolve_runtime_resource,
)


class RuntimeResourceTests(unittest.TestCase):
    def test_packaging_self_test_refuses_source_mode(self):
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "smoke"
            with self.assertRaisesRegex(RuntimeError, "frozen application"):
                run_packaging_self_test(output)
            self.assertFalse(output.exists())

    def test_source_mode_keeps_compile_on_demand_target(self):
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / "Bin_packing_3D.exe"
            resolution = resolve_greedy_executable(target, frozen=False)
        self.assertEqual(resolution.path, target.resolve())
        self.assertTrue(resolution.requires_compilation)
        self.assertEqual(resolution.mode, "source")

    def test_packaged_mode_chooses_bundled_backend_without_compilation(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            executable = root / "backend" / "Bin_packing_3D.exe"
            executable.parent.mkdir()
            executable.write_bytes(b"packaged-backend")
            resolution = resolve_greedy_executable(
                None, frozen=True, bundle_root=root
            )
        self.assertEqual(resolution.path, executable.resolve())
        self.assertFalse(resolution.requires_compilation)
        self.assertEqual(resolution.mode, "packaged")

    def test_packaged_mode_fails_clearly_when_backend_is_missing(self):
        with tempfile.TemporaryDirectory() as directory:
            with self.assertRaisesRegex(RuntimeResourceError, "missing"):
                resolve_greedy_executable(None, frozen=True, bundle_root=directory)

    def test_resource_resolver_rejects_absolute_and_parent_paths(self):
        with self.assertRaises(ValueError):
            resolve_runtime_resource(ROOT, frozen=False)
        with self.assertRaises(ValueError):
            resolve_runtime_resource("../outside", frozen=False)


class PackagingDefinitionTests(unittest.TestCase):
    def test_application_release_version_is_independent_v1_1(self):
        self.assertEqual(__version__, "1.1.0")
        instance_schema = (ROOT / "schemas" / "container_loading_instance.schema.json").read_text(
            encoding="utf-8"
        )
        solution_schema = (ROOT / "schemas" / "container_loading_solution.schema.json").read_text(
            encoding="utf-8"
        )
        self.assertIn('"const": "1.0"', instance_schema)
        self.assertIn('"const": "1.0"', solution_schema)

    def test_spec_bundles_only_normal_examples_and_greedy_backend(self):
        spec = (ROOT / "packaging" / "windows" / "3DContainerLoading.spec").read_text(
            encoding="utf-8"
        )
        self.assertIn("Bin_packing_3D.exe", spec)
        self.assertIn("benchmarks", spec)
        self.assertNotIn("external/orlib_br", spec)
        self.assertNotIn("Reinforce_learning", spec)
        self.assertIn('PYINSTALLER_DIAGNOSTIC_CONSOLE") == "1"', spec)
        self.assertIn("console=CONSOLE_MODE", spec)

    def test_installer_and_workflow_use_stable_nonpublishing_assets(self):
        installer = (ROOT / "packaging" / "windows" / "installer.iss").read_text(
            encoding="utf-8"
        )
        workflow = (ROOT / ".github" / "workflows" / "windows-package.yml").read_text(
            encoding="utf-8"
        )
        self.assertIn("PrivilegesRequired=lowest", installer)
        self.assertIn("3DContainerLoading-Windows-x64-Setup", installer)
        for name in (
            "3DContainerLoading-Windows-x64-Setup.exe",
            "3DContainerLoading-Windows-x64-Portable.zip",
            "SHA256SUMS.txt",
        ):
            self.assertIn(name, workflow)
        self.assertNotIn("release create", workflow.lower())


if __name__ == "__main__":
    unittest.main()
