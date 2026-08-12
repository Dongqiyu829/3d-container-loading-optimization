import copy
import json
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from baseline_common import load_instance  # noqa: E402
from benchmarks.external.orlib_br.adapter import (  # noqa: E402
    BRBoxType,
    BRFormatError,
    convert_problem,
    load_source_manifest,
    parse_br_file,
    parse_br_text,
    sha256_file,
    verify_source_files,
)
from external_br_benchmark import (  # noqa: E402
    aggregate_external_results,
    class_aggregates,
    compare_external_records,
    create_run_directory,
    equality_classification,
    regression_case,
    select_pilot_problems,
)


SOURCE_ROOT = ROOT / "benchmarks" / "external" / "orlib_br"
SYNTHETIC_TWO_PROBLEMS = """\
2
1 11111
10 9 8
2
7 4 1 3 0 2 1 2
8 2 0 2 1 2 0 1
2 22222
12 10 7
1
3 5 0 4 0 3 1 4
"""


class BRParserTests(unittest.TestCase):
    def test_multiple_problems_types_and_quantities(self):
        problems = parse_br_text(SYNTHETIC_TWO_PROBLEMS, source_filename="thpack1.txt")
        self.assertEqual(len(problems), 2)
        self.assertEqual(problems[0].container, (10, 9, 8))
        self.assertEqual(problems[0].generation_seed, 11111)
        self.assertEqual(len(problems[0].box_types), 2)
        self.assertEqual(problems[0].expanded_box_count, 3)
        self.assertEqual(problems[1].expanded_box_count, 4)

    def test_malformed_inputs_fail_loudly(self):
        malformed = {
            "bad problem header": "1\n1\n10 9 8\n1\n1 2 1 2 1 2 1 1\n",
            "bad type record": "1\n1 11\n10 9 8\n1\n1 2 1 2 1 2 1\n",
            "missing type": "1\n1 11\n10 9 8\n2\n1 2 1 2 1 2 1 1\n",
            "invalid indicator": "1\n1 11\n10 9 8\n1\n1 2 2 2 1 2 1 1\n",
            "no permitted orientation": "1\n1 11\n10 9 8\n1\n1 2 0 2 0 2 0 1\n",
            "zero dimension": "1\n1 11\n10 9 8\n1\n1 0 1 2 1 2 1 1\n",
            "negative quantity": "1\n1 11\n10 9 8\n1\n1 2 1 2 1 2 1 -1\n",
            "duplicate type": "1\n1 11\n10 9 8\n2\n1 2 1 2 1 2 1 1\n1 3 1 3 1 3 1 1\n",
            "extra data": "1\n1 11\n10 9 8\n1\n1 2 1 2 1 2 1 1\n999\n",
        }
        for name, text in malformed.items():
            with self.subTest(name=name), self.assertRaises(BRFormatError):
                parse_br_text(text, source_filename="thpack1.txt")

    def test_all_nonempty_vertical_indicator_combinations(self):
        expected = {
            (1, 0, 0): ("WHL", "HWL"),
            (0, 1, 0): ("LHW", "HLW"),
            (0, 0, 1): ("LWH", "WLH"),
            (1, 1, 0): ("LHW", "WHL", "HLW", "HWL"),
            (1, 0, 1): ("LWH", "WLH", "WHL", "HWL"),
            (0, 1, 1): ("LWH", "LHW", "WLH", "HLW"),
            (1, 1, 1): ("LWH", "LHW", "WLH", "WHL", "HLW", "HWL"),
        }
        for indicators, orientations in expected.items():
            box_type = BRBoxType(
                1, 2, indicators[0], 2, indicators[1], 3, indicators[2], 1
            )
            with self.subTest(indicators=indicators):
                self.assertEqual(box_type.allowed_orientations, orientations)

    def test_repeated_dimensions_do_not_collapse_orientation_identities(self):
        box_type = BRBoxType(1, 2, 1, 2, 1, 3, 1, 1)
        self.assertEqual(len(box_type.allowed_orientations), 6)
        self.assertEqual(len(set(box_type.allowed_orientations)), 6)


class BRConversionTests(unittest.TestCase):
    def setUp(self):
        self.problem = parse_br_text(
            "1\n7 12345\n20 10 8\n2\n4 5 1 4 0 3 1 3\n9 2 0 2 1 2 0 2\n",
            source_filename="thpack3.txt",
        )[0]

    def test_conversion_is_deterministic_and_ids_are_stable(self):
        first = convert_problem(self.problem)
        second = convert_problem(self.problem)
        self.assertEqual(first, second)
        instance, _ = first
        self.assertEqual(instance["instance_id"], "orlib-br-thpack3-p007-s12345")
        self.assertEqual(instance["box_types"][0]["type_id"], "br-type-004")
        self.assertEqual(
            instance["box_types"][0]["box_ids"],
            ["br-type-004-box-001", "br-type-004-box-002", "br-type-004-box-003"],
        )

    def test_volume_quantity_dimensions_and_source_metadata_are_preserved(self):
        instance, metadata = convert_problem(self.problem)
        expected_volume = 5 * 4 * 3 * 3 + 2 * 2 * 2 * 2
        self.assertEqual(metadata["candidate_volume"], expected_volume)
        self.assertEqual(metadata["expanded_candidate_box_count"], 5)
        self.assertEqual(metadata["source_problem_number"], 7)
        self.assertEqual(metadata["source_generation_seed"], 12345)
        self.assertEqual(metadata["source_filename"], "thpack3.txt")
        self.assertEqual(instance["box_types"][0]["dimensions"], {
            "length": 5, "width": 4, "height": 3
        })
        self.assertEqual(instance["box_types"][0]["allowed_orientations"], [
            "LWH", "WLH", "WHL", "HWL"
        ])

    def test_converted_instance_is_accepted_by_canonical_loader(self):
        instance, _ = convert_problem(self.problem)
        with tempfile.TemporaryDirectory() as temporary_directory:
            path = Path(temporary_directory) / "instance.json"
            path.write_text(json.dumps(instance), encoding="utf-8")
            loaded = load_instance(path)
        self.assertEqual(loaded.instance_id, instance["instance_id"])
        self.assertEqual(len(loaded.boxes), 5)


class BRSourceIntegrityTests(unittest.TestCase):
    def test_committed_source_files_match_manifest_hashes_and_counts(self):
        manifest = load_source_manifest(SOURCE_ROOT / "source_manifest.json")
        verified = verify_source_files(manifest, SOURCE_ROOT / "raw")
        self.assertEqual(len(verified), 7)
        self.assertTrue(all(entry["verified"] for entry in verified))
        self.assertEqual([len(parse_br_file(SOURCE_ROOT / "raw" / entry["filename"])) for entry in manifest["files"]], [100] * 7)

    def test_checksum_detects_changed_source(self):
        source = SOURCE_ROOT / "raw" / "thpack1.txt"
        with tempfile.TemporaryDirectory() as temporary_directory:
            changed = Path(temporary_directory) / "thpack1.txt"
            changed.write_bytes(source.read_bytes() + b"\n")
            self.assertNotEqual(sha256_file(changed), sha256_file(source))


class BRExperimentAnalysisTests(unittest.TestCase):
    @staticmethod
    def _records(instance_id, source_class, volumes, fingerprint="same"):
        return [
            {
                "source_class": source_class,
                "source_filename": f"thpack{source_class[2:]}.txt",
                "source_problem_number": 1,
                "source_generation_seed": 99,
                "instance_id": instance_id,
                "mode": mode,
                "instance_sha256": fingerprint,
                "packed_volume": volume,
                "packed_box_count": volume // 10,
                "utilization": volume / 100,
                "physical_volume_optimal": volume == 100,
                "solver_core_runtime_seconds": 0.1,
                "end_to_end_runtime_seconds": 0.2,
                "validation": "VALID",
                "box_type_count": int(source_class[2:]),
                "candidate_box_count": 20,
                "candidate_to_container_volume_ratio": 1.1,
            }
            for mode, volume in zip(
                ("historical", "planar-inclusive", "geometry-first"), volumes
            )
        ]

    def test_pilot_selection_is_first_n_per_file(self):
        first = parse_br_text(SYNTHETIC_TWO_PROBLEMS, source_filename="thpack1.txt")
        second = parse_br_text(SYNTHETIC_TWO_PROBLEMS, source_filename="thpack2.txt")
        selected = select_pilot_problems({"thpack2.txt": second, "thpack1.txt": first}, 1)
        self.assertEqual(
            [(problem.source_filename, problem.problem_number) for problem in selected],
            [("thpack1.txt", 1), ("thpack2.txt", 1)],
        )

    def test_pair_math_and_class_aggregation(self):
        records = self._records("a", "BR1", (80, 90, 85)) + self._records(
            "b", "BR2", (100, 100, 90)
        )
        comparisons = [
            compare_external_records(records[:3]), compare_external_records(records[3:])
        ]
        aggregate = aggregate_external_results(records, comparisons)
        inclusive = aggregate["comparisons"]["planar-inclusive_vs_historical"]
        self.assertEqual((inclusive["win"], inclusive["tie"], inclusive["loss"]), (1, 1, 0))
        classes = class_aggregates(records, comparisons)
        self.assertEqual(classes["BR1"]["instance_count"], 1)
        self.assertEqual(classes["BR2"]["instance_count"], 1)

    @staticmethod
    def _trace(position, *, volume=8, success=True):
        return {
            "attempts": [{
                "step_index": 0, "box_id": "box-001", "orientations_attempted": ["LWH"],
                "selected_orientation": "LWH" if success else None,
                "selected_candidate_point": position if success else None,
                "selected_position": position if success else None,
                "placement_succeeded": success,
                "status": "PLACED" if success else "NO_ACCEPTED_PLACEMENT",
                "candidate_points_before": [{"x": 0, "y": 0, "z": 0}],
                "planar_state_before": {"horizontal": 2, "vertical": 2},
                "original_dimensions": {"length": 2, "width": 2, "height": 2},
                "state_after_attempt": {
                    "cumulative_packed_box_count": 1 if success else 0,
                    "cumulative_packed_volume": volume if success else 0,
                },
            }]
        }

    def test_regression_and_equality_extraction(self):
        records = self._records("a", "BR1", (90, 80, 80))
        comparison = compare_external_records(records)
        historical = self._trace({"x": 0, "y": 0, "z": 0})
        inclusive = self._trace({"x": 0, "y": 2, "z": 0})
        traces = {
            "historical": historical,
            "planar-inclusive": inclusive,
            "geometry-first": inclusive,
        }
        regression = regression_case(
            comparison, "planar-inclusive", "historical", traces
        )
        self.assertEqual(regression["first_divergence"]["step_index"], 0)
        equality = equality_classification(comparison, historical, inclusive)
        self.assertEqual(equality["classification"], "clear_equality_triggered_divergence")

    def test_run_directory_refuses_overwrite(self):
        with tempfile.TemporaryDirectory() as temporary_directory:
            create_run_directory(temporary_directory, "external-run")
            with self.assertRaises(FileExistsError):
                create_run_directory(temporary_directory, "external-run")


if __name__ == "__main__":
    unittest.main()
