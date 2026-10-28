"""Pure external-watchdog decision model; NO child launch/kill/native execution."""
from dataclasses import dataclass
import math
from research.symmetry_guard import SolveForbidden

def _positive(value):
    return type(value) in (int,float) and math.isfinite(value) and value>0

@dataclass(frozen=True)
class Limits:
    cp_calls:int=24
    oracle_calls:int=8
    child_wall_seconds:int=2
    stage_wall_seconds:int=90
    cumulative_cpu_seconds:int=75
    oracle_max_nodes:int=200000
    def validate(self):
        if self!=Limits() or any(type(x) is not int for x in vars(self).values()):
            raise ValueError("unreviewed Stage-A budget")

class BudgetModel:
    """Simulation-only ledger; reservations describe intended attempts, not actual calls."""
    def __init__(self,limits=Limits()):
        limits.validate();self.limits=limits
        self.reservations={"cpsat":0,"oracle":0};self.stopped=False
    def reserve_simulated(self,kind):
        if kind not in self.reservations or self.stopped:
            raise ValueError("invalid/stopped reservation")
        cap=self.limits.cp_calls if kind=="cpsat" else self.limits.oracle_calls
        if self.reservations[kind]>=cap:
            self.stopped=True
            raise ValueError("simulated call cap reached; no retry expansion")
        self.reservations[kind]+=1
        return dict(self.reservations)
    def observe_simulated(self,*,stage_wall,child_wall,cumulative_child_cpu,cpu_accounting_available):
        values=(stage_wall,child_wall,cumulative_child_cpu)
        if type(cpu_accounting_available) is not bool or any(
            type(v) not in (int,float) or not math.isfinite(v) or v<0 for v in values):
            raise ValueError("invalid watchdog observations")
        reason=("cpu_accounting_unavailable" if not cpu_accounting_available else
                "stage_wall_limit" if stage_wall>=self.limits.stage_wall_seconds else
                "child_wall_limit" if child_wall>=self.limits.child_wall_seconds else
                "cumulative_cpu_limit" if cumulative_child_cpu>=self.limits.cumulative_cpu_seconds else None)
        if reason:self.stopped=True
        return {"reason":reason,"stop_stage":self.stopped,
                "owned_child_action":"terminate_then_kill_if_still_alive" if self.stopped else "continue",
                "simulation_only":True,"os_enforcement_calibrated":False}
    def launch(self,*args,**kwargs):
        raise SolveForbidden("external process supervisor/approval not installed in P1b")
