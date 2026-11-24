"""Readers for the files produced by the four automations.

Each reader works from the tool's *output* (Excel or SQLite), not its code, so the dashboard
stays decoupled: any tool can be replaced as long as its export keeps the same columns.
A missing or unreadable source returns None and the dashboard shows that section as empty.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

from openpyxl import load_workbook

SEVERITY_ORDER = {"error": 0, "warning": 1, "info": 2}


def _rows(path: Path, sheet: str) -> list[dict[str, object]]:
    wb = load_workbook(path, read_only=True, data_only=True)
    try:
        ws = wb[sheet]
        rows = list(ws.iter_rows(values_only=True))
    finally:
        wb.close()
    if not rows:
        return []
    header = [str(h) if h is not None else "" for h in rows[0]]
    return [dict(zip(header, r)) for r in rows[1:] if any(v is not None for v in r)]


def _col(row: dict, prefix: str, nth: int = 0):
    """Value of the nth column whose header starts with prefix (headers can carry labels)."""
    matches = [k for k in row if k.startswith(prefix)]
    return row[matches[nth]] if len(matches) > nth else None


def read_hour_bank(path: str | Path | None) -> dict | None:
    if not path or not Path(path).exists():
        return None
    path = Path(path)
    employees = [
        {"id": r["Employee ID"], "name": r["Name"], "team": r["Team"],
         "period_h": float(r["Period balance (h)"]), "closing_h": float(r["Closing balance (h)"]),
         "days_with_issues": int(r["Days with issues"] or 0), "errors": int(r["Errors"] or 0)}
        for r in _rows(path, "Summary") if r.get("Employee ID")
    ]
    issues = [
        {"severity": str(r["Severity"]).lower(), "date": str(r["Date"])[:10], "who": r["Name"],
         "code": r["Issue"], "details": r["Details"]}
        for r in _rows(path, "Issues")
    ]
    days = len(_rows(path, "Daily"))
    return {"employees": employees, "issues": issues, "employee_days": days,
            "total_closing_h": round(sum(e["closing_h"] for e in employees), 2)}


def read_payroll(path: str | Path | None) -> dict | None:
    if not path or not Path(path).exists():
        return None
    path = Path(path)
    employees = []
    for r in _rows(path, "Summary"):
        if not r.get("Employee ID"):
            continue  # blank line and the "Total net" row
        net_a, net_b = _col(r, "Net ("), _col(r, "Net (", 1)
        employees.append({"id": r["Employee ID"], "name": r["Name"], "status": r["Status"],
                          "net_a": float(net_a) if net_a is not None else None,
                          "net_b": float(net_b) if net_b is not None else None,
                          "net_difference": float(r["Net difference"] or 0), "issues": int(r["Issues"] or 0)})
    issues = [{"severity": str(r["Severity"]).lower(), "who": r["Name"], "code": r["Issue"], "details": r["Details"]}
              for r in _rows(path, "Issues")]
    header = next(iter(_rows(path, "Summary")), {})
    labels = [k[len("Net ("):-1] for k in header if k.startswith("Net (")]
    return {"employees": employees, "issues": issues, "items_compared": len(_rows(path, "Items")),
            "labels": labels or ["A", "B"],
            "net_difference": round(sum(e["net_difference"] for e in employees), 2)}


def read_einvoices(path: str | Path | None) -> dict | None:
    if not path or not Path(path).exists():
        return None
    con = sqlite3.connect(f"file:{Path(path).as_posix()}?mode=ro", uri=True)
    con.row_factory = sqlite3.Row
    try:
        invoices = [dict(r) for r in con.execute(
            "SELECT source_file, doc_type, number, seller_name, issue_date, payable, status FROM invoices ORDER BY issue_date")]
        issues = [dict(r) for r in con.execute(
            "SELECT source_file, invoice_number, severity, code, rule, message FROM issues")]
        duplicates = {i["source_file"] for i in issues if i["code"] == "DUPLICATE_INVOICE"}
        suppliers: dict[str, float] = {}
        for inv in invoices:
            if inv["source_file"] not in duplicates:
                suppliers[inv["seller_name"]] = suppliers.get(inv["seller_name"], 0.0) + inv["payable"]
        vat = [dict(r) for r in con.execute(
            "SELECT v.category, v.rate, ROUND(SUM(v.taxable), 2) AS taxable, ROUND(SUM(v.tax), 2) AS tax "
            "FROM vat_breakdown v WHERE v.source_file NOT IN "
            "(SELECT source_file FROM issues WHERE code = 'DUPLICATE_INVOICE') "
            "GROUP BY v.category, v.rate ORDER BY tax DESC")]
    finally:
        con.close()
    unreadable = sorted({i["source_file"] for i in issues if i["code"] == "UNREADABLE_FILE"})
    return {
        "invoices": invoices,
        "issues": [{"severity": i["severity"], "who": i["source_file"], "code": i["code"],
                    "details": i["message"]} for i in issues],
        "suppliers": sorted(({"name": k, "total": round(v, 2)} for k, v in suppliers.items()), key=lambda s: -s["total"]),
        "vat": vat,
        "files": len(invoices) + len(unreadable),
        "ready": sum(1 for i in invoices if i["status"] == "ok"),
        "total_due": round(sum(s for s in suppliers.values()), 2),
    }


def read_robot(path: str | Path | None) -> dict | None:
    if not path or not Path(path).exists():
        return None
    tasks = [{"task": r["Task"], "item": r["Item"], "status": str(r["Status"]).lower(),
              "result": Path(str(r["Result"])).name if r["Result"] and r["Task"] == "report" else (r["Result"] or ""),
              "details": r["Details"] or "", "attempts": int(r["Attempts"] or 0), "seconds": float(r["Seconds"] or 0)}
             for r in _rows(Path(path), "Run summary")]
    count = {s: sum(1 for t in tasks if t["status"] == s) for s in ("done", "rejected", "failed")}
    return {"tasks": tasks, **count, "retries": sum(max(t["attempts"] - 1, 0) for t in tasks),
            "seconds": round(sum(t["seconds"] for t in tasks), 1)}
