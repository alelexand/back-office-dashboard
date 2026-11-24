import json
import re
import sqlite3
from pathlib import Path

import pytest

from dashboard import Assumptions, build, collect, render
from dashboard.cli import main
from dashboard.sources import read_einvoices, read_hour_bank, read_payroll, read_robot

INPUTS = Path(__file__).resolve().parent.parent / "sample_inputs"
HOUR_BANK = INPUTS / "hour_bank_2026-10.xlsx"
PAYROLL = INPUTS / "payroll_reconciliation_2026-10.xlsx"
EINVOICES = INPUTS / "einvoices.sqlite"
ROBOT = INPUTS / "robot" / "summary.xlsx"
ALL = dict(hour_bank=HOUR_BANK, payroll=PAYROLL, einvoices=EINVOICES, robot=ROBOT)


def test_hour_bank_reader():
    h = read_hour_bank(HOUR_BANK)
    assert len(h["employees"]) == 8
    hugo = next(e for e in h["employees"] if e["name"] == "Hugo Martins")
    assert hugo["closing_h"] > 11
    assert {i["code"] for i in h["issues"]} >= {"MISSING_PUNCH", "SHORT_REST", "ABSENCE"}
    assert h["employee_days"] == 8 * 31


def test_payroll_reader():
    p = read_payroll(PAYROLL)
    assert len(p["employees"]) == 12          # the "Total net" row is not an employee
    assert p["labels"] == ["HR system", "Payroll provider"]
    assert p["net_difference"] == pytest.approx(589.53)
    luca = next(e for e in p["employees"] if e["name"] == "Luca Bianchi")
    assert luca["net_a"] is None and luca["status"].startswith("Missing")


def test_einvoice_reader_excludes_duplicates():
    e = read_einvoices(EINVOICES)
    assert (len(e["invoices"]), e["files"], e["ready"]) == (8, 10, 4)
    assert e["total_due"] == pytest.approx(5112.14)
    atlantico = next(s for s in e["suppliers"] if s["name"].startswith("Atl"))
    assert atlantico["total"] == pytest.approx(502.86)
    vat23 = next(v for v in e["vat"] if v["rate"] == 23)
    assert vat23["taxable"] == pytest.approx(376.25)   # counted once, not twice


def test_robot_reader_keeps_only_file_names():
    r = read_robot(ROBOT)
    assert (r["done"], r["rejected"], r["failed"]) == (9, 3, 0)
    assert all("\\" not in t["result"] and "/" not in t["result"] for t in r["tasks"] if t["task"] == "report")


def test_missing_sources_are_none(tmp_path):
    assert read_hour_bank(tmp_path / "nope.xlsx") is None
    assert read_einvoices(None) is None


def test_action_items_merge_all_sources_errors_first():
    data = collect(**ALL)
    actions = data["actions"]
    assert {a["source"] for a in actions} == {"Hour bank", "Payroll", "E-invoices", "Portal robot"}
    assert len(actions) == 23
    severities = [a["severity"] for a in actions]
    assert severities == sorted(severities, key=lambda s: s != "error")
    assert not any(a["code"] in ("NON_WORKDAY", "DUPLICATE_PUNCH") for a in actions)   # info only


def test_manual_hours_follow_assumptions():
    base = collect(**ALL)["manual_hours"]
    double = collect(**ALL, assumptions=Assumptions(minutes_per_invoice=12))["manual_hours"]
    assert double["E-invoices"] == pytest.approx(base["E-invoices"] * 2, abs=0.1)
    assert double["Hour bank"] == base["Hour bank"]


def test_render_embeds_data_safely():
    data = collect(**ALL)
    data["actions"].append({"source": "x", "severity": "error", "who": "</script><script>alert(1)</script>",
                            "code": "X", "details": ""})
    html = render(data)
    assert "</script><script>alert(1)" not in html
    payload = re.search(r'<script id="data" type="application/json">(.*?)</script>', html, re.S).group(1)
    assert json.loads(payload)["actions"][-1]["who"].startswith("</script>")


def test_template_never_uses_innerhtml():
    template = (Path(__file__).resolve().parent.parent / "dashboard" / "template.html").read_text(encoding="utf-8")
    assert "innerHTML" not in template   # all data goes through textContent


def test_build_and_cli(tmp_path, capsys):
    out = build(tmp_path / "a.html", **ALL)
    assert "Back-office automation" in out.read_text(encoding="utf-8")
    assert main(["--inputs", str(INPUTS), "--out", str(tmp_path / "b.html"), "--period", "October 2026"]) == 0
    assert main(["--hour-bank", str(HOUR_BANK), "--out", str(tmp_path / "c.html")]) == 0
    assert "no data for payroll" in capsys.readouterr().out
    assert main(["--inputs", str(tmp_path / "empty"), "--out", str(tmp_path / "d.html")]) == 2


def test_sample_inputs_contain_no_local_paths():
    con = sqlite3.connect(EINVOICES)
    files = [r[0] for r in con.execute("select source_file from invoices")]
    assert all("/" not in f and "\\" not in f for f in files)
