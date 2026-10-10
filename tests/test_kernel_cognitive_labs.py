"""Kernel cognitive pickup must see F&O admissions, not only the equity home lab."""

from __future__ import annotations

import json
from pathlib import Path

from atlas.agent_kernel.kernel import AgentKernel
from atlas.investment.cognitive.queue import STATUS_ADMITTED


def test_cognitive_payloads_scan_fno_lab(tmp_path: Path):
    lab = "india_fno_learner"
    qdir = tmp_path / "investment" / "cognitive" / "queue"
    qdir.mkdir(parents=True)
    (qdir / f"{lab}.jsonl").write_text(
        json.dumps(
            {
                "version": "cognitive.queue.v1",
                "laboratory_id": lab,
                "hypothesis_id": "5623ea11-016e-4a70-8843-3908ff3d4c48",
                "dimension": "underlier_direction",
                "status": STATUS_ADMITTED,
                "statement": "up matched more often than down",
                "falsifier": "gap below 0.5",
                "experiment_spec": {
                    "evaluable": True,
                    "baseline_required": True,
                    "dimension": "underlier_direction",
                    "groups": ["up", "down"],
                },
            }
        )
        + "\n",
        encoding="utf-8",
    )
    # Equity-defaulted kernel must still see the F&O admission.
    kernel = AgentKernel(tmp_path, laboratory_id="india_equity_learner")
    payloads = kernel._cognitive_payloads()
    assert len(payloads) == 1
    assert payloads[0]["laboratory_id"] == lab
    assert payloads[0]["hypothesis_id"].startswith("5623ea11")
    assert payloads[0]["priority_class"] == "P3"
