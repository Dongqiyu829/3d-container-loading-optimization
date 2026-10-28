from functools import lru_cache
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


@lru_cache(maxsize=1)
def proposal():
    from research.p1e_plan import build_proposal
    return build_proposal(ROOT)
