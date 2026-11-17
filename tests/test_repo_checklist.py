"""Repo checklist: required files, README/ARCHITECTURE headings, LICENSE, decision_log schema, outputs naming."""
import json
import re

import jsonschema
import yaml

from app.config import ROOT

README_HEADINGS = ["Quickstart", "What works and what is mocked", "Architecture", "Models and free resources",
                   "Cost per run", "Demo video", "What our system will NOT do", "How the project stays alive after the hackathon"]
ARCH_HEADINGS = ["Overview", "Phases", "Gates", "Sale to cash", "Data flow", "Built vs. stubbed", "Roadmap"]


def test_required_files_exist():
    for f in ["README.md", "LICENSE", "docker-compose.yml", "decision_log.json", "ARCHITECTURE.md", ".env.example",
              "outputs", "tests", "prompts", "schemas/decision_log.schema.json", "config/models.yaml", "config/mocks.yaml"]:
        assert (ROOT / f).exists(), f


def test_readme_headings_in_order():
    heads = re.findall(r"^## (.+)$", (ROOT / "README.md").read_text(encoding="utf-8"), re.M)
    assert heads[: len(README_HEADINGS)] == README_HEADINGS


def test_readme_quickstart_and_cost():
    t = (ROOT / "README.md").read_text(encoding="utf-8")
    assert "```bash\ndocker compose up\n```" in t
    cost = t.split("## Cost per run")[1].split("\n## ")[0]
    assert "$" in cost


def test_architecture_headings():
    t = (ROOT / "ARCHITECTURE.md").read_text(encoding="utf-8")
    heads = re.findall(r"^## (.+)$", t, re.M)
    assert heads[: len(ARCH_HEADINGS)] == ARCH_HEADINGS
    assert "```mermaid" in t


def test_license_is_apache():
    t = (ROOT / "LICENSE").read_text(encoding="utf-8")
    assert "Apache License" in t and "Version 2.0, January 2004" in t and "END OF TERMS AND CONDITIONS" in t


def test_decision_log_validates():
    schema = json.loads((ROOT / "schemas" / "decision_log.schema.json").read_text(encoding="utf-8"))
    data = json.loads((ROOT / "decision_log.json").read_text(encoding="utf-8"))
    jsonschema.validate(data, schema)


def test_outputs_named_by_phase_and_step():
    pat = re.compile(r"^phase[1-6]_(step\d+|gate)_[\w-]+\.(md|json|csv|txt|html)$")
    allowed = {"payment_test_log.md", "cost.json", "DEMO_RUN.txt", ".gitkeep", "README.md"}
    for p in (ROOT / "outputs").iterdir():
        if p.is_file():
            assert p.name in allowed or pat.match(p.name), p.name


def test_every_mock_is_registered_and_labeled():
    mocks = yaml.safe_load((ROOT / "config" / "mocks.yaml").read_text(encoding="utf-8"))["mocks"]
    assert all(m["label"] in {"MOCKED", "STUBBED"} for m in mocks)
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    for m in mocks:
        assert m["component"].split(" (")[0][:25] in readme, m["component"]


def test_env_example_has_no_secrets():
    t = (ROOT / ".env.example").read_text(encoding="utf-8")
    assert not re.search(r"(sk-[A-Za-z0-9]{10,}|api[_-]?key\s*=\s*\S{8,})", t, re.I)
