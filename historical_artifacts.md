# Historical artifact manifest

This manifest records the evidence currently available for committed outputs and historical result claims. It is a provenance record, not a benchmark report. No historical file was regenerated, moved, or overwritten while preparing it.

Last reviewed: 2026-08-11

## Classification meanings

- **Independently validated:** the recorded coordinates were checked independently of the generating solver for IDs/counts, realized volume, container boundaries, and pairwise non-overlap.
- **Geometrically validated only:** the available coordinates are internally non-overlapping and have plausible extents, but the original instance, generating revision, or full container metadata is missing.
- **Unknown provenance:** the generating code revision, inputs, or run configuration cannot currently be established.
- **Unsupported historical claim:** a number is mentioned in project material but has no supporting raw instance and solution data in the repository.

## Artifact inventory

| Artifact or claim | Classification | Evidence and limitations |
| --- | --- | --- |
| `ortool_Bin_packing.ipynb`: CP-SAT solution with 55 of 60 boxes, packed volume 66,528,000, and 87.7007% utilization | **Independently validated** | The 55 unique printed placements were independently checked against the recorded `1200 x 235 x 269` container. All placements are within bounds, no pair overlaps, and the summed volume is 66,528,000 (`66,528,000 / 75,858,000 = 0.877007...`). The recorded status is FEASIBLE, not proven optimal. Exact rerun equivalence is not established because the dependency version and solver configuration are not pinned. |
| `assets/cp_sat_packing_example.png` | **Unknown provenance** | The image labels match the notebook's 55-box and 87.7% summary, but an image alone is not raw solution data. Treat it as a visualization of the notebook record, not an additional experiment. |
| `encasement.csv` | **Geometrically validated only** | Contains 168 non-overlapping cuboids with summed volume 42,688,000 and occupied extents `480 x 400 x 280`. Plausible inferred inputs do not reproduce the exact coordinate file with the current `Bin_packing_3D.cpp`; the current orientation order produces different placements. Original container metadata and run configuration are absent. |
| `装箱结果.xlsx` | **Geometrically validated only** | Contains seven non-overlapping `200 x 180 x 160` boxes in one row. It does not contain the notebook's 55-box solution, and the generating instance is not recorded. |
| README claim: 63 boxes and 78.46% utilization with a 60-second limit | **Unsupported historical claim** | No matching instance file, coordinate solution, solver log, or notebook output was found. This result is not currently reproducible. |
| README comparison: C++ heuristic 57.5813% versus CP-SAT 83.29% | **Unsupported historical claim** | The repository has no common instance definition, raw coordinate outputs, solver logs, or validation report supporting this comparison. |
| Performance tables and claims in `Project.doc`, including 65.2% versus 76.8%, 71.19%, and claimed speedups | **Unsupported historical claim** | `Project.doc` is UTF-8 plain text despite its extension. The cited experimental tables and comparisons have no associated datasets or raw results in the repository. |
| `Reinforce_learning_bin_packing.ipynb` retained console output | **Unknown provenance** | Development output from an unfinished notebook. The execution ends in a visualization error, and no committed trained model, environment lock, or repeated evaluation data supports it. It is a development remnant, not a benchmark result. |
| `rl_packing_result.csv` | **Unknown provenance** | Contains ten non-overlapping placements within the small test environment's apparent bounds, but its columns do not match the current notebook's `save_results` output and the generating code revision is unknown. It is a development remnant, not a benchmark result. |
| `assets/rl_training_demo.png` | **Unknown provenance** | Retained development visualization from the unfinished RL notebook. It is not evidence of a validated solution or benchmark. |

## Preservation rule

Historical artifacts should remain unchanged until their generating instance, code revision, dependency versions, solver settings, and validation status are known. New experiments should write to new, uniquely named output locations and should include the versioned instance and solution JSON files plus an independent validator report.
