"""Headless runs (for timing, the recorded STOP run, and committing demo outputs).

  python -m app.cli run --brief evals/briefs/invoice_templates.json
  python -m app.cli run --brief evals/briefs/crowded_todo_app.json --decide STOP --publish
  python -m app.cli decide <run_id> <gate> <CHOICE> --reason "..."
  python -m app.cli publish <run_id>
  python -m app.cli vram     # nvidia-smi snapshot

The person typing --decide is the founder; the CLI records the decision as the founder's.
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
import threading
import time
from pathlib import Path

from app import llm
from app.models import FounderInput
from app.orchestrator import orchestrator as orch
from app.services import decision_log


def _vram_sampler(stop: threading.Event, samples: list[int]) -> None:
    while not stop.is_set():
        try:
            out = subprocess.run(["nvidia-smi", "--query-gpu=memory.used", "--format=csv,noheader,nounits"],
                                 capture_output=True, text=True, timeout=5).stdout
            samples.append(sum(int(x) for x in out.split() if x.strip().isdigit()))
        except Exception:
            return
        stop.wait(2)


def cmd_run(a: argparse.Namespace) -> int:
    data = json.loads(Path(a.brief).read_text(encoding="utf-8"))
    fi = FounderInput(**data.get("founder_input", data))
    for w in llm.config_warnings():
        print("CONFIG WARNING:", w)
    stop, samples = threading.Event(), []
    threading.Thread(target=_vram_sampler, args=(stop, samples), daemon=True).start()
    t0 = time.time()
    st = orch.start(fi, background=False)
    elapsed = time.time() - t0
    stop.set()
    rid = st["id"]
    print(f"run_id={rid} status={st['status']} elapsed={elapsed:.1f}s peak_vram_mib={max(samples) if samples else 'n/a'}")
    if st["status"] != "awaiting_founder":
        print("error/blocked:", st.get("error"))
        return 0 if st["status"] == "blocked" else 1
    rec = st["gates"]["desk_evidence"]
    print("desk gate verdict (code):", rec["result"]["verdict"])
    print("explanation:", rec["explanation"])
    for c in rec["result"]["checks"]:
        print(f"  - {c['name']}: {c['value']} (threshold {c['threshold']}) pass={c['passed']}")
    timing = {"run_id": rid, "profile": st["profile"], "intake_to_desk_verdict_s": round(elapsed, 1),
              "peak_vram_mib": max(samples) if samples else None, "measured_at": st["created_at"]}
    (decision_log.run_dir(rid) / "timing.json").write_text(json.dumps(timing, indent=1), encoding="utf-8")
    if a.decide:
        orch.decide(rid, "desk_evidence", a.decide, a.reason or "", background=False)
        print("founder decision recorded:", a.decide, "->", orch.load(rid)["status"])
    if a.publish:
        print("published:", orch.publish(rid))
    return 0


def cmd_decide(a: argparse.Namespace) -> int:
    orch.decide(a.run_id, a.gate, a.choice, a.reason or "", background=False)
    print(orch.load(a.run_id)["status"])
    return 0


def cmd_publish(a: argparse.Namespace) -> int:
    print(orch.publish(a.run_id))
    return 0


def cmd_vram(_: argparse.Namespace) -> int:
    return subprocess.call(["nvidia-smi"])


def main() -> int:
    p = argparse.ArgumentParser(prog="venture")
    sub = p.add_subparsers(dest="cmd", required=True)
    r = sub.add_parser("run")
    r.add_argument("--brief", required=True)
    r.add_argument("--decide", choices=["GO", "STOP", "PARK", "PIVOT_BACK", "REPEAT"])
    r.add_argument("--reason", default="")
    r.add_argument("--publish", action="store_true")
    r.set_defaults(fn=cmd_run)
    d = sub.add_parser("decide")
    d.add_argument("run_id")
    d.add_argument("gate")
    d.add_argument("choice")
    d.add_argument("--reason", default="")
    d.set_defaults(fn=cmd_decide)
    pu = sub.add_parser("publish")
    pu.add_argument("run_id")
    pu.set_defaults(fn=cmd_publish)
    v = sub.add_parser("vram")
    v.set_defaults(fn=cmd_vram)
    a = p.parse_args()
    return a.fn(a)


if __name__ == "__main__":
    sys.exit(main())
