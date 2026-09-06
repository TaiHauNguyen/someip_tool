#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
someip_update_all.py
====================
Chay MOT LAN ca hai buoc cho TAT CA workbook trong mot thu muc (ke ca thu muc con):

  1. dbc_bitfield_excel.py  -> sheet DataStructures (bitfield struct + enum)
  2. someip_events_excel.py -> sheet Events (PayloadLengthBytes, ParameterType)

Ca hai buoc ghi vao CUNG mot file dau ra, nen ket qua cuoi cung co ca hai sheet
da duoc cap nhat.

Tim file
--------
* Excel : moi *.xlsx duoi --root (de quy). Tu dong bo qua file tam ``~$...``,
          file ``.bak`` va file do chinh tool nay sinh ra
          (``*_bitfield.xlsx``, ``*_events.xlsx``, ``*_updated.xlsx``).
* DBC   : mac dinh lay cac *.dbc nam CUNG THU MUC voi workbook; neu thu muc do
          khong co file .dbc nao thi dung toan bo *.dbc tim duoc duoi --root.
          Co the ep bang --dbc (file hoac thu muc) hoac --dbc-scope.

Che do ghi
----------
* --dry-run  : khong ghi gi, chi in ra nhung gi se sua  (nen chay dau tien)
* --inplace  : ghi de file goc, tu tao ban .bak mot lan cho moi file
* mac dinh   : copy sang ``<ten>_updated.xlsx`` roi sua tren ban copy

Usage
-----
  python someip_update_all.py --root . --dry-run
  python someip_update_all.py --root C:\\...\\filled_services_by_zone_config --inplace
  python someip_update_all.py --root . --dbc SCAN.dbc --only events

Requires: openpyxl, dbc_struct.py, dbc_bitfield_excel.py, someip_events_excel.py
"""

from __future__ import annotations

import argparse
import fnmatch
import os
import shutil
import sys

try:
    import openpyxl
except ImportError:  # pragma: no cover
    sys.exit("Can openpyxl: python -m pip install openpyxl")

import dbc_bitfield_excel
import someip_events_excel

STRUCT_SHEET = "DataStructures"
EVENTS_SHEET = "Events"

SKIP_PATTERNS = ["~$*", "*.bak", "*_bitfield.xlsx", "*_events.xlsx", "*_updated.xlsx"]


# --------------------------------------------------------------------------- #
# Quet file
# --------------------------------------------------------------------------- #
def walk_files(root, ext, exclude):
    out = []
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames
                       if not d.startswith(".")
                       and not any(fnmatch.fnmatch(d, p) for p in exclude)]
        for fn in filenames:
            if not fn.lower().endswith(ext):
                continue
            if any(fnmatch.fnmatch(fn, p) for p in SKIP_PATTERNS + exclude):
                continue
            out.append(os.path.join(dirpath, fn))
    return sorted(out)


def collect_dbc(spec):
    """--dbc nhan file hoac thu muc, tra ve danh sach file .dbc."""
    out = []
    for item in spec:
        if os.path.isdir(item):
            out.extend(walk_files(item, ".dbc", []))
        elif os.path.isfile(item):
            out.append(item)
        else:
            sys.stderr.write("WARN: khong thay '%s'\n" % item)
    return out


def dbc_for(xlsx, scope, all_dbc, forced):
    if forced:
        return forced
    folder = os.path.dirname(os.path.abspath(xlsx))
    local = [d for d in all_dbc if os.path.dirname(os.path.abspath(d)) == folder]
    if scope == "folder":
        return local
    if scope == "root":
        return all_dbc
    return local or all_dbc          # scope == "auto"


def sheets_of(path):
    try:
        wb = openpyxl.load_workbook(path, read_only=True)
        names = list(wb.sheetnames)
        wb.close()
        return names
    except Exception as e:                       # file hong / dang mo / khong phai xlsx
        return e


# --------------------------------------------------------------------------- #
# Goi tung tool
# --------------------------------------------------------------------------- #
def run(module, argv, label):
    """Goi main() cua module, tra ve (rc, loi)."""
    print("\n--- %s ---" % label)
    sys.stdout.flush()
    try:
        rc = module.main(argv)
    except SystemExit as e:                      # cac tool co dung sys.exit("...")
        code = e.code
        if isinstance(code, str):
            sys.stderr.write("%s\n" % code)
            return 1, code
        return int(code or 0), None
    except Exception as e:                       # khong de mot file hong chan ca lo
        sys.stderr.write("LOI: %s: %s\n" % (type(e).__name__, e))
        return 1, "%s: %s" % (type(e).__name__, e)
    return rc, None


# --------------------------------------------------------------------------- #
# main
# --------------------------------------------------------------------------- #
def main(argv=None):
    ap = argparse.ArgumentParser(
        description="Quet thu muc, cap nhat sheet DataStructures va Events tu DBC")
    ap.add_argument("--root", default=".", help="thu muc goc de quet (de quy)")
    ap.add_argument("--dbc", nargs="*", default=None,
                    help="ep dung file/thu muc .dbc nay cho moi workbook")
    ap.add_argument("--dbc-scope", choices=["auto", "folder", "root"], default="auto",
                    help="auto: uu tien .dbc cung thu muc, khong co thi lay toan bo")
    ap.add_argument("--only", choices=["both", "struct", "events"], default="both")
    ap.add_argument("--exclude", nargs="*", default=[],
                    help="mau ten file/thu muc bo qua, vd: *_old.xlsx backup")
    ap.add_argument("--dry-run", action="store_true", help="khong ghi gi, chi in")
    ap.add_argument("--inplace", action="store_true", help="ghi de file goc, tao .bak")
    ap.add_argument("--suffix", default="_updated",
                    help="hau to file dau ra khi khong dung --inplace")
    ap.add_argument("--continue-on-error", action="store_true",
                    help="gap loi o mot file thi bo qua file do va chay tiep")
    # tuy chon chuyen tiep cho tung tool
    ap.add_argument("--no-reserved", action="store_true",
                    help="[struct] bo cac element Reserved_n")
    ap.add_argument("--fix-serializer", action="store_true",
                    help="[events] sua luon cot Serializer")
    ap.add_argument("--payload-extra", type=int, default=0,
                    help="[events] cong them N byte vao PayloadLengthBytes")
    a = ap.parse_args(argv)

    if a.dry_run and a.inplace:
        sys.exit("--dry-run va --inplace loai tru nhau")
    if not os.path.isdir(a.root):
        sys.exit("Khong phai thu muc: %s" % a.root)

    all_dbc = collect_dbc(a.dbc) if a.dbc else walk_files(a.root, ".dbc", a.exclude)
    forced = collect_dbc(a.dbc) if a.dbc else None
    books = walk_files(a.root, ".xlsx", a.exclude)

    print("Root      : %s" % os.path.abspath(a.root))
    print("Workbook  : %d file" % len(books))
    print("DBC       : %d file" % len(all_dbc))
    print("Che do    : %s" % ("dry-run" if a.dry_run else
                              ("inplace" if a.inplace else "copy -> *%s.xlsx" % a.suffix)))
    if not books:
        sys.exit("Khong tim thay .xlsx nao duoi %s" % a.root)
    if not all_dbc:
        sys.exit("Khong tim thay .dbc nao. Dung --dbc de chi dinh.")

    summary = []
    for xlsx in books:
        rel = os.path.relpath(xlsx, a.root)
        print("\n" + "=" * 78)
        print("FILE: %s" % rel)
        print("=" * 78)

        names = sheets_of(xlsx)
        if isinstance(names, Exception):
            print("  Bo qua: khong doc duoc (%s)" % names)
            summary.append((rel, "-", "-", "khong doc duoc"))
            continue

        do_struct = a.only in ("both", "struct") and STRUCT_SHEET in names
        do_events = a.only in ("both", "events") and EVENTS_SHEET in names
        if not do_struct and not do_events:
            print("  Bo qua: khong co sheet %s / %s" % (STRUCT_SHEET, EVENTS_SHEET))
            summary.append((rel, "-", "-", "khong co sheet can sua"))
            continue

        dbcs = dbc_for(xlsx, a.dbc_scope, all_dbc, forced)
        if not dbcs:
            print("  Bo qua: khong co .dbc tuong ung (scope=%s)" % a.dbc_scope)
            summary.append((rel, "-", "-", "khong co dbc"))
            continue
        print("  DBC dung: %s" % ", ".join(os.path.relpath(d, a.root) for d in dbcs))

        # ---- xac dinh file dich (ca hai buoc ghi vao cung file nay)
        if a.dry_run:
            target = xlsx
        elif a.inplace:
            target = xlsx
            bak = xlsx + ".bak"
            shutil.copy2(xlsx, bak)
            print("  Sao luu : %s" % os.path.relpath(bak, a.root))
        else:
            stem, ext = os.path.splitext(xlsx)
            target = stem + a.suffix + ext
            shutil.copy2(xlsx, target)
            print("  Ban sao : %s" % os.path.relpath(target, a.root))

        st_rc = ev_rc = None

        if do_struct:
            argv1 = ["--excel", target, "--dbc"] + dbcs
            if a.no_reserved:
                argv1.append("--no-reserved")
            if a.dry_run:
                argv1.append("--dry-run")
            else:
                argv1 += ["--out", target]       # ghi de chinh no, khong tao them .bak
            st_rc, _ = run(dbc_bitfield_excel, argv1, "DataStructures")

        if do_events:
            if st_rc not in (None, 0) and not a.continue_on_error:
                print("\n  Bo qua buoc Events vi buoc truoc loi (rc=%s). "
                      "Dung --continue-on-error de van chay tiep." % st_rc)
            else:
                argv2 = ["--excel", target, "--dbc"] + dbcs
                if a.fix_serializer:
                    argv2.append("--fix-serializer")
                if a.payload_extra:
                    argv2 += ["--payload-extra", str(a.payload_extra)]
                if a.dry_run:
                    argv2.append("--dry-run")
                else:
                    argv2 += ["--out", target]
                ev_rc, _ = run(someip_events_excel, argv2, "Events")

        def tag(rc, done):
            if not done:
                return "-"
            return "OK" if rc == 0 else "LOI(rc=%s)" % rc

        out_note = ("dry-run" if a.dry_run
                    else os.path.relpath(target, a.root))
        summary.append((rel, tag(st_rc, do_struct), tag(ev_rc, do_events), out_note))

        if not a.continue_on_error and ((st_rc or 0) != 0 or (ev_rc or 0) != 0):
            print("\nDung lai vi co loi. Dung --continue-on-error de chay het.")
            break

    print("\n" + "=" * 78)
    print("TONG KET")
    print("=" * 78)
    print("%-46s %-10s %-10s %s" % ("FILE", "STRUCT", "EVENTS", "OUTPUT"))
    for rel, st, ev, note in summary:
        show = rel if len(rel) <= 45 else "..." + rel[-42:]
        print("%-46s %-10s %-10s %s" % (show, st, ev, note))

    bad = sum(1 for _r, st, ev, _n in summary if "LOI" in st or "LOI" in ev)
    print("\n%d workbook xu ly, %d loi." % (len(summary), bad))
    if a.dry_run:
        print("--dry-run: khong file nao bi thay doi.")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
