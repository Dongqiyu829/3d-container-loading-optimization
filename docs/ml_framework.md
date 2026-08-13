# Learning Framework

> **No trained ML or RL policy is currently part of the validated user-facing solver stack.**

## 1. Motivation

The project now has reproducible canonical instances, independently validated solver outcomes, and controlled Hybrid experiments. The `learning/` package provides a lightweight path from that evidence to future learning studies without returning to ad-hoc notebook-only data preparation.

The framework is infrastructure only. It does not train a model, alter Fast or Optimize, generate placements, or validate geometry.

## 2. What currently exists

```text
learning/
  features.py        named deterministic physical features
  dataset.py         repository benchmark enumeration and feature records
  records.py         explicit optional label-manifest loading/joining
  split.py           deterministic train/validation/test splits
  interfaces.py      framework-neutral predictor/scorer protocols
  export_dataset.py  non-overwriting JSONL/CSV export CLI
```

Only the Python standard library and existing repository parsers/validator are used. There is no PyTorch, TensorFlow, GPU, model-weight, or training dependency.

## 3. Feature schema

The schema identity is `learning_features_v1`, version `1.0`. The primary interchange is a named mapping, not a positional array.

### Instance-level features

- container length, width, height, and volume;
- physical box count and box type count;
- total candidate volume and candidate/container volume ratio;
- min/max/mean/median/population standard deviation of physical box volume;
- min/max/mean/median/population standard deviation of normalized base dimensions;
- min/max/mean/median/population standard deviation of box aspect ratio;
- min/max/mean/median/population standard deviation of allowed orientation count;
- fraction of physical boxes with all six orientations and fraction restricted;
- repeated type-group count (canonical types with quantity greater than one) and repeated-box fraction;
- min/max/mean/median/population standard deviation of type quantity.

The basic extractor deliberately excludes solver results, packed utilization, labels, and hashes or encodings of textual IDs.

### Type-level features

Each ordered type record keeps its ID and type-order index in `metadata`. Predictive `features` contain only base and container-normalized dimensions, volume and volume/container ratio, allowed orientation count, quantity, per-axis container-fit ratios, and aspect ratio. The repeated type-group statistic does not claim strict symmetry equivalence across separate canonical types.

### Physical-box features

Each physical box inherits its type's physical features. `box_id`, `type_id`, type-order index, and zero-based copy index remain metadata rather than predictive inputs. Tests verify that textual relabeling, identical-copy ID reordering, and safe permutation of physically identical types leave physical feature vectors unchanged. A future order-aware representation would require a separate explicit schema.

Base-dimension normalization uses `length/container_length`, `width/container_width`, and `height/container_height`. It is not rotation-invariant; allowed-orientation statistics separately describe rotational freedom.

## 4. Dataset records

`learning.dataset` deterministically enumerates:

- the 28 internal instances from `benchmarks/suite.json`;
- the 60 fixed-seed instances from `benchmarks/distributional/manifest.json`;
- all 700 BR problems by converting the committed authoritative raw files in memory.

Every record preserves instance ID, benchmark family, repository-relative source path, source/generator metadata, feature schema identity, instance features, and optionally type/box records. Enumeration never assumes a local ignored `results/` directory exists.

BR features describe this repository's documented canonical conversion. They retain the source class, problem number, generation seed, source hash, and importer version.

## 5. Split strategy

`learning.split.SplitConfig` records a non-negative seed and train/validation/test fractions summing to one. The algorithm is explicit:

1. compute `SHA-256(str(seed) + NUL + instance_id)`;
2. sort lexicographically by digest, then instance ID;
3. allocate contiguous partitions using recorded fractions.

Output includes the configuration, counts, and IDs per split. IDs cannot overlap and duplicate input IDs are rejected. Records retain their family metadata. This is a stable general-purpose baseline, not a claim that random instance-level splitting is statistically ideal for every future study; BR class or generated-family leakage may require grouped designs.

## 6. Optional label provenance

Core datasets are label-free. Labels are joined only when the caller supplies an explicit normalized label manifest containing:

- `label_manifest_version`;
- experiment run ID;
- result source;
- solver configuration, including budget/workers/seed where relevant;
- one values mapping per unique instance ID.

Missing labels remain explicit `null`. Duplicate or malformed label records fail loudly. The join does not scan arbitrary result trees or infer outcomes from filenames. A future adapter may deliberately normalize a particular Hybrid artifact into this format, but that adapter must record its source and selection semantics.

Portable label provenance records the manifest version, experiment run ID, result source, solver configuration, and SHA-256 of the exact manifest contents. Local manifest paths are not exported. Labels for dataset records may be partial, but a manifest label whose instance ID is absent from the selected dataset is rejected rather than silently discarded.

## 7. Learning interfaces

`learning.interfaces` provides small framework-neutral protocols:

- `InstancePredictor.predict(instance_features)`;
- `BudgetPredictor.predict_improvement_probability(instance_features, budget_seconds)`;
- `BoxScorer.score_boxes(box_features)`;
- `CandidateScorer.score_candidate(instance_features, candidate_features)`.

These protocols do not instantiate a model or connect it to a solver. Probability outputs can use `checked_probability` to enforce `[0, 1]`.

## 8. Recommended first experiment

The first low-risk research target is:

> Given physical instance features and CP-SAT budget `t`, predict whether CP-SAT will improve the validated Portfolio solution within `t`.

Hybrid campaign records naturally supply candidate labels after explicit normalization. A prediction error changes compute allocation, not geometry: Portfolio remains the validated fallback and the independent validator remains authoritative. Evaluation should compare against simple baselines such as always optimize, never optimize, candidate/container-volume thresholds, and family-conditioned rates.

No such model is trained or evaluated in the current repository state.

## 9. Possible later targets

- predict a useful Optimize search budget;
- rank existing Greedy policies without changing their geometry;
- predict likelihood of CP-SAT proof closure;
- prioritize candidate points or boxes only after a safe controlled interface exists.

Direct coordinate generation is intentionally not the first target because it couples learning errors to geometric feasibility and identity/orientation correctness.

## 10. Integration safety rules

1. Keep Fast and Optimize behavior unchanged until a controlled experiment supports an explicit decision.
2. Treat learned outputs as guidance, never geometric truth.
3. Preserve canonical physical IDs and allowed orientations.
4. Record model version, training data manifest, split, features, label provenance, and inference configuration.
5. Evaluate against trivial and non-learned baselines on held-out, leakage-aware data.
6. Preserve a deterministic validated fallback.
7. Do not load untrusted serialized model code in the GUI.
8. Do not make a heavyweight ML framework a core solver dependency.

## 11. Validation boundary

The independent validator checks canonical solutions after solver/orchestration output. Feature extraction validates instance semantics but does not validate or predict a packing. Any future learned component that influences solver search must still end in a canonical solution checked by `validate_solution.py` before display, saving, comparison, or benchmark attribution.

## 12. Export CLI and current status

Example label-free export:

```cmd
python -m learning.export_dataset --output learning_exports/internal.jsonl --families internal
```

Use `--families internal distributional orlib-br`, `--limit`, `--format jsonl|csv`, or omission flags for type/box features as needed. `--label-manifest` is explicit and labels are off by default. Existing output paths are refused rather than overwritten.

Current status: deterministic extraction, enumeration, splitting, explicit optional label joins, protocol interfaces, and export are implemented and tested. Training, model selection, accuracy measurement, solver integration, and user-facing ML controls do not exist.
