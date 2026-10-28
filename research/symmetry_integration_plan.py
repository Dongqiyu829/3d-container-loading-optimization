"""P1b plan-only integration inventory; no worker launcher or positive-budget path."""
import argparse
from contextlib import nullcontext
import json
from pathlib import Path
from research.symmetry_guard import ZeroSolveGuard,SolveForbidden
from research.symmetry_micro_acceptance import build_plan,load_config,DEFAULT_CONFIG,_write
from research.symmetry_oracle_contract import audit_source_bytes,compatibility
from research.symmetry_telemetry import capsule_manifest,source_manifest,verify_capsule
ROOT=Path(__file__).resolve().parents[1]

def integration_plan():
    plan=build_plan()
    _,instances=load_config(DEFAULT_CONFIG)
    path=ROOT/"research/tiny_oracle.py"
    contract=audit_source_bytes(path.read_bytes()) if path.exists() else {
        "source_available":False,"reason":"publication_consent_or_source_integration_pending"}
    plan.update(schema_version="symmetry-integration-plan-v1",
                oracle_source_contract=contract,
                static_compatibility=[{"case_id":i.instance_id,**compatibility(i)} for i in instances],
                execution_authorized=False,positive_budget_worker_implemented=False,
                os_watchdog_implemented=False,callback_AA_calibrated=False,
                source_reconciliation="docs/research/symmetry-search-bias/p1b/source-reconciliation.json")
    for row in plan["rows"]:
        row["internal_solver_limit_seconds"]=2
        row["proposed_child_hard_wall_seconds"]=2
        row["child_wall_scope"]="from_owned_process_start_including_import_and_build"
        row["no_retries"]=True
    return plan

def request_stage(*args,**kwargs):
    raise SolveForbidden("P1b positive-budget stage is unavailable; no approval flag enables it")

def main(argv=None):
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument("--stage",required=True,choices=["plan"])
    p.add_argument("--max-cpsat-calls",type=int,required=True)
    p.add_argument("--max-oracle-calls",type=int,required=True)
    p.add_argument("--output-dir",type=Path,required=True)
    a=p.parse_args(argv)
    if a.max_cpsat_calls!=0 or a.max_oracle_calls!=0:
        p.error("only zero call budgets are permitted in P1b")
    if a.output_dir.exists():p.error("refuse overwrite")
    context=nullcontext(ZeroSolveGuard.current) if ZeroSolveGuard.current else ZeroSolveGuard()
    with context as guard:
        before=dict(guard.blocked)
        plan=integration_plan()
        if guard.blocked!=before:raise SolveForbidden("plan attempted execution")
        a.output_dir.mkdir(parents=True,exist_ok=False)
        _write(a.output_dir/"integration-plan.json",plan)
        _write(a.output_dir/"guard.json",{"blocked_attempt_deltas":{k:guard.blocked[k]-before[k] for k in before},
                                        "executed_cpsat_calls":0,"executed_oracle_calls":0})
        paths=["research/symmetry_integration.py","research/symmetry_budget.py",
               "research/symmetry_oracle_contract.py","research/symmetry_integration_plan.py",
               "research/run_p1b_zero_tests.py","research/tests/test_integration.py",
               "research/symmetry_models.py","research/symmetry_telemetry.py",
               "research/symmetry_guard.py","cpsat_baseline.py","cpsat_prefix_search_diagnostics.py",
               "baseline_common.py","validate_solution.py","identical_box_symmetry_audit.py",
               "docs/research/symmetry-search-bias/micro-v1.json",
                "docs/research/symmetry-search-bias/p1b/source-reconciliation.json",
               "research/tests/test_telemetry.py","research/tests/test_models.py",
               "research/tests/test_plan.py","requirements.txt",
               "schemas/container_loading_instance.schema.json"]
        if (ROOT/"research/tiny_oracle.py").exists():paths.append("research/tiny_oracle.py")
        paths.extend(f"docs/research/symmetry-search-bias/fixtures/T{i:02}.json" for i in range(8))
        _write(a.output_dir/"source-manifest.json",source_manifest(ROOT,paths))
        m=capsule_manifest(a.output_dir,["integration-plan.json","guard.json","source-manifest.json"])
        _write(a.output_dir/"artifact-manifest.json",m)
        verify_capsule(a.output_dir,m)
        print(json.dumps({"stage":"plan","actual_cpsat_calls":0,"actual_oracle_calls":0,
                          "proposed_cpsat_calls":48,"proposed_oracle_calls":16,
                          "static_fixture_compatibility":8,"execution_worker":False}))
    return 0

if __name__=="__main__":
    raise SystemExit(main())
