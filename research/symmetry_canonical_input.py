"""Canonical prevalidation only. This module cannot invoke the Oracle."""
from dataclasses import dataclass
import hashlib
import json
from pathlib import Path

from baseline_common import load_instance


@dataclass(frozen=True)
class OracleInput:
    """Detached validated JSON snapshot, not an execution authorization."""
    canonical_json: bytes
    sha256: str
    instance_id: str

    def raw_copy(self):
        # Each consumer gets a new object; mutation cannot alter the snapshot.
        return json.loads(self.canonical_json)


def load_oracle_input(path: str | Path) -> OracleInput:
    # load_instance reads once and invokes the original validator with an empty
    # witness. Never reopen the path to obtain the raw JSON after validation.
    instance = load_instance(path)
    data = json.dumps(instance.raw, sort_keys=True, separators=(",", ":"),
                      ensure_ascii=False, allow_nan=False).encode("utf-8")
    return OracleInput(data, hashlib.sha256(data).hexdigest(), instance.instance_id)
