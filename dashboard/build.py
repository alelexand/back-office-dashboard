"""Combines the four sources into one data structure and renders the dashboard page."""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path

from .sources import SEVERITY_ORDER, read_einvoices, read_hour_bank, read_payroll, read_robot

TEMPLATE = Path(__file__).with_name("template.html")


@dataclass(frozen=True)
class Assumptions:
    """Minutes a person would spend doing each unit of work by hand. Shown on the page, editable."""

    minutes_per_employee_day: float = 1.0      # checking one employee's punches for one day
    minutes_per_payroll_item: float = 0.5      # comparing one pay item between two systems
    minutes_per_invoice: float = 6.0           # typing and checking one invoice
    minutes_per_portal_task: float = 4.0       # one report download or one form submission


def manual_hours(data: dict, a: Assumptions) -> dict[str, float]:
    parts = {
        "Hour bank": (data["hour_bank"] or {}).get("employee_days", 0) * a.minutes_per_employee_day,
        "Payroll check": (data["payroll"] or {}).get("items_compared", 0) * a.minutes_per_payroll_item,
        "E-invoices": len((data["einvoices"] or {}).get("invoices", [])) * a.minutes_per_invoice,
        "Portal robot": len((data["robot"] or {}).get("tasks", [])) * a.minutes_per_portal_task,
    }
    return {k: round(v / 60, 1) for k, v in parts.items()}


def action_items(data: dict) -> list[dict]:
    """One to-do list for people: everything the automations could not resolve on their own."""
    items = []
    for source, key in (("Hour bank", "hour_bank"), ("Payroll", "payroll"), ("E-invoices", "einvoices")):
        for issue in (data[key] or {}).get("issues", []):
            if issue["severity"] in ("error", "warning"):
                items.append({"source": source, **{k: issue.get(k, "") for k in ("severity", "who", "code", "details")}})
    for task in (data["robot"] or {}).get("tasks", []):
        if task["status"] in ("rejected", "failed"):
            items.append({"source": "Portal robot", "severity": "error" if task["status"] == "failed" else "warning",
                          "who": task["item"], "code": task["status"].upper(), "details": task["details"]})
    items.sort(key=lambda i: (SEVERITY_ORDER.get(i["severity"], 9), i["source"]))
    return items


def collect(hour_bank=None, payroll=None, einvoices=None, robot=None, period: str = "",
            assumptions: Assumptions | None = None) -> dict:
    assumptions = assumptions or Assumptions()
    data = {
        "hour_bank": read_hour_bank(hour_bank),
        "payroll": read_payroll(payroll),
        "einvoices": read_einvoices(einvoices),
        "robot": read_robot(robot),
    }
    data["actions"] = action_items(data)
    data["manual_hours"] = manual_hours(data, assumptions)
    data["assumptions"] = asdict(assumptions)
    data["period"] = period
    data["generated_at"] = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    return data


def render(data: dict) -> str:
    payload = json.dumps(data, ensure_ascii=False, default=str)
    payload = payload.replace("</", "<\\/").replace("<!--", "<\\!--")  # safe inside <script>
    return TEMPLATE.read_text(encoding="utf-8").replace("/*__DATA__*/null", payload)


def build(out: str | Path, **sources) -> Path:
    out = Path(out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(render(collect(**sources)), encoding="utf-8")
    return out
