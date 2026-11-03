"""Which passed shard attempt counts.

Rule (fixed 2026-10-09 22:10 UTC, before any analysis of the duplicated shards): when one shard passed in
more than one attempt (two lanes ran it), the lowest attempt index counts. Later passed attempts are kept
in the raw records and costed, but their decisions are not used.
"""
import json
import re
from pathlib import Path


def counted_audits(model_runs: Path) -> list[Path]:
    best = {}
    for audit_path in sorted(model_runs.rglob("audit.json")):
        if json.loads(audit_path.read_text()).get("passed") is not True:
            continue
        m = re.search(r"_s(\d\d)(?:_r(\d))?", audit_path.parent.name)
        shard, attempt = int(m.group(1)), int(m.group(2) or 0)
        if shard not in best or attempt < best[shard][0]:
            best[shard] = (attempt, audit_path)
    return [best[s][1] for s in sorted(best)]
