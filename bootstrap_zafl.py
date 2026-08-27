"""Rebuild the ZAFL project from the customer workbooks.

    python someip_tool/bootstrap_zafl.py [base.arxml|base.json]

Nothing here is project specific.  It picks up whatever workbooks sit next to
it, uses the existing ARXML (or a JSON you pass in) as the *base*, and lets the
generic rules in resolve.py fill the gaps the workbooks cannot express:

  * the remote provider endpoint of a consumed service,
  * the type names and <VT> texts the ECU code already uses,
  * struct member types whose declaration is spelled slightly differently.

Every adjustment is printed, so you can see exactly what was taken from where.
"""

from __future__ import annotations

import glob
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, HERE)

import arxml_gen
import arxml_io
import excel_io
import validate as validator
from someip_model import Project


def load_base(path: str):
    if not path or not os.path.exists(path):
        return None
    return Project.from_json(path) if path.lower().endswith(".json") else arxml_io.read(path)


def main(argv=None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    # "~$name.xlsx" is the lock file Excel keeps while the workbook is open
    workbooks = sorted(w for w in glob.glob(os.path.join(ROOT, "*.xlsx"))
                       if not os.path.basename(w).startswith("~$"))
    if not workbooks:
        print("No .xlsx workbook found in", ROOT)
        return 1

    base_path = argv[0] if argv else os.path.join(ROOT, "ZA_someip.arxml")
    base = load_base(base_path)
    print("Workbooks : %s" % ", ".join(os.path.basename(w) for w in workbooks))
    print("Base      : %s" % (os.path.basename(base_path) if base else "(none)"))

    log = []
    prj = excel_io.import_project(workbooks, base, log=log)
    prj.name = os.path.splitext(os.path.basename(base_path))[0] if base else "someip"

    if log:
        print("\nAdjustments:")
        for line in log:
            print("  " + line)

    print("\nValidation:")
    issues = validator.validate(prj)
    for sev, where, msg in issues:
        if sev == "INFO":
            continue
        print("  %-8s %-34s %s" % (sev, where, msg))
    print("  -- " + validator.summary(issues))
    errors = sum(1 for sev, _, _ in issues if sev == validator.ERROR)

    json_path = os.path.join(ROOT, prj.name + ".someip.json")
    arxml_path = os.path.join(ROOT, prj.name + ".generated.arxml")
    prj.to_json(json_path)
    arxml_gen.write(prj, arxml_path)
    print("\nWritten %s\nWritten %s" % (json_path, arxml_path))
    return 1 if errors else 0


if __name__ == "__main__":
    sys.exit(main())
