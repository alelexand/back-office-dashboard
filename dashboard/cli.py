"""python -m dashboard --hour-bank X.xlsx --payroll Y.xlsx --einvoices Z.sqlite --robot R.xlsx --out site/index.html"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from .build import Assumptions, build


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="dashboard", description="Build the back-office automation dashboard.")
    p.add_argument("--inputs", type=Path, help="folder with the default file names (see sample_inputs/)")
    p.add_argument("--hour-bank", type=Path, help="hour-bank-checker Excel report")
    p.add_argument("--payroll", type=Path, help="payroll-reconciliation Excel report")
    p.add_argument("--einvoices", type=Path, help="einvoice-reader SQLite database")
    p.add_argument("--robot", type=Path, help="portal-robot summary.xlsx")
    p.add_argument("--period", default="", help='label shown in the header, e.g. "October 2026"')
    p.add_argument("--assumptions", type=Path, help="JSON file overriding the minutes-per-task assumptions")
    p.add_argument("--out", type=Path, default=Path("site/index.html"))
    args = p.parse_args(argv)

    sources = {"hour_bank": args.hour_bank, "payroll": args.payroll, "einvoices": args.einvoices, "robot": args.robot}
    if args.inputs:
        defaults = {"hour_bank": next(iter(sorted(args.inputs.glob("hour_bank_*.xlsx"))), None),
                    "payroll": next(iter(sorted(args.inputs.glob("payroll_reconciliation*.xlsx"))), None),
                    "einvoices": args.inputs / "einvoices.sqlite",
                    "robot": args.inputs / "robot" / "summary.xlsx"}
        sources = {k: v or defaults[k] for k, v in sources.items()}
    missing = [k for k, v in sources.items() if not v or not Path(v).exists()]
    if len(missing) == len(sources):
        print("error: no input files found", file=sys.stderr)
        return 2

    assumptions = Assumptions(**json.loads(args.assumptions.read_text())) if args.assumptions else Assumptions()
    out = build(args.out, **sources, period=args.period, assumptions=assumptions)
    for name in missing:
        print(f"  note: no data for {name.replace('_', ' ')}; that section will be empty")
    print(f"  Dashboard: {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
