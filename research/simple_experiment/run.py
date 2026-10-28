"""Fixed tiny research batch. Default: plan. --execute is manual opt-in, not authorization."""
import argparse
from datetime import datetime, timezone
import importlib.metadata
import json
import math
import os
from pathlib import Path
import platform
import subprocess
import sys
import time
from types import SimpleNamespace
import uuid

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
DEFAULT_CONFIG = Path(__file__).with_name("config.json")
FIXTURES = ROOT/"docs/research/symmetry-search-bias/fixtures"
MAX_FILE = 1024 * 1024


def read_json(path):
    with Path(path).open("rb") as f:
        data = f.read(MAX_FILE+1)
    if len(data) > MAX_FILE:
        raise ValueError("JSON exceeds 1MiB")
    return json.loads(data)


def save(path, value):
    data = json.dumps(value, indent=2, allow_nan=False).encode("utf-8")+b"\n"
    if len(data) > MAX_FILE:
        raise ValueError("result exceeds 1MiB; not truncated")
    with Path(path).open("xb") as f:
        f.write(data); f.flush(); os.fsync(f.fileno())


def limits(config):
    """Plain parameters for the existing watchdog; no new supervisor."""
    values = dict(config["resources"])
    def validate():
        ceilings = {"child_wall":4.5, "stage_wall":170, "cpu":110, "poll":.01, "cleanup_wall":1}
        for key, cap in ceilings.items():
            v = values[key]
            if type(v) not in (int, float) or not math.isfinite(v) or not 0 < v <= cap:
                raise ValueError("invalid resource: "+key)
        if type(values["memory_bytes"]) is not int or type(values["max_attempts"]) is not int or values["memory_bytes"] != 268435456 or values["max_attempts"] != 32:
            raise ValueError("fixed 256MiB / 32-attempt batch required")
    validate()
    return SimpleNamespace(**values, validate=validate)


def load_config(path=DEFAULT_CONFIG):
    c = read_json(path)
    if (c["cases"] != ["T00","T01","T02","T03"] or c["objectives"] != ["volume","count"]
            or c["models"] != ["ORACLE","M0","M1","M2"] or c["hints"] != "none"
            or c["oracle_max_nodes"] != 200000 or c["trace_cap"] != 128):
        raise ValueError("only fixed Stage A is implemented")
    expected = {"worker_count":1,"random_seed":0,"linearization_level":2,"symmetry_level":2,
                "solve_wall_seconds":2,"construction_order":"source","volume_bound":False}
    if c["cp_sat"] != expected:
        raise ValueError("fixed Stage-A CP parameters required")
    limits(c)
    return c


def plan(config):
    return [{"ordinal":i, "case":case, "objective":obj, "model":model}
            for i,(case,obj,model) in enumerate((case,obj,model) for case in config["cases"]
                for obj in config["objectives"] for model in config["models"])]


def solve_task(job, config, input_path, directory):
    """Reuses algorithms. Only called by the isolated child, or with mocks in tests."""
    from baseline_common import load_instance
    instance = load_instance(input_path)  # SAME complete validator/input for CP and Oracle
    result = {"job":job, "status":None, "objective_value":None, "solution":None, "error":None}
    try:
        if job["model"] == "ORACLE":
            from research import tiny_oracle
            started = time.perf_counter()
            try:
                answer = tiny_oracle.solve(instance.raw, job["objective"], max_nodes=config["oracle_max_nodes"])
                if answer.get("objective") != job["objective"]: raise ValueError("Oracle objective mismatch")
                result.update(answer)
            except tiny_oracle.ResourceLimit as exc:
                result.update(status="INCOMPLETE", error=str(exc))
            finally:
                result["solve_elapsed_seconds"] = time.perf_counter()-started
        else:
            from research.symmetry_integration import RunSpec, prepare_run, Capture, make_callback, collect_terminal
            p = prepare_run(instance, RunSpec(objective_kind=job["objective"], variant=job["model"], **config["cp_sat"]))
            capture = Capture(p, max_events=config["trace_cap"])
            callback = make_callback(capture)
            result["resolved_parameters"] = p.metadata["resolved_parameters"]
            result["model_proto_sha256"] = p.metadata["model_sha256"]
            started = time.perf_counter()
            try:
                p.solver.solve(p.artifacts.model, callback)
            finally:
                result["solve_elapsed_seconds"] = time.perf_counter()-started
            response = p.solver.ResponseProto()
            result["status"] = p.solver.StatusName(response.status).upper()
            if hasattr(response, "SerializeToString"):
                raw = response.SerializeToString()
                if len(raw) > MAX_FILE:
                    raise ValueError("raw solver response exceeds 1MiB")
                with (Path(directory)/"solver-response.pb").open("xb") as f:
                    f.write(raw)
            log = getattr(response, "solve_log", "")
            if len(log.encode("utf-8")) > MAX_FILE:
                raise ValueError("solver log exceeds 1MiB")
            with (Path(directory)/"solve.log").open("x", encoding="utf-8") as f:
                f.write(log)
            row = collect_terminal(p, p.solver, capture, evidence_kind="native_unvalidated", log_complete=False)
            for key in ("status","objective_value","solution","bounds","terminal_stats","lp","presolve",
                        "trace","capture","clock","stop_reasons","validated_first_incumbent_wall",
                        "callback_inclusive_wall_seconds","first_extraction_wall_seconds"):
                result[key] = row[key]
    except Exception as exc:
        import traceback
        result["error"] = type(exc).__name__+": "+str(exc)
        result["traceback"] = traceback.format_exc()
    return result


def validate_result(result, job, input_path):
    """Independent physical/objective check; an empty OPTIMAL witness is valid."""
    from baseline_common import load_instance
    from validate_solution import validate_solution
    instance = load_instance(input_path)
    if result.get("job") != job:
        raise ValueError("wrong task response")
    status, value, solution = result.get("status"), result.get("objective_value"), result.get("solution")
    if status == "UNKNOWN":
        if value is not None or solution is not None or (result.get("bounds") or {}).get("usable_solver_upper_bound") is not None:
            raise ValueError("UNKNOWN cannot claim an incumbent/bound")
        return False
    if status not in ("OPTIMAL","FEASIBLE"):
        return False
    checked = validate_solution(instance.raw, solution)
    if not checked.valid or type(value) is not int:
        raise ValueError("invalid physical witness/objective")
    expected = checked.packed_volume if job["objective"] == "volume" else checked.placement_count
    if value != expected:
        raise ValueError("objective unit/value mismatch")
    if job["model"] != "ORACLE":
        from cpsat_prefix_search_diagnostics import selection_is_direction_valid
        direction = {"M1":"forward","M2":"reverse"}.get(job["model"])
        if direction and not selection_is_direction_valid(instance, solution, direction):
            raise ValueError("prefix labels invalid")
        if status == "OPTIMAL" and result.get("bounds",{}).get("usable_solver_upper_bound") != value:
            raise ValueError("OPTIMAL bound mismatch")
    elif status != "OPTIMAL" or "bounds" in result:
        raise ValueError("Oracle has no CP bound contract")
    return status == "OPTIMAL" and not result.get("error") and not result.get("stop_reasons")


def check_os(stats, controller):
    a = stats.get("job_accounting") or {}
    if (not all(stats.get(k) is True for k in ("complete","cleanup_confirmed","handles_closed","final_cpu_known","root_created"))
            or a.get("active_processes") != 0
            or type(a.get("peak_job_memory_bytes")) is not int
            or not 0 <= a["peak_job_memory_bytes"] <= controller.limits.memory_bytes
            or a.get("configured_job_memory_limit_bytes") != controller.limits.memory_bytes
            or stats.get("exit_code") != 0
            or not 0 <= stats.get("child_wall_including_cleanup",float("inf")) < controller.limits.child_wall
            or not 0 <= controller.cpu < controller.limits.cpu
            or controller.clock()-controller.started >= controller.limits.stage_wall):
        raise ValueError("OS budget/cleanup incomplete: "+str(stats.get("reason")))


def worker(directory):
    directory = Path(directory)
    request = read_json(directory/"request.json")
    try:
        result = solve_task(request["job"], request["config"], directory/"input.json", directory)
    except Exception as exc:
        result = {"job":request["job"], "status":None, "objective_value":None,
                  "solution":None, "error":type(exc).__name__+": "+str(exc)}
    result["versions"] = {"python":platform.python_version(), "ortools":importlib.metadata.version("ortools")}
    save(directory/"worker-result.json", result)
    save(directory/"worker-control.json", {"kind":"worker_terminal"})


def run_batch(config, output_root):
    if os.name != "nt":
        raise OSError("this minimal launcher requires Windows Job Objects")
    from baseline_common import load_instance
    from research.symmetry_watchdog import DummyStage, _supervise
    # Research process + descendants only; no system or production settings changed.
    for name in ("OPENBLAS_NUM_THREADS","OMP_NUM_THREADS","MKL_NUM_THREADS","NUMEXPR_NUM_THREADS"):
        os.environ[name] = "1"
    controller = DummyStage(limits(config))
    run_id = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")+"_"+uuid.uuid4().hex[:8]
    output = Path(output_root)/run_id
    output.mkdir(parents=True, exist_ok=False)
    commit = subprocess.check_output(["git","-C",str(ROOT),"rev-parse","HEAD"]).decode().strip()
    dirty = bool(subprocess.check_output(["git","-C",str(ROOT),"status","--porcelain"]))
    jobs = plan(config)
    summary = {"run_id":run_id, "git_commit":commit, "git_dirty":dirty,
               "versions":{"python":platform.python_version(),"ortools":importlib.metadata.version("ortools")},
               "config":config, "planned":jobs, "completed":0, "accepted":False, "stop_reason":None}
    save(output/"config.json", config)
    save(output/"run.json", summary)
    references = {}
    cpu_known = True
    try:
        inputs = {case:load_instance(FIXTURES/(case+".json")).raw for case in config["cases"]}
        for job in jobs:
            directory = output/f"{job['ordinal']:02}_{job['case']}_{job['objective']}_{job['model']}"
            directory.mkdir()
            save(directory/"input.json", inputs[job["case"]])
            save(directory/"request.json", {"job":job,"config":config,"git_commit":commit,"git_dirty":dirty})
            result = {"job":job,"status":None,"objective_value":None,"solution":None,"error":None,"accepted":False}
            try:
                cpu_known = False
                stats = _supervise([sys.executable,"-I","-B",str(Path(__file__).resolve()),"--worker",str(directory.resolve())],
                    ROOT, directory/"worker-control.json", controller, str(job["ordinal"]), control_kind="worker_terminal")
                cpu_known = stats.get("final_cpu_known") is True
                # Old watchdog's dummy counters are NOT native call measurements.
                for key in ("actual_cpsat_calls","actual_oracle_calls","dummy_payload"):
                    stats.pop(key, None)
                stats["evidence_kind"] = "os_supervised_local_task"
                save(directory/"supervision.json", stats)
                if (directory/"worker-result.json").exists():
                    result.update(read_json(directory/"worker-result.json"))
                result["accepted"] = False
                check_os(stats, controller)
                if not validate_result(result, job, directory/"input.json"):
                    raise ValueError("not a complete validated optimum: "+str(result.get("status")))
                key = (job["case"],job["objective"])
                if job["model"] == "ORACLE":
                    references[key] = result["objective_value"]
                elif references.get(key) != result["objective_value"]:
                    raise ValueError("CP/independent Oracle objective mismatch")
                if controller.clock()-controller.started >= controller.limits.stage_wall:
                    raise ValueError("stage wall exhausted after result validation")
                result["accepted"] = True
            except BaseException as exc:
                result["failure_reason"] = type(exc).__name__+": "+str(exc)
                save(directory/"result.json", result)
                raise
            save(directory/"result.json", result)
            summary["completed"] += 1
        summary["accepted"] = True
    except BaseException as exc:
        summary["stop_reason"] = type(exc).__name__+": "+str(exc)
    summary["stage_wall_seconds"] = controller.clock()-controller.started
    summary["child_cpu_seconds"] = controller.cpu if cpu_known else None
    if summary["stage_wall_seconds"] >= controller.limits.stage_wall:
        summary.update(accepted=False, stop_reason="stage wall exhausted during finalization")
    save(output/"summary.json", summary)
    return output


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--config",type=Path,default=DEFAULT_CONFIG)
    p.add_argument("--execute",action="store_true",help="run 32 real tasks only AFTER separate owner approval")
    p.add_argument("--output",type=Path,default=ROOT/"results/simple-experiment")
    p.add_argument("--worker",type=Path,help=argparse.SUPPRESS)
    a = p.parse_args(argv)
    if a.worker:
        worker(a.worker); return 0
    config = load_config(a.config)
    if not a.execute:
        print(json.dumps({"tasks":plan(config),"config":config,"executed":False},indent=2)); return 0
    path = run_batch(config,a.output)
    print(path)
    return 0 if read_json(path/"summary.json")["accepted"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
