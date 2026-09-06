#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
dbc_bitfield_excel.py
=====================

Sinh BITFIELD STRUCT tu file CAN .dbc va ghi vao sheet ``DataStructures``
cua workbook SOME/IP theo dung format cua khach hang:

    A1 'Enumerate'                                    H1 'Struct'
    A2..F2  Index | Name | Type | Enumerate | Value | Description
                                                      H2..L2  Index | Name | Element | Type | Description

Bitfield struct = map 1:1 voi khung CAN:
  * thu tu element = thu tu tren duong truyen (byte0 truoc, trong byte MSB truoc)
  * do rong = do dai bit trong DBC  -> cot Type ghi "<kieu> : <so bit>"
  * cac khoang trong duoc chen Reserved_n de tong bang DLC*8 bit
  * signal co bang VAL_ -> dung enum type, va enum duoc sinh o khoi Enumerate

Vi tri cot duoc DO tu chinh sheet (tim 'Enumerate' / 'Struct' o dong 1),
khong hard-code, nen file khach doi cot van chay dung.

Usage
-----
    # xem truoc, khong ghi gi
    python dbc_bitfield_excel.py --excel ACU_Provider.xlsx --dbc SCAN.dbc --dry-run

    # giu nguyen bo message dang co trong sheet -> ghi ra file moi
    python dbc_bitfield_excel.py --excel ACU_Provider.xlsx --dbc SCAN.dbc

    # chi dinh message, ghi de tai cho (tu dong tao .bak)
    python dbc_bitfield_excel.py --excel ACU_Provider.xlsx --dbc SCAN.dbc \
        --msg ACU_CRASH_INFO ACU_OCCUPANT_STATUS --inplace

Requires: openpyxl
"""

from __future__ import annotations

import argparse
import os
import re
import shutil
import sys
from copy import copy

try:
    import openpyxl
except ImportError:  # pragma: no cover
    sys.exit("Can openpyxl:  python -m pip install openpyxl")

from dbc_struct import parse_dbc, build_layout, bf_ctype

SHEET_NAME = "DataStructures"


# --------------------------------------------------------------------------- #
# Naming (giu dung quy uoc dang co trong workbook)
# --------------------------------------------------------------------------- #

def camel(text, upper_first=True):
    """``No_Airbag_Deployment`` -> ``NoAirbagDeployment``."""
    parts = [p for p in re.split(r"[^0-9A-Za-z]+", str(text)) if p]
    if not parts:
        return ""
    out = []
    for i, part in enumerate(parts):
        if i == 0 and not upper_first:
            out.append(part[0].lower() + part[1:])
        else:
            out.append(part[0].upper() + part[1:])
    return "".join(out)


def enum_type_name(signal_name):
    """``ACU_Airbag_Deployment_Status`` -> ``ACUAirbagDeploymentStatusType``."""
    return camel(signal_name) + "Type"


def struct_type_name(message_name):
    """``ACU_CRASH_INFO`` -> ``ACUCrashInfoStruct``."""
    parts = [p for p in re.split(r"[^0-9A-Za-z]+", message_name) if p]
    out = []
    for part in parts:
        if part.isupper() and len(part) > 3:
            out.append(part[0] + part[1:].lower())
        elif part.isupper():
            out.append(part)
        else:
            out.append(part[0].upper() + part[1:])
    return "".join(out) + "Struct"


# --------------------------------------------------------------------------- #
# Do vi tri cot cua sheet
# --------------------------------------------------------------------------- #

class SheetMap(object):
    """Vi tri cac cot cua khoi Enumerate va khoi Struct."""

    def __init__(self, ws):
        self.ws = ws
        self.enum = {}
        self.struct = {}
        self.title_row = None
        self.header_row = None
        self._detect()

    def _detect(self):
        ws = self.ws
        enum_col = struct_col = None
        for row in range(1, min(ws.max_row, 10) + 1):
            for col in range(1, ws.max_column + 1):
                v = ws.cell(row, col).value
                if not isinstance(v, str):
                    continue
                key = v.strip().lower()
                if key in ("enumerate", "enum") and enum_col is None:
                    enum_col, self.title_row = col, row
                elif key == "struct" and struct_col is None:
                    struct_col = col
            if enum_col is not None and struct_col is not None:
                break
        if enum_col is None or struct_col is None:
            raise ValueError("Khong tim thay tieu de 'Enumerate' / 'Struct' o dau sheet")

        self.header_row = self.title_row + 1
        hdr = {}
        for col in range(1, ws.max_column + 1):
            v = ws.cell(self.header_row, col).value
            if isinstance(v, str) and v.strip():
                hdr[col] = v.strip().lower()

        def pick(block_start, block_end, wanted):
            for col in range(block_start, block_end):
                name = hdr.get(col, "")
                if name == wanted or name.startswith(wanted):
                    return col
            raise ValueError("Thieu cot '%s' trong dong tieu de %d"
                             % (wanted, self.header_row))

        for k in ("index", "name", "type", "enumerate", "value", "description"):
            self.enum[k] = pick(enum_col, struct_col, k)
        end = ws.max_column + 1
        for k in ("index", "name", "element", "type", "description"):
            self.struct[k] = pick(struct_col, end, k)

        self.first_data_row = self.header_row + 1


# --------------------------------------------------------------------------- #
# Xay du lieu tu DBC
# --------------------------------------------------------------------------- #

def build_enums(messages):
    """Tra ve OrderedDict {enum_type: [(literal, value, description), ...]}.

    Enum trung ten giua cac message duoc gop, va bao loi neu bang gia tri khac nhau.
    """
    enums = {}
    order = []
    for msg in messages:
        for sig in msg.signals:
            if not sig.values:
                continue
            name = enum_type_name(sig.name)
            items = [(camel(sig.values[v]), "0x%X" % v, sig.values[v])
                     for v in sorted(sig.values)]
            if name in enums:
                if enums[name] != items:
                    sys.stderr.write(
                        "WARN: enum '%s' co 2 bang gia tri khac nhau, giu ban dau\n" % name)
                continue
            enums[name] = items
            order.append(name)
    return [(n, enums[n]) for n in order]


def build_struct_rows(msg, include_reserved=True):
    """Cac dong (Element, Type, Description) cho bitfield struct cua 1 message."""
    rows = []
    for f in build_layout(msg):
        b0 = f.wire_start // 8
        p0 = 7 - (f.wire_start % 8)
        p1 = p0 - f.width + 1
        pos = ("byte%d [%d:%d]" % (b0, p0, p1) if p1 >= 0
               else "byte%d..byte%d" % (b0, (f.wire_start + f.width - 1) // 8))

        if f.is_reserved:
            if not include_reserved:
                continue
            rows.append((f.name,
                         "%s : %d" % (bf_ctype(f), f.width),
                         "padding; %s; wire bit %d..%d"
                         % (pos, f.wire_start, f.wire_start + f.width - 1)))
            continue

        sig = f.signal
        base = enum_type_name(sig.name) if sig.values else sig.raw_ctype
        desc = ["%s.%s" % (msg.name, sig.name)]
        if sig.comment:
            desc.append(sig.comment)
        desc.append(pos)
        desc.append("dbc start=%d, len=%d, %s%s"
                    % (sig.start_bit, sig.length,
                       "Motorola" if sig.is_motorola else "Intel",
                       ", signed" if sig.is_signed else ""))
        if sig.unit:
            desc.append("unit=%s" % sig.unit)
        if sig.factor != 1 or sig.offset != 0:
            desc.append("phys=raw*%g%+g" % (sig.factor, sig.offset))
        rows.append((f.name, "%s : %d" % (base, f.width), "; ".join(desc)))
    return rows


def structs_already_in_sheet(ws, smap):
    """Doc ten CAN message dang duoc tham chieu trong sheet, giu thu tu."""
    names = []
    col_desc = smap.struct["description"]
    for row in range(smap.first_data_row, ws.max_row + 1):
        v = ws.cell(row, col_desc).value
        if isinstance(v, str) and "." in v:
            m = re.match(r"\s*([A-Za-z_]\w*)\s*\.", v)
            if m and m.group(1) not in names:
                names.append(m.group(1))
    return names


# --------------------------------------------------------------------------- #
# Ghi sheet
# --------------------------------------------------------------------------- #

def _clear_block(ws, cols, first_row):
    for row in range(first_row, ws.max_row + 1):
        for col in cols:
            ws.cell(row, col).value = None


def _styles(ws, cols, row):
    return {c: copy(ws.cell(row, c)._style) for c in cols}


def write_sheet(ws, smap, enums, structs):
    enum_cols = [smap.enum[k] for k in
                 ("index", "name", "type", "enumerate", "value", "description")]
    struct_cols = [smap.struct[k] for k in
                   ("index", "name", "element", "type", "description")]

    first = smap.first_data_row
    enum_style = _styles(ws, enum_cols, first)
    struct_style = _styles(ws, struct_cols, first)

    _clear_block(ws, enum_cols, first)
    _clear_block(ws, struct_cols, first)

    def put(row, col, value, styles):
        cell = ws.cell(row, col)
        cell._style = copy(styles[col])
        cell.value = value

    # ---- khoi Enumerate
    row = first
    for idx, (type_name, items) in enumerate(enums, start=1):
        for i, (literal, value, desc) in enumerate(items):
            if i == 0:
                put(row, smap.enum["index"], idx, enum_style)
                put(row, smap.enum["name"], type_name, enum_style)
                put(row, smap.enum["type"], "uint8_t", enum_style)
            put(row, smap.enum["enumerate"], literal, enum_style)
            put(row, smap.enum["value"], value, enum_style)
            put(row, smap.enum["description"], desc, enum_style)
            row += 1
    enum_rows = row - first

    # ---- khoi Struct
    row = first
    for idx, (struct_name, rows) in enumerate(structs, start=1):
        for i, (element, ctype, desc) in enumerate(rows):
            if i == 0:
                put(row, smap.struct["index"], idx, struct_style)
                put(row, smap.struct["name"], struct_name, struct_style)
            put(row, smap.struct["element"], element, struct_style)
            put(row, smap.struct["type"], ctype, struct_style)
            put(row, smap.struct["description"], desc, struct_style)
            row += 1
    struct_rows = row - first

    return enum_rows, struct_rows


# --------------------------------------------------------------------------- #
# main
# --------------------------------------------------------------------------- #

def main(argv=None):
    ap = argparse.ArgumentParser(
        description="Sinh bitfield struct tu DBC va ghi vao sheet DataStructures")
    ap.add_argument("--excel", required=True, help="workbook SOME/IP (.xlsx)")
    ap.add_argument("--dbc", required=True, nargs="+", help="mot hoac nhieu file .dbc")
    ap.add_argument("--msg", nargs="*", default=None,
                    help="ten CAN message; mac dinh lay dung bo dang co trong sheet")
    ap.add_argument("--sheet", default=SHEET_NAME)
    ap.add_argument("--out", help="file .xlsx dau ra (mac dinh: <ten>_bitfield.xlsx)")
    ap.add_argument("--inplace", action="store_true", help="ghi de, tao ban .bak")
    ap.add_argument("--dry-run", action="store_true", help="chi in, khong ghi file")
    ap.add_argument("--no-reserved", action="store_true",
                    help="bo cac element Reserved_n (struct se KHONG con 1:1)")
    a = ap.parse_args(argv)

    by_name = {}
    for path in a.dbc:
        for m in parse_dbc(path):
            by_name.setdefault(m.name, m)

    wb = openpyxl.load_workbook(a.excel)
    if a.sheet not in wb.sheetnames:
        sys.exit("Workbook khong co sheet '%s'" % a.sheet)
    ws = wb[a.sheet]
    smap = SheetMap(ws)

    wanted = a.msg if a.msg else structs_already_in_sheet(ws, smap)
    if not wanted:
        sys.exit("Khong xac dinh duoc message nao. Dung --msg de chi dinh.")

    missing = [n for n in wanted if n not in by_name]
    if missing:
        sys.exit("Khong co trong DBC: %s" % ", ".join(missing))

    messages = [by_name[n] for n in wanted]
    enums = build_enums(messages)
    structs = [(struct_type_name(m.name),
                build_struct_rows(m, include_reserved=not a.no_reserved))
               for m in messages]

    print("Sheet    : %s  (Enumerate@col%d, Struct@col%d, dong du lieu tu %d)"
          % (a.sheet, smap.enum["index"], smap.struct["index"], smap.first_data_row))
    print("Message  : %s" % ", ".join(wanted))
    print()
    for m, (sname, rows) in zip(messages, structs):
        total = sum(int(t.rsplit(":", 1)[1]) for _e, t, _d in rows)
        print("%-26s %-24s %2d element, %3d bit / %d byte  %s"
              % (m.name, sname, len(rows), total, m.dlc,
                 "OK" if total == m.dlc * 8 else "!! KHONG KHOP DLC"))
        for element, ctype, _desc in rows:
            print("      %-36s %s" % (element, ctype))
        print()
    print("Enumerate: %d type" % len(enums))

    if a.dry_run:
        print("\n--dry-run: khong ghi file.")
        return 0

    enum_rows, struct_rows = write_sheet(ws, smap, enums, structs)

    if a.inplace:
        out = a.excel
        bak = a.excel + ".bak"
        shutil.copy2(a.excel, bak)
        print("\nBan sao luu -> %s" % bak)
    else:
        out = a.out or (os.path.splitext(a.excel)[0] + "_bitfield.xlsx")

    wb.save(out)
    print("Da ghi %d dong enum, %d dong struct -> %s" % (enum_rows, struct_rows, out))
    return 0


if __name__ == "__main__":
    sys.exit(main())
