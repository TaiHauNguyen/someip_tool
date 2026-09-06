#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
someip_events_excel.py
======================
Cap nhat sheet ``Events`` cua workbook SOME/IP cho khop 1:1 voi file CAN .dbc.

Hai cot duoc sua:
  * PayloadLengthBytes  = DLC cua CAN message (bitfield struct map 1:1 khung CAN)
  * ParameterType       = ten struct sinh tu ten message (giong dbc_bitfield_excel.py)

Cach xac dinh message cho tung dong (theo thu tu uu tien):
  1. cot Description dang ``CAN: <MESSAGE>; <signal>; ...; ECU: <ecu>``
  2. cot ParameterType / Serializer khop voi struct_type_name(<message>) cua DBC
  3. cot Name chua ten message da camel-hoa, vd ...ACUCrashInfoEvent

Kiem tra them (chi canh bao, khong tu sua):
  * Serializer khac ParameterType
  * danh sach signal liet ke trong Description khac voi signal thuc trong DBC
  * tong bit cua cac signal vuot ngoai DLC
  * EventId trung nhau

Usage
-----
  python someip_events_excel.py --excel ACM_1.2_split.xlsx --dbc X.dbc --dry-run
  python someip_events_excel.py --excel ACM_1.2_split.xlsx --dbc X.dbc --dump-header
  python someip_events_excel.py --excel ACM_1.2_split.xlsx --dbc X.dbc --inplace
  python someip_events_excel.py --excel ACM_1.2_split.xlsx --dbc X.dbc --fix-serializer

Requires: openpyxl, dbc_struct.py, dbc_bitfield_excel.py (cung thu muc)
"""

from __future__ import annotations

import argparse
import os
import re
import shutil
import sys

try:
    import openpyxl
    from openpyxl.utils import column_index_from_string, get_column_letter
except ImportError:  # pragma: no cover
    sys.exit("Can openpyxl: python -m pip install openpyxl")

from dbc_struct import parse_dbc, build_layout
from dbc_bitfield_excel import struct_type_name

SHEET_NAME = "Events"

# Cot bat buoc phai tim thay.
REQUIRED = ["name", "payloadlengthbytes", "parametertype", "description"]

ALIASES = {
    "index":                ["index", "idx", "no", "stt", "num"],
    "name":                 ["name", "eventname"],
    "eventid":              ["eventid", "id", "eventidhex"],
    "payloadlengthbytes":   ["payloadlengthbytes", "payloadlength", "payloadlen",
                             "payloadsize", "lengthbytes", "payloadbytes",
                             "payloadlengthbyte", "payload"],
    "maximumsegmentlength": ["maximumsegmentlength", "maxsegmentlength", "maxsegmentlen",
                             "segmentlength"],
    "separationtime":       ["separationtime", "septime", "separation"],
    "serializer":           ["serializer", "serialiser", "serializertype"],
    "transportprotocol":    ["transportprotocol", "protocol", "transport"],
    "eventgroup":           ["eventgroup", "eventgroups", "group"],
    "parameterindex":       ["parameterindex", "paramindex", "paramidx"],
    "parametername":        ["parametername", "paramname"],
    "parametertype":        ["parametertype", "paramtype", "parameterdatatype",
                             "paramdatatype"],
    "parameterdescription": ["parameterdescription", "paramdescription", "paramdesc"],
    "description":          ["description", "desc", "comment", "note", "remark"],
}
# Xep theo do dai giam dan de 'parameterdescription' duoc gan truoc 'description',
# 'parametername' truoc 'name' ...
MATCH_ORDER = ["payloadlengthbytes", "maximumsegmentlength", "parameterdescription",
               "parameterindex", "parametername", "parametertype",
               "transportprotocol", "separationtime", "serializer", "eventgroup",
               "eventid", "description", "index", "name"]


def _norm(v):
    if v is None:
        return ""
    return re.sub(r"[^a-z0-9]+", "", str(v).strip().lower())


class SheetError(Exception):
    pass


# --------------------------------------------------------------------------- #
# Do cot cua sheet Events
# --------------------------------------------------------------------------- #
class EventsMap(object):
    def __init__(self, ws, cols_override=None, verbose=True):
        self.ws = ws
        self.col = {}
        self.header_row = None
        self.notes = []
        self._merged = self._merged_lookup(ws)
        if cols_override:
            self._manual(cols_override)
        else:
            self._detect()
        self.first_data_row = self.header_row + 1
        if verbose:
            for n in self.notes:
                sys.stderr.write("NOTE: %s\n" % n)

    @staticmethod
    def _merged_lookup(ws):
        look = {}
        merged = getattr(ws, "merged_cells", None)
        for rng in (list(merged.ranges) if merged is not None else []):
            top = (rng.min_row, rng.min_col)
            for r in range(rng.min_row, rng.max_row + 1):
                for c in range(rng.min_col, rng.max_col + 1):
                    look[(r, c)] = top
        return look

    def cell_value(self, row, col):
        r, c = self._merged.get((row, col), (row, col))
        return self.ws.cell(r, c).value

    def _manual(self, spec):
        for part in spec.split(","):
            if "=" not in part:
                raise SheetError("--cols dang key=COT, vd: payloadlengthbytes=D")
            k, v = part.split("=", 1)
            k, v = _norm(k), v.strip()
            if k not in ALIASES:
                raise SheetError("Khoa '%s' khong hop le. Cac khoa: %s"
                                 % (k, ", ".join(sorted(ALIASES))))
            self.col[k] = int(v) if v.isdigit() else column_index_from_string(v.upper())
        self.header_row = self._guess_header_row() or 1
        missing = [k for k in REQUIRED if k not in self.col]
        if missing:
            raise SheetError("Thieu cot chi dinh tay: %s" % ", ".join(missing))
        self.notes.append("Dung cot do nguoi dung chi dinh, dong tieu de = %d"
                          % self.header_row)

    def _guess_header_row(self):
        for row in range(1, min(self.ws.max_row, 10) + 1):
            vals = set(_norm(self.cell_value(row, c))
                       for c in range(1, self.ws.max_column + 1))
            if "name" in vals or "eventid" in vals:
                return row
        return None

    def _detect(self):
        ws = self.ws
        best = None
        for row in range(1, min(ws.max_row, 10) + 1):
            hdr = {}
            for col in range(1, ws.max_column + 1):
                n = _norm(self.cell_value(row, col))
                if n:
                    hdr[col] = n
            if not hdr:
                continue
            got = self._match(hdr)
            score = len(got)
            if best is None or score > best[0]:
                best = (score, row, hdr, got)
            if all(k in got for k in REQUIRED):
                break
        if best is None:
            raise SheetError("Sheet trong, khong co dong tieu de.\n" + self.dump_rows(1, 5))
        _score, row, hdr, got = best
        self.header_row, self.col = row, got
        missing = [k for k in REQUIRED if k not in got]
        if missing:
            raise SheetError(
                "Khong xac dinh duoc cot: %s (dong tieu de doan la %d).\n"
                "Doc duoc: %s\n"
                "Cach xu ly: sua ten cot trong Excel, hoac chay lai voi\n"
                "  --cols name=B,payloadlengthbytes=D,parametertype=L,description=N"
                % (", ".join(missing), row,
                   ", ".join("%s='%s'" % (get_column_letter(c), hdr[c])
                             for c in sorted(hdr))))

    @staticmethod
    def _match(hdr):
        used, got = set(), {}
        for key in MATCH_ORDER:                      # vong 1: khop chinh xac
            for c in sorted(hdr):
                if c not in used and hdr[c] in ALIASES[key]:
                    got[key] = c
                    used.add(c)
                    break
        for key in MATCH_ORDER:                      # vong 2: khop chua/bat dau
            if key in got:
                continue
            for c in sorted(hdr):
                if c in used:
                    continue
                h = hdr[c]
                if any(h.startswith(a) or a.startswith(h) for a in ALIASES[key]):
                    got[key] = c
                    used.add(c)
                    break
        return got

    def dump_rows(self, r0, r1):
        out = ["--- Noi dung doc duoc tu sheet ---"]
        for row in range(r0, r1 + 1):
            cells = []
            for col in range(1, min(self.ws.max_column, 30) + 1):
                v = self.cell_value(row, col)
                if v is not None and str(v).strip():
                    s = str(v).strip()
                    cells.append("%s%d='%s'" % (get_column_letter(col), row,
                                                s if len(s) <= 40 else s[:37] + "..."))
            out.append("  row %d: %s" % (row, "  ".join(cells) if cells else "(trong)"))
        return "\n".join(out)

    def describe(self):
        return "Dong tieu de %d; cot: %s" % (
            self.header_row,
            ", ".join("%s=%s" % (k, get_column_letter(self.col[k]))
                      for k in MATCH_ORDER if k in self.col))


# --------------------------------------------------------------------------- #
# Xac dinh CAN message cho tung dong Events
# --------------------------------------------------------------------------- #
RE_CAN_IN_DESC = re.compile(r"CAN\s*:\s*([A-Za-z_]\w*)", re.I)


def signals_in_desc(text):
    """Tach danh sach signal trong 'CAN: MSG; SIG1; SIG2; ECU: ACM'."""
    if not text:
        return []
    parts = [p.strip() for p in str(text).split(";")]
    out = []
    for i, p in enumerate(parts):
        if i == 0 or not p:
            continue
        if re.match(r"^(ECU|CAN)\s*:", p, re.I):
            continue
        out.append(p)
    return out


def resolve_message(row_vals, by_name, by_struct):
    """Tra ve (message, cach_tim_ra) hoac (None, ly_do)."""
    desc = row_vals.get("description")
    if isinstance(desc, str):
        m = RE_CAN_IN_DESC.search(desc)
        if m:
            name = m.group(1)
            if name in by_name:
                return by_name[name], "Description CAN:"
            return None, "Description ghi CAN: %s nhung DBC khong co message nay" % name

    for key in ("parametertype", "serializer"):
        v = row_vals.get(key)
        if isinstance(v, str) and v.strip() in by_struct:
            return by_struct[v.strip()], "cot %s" % key

    name = row_vals.get("name")
    if isinstance(name, str):
        flat = re.sub(r"[^0-9a-z]+", "", name.lower())
        hits = [msg for st, msg in by_struct.items()
                if re.sub(r"[^0-9a-z]+", "", st.lower()).replace("struct", "") in flat]
        if len(hits) == 1:
            return hits[0], "ten Event"
        if len(hits) > 1:
            return None, "ten Event khop nhieu message: %s" % ", ".join(h.name for h in hits)

    return None, "khong xac dinh duoc CAN message"


def payload_bytes(msg, warn):
    """So byte payload = DLC. Kiem tra lai bang layout bit neu co the."""
    try:
        fields = build_layout(msg)
        total = sum(f.width for f in fields)
        if total != msg.dlc * 8:
            warn("%s: tong bit layout (%d) khac DLC*8 (%d)"
                 % (msg.name, total, msg.dlc * 8))
    except ValueError as e:
        warn("%s: khong dung layout 1:1 duoc (%s) - van dung DLC lam payload"
             % (msg.name, e))
    return msg.dlc


# --------------------------------------------------------------------------- #
# main
# --------------------------------------------------------------------------- #
def main(argv=None):
    ap = argparse.ArgumentParser(
        description="Cap nhat PayloadLengthBytes / ParameterType cua sheet Events tu DBC")
    ap.add_argument("--excel", required=True, help="workbook SOME/IP (.xlsx)")
    ap.add_argument("--dbc", required=True, nargs="+", help="mot hoac nhieu file .dbc")
    ap.add_argument("--sheet", default=SHEET_NAME)
    ap.add_argument("--out", help="file .xlsx dau ra (mac dinh: <ten>_events.xlsx)")
    ap.add_argument("--inplace", action="store_true", help="ghi de, tao ban .bak")
    ap.add_argument("--dry-run", action="store_true", help="chi in, khong ghi file")
    ap.add_argument("--payload-extra", type=int, default=0, metavar="N",
                    help="cong them N byte vao PayloadLengthBytes (mac dinh 0 = dung DLC)")
    ap.add_argument("--fix-serializer", action="store_true",
                    help="sua luon cot Serializer cho bang ParameterType")
    ap.add_argument("--dump-header", action="store_true",
                    help="in 8 dong dau cua sheet roi thoat (chan doan cot)")
    ap.add_argument("--cols", help="chi dinh tay cot, vd: name=B,payloadlengthbytes=D,"
                                   "parametertype=L,description=N")
    a = ap.parse_args(argv)

    warnings = []

    def warn(m):
        warnings.append(m)
        sys.stderr.write("WARN: %s\n" % m)

    wb = openpyxl.load_workbook(a.excel)
    if a.sheet not in wb.sheetnames:
        sys.exit("Workbook khong co sheet '%s'. Sheet dang co: %s"
                 % (a.sheet, ", ".join(wb.sheetnames)))
    ws = wb[a.sheet]

    if a.dump_header:
        probe = EventsMap.__new__(EventsMap)
        probe.ws = ws
        probe._merged = EventsMap._merged_lookup(ws)
        print(probe.dump_rows(1, min(8, ws.max_row)))
        return 0

    try:
        emap = EventsMap(ws, a.cols)
    except SheetError as e:
        sys.stderr.write("LOI DO COT:\n%s\n" % e)
        return 2

    by_name = {}
    for path in a.dbc:
        for m in parse_dbc(path):
            by_name.setdefault(m.name, m)
    by_struct = {}
    for m in by_name.values():
        by_struct.setdefault(struct_type_name(m.name), m)

    print("Sheet   : %s" % a.sheet)
    print(emap.describe())
    print("DBC     : %d message" % len(by_name))
    print()

    col = emap.col
    changes = []          # (row, cot, cu, moi)
    unresolved = []
    seen_eventid = {}

    for row in range(emap.first_data_row, ws.max_row + 1):
        row_vals = dict((k, ws.cell(row, c).value) for k, c in col.items())
        if not any(v is not None and str(v).strip() for v in row_vals.values()):
            continue

        ev_name = row_vals.get("name")
        if not (isinstance(ev_name, str) and ev_name.strip()):
            continue

        # EventId trung
        if "eventid" in col:
            eid = row_vals.get("eventid")
            if eid is not None and str(eid).strip():
                key = str(eid).strip().lower()
                if key in seen_eventid:
                    warn("EventId %s trung o dong %d va %d"
                         % (eid, seen_eventid[key], row))
                else:
                    seen_eventid[key] = row

        msg, how = resolve_message(row_vals, by_name, by_struct)
        if msg is None:
            unresolved.append((row, ev_name, how))
            continue

        want_type = struct_type_name(msg.name)
        want_len = payload_bytes(msg, warn) + a.payload_extra

        # --- PayloadLengthBytes
        cur_len = row_vals.get("payloadlengthbytes")
        cur_len_i = None
        if cur_len is not None and str(cur_len).strip():
            try:
                cur_len_i = int(str(cur_len).strip(), 0)
            except ValueError:
                cur_len_i = None
        if cur_len_i != want_len:
            changes.append((row, "PayloadLengthBytes", cur_len, want_len,
                            col["payloadlengthbytes"]))

        # --- ParameterType
        cur_type = row_vals.get("parametertype")
        if (str(cur_type).strip() if cur_type is not None else "") != want_type:
            changes.append((row, "ParameterType", cur_type, want_type,
                            col["parametertype"]))

        # --- Serializer (chi sua khi duoc yeu cau)
        if "serializer" in col:
            cur_ser = row_vals.get("serializer")
            cur_ser_s = str(cur_ser).strip() if cur_ser is not None else ""
            if cur_ser_s != want_type:
                if a.fix_serializer:
                    changes.append((row, "Serializer", cur_ser, want_type,
                                    col["serializer"]))
                else:
                    warn("dong %d: Serializer='%s' khac ParameterType='%s' "
                         "(dung --fix-serializer de sua)" % (row, cur_ser_s, want_type))

        # --- doi chieu danh sach signal trong Description
        listed = signals_in_desc(row_vals.get("description"))
        if listed:
            real = set(s.name for s in msg.signals)
            extra = [s for s in listed if s not in real]
            miss = [s for s in sorted(real) if s not in listed]
            if extra:
                warn("dong %d (%s): Description co signal khong co trong DBC: %s"
                     % (row, msg.name, ", ".join(extra)))
            if miss:
                warn("dong %d (%s): Description thieu signal cua DBC: %s"
                     % (row, msg.name, ", ".join(miss)))

        print("row %-4d %-38s -> %-14s DLC=%-3d %s  [%s]"
              % (row, ev_name, msg.name, msg.dlc, want_type, how))

    print()
    if unresolved:
        print("Khong map duoc %d dong:" % len(unresolved))
        for row, name, why in unresolved:
            print("  row %-4d %-38s %s" % (row, name, why))
        print()

    if not changes:
        print("Khong co gi phai sua - sheet da khop DBC.")
    else:
        print("Can sua %d o:" % len(changes))
        for row, what, old, new, _c in changes:
            print("  row %-4d %-18s %-28s -> %s"
                  % (row, what, repr(old), new))
    if warnings:
        print("\nCanh bao: %d (xem stderr)" % len(warnings))

    if a.dry_run:
        print("\n--dry-run: khong ghi file.")
        return 0
    if not changes:
        return 0

    for row, _what, _old, new, c in changes:
        ws.cell(row, c).value = new

    if a.inplace:
        out = a.excel
        bak = a.excel + ".bak"
        shutil.copy2(a.excel, bak)
        print("\nBan sao luu -> %s" % bak)
    else:
        out = a.out or (os.path.splitext(a.excel)[0] + "_events.xlsx")

    wb.save(out)
    print("Da sua %d o -> %s" % (len(changes), out))
    return 0


if __name__ == "__main__":
    sys.exit(main())
