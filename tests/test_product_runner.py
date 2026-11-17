"""The product test runner is plain code; its exit code is the Build gate."""
import json
import subprocess
import sys

from app.agents import builder
from app.config import ROOT
from app.models import GuidePack, GuideSection

BODY = ("Write down every unpaid invoice with its due date and the client contact. Send a short and polite reminder "
        "the day after the due date, then a firmer note after one week.")


def _pack(headings):
    return GuidePack(title="Get Paid", intro="A guide.", sections=[GuideSection(heading=h, body_markdown=BODY) for h in headings])


def _run(tmp_path, pack, spec):
    builder.write(pack, tmp_path / "p")
    (tmp_path / "spec.json").write_text(json.dumps(spec))
    return subprocess.run([sys.executable, "-m", "app.product.test_runner", str(tmp_path / "p"), str(tmp_path / "spec.json")],
                          cwd=ROOT, capture_output=True, text=True).returncode


SPEC = {"required_headings": ["Start", "Remind", "Follow Up"], "min_sections": 3, "min_words_per_section": 15,
        "forbidden_phrases": ["guaranteed income"], "max_spelling_error_rate": 0.1}


def test_runner_passes_good_pack(tmp_path):
    assert _run(tmp_path, _pack(["Start", "Remind", "Follow Up"]), SPEC) == 0


def test_runner_fails_missing_heading(tmp_path):
    assert _run(tmp_path, _pack(["Start", "Remind", "Other"]), SPEC) == 1
