"""Only focused zero-Solve tests. Run as a module to install Guard before imports."""
import copy
import io
import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

if __name__ == "__main__":
    from research.symmetry_guard import ZeroSolveGuard
    with ZeroSolveGuard() as guard:
        suite=unittest.defaultTestLoader.loadTestsFromName("research.simple_experiment.test_run")
        result=unittest.TextTestRunner(verbosity=2).run(suite)
        print(json.dumps({"tests_run":result.testsRun,**guard.evidence()}))
        code=0 if result.wasSuccessful() and not any(guard.blocked.values()) else 1
    raise SystemExit(code)

from research.simple_experiment import run, analyze
from baseline_common import build_solution, load_instance
from research.symmetry_integration import RunSpec, prepare_run
from research.symmetry_models import without_prefix
from research.tests.test_integration import FakeReader, place


class SimpleTests(unittest.TestCase):
    def setUp(self):
        self.config = run.load_config()
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.directory = Path(self.temp.name)
        self.job = run.plan(self.config)[0]

    def mocked_cp(self, case="T00", objective="volume", model="M0", status="OPTIMAL", value=0, placements=()):
        job={"ordinal":1,"case":case,"objective":objective,"model":model}
        instance=load_instance(run.FIXTURES/(case+".json"))
        p=prepare_run(instance,RunSpec(objective,model,**self.config["cp_sat"]))
        reader=FakeReader(p,list(placements),status=status,value=value,bound=value)
        reader.solve=Mock()
        p.solver=reader
        folder=self.directory/(case+"_"+objective+"_"+model+"_"+status);folder.mkdir()
        with patch("research.symmetry_integration.prepare_run",return_value=p):
            result=run.solve_task(job,self.config,run.FIXTURES/(case+".json"),folder)
        reader.solve.assert_called_once()
        return job,result

    def test_32_plan_and_zero_execution_default(self):
        jobs=run.plan(self.config)
        self.assertEqual(len(jobs),32)
        self.assertEqual(sum(j["model"]=="ORACLE" for j in jobs),8)
        self.assertEqual([j["model"] for j in jobs[:4]],["ORACLE","M0","M1","M2"])
        with patch.object(run,"run_batch") as execute,patch("sys.stdout",new=io.StringIO()):
            self.assertEqual(run.main([]),0)
            execute.assert_not_called()

    def test_worker_rejects_direct_and_forged_requests_before_solver(self):
        variants = []
        for model_index in (0,1):  # Oracle and CP paths both stop before solve_task.
            job = run.plan(self.config)[model_index]
            variants.extend([(job,self.config,"missing"),(job,self.config,"forged")])
        expanded = copy.deepcopy(self.config);expanded["oracle_max_nodes"] = 200001
        changed = copy.deepcopy(self.config);changed["cp_sat"]["solve_wall_seconds"] = 100
        variants.extend([(self.job,expanded,"parent"),(run.plan(self.config)[1],changed,"parent")])
        for change in ({"ordinal":32},{"ordinal":False},{"model":"M3"},{"case":"other"},{"objective":"other"}):
            variants.append(({**self.job,**change},self.config,"parent"))
        for i,(job,config,marker) in enumerate(variants):
            with self.subTest(i=i):
                directory=self.directory/str(i);directory.mkdir()
                run.save(directory/"request.json",{"job":job,"config":config})
                with patch.dict(run.os.environ),patch.object(run,"solve_task") as solve:
                    run.os.environ.pop(run.WORKER_PARENT_ENV,None)
                    if marker != "missing":
                        run.os.environ[run.WORKER_PARENT_ENV] = (
                            str(directory.resolve()) if marker == "parent" else "forged")
                    with self.assertRaises(ValueError):run.main(["--worker",str(directory)])
                    solve.assert_not_called()
                self.assertFalse((directory/"worker-result.json").exists())
                error=run.read_json(directory/"worker-error.json")
                self.assertEqual(error["exception_type"],"ValueError")
                self.assertTrue(error["message"])
                self.assertIn("ValueError",error["traceback"])
                self.assertLessEqual(len(error["message"]),512)
                self.assertLessEqual(len(error["traceback"]),4096)
        # The expected parent marker + fixed request still reaches the existing seam.
        for i in (0,1):
            directory=self.directory/("valid"+str(i));directory.mkdir()
            job=run.plan(self.config)[i]
            run.save(directory/"request.json",{"job":job,"config":self.config})
            with patch.dict(run.os.environ,{run.WORKER_PARENT_ENV:str(directory.resolve())}),patch.object(run.os,"getppid",return_value=-1),patch.object(run,"solve_task",return_value={"job":job}) as solve:
                self.assertEqual(run.main(["--worker",str(directory)]),0)
                solve.assert_called_once_with(job,self.config,directory/"input.json",directory)
                self.assertNotIn(run.WORKER_PARENT_ENV,run.os.environ)
                self.assertFalse((directory/"worker-error.json").exists())

    def test_worker_error_records_read_failure_and_preserves_existing_evidence(self):
        for i,raw,kind in ((0,None,"FileNotFoundError"),(1,"{broken","JSONDecodeError")):
            directory=self.directory/str(i);directory.mkdir()
            if raw is not None:(directory/"request.json").write_text(raw,encoding="utf-8")
            with patch.dict(run.os.environ,{run.WORKER_PARENT_ENV:str(directory.resolve())}),patch.object(run,"solve_task") as solve:
                with self.assertRaises((FileNotFoundError,json.JSONDecodeError)):
                    run.main(["--worker",str(directory)])
                solve.assert_not_called()
            error=run.read_json(directory/"worker-error.json")
            self.assertEqual(error["exception_type"],kind)
            self.assertIn(kind,error["traceback"])
            before=(directory/"worker-error.json").read_bytes()
            # Logging failure (existing file) must not mask the original rejection.
            with patch.dict(run.os.environ),patch.object(run,"solve_task") as solve:
                run.os.environ.pop(run.WORKER_PARENT_ENV,None)
                with self.assertRaisesRegex(ValueError,"supervised parent launch"):
                    run.main(["--worker",str(directory)])
                solve.assert_not_called()
            self.assertEqual((directory/"worker-error.json").read_bytes(),before)

    def test_three_model_protos_only_change_prefix(self):
        # Check all4 fixtures and both objectives without any Solve.
        for case in self.config["cases"]:
            instance=load_instance(run.FIXTURES/(case+".json"))
            for objective in self.config["objectives"]:
                models=[prepare_run(instance,RunSpec(objective,m,**self.config["cp_sat"])) for m in ("M0","M1","M2")]
                stripped=[without_prefix(m.artifacts.model.Proto()).SerializeToString(deterministic=True) for m in models]
                self.assertEqual(stripped[0],stripped[1]);self.assertEqual(stripped[0],stripped[2])
                from cpsat_baseline import build_cpsat_model
                baseline=build_cpsat_model(instance,maximize_volume=objective=="volume",volume_bound=False)
                self.assertEqual(stripped[0],baseline.model.Proto().SerializeToString(deterministic=True))
                self.assertEqual(models[0].metadata["actual_added_prefix_count"],0)
                self.assertGreater(models[1].metadata["actual_added_prefix_count"],0)
                self.assertEqual(models[1].metadata["actual_added_prefix_count"],models[2].metadata["actual_added_prefix_count"])
                for m in models:
                    p=m.solver.parameters
                    self.assertEqual((p.num_search_workers,p.random_seed,p.linearization_level,p.symmetry_level,p.max_time_in_seconds),(1,0,2,2,2))
                    self.assertEqual(m.spec.volume_bound,False)
                    self.assertEqual(len(m.artifacts.model.Proto().solution_hint.vars),0)

    def test_oracle_input_is_validated_original_and_objective_distinct(self):
        from research import tiny_oracle
        for objective,placements,value in (("volume",[place("a0",dims=(3,1,1))],3),("count",[place("b0"),place("b1",1)],2)):
            path=run.FIXTURES/"T03.json";instance=load_instance(path)
            job={"ordinal":0,"case":"T03","objective":objective,"model":"ORACLE"}
            answer={"status":"OPTIMAL","objective":objective,"objective_value":value,"solution":build_solution(instance,placements),"nodes":1,"candidate_placements":0}
            with patch.object(tiny_oracle,"solve",return_value=answer) as call:
                result=run.solve_task(job,self.config,path,self.directory)
            call.assert_called_once_with(instance.raw,objective,max_nodes=200000)
            self.assertTrue(run.validate_result(result,job,path))
            self.assertNotIn("bounds",result)
            cpjob,cpresult=self.mocked_cp("T03",objective,value=value,placements=placements)
            self.assertTrue(run.validate_result(cpresult,cpjob,path))
        bad=self.directory/"invalid.json";run.save(bad,{"format_version":"broken"})
        with patch.object(tiny_oracle,"solve") as call:
            with self.assertRaises(ValueError):run.solve_task(self.job,self.config,bad,self.directory)
            call.assert_not_called()

    def test_empty_optimum_and_unknown_never_confused(self):
        job,result=self.mocked_cp()
        self.assertEqual(result["objective_value"],0)
        self.assertTrue(run.validate_result(result,job,run.FIXTURES/"T00.json"))
        job,unknown=self.mocked_cp(status="UNKNOWN")
        self.assertIsNone(unknown["objective_value"]);self.assertIsNone(unknown["solution"])
        self.assertIsNone(unknown["bounds"]["usable_solver_upper_bound"])
        self.assertFalse(run.validate_result(unknown,job,run.FIXTURES/"T00.json"))
        corrupted=copy.deepcopy(result);corrupted["solution"]=None
        with self.assertRaises(ValueError):run.validate_result(corrupted,job,run.FIXTURES/"T00.json")

    def test_physics_and_oracle_exhaustion_rejected(self):
        from research import tiny_oracle
        instance=load_instance(run.FIXTURES/"T01.json")
        job={"ordinal":0,"case":"T01","objective":"count","model":"ORACLE"}
        bad={"job":job,"status":"OPTIMAL","objective_value":2,"solution":build_solution(instance,[place("a0"),place("a1")])}
        with self.assertRaises(ValueError):run.validate_result(bad,job,run.FIXTURES/"T01.json")
        class Limited(RuntimeError):pass
        with patch.object(tiny_oracle,"ResourceLimit",Limited,create=True),patch.object(tiny_oracle,"solve",side_effect=Limited("node budget")):
            result=run.solve_task(job,self.config,run.FIXTURES/"T01.json",self.directory)
        self.assertEqual(result["status"],"INCOMPLETE")
        self.assertIsNone(result["objective_value"])
        self.assertFalse(run.validate_result(result,job,run.FIXTURES/"T01.json"))

    def test_failure_stop_budget_and_fresh_output_no_worker(self):
        # Existing supervisor is mocked: no Win32 child or solver is ever launched.
        fake={"complete":False,"reason":"CHILD_WALL_LIMIT","cleanup_confirmed":True,
              "handles_closed":True,"final_cpu_known":True,"root_created":True,"exit_code":1,
              "job_accounting":{"active_processes":0,"cpu_seconds":.1,"peak_job_memory_bytes":1,"configured_job_memory_limit_bytes":268435456}}
        def stopped(argv,cwd,output,controller,key,**kw):
            controller.reserve(key);controller.busy=False;controller.cpu=.1
            return dict(fake)
        with patch("research.symmetry_watchdog._supervise",side_effect=stopped) as launch:
            path=run.run_batch(self.config,self.directory)
            other=run.run_batch(self.config,self.directory)
        self.assertNotEqual(path,other)
        self.assertEqual(launch.call_count,2)  # one failed attempt per independent mock batch, no retry
        summary=run.read_json(path/"summary.json")
        self.assertFalse(summary["accepted"]);self.assertEqual(summary["completed"],0)
        first=run.read_json(next(path.glob("*/result.json")))
        self.assertIsNone(first["objective_value"]);self.assertFalse(first["accepted"])
        self.assertEqual(len(list(path.glob("*/request.json"))),1)
        limits=run.limits(self.config)
        controller=SimpleNamespace(limits=limits,cpu=0,clock=lambda:0,started=0)
        fake.update(complete=True,root_created=True,exit_code=0,child_wall_including_cleanup=.1)
        run.check_os(fake,controller)
        for change in ({"cleanup_confirmed":False},{"handles_closed":False},{"final_cpu_known":False},
                       {"child_wall_including_cleanup":4.5}):
            with self.assertRaises(ValueError):run.check_os({**fake,**change},controller)
        controller.cpu=110
        with self.assertRaises(ValueError):run.check_os(fake,controller)

    def test_full_mock_batch_and_oracle_disagreement_stop(self):
        # Synthetic OPTIMAL replies exercise orchestration, not fixture optima.
        # No subprocess is launched and no algorithm computes these answers.
        mismatch = False
        def reply(argv, cwd, output, controller, key, **kw):
            controller.reserve(key)
            folder = Path(output).parent
            self.assertEqual(run.os.environ.get(run.WORKER_PARENT_ENV),str(folder.resolve()))
            job = run.read_json(folder/"request.json")["job"]
            instance = load_instance(folder/"input.json")
            placements = [place("a0")] if mismatch and job["case"] == "T01" and job["model"] == "M0" else []
            value = len(placements)  # all synthetic placements have unit volume
            row = {"job":job,"status":"OPTIMAL","objective_value":value,
                   "solution":build_solution(instance,placements),"error":None}
            if job["model"] != "ORACLE":
                row["bounds"] = {"usable_solver_upper_bound":value}
            run.save(folder/"worker-result.json", row)
            controller.busy = False
            controller.cpu += .01
            return {"complete":True,"cleanup_confirmed":True,"handles_closed":True,
                    "final_cpu_known":True,"root_created":True,"exit_code":0,
                    "child_wall_including_cleanup":.01,"job_accounting":{
                        "active_processes":0,"peak_job_memory_bytes":1,
                        "configured_job_memory_limit_bytes":268435456}}
        previous_marker = run.os.environ.get(run.WORKER_PARENT_ENV)
        with patch("research.symmetry_watchdog._supervise",side_effect=reply) as launch:
            output = run.run_batch(self.config,self.directory)
            self.assertEqual(launch.call_count,32)
            self.assertTrue(run.read_json(output/"summary.json")["accepted"])
            self.assertTrue(all(row["all_equal"] for row in analyze.comparison(output)))
            mismatch = True
            launch.reset_mock()
            failed = run.run_batch(self.config,self.directory)
            summary = run.read_json(failed/"summary.json")
            self.assertFalse(summary["accepted"])
            self.assertIn("Oracle objective mismatch",summary["stop_reason"])
            self.assertEqual(summary["completed"],9)
            self.assertEqual(launch.call_count,10)  # stop at T01/volume/M0
        self.assertEqual(run.os.environ.get(run.WORKER_PARENT_ENV),previous_marker)

    def test_analysis_keeps_zero_but_not_missing_as_success(self):
        run.save(self.directory/"run.json",{"config":self.config})
        for model in self.config["models"]:
            folder=self.directory/model;folder.mkdir()
            run.save(folder/"result.json",{"job":{"case":"T00","objective":"volume","model":model},
                     "status":"OPTIMAL","objective_value":0,"accepted":True})
        rows=analyze.comparison(self.directory)
        self.assertTrue(rows[0]["all_equal"]);self.assertEqual(rows[0]["ORACLE"],0)
        self.assertFalse(rows[1]["all_equal"]);self.assertIsNone(rows[1]["ORACLE"])
