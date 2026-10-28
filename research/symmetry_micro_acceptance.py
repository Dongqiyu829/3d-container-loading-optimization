"""Plan-only executable. No execution stage exists in P1a."""
import argparse
from contextlib import nullcontext
import json
from pathlib import Path
from baseline_common import load_instance
from research.symmetry_guard import ZeroSolveGuard, SolveForbidden
from research.symmetry_models import groups
from research.symmetry_telemetry import capsule_manifest, verify_capsule, source_manifest

ROOT=Path(__file__).resolve().parents[1]
DEFAULT_CONFIG=ROOT/"docs/research/symmetry-search-bias/micro-v1.json"

def load_config(path, root=ROOT):
    root=Path(root).resolve()
    config=json.loads(Path(path).read_text(encoding="utf-8"))
    if config.get("schema_version")!="symmetry-plan-v1" or config.get("stage")!="plan":
        raise ValueError("only registered plan schema/stage accepted")
    for key in ("max_cpsat_calls","max_oracle_calls"):
        if type(config.get(key)) is not int or config[key]!=0:
            raise SolveForbidden("configuration must explicitly forbid all calls")
    if config.get("variants")!=["M0","M1","M2"] or config.get("objectives")!=["volume","count"]:
        raise ValueError("unregistered variant/objective matrix")
    controls={"workers":1,"random_seed":0,"linearization_level":2,"symmetry_level":2,
              "cp_model_presolve":True,"cp_model_probing_level":2,"volume_bound":False,
              "absolute_gap_limit":0,"relative_gap_limit":0,
              "instrumentation":"bounded_scalars_offline_witness_validation_pending"}
    if json.dumps(config.get("future_controls"),sort_keys=True)!=json.dumps(controls,sort_keys=True):
        raise ValueError("frozen controls changed; review required")
    limits={"core-a":{"cpsat_calls":24,"oracle_calls":8,"wall_seconds":90,"cpu_seconds":75},
            "core-b":{"cpsat_calls":24,"oracle_calls":8,"wall_seconds":90,"cpu_seconds":75}}
    call_limits={"solve_wall_seconds":2,"oracle_wall_seconds":2,"oracle_max_nodes":200000}
    for key,expected in (("future_stage_limits",limits),("future_call_limits",call_limits)):
        if json.dumps(config.get(key),sort_keys=True)!=json.dumps(expected,sort_keys=True):
            raise ValueError("frozen limits changed; review required")
    cases=config.get("cases",[])
    if [c.get("id") for c in cases]!=[f"T{i:02}" for i in range(8)]:
        raise ValueError("exactly ordered T00-T07 required")
    capsule_manifest(root,[c["path"] for c in cases])
    instances=[]
    for c in cases:
        instance=load_instance(root/c["path"])  # pure empty-witness instance validation
        if instance.instance_id!=c["id"] or c.get("prediction_status")!="manual_not_solved":
            raise ValueError("fixture identity/prediction label mismatch")
        if set(c["manual_predictions"])!={"volume","count"} or any(
            type(v) is not int or v<0 for v in c["manual_predictions"].values()):
            raise ValueError("invalid manual prediction")
        if not 1<=len(instance.boxes)<=5 or instance.container_volume>64:
            raise ValueError("outside existing tiny Oracle size domain")
        instances.append(instance)
    return config,instances

def build_plan(config_path=DEFAULT_CONFIG,root=ROOT):
    config,instances=load_config(config_path,root)
    rows=[]
    for idx,(case,instance) in enumerate(zip(config["cases"],instances)):
        gs=groups(instance)
        potential=sum(len(g["box_ids"])-1 for g in gs)
        for objective in config["objectives"]:
            oracle_key=f"{case['id']}:{objective}"
            for variant in config["variants"]:
                rows.append({"case_id":case["id"],"future_stage":"core-a" if idx<4 else "core-b",
                             "objective_kind":objective,"objective_unit":"volume" if objective=="volume" else "boxes",
                             "variant":variant,"oracle_reference_key":oracle_key,
                             "expected_objective_manual":case["manual_predictions"][objective],
                             "expectation_status":"manual_prediction_not_solver_result",
                             "actual_added_prefix_count":0 if variant=="M0" else potential,
                             "potential_prefix_count":potential,
                             "groups":gs,"construction_order":"source",
                             "paired_baseline_key":f"{case['id']}:{objective}:source:cold:B0:LP2:SYM2:M0"})
    # This is a plan, not a cache of executable solver jobs.
    return {"schema_version":"symmetry-plan-v1","stage":"plan","execution_authorized":False,
            "actual_cpsat_calls":0,"actual_oracle_calls":0,
            "intended_future_cpsat_calls":len(rows),
            "intended_future_oracle_calls":len(instances)*len(config["objectives"]),
            "future_stage_limits":config["future_stage_limits"],
            "future_call_limits":config["future_call_limits"],
            "controls":config["future_controls"],"oracle_source_reference":config["oracle_source_reference"],
            "rows":rows,"results":[],"future_stages_require_separate_approval":True}

def execute_plan(*args,**kwargs):
    raise SolveForbidden("no execution implementation exists; separate approval and code review required")

def _write(path,value):
    with path.open("x",encoding="utf-8",newline="\n") as f:
        json.dump(value,f,ensure_ascii=False,sort_keys=True,indent=2,allow_nan=False);f.write("\n")

def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--stage",required=True,choices=["plan"])
    parser.add_argument("--max-cpsat-calls",required=True,type=int)
    parser.add_argument("--max-oracle-calls",required=True,type=int)
    parser.add_argument("--config",type=Path,default=DEFAULT_CONFIG)
    parser.add_argument("--output-dir",type=Path,required=True)
    args=parser.parse_args(argv)
    if args.max_cpsat_calls!=0 or args.max_oracle_calls!=0:
        parser.error("P1a requires exactly zero call budgets")
    if args.output_dir.exists():
        parser.error("output path already exists; choose a new path")
    context=nullcontext(ZeroSolveGuard.current) if ZeroSolveGuard.current else ZeroSolveGuard()
    with context as guard:
        before=dict(guard.blocked)
        plan=build_plan(args.config)
        if guard.blocked!=before:
            raise SolveForbidden("plan attempted forbidden execution")
        args.output_dir.mkdir(parents=True,exist_ok=False)
        _write(args.output_dir/"plan.json",plan)
        _write(args.output_dir/"guard.json",{
            "guard_active_during_plan":True,"blocked_attempt_deltas":{k:guard.blocked[k]-before[k] for k in before},
            "executed_cpsat_calls":0,"executed_oracle_calls":0})
        _write(args.output_dir/"config.json",json.loads(args.config.read_text(encoding="utf-8")))
        source_files=["research/symmetry_micro_acceptance.py","research/symmetry_models.py",
                      "research/symmetry_telemetry.py","research/symmetry_guard.py",
                      "cpsat_baseline.py","cpsat_prefix_search_diagnostics.py",
                      "baseline_common.py","identical_box_symmetry_audit.py","validate_solution.py",
                      "schemas/container_loading_instance.schema.json"]
        source_files.extend(c["path"] for c in json.loads(args.config.read_text(encoding="utf-8"))["cases"])
        source_files.extend(["research/run_zero_tests.py","research/tests/test_telemetry.py",
                             "research/tests/test_models.py","research/tests/test_plan.py"])
        _write(args.output_dir/"source-manifest.json",source_manifest(ROOT,source_files))
        manifest=capsule_manifest(args.output_dir,["plan.json","guard.json","config.json","source-manifest.json"])
        _write(args.output_dir/"artifact-manifest.json",manifest)
        verify_capsule(args.output_dir,manifest)
        print(json.dumps({"stage":"plan","future_cpsat_calls":48,"future_oracle_calls":16,
                          "actual_cpsat_calls":0,"actual_oracle_calls":0,"manifest_verified":True}))
    return 0

if __name__=="__main__":
    raise SystemExit(main())
