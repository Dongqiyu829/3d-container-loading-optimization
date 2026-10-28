"""Closed-harness zero-call guard. Not a security boundary for arbitrary native code."""
from contextlib import ExitStack
import sys
import types
from unittest.mock import patch

class SolveForbidden(RuntimeError):
    pass

class ZeroSolveGuard:
    current = None
    def __init__(self):
        self.blocked={"cpsat_api":0,"native_factory":0,"oracle":0}
        self.active=False
    def _deny(self,kind):
        def denied(*args,**kwargs):
            self.blocked[kind]+=1
            raise SolveForbidden("P1a forbids "+kind+" execution")
        return denied
    def __enter__(self):
        if self.active or ZeroSolveGuard.current is not None:
            raise RuntimeError("guard cannot be reentered")
        self.stack=ExitStack()
        from ortools.sat.python import cp_model, cp_model_helper
        for name in ("solve","Solve","SolveWithSolutionCallback","SearchForAllSolutions"):
            if hasattr(cp_model.CpSolver,name):
                self.stack.enter_context(patch.object(cp_model.CpSolver,name,self._deny("cpsat_api")))
        self.stack.enter_context(patch.object(cp_model_helper,"SolveWrapper",self._deny("native_factory")))
        old_oracle=sys.modules.get("research.tiny_oracle")
        if old_oracle is not None:
            for name in ("solve","main"):
                if hasattr(old_oracle,name):
                    self.stack.enter_context(patch.object(old_oracle,name,self._deny("oracle")))
        oracle=types.ModuleType("research.tiny_oracle")
        oracle.solve=self._deny("oracle"); oracle.main=self._deny("oracle")
        self.stack.enter_context(patch.dict(sys.modules,{"research.tiny_oracle":oracle}))
        # Existing Oracle-module references, if any, must also be patched.
        parent=sys.modules.get("research")
        if parent is not None:
            self.stack.enter_context(patch.object(parent,"tiny_oracle",oracle,create=True))
        self.active=True
        ZeroSolveGuard.current=self
        return self
    def __exit__(self,*exc):
        self.active=False
        ZeroSolveGuard.current=None
        return self.stack.__exit__(*exc)
    def evidence(self):
        return {"guard_active":self.active,"blocked_attempts":dict(self.blocked),
                "executed_cpsat_calls":0,"executed_oracle_calls":0,
                "scope":"guarded Python APIs; no native constructor or Oracle delegation"}
