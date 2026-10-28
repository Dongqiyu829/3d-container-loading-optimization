"""Eight-row Stage-A comparison; missing/failed observations never become zero."""
import argparse
import csv
import json
from pathlib import Path
import sys


def comparison(directory):
    directory = Path(directory)
    info = json.loads((directory/"run.json").read_text(encoding="utf-8"))
    results = {}
    for path in directory.glob("*/result.json"):
        r = json.loads(path.read_text(encoding="utf-8"));j=r["job"]
        results[(j["case"],j["objective"],j["model"])] = r
    rows = []
    for case in info["config"]["cases"]:
        for objective in info["config"]["objectives"]:
            row = {"case":case,"objective":objective}
            values = []
            for model in info["config"]["models"]:
                r = results.get((case,objective,model),{})
                valid = r.get("accepted") is True and r.get("status") == "OPTIMAL"
                value = r.get("objective_value") if valid else None
                row[model] = value
                row[model+"_status"] = r.get("status") or "NOT_COMPLETED"
                row[model+"_error"] = r.get("failure_reason") or r.get("error")
                values.append(value)
            row["all_equal"] = all(v is not None for v in values) and len(set(values)) == 1
            rows.append(row)
    return rows


def main(argv=None):
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument("run_directory",type=Path)
    p.add_argument("--csv",type=Path,help="new output file; refuse overwrite")
    a=p.parse_args(argv);rows=comparison(a.run_directory)
    summary=json.loads((a.run_directory/"summary.json").read_text(encoding="utf-8"))
    print("Batch accepted:",summary["accepted"])
    columns=["case","objective","ORACLE","M0","M1","M2","all_equal"]
    print("\t".join(columns))
    for row in rows:print("\t".join("-" if row[c] is None else str(row[c]) for c in columns))
    if a.csv:
        with a.csv.open("x",encoding="utf-8",newline="") as f:
            w=csv.DictWriter(f,fieldnames=list(rows[0]));w.writeheader();w.writerows(rows)
    return 0


if __name__=="__main__":raise SystemExit(main())
