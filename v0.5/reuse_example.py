#!/usr/bin/env python3
"""Show how review status gates a publisher-linked revision and why a changed baseline is refused.
Produced through an AI-assisted workflow (OpenAI GPT-6; Anthropic Opus 5.5) directed and reviewed by the author."""
import importlib.util
import json
from pathlib import Path

root = Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location("forecast_reproducer", root / "reproduce.py")
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)
data, sources, receipts = module.load(root)
rows = {r["id"]: r for r in data["records"]}
status = module.review_status(data, sources, receipts)
revision = module.compare(rows["O13"], rows["O14"], status)
refused = module.compare(rows["O11"], rows["O12"], status)
if refused["status"] != "not_comparable" or "different base_year" not in refused["reasons"]:
    raise ValueError("The changed-baseline example did not reach its expected state")
if revision["status"] == "conditional_arithmetic" and status["O13"] != "supported":
    raise ValueError("Arithmetic was produced for an observation without a supported review receipt")
print(json.dumps({"purpose": __doc__, "capacity_revision": revision, "changed_baseline": refused,
                  "support_review": {i: status[i] for i in ("O11", "O12", "O13", "O14")}, "source_truth": "not_assessed"}, indent=2, allow_nan=False))
