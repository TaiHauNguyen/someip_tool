#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
split_someip_events.py
======================
Tach mot SOME/IP event dang "gop" nhieu CAN message thanh nhieu event rieng,
moi event = 1 CAN message.

QUY TAC PHAT HIEN (theo yeu cau):
  - Sheet "DataStructures", bang "Struct" (cot Index / Name / Element / Type / Description).
  - Voi moi event trong sheet "Events", lay ParameterType -> do la struct cua event.
  - Neu struct do co >= 2 element  ->  event gop  ->  tach.
    (Them mot chot an toan: chi tach khi TAT CA element cua struct do lai la struct khac,
     tuc la moi element = 1 CAN message. Neu element la kieu enum/primitive thi day la
     event 1 CAN message da duoc flatten -> KHONG tach, chi bao cao.)
  - Struct co 1 element -> giu nguyen.

CACH DUNG:
    python split_someip_events.py input.xlsx
    python split_someip_events.py input.xlsx -o output.xlsx
    python split_someip_events.py input.xlsx --dry-run      # chi in bao cao, khong ghi file

KHONG BAO GIO ghi de len file goc: mac dinh xuat ra "<ten file>_split.xlsx".

Yeu cau: pip install openpyxl
"""

import argparse
import os
import re
import sys
from copy import copy

try:
    from openpyxl import load_workbook
except ImportError:
    sys.exit("Thieu thu vien openpyxl. Chay: pip install openpyxl")


# =============================================================================
# CAU HINH  -  sua o day neu quy uoc cua du an khac
# =============================================================================

SHEET_EVENTS = "Events"
SHEET_DATASTRUCT = "DataStructures"

# Cach dat ten event moi:
#   "element" -> lay ten element cua struct cha, viet hoa chu dau
#                acuCrashInfo  ->  ACMIVA20ms + AcuCrashInfo + Event
#   "canmsg"  -> lay ten CAN message trong cot Description cua element
#                ACU_CRASH_INFO -> ACMIVA20ms + ACUCrashInfo + Event
NAME_STYLE = "element"

# Cach cap EventId cho cac event moi:
#   "offset"       -> event con thu k (k=1,2,3...) = EventId goc + k * EVENT_ID_CHILD_STEP
#                     Vi du 0x8002 tach thanh 2  ->  0x8102, 0x8202
#   "keep_first"   -> event con dau tien giu nguyen EventId cu, cac con sau lay max+1
#   "reassign_all" -> tat ca event con deu lay id moi tu max+1
EVENT_ID_MODE = "offset"

# Buoc cong cho mode "offset". 0x100 = cong vao byte thu 2 tu phai sang.
EVENT_ID_CHILD_STEP = 0x100

# Tinh lai PayloadLengthBytes cho tung event con (= tong size cac element cua sub-struct).
RECALC_PAYLOAD_LENGTH = True

# Xoa cac struct "vo boc" (vd ACMIVA20msStruct) khoi sheet DataStructures sau khi tach,
# vi khong con event nao tham chieu toi chung nua.
REMOVE_UNUSED_WRAPPER_STRUCTS = True

# Gop cac struct trung lap (vd ACUCrashInfoStruct / ...Struct2 / ...Struct3 giong het nhau)
# thanh 1 struct duy nhat, va sua moi tham chieu sang ten duoc giu lai.
DEDUP_STRUCTS = True

# True  -> chi gop khi ca Element + Type + Description deu giong nhau (chat che, an toan)
# False -> chi so sanh Element + Type, bo qua cot Description
DEDUP_MATCH_DESCRIPTION = True

# Format lai ten Element trong bang Struct, lay theo cot Description cua chinh element do.
# Description dang "ACU_CRASH_INFO.ACU_Airbag_Deployment_Status" -> lay phan sau dau '.'
#   "description" -> ACU_Airbag_Deployment_Status   (giong het Description)
#   "pascal"      -> ACUAirbagDeploymentStatus
#   "camel"       -> aCUAirbagDeploymentStatus      (dung nhu file khach dang de)
#   "keep"        -> giu nguyen ten trong file goc, khong doi gi
ELEMENT_NAME_STYLE = "description"

# Danh lai so thu tu cot Index cua sheet Events va bang Struct.
RENUMBER_INDEX = True

# Kich thuoc kieu co ban (byte) de tinh PayloadLengthBytes.
PRIMITIVE_SIZES = {
    "bool": 1, "boolean": 1,
    "uint8_t": 1, "int8_t": 1, "uint8": 1, "int8": 1, "char": 1,
    "uint16_t": 2, "int16_t": 2, "uint16": 2, "int16": 2,
    "uint32_t": 4, "int32_t": 4, "uint32": 4, "int32": 4, "float": 4, "float32": 4,
    "uint64_t": 8, "int64_t": 8, "uint64": 8, "int64": 8, "double": 8, "float64": 8,
}


# =============================================================================
# Tien ich chung
# =============================================================================

def cell_str(value):
    """Doc cell ve chuoi da strip; None/rong -> ''."""
    if value is None:
        return ""
    if isinstance(value, float) and value.is_integer():
        return str(int(value))
    return str(value).strip()


def upper_first(name):
    return name[:1].upper() + name[1:] if name else name


def pascal_from_can_name(can_name):
    """ACU_CRASH_INFO -> ACUCrashInfo (giu nguyen token viet tat <= 3 ky tu: ACU, CAN, ECU...)."""
    out = []
    for tok in re.split(r"[^A-Za-z0-9]+", can_name):
        if not tok:
            continue
        if tok.isupper() and len(tok) <= 3:
            out.append(tok)                                   # ACU, BCM, ECU -> giu nguyen
        elif tok.isupper():
            out.append(tok[:1] + tok[1:].lower())             # INFO -> Info, VOLTAGE -> Voltage
        else:
            out.append(tok[:1].upper() + tok[1:])             # DoorStatus -> DoorStatus (giu chu hoa giua)
    return "".join(out)


def coerce(value):
    """Chuoi chi gom chu so -> ghi ra cell duoi dang so (khong bi 'text' trong Excel)."""
    if isinstance(value, str) and re.fullmatch(r"-?\d+", value.strip()):
        return int(value)
    return value


def copy_style(src_cell, dst_cell):
    if src_cell is None or dst_cell is None:
        return
    try:
        dst_cell._style = copy(src_cell._style)
    except Exception:
        pass


def unmerge_region(ws, min_row, min_col, max_col):
    """Bo merge trong vung sap ghi de lai, tranh loi MergedCell read-only."""
    for rng in list(ws.merged_cells.ranges):
        if rng.max_row >= min_row and not (rng.max_col < min_col or rng.min_col > max_col):
            ws.unmerge_cells(str(rng))


# =============================================================================
# Doc sheet DataStructures
# =============================================================================

def find_marker(ws, marker, limit_rows=30):
    """Tim cell co gia tri == marker trong vung header phia tren."""
    for row in ws.iter_rows(min_row=1, max_row=min(limit_rows, ws.max_row)):
        for c in row:
            if cell_str(c.value).lower() == marker.lower():
                return c.row, c.column
    return None, None


def read_structs(ws):
    """
    Doc bang Struct.
    Tra ve: (structs, layout)
      structs: dict ten_struct -> {"index":.., "elements":[{"name","type","desc","row"}], "first_row":..}
      layout : {"header_row","col_index","col_name","col_element","col_type","col_desc","first_data_row"}
    """
    hrow, ecol = find_marker(ws, "Element")
    if hrow is None:
        raise RuntimeError(
            "Khong tim thay header 'Element' cua bang Struct trong sheet %s." % ws.title)

    layout = {
        "header_row": hrow,
        "col_index": ecol - 2,
        "col_name": ecol - 1,
        "col_element": ecol,
        "col_type": ecol + 1,
        "col_desc": ecol + 2,
        "first_data_row": hrow + 1,
    }

    structs = {}
    order = []
    current = None
    for r in range(layout["first_data_row"], ws.max_row + 1):
        name = cell_str(ws.cell(r, layout["col_name"]).value)
        elem = cell_str(ws.cell(r, layout["col_element"]).value)
        etype = cell_str(ws.cell(r, layout["col_type"]).value)
        edesc = cell_str(ws.cell(r, layout["col_desc"]).value)
        idx = cell_str(ws.cell(r, layout["col_index"]).value)

        if name:
            current = {"name": name, "index": idx, "elements": [], "first_row": r}
            structs[name] = current
            order.append(name)
        if elem and current is not None:
            current["elements"].append(
                {"name": elem, "type": etype, "desc": edesc, "row": r})

    return structs, order, layout


def read_enums(ws):
    """Doc bang Enumerate -> dict ten_enum -> kieu co ban (uint8_t...)."""
    hrow, ecol = find_marker(ws, "Enumeral")
    if hrow is None:
        return {}
    col_name, col_type = ecol - 2, ecol - 1
    enums = {}
    for r in range(hrow + 1, ws.max_row + 1):
        name = cell_str(ws.cell(r, col_name).value)
        typ = cell_str(ws.cell(r, col_type).value)
        if name:
            enums[name] = typ or "uint8_t"
    return enums


def type_size(type_name, structs, enums, _seen=None):
    """Tinh size (byte) cua mot kieu. Tra ve None neu khong xac dinh duoc."""
    _seen = _seen or set()
    t = (type_name or "").strip()
    if not t or t in _seen:
        return None
    _seen = _seen | {t}

    if t.lower() in PRIMITIVE_SIZES:
        return PRIMITIVE_SIZES[t.lower()]
    if t in enums:
        return PRIMITIVE_SIZES.get(enums[t].lower())
    if t in structs:
        total = 0
        for el in structs[t]["elements"]:
            s = type_size(el["type"], structs, enums, _seen)
            if s is None:
                return None
            total += s
        return total
    return None


# =============================================================================
# Format lai ten Element theo cot Description
# =============================================================================

def split_desc(desc):
    """
    Tach Description thanh (ten_CAN_message, ten_signal).

    Description co the kem thuoc tinh phia sau dau ';':
        "BCMFL_Temperature.BCMFL_AmbientTemp; unit=Degree C; factor=0.5; range=-40..85"
    -> phai CAT BO phan tu dau ';' TRUOC, roi moi tach o dau '.' DAU TIEN.
    Neu khong se lay nham '85' trong 'range=-40..85' lam ten signal.
    """
    d = (desc or "").split(";")[0].strip()      # bo unit/factor/offset/range
    if not d:
        return "", ""
    if "." in d:
        msg, sig = d.split(".", 1)              # tach o dau '.' DAU TIEN
        return msg.strip(), sig.strip()
    return d, ""                                # khong co dau '.' -> ca chuoi la ten CAN message


def signal_from_desc(desc):
    """Lay ten signal; neu Description khong co phan signal thi lay ten CAN message."""
    msg, sig = split_desc(desc)
    return sig or msg


def format_element_name(sig, style):
    if not sig:
        return ""
    if style == "description":
        return sig
    tokens = [t for t in re.split(r"[^A-Za-z0-9]+", sig) if t]
    pascal = "".join(
        t if (t.isupper() and len(t) <= 3)
        else (t[:1] + t[1:].lower() if t.isupper() else t[:1].upper() + t[1:])
        for t in tokens)
    if style == "pascal":
        return pascal
    if style == "camel":
        return pascal[:1].lower() + pascal[1:]
    return sig


def rename_elements(structs):
    """
    Doi ten Element theo Description. Element khong co Description thi giu nguyen.
    Tra ve (so_element_da_doi, danh_sach_canh_bao_trung_ten).
    """
    if ELEMENT_NAME_STYLE == "keep":
        return 0, []

    changed = 0
    clashes = []
    for st_name, st in structs.items():
        used = {}
        for el in st["elements"]:
            sig = signal_from_desc(el["desc"])
            new = format_element_name(sig, ELEMENT_NAME_STYLE)
            if not new:
                new = el["name"]
            if new in used:                      # 2 element cung ten sau khi doi
                used[new] += 1
                clashes.append("%s.%s" % (st_name, new))
                new = "%s_%d" % (new, used[new])
            else:
                used[new] = 1
            if new != el["name"]:
                el["name"] = new
                changed += 1
    return changed, clashes


# =============================================================================
# Gop struct trung lap
# =============================================================================

def _pick_canonical(group, order):
    """
    Chon ten dai dien cho 1 nhom struct trung nhau:
      1. Uu tien ten KHONG ket thuc bang chu so  (ACUCrashInfoStruct > ACUCrashInfoStruct2)
      2. Roi den ten ngan hon
      3. Roi den ten xuat hien truoc trong file
    """
    def key(n):
        return (1 if re.search(r"\d+$", n) else 0, len(n), order.index(n))
    return sorted(group, key=key)[0]


def dedup_structs(structs, order):
    """
    Tra ve alias: dict {ten_bi_bo -> ten_giu_lai} va groups de bao cao.
    Lap den khi on dinh, vi struct cha chi trung nhau SAU KHI struct con da duoc gop.
    """
    alias = {}

    def resolve(t):
        seen = set()
        while t in alias and t not in seen:
            seen.add(t)
            t = alias[t]
        return t

    groups_report = []
    for _ in range(50):
        buckets = {}
        for name in order:
            if resolve(name) != name:          # da bi gop vao struct khac
                continue
            sig = tuple(
                (el["name"], resolve(el["type"]),
                 el["desc"] if DEDUP_MATCH_DESCRIPTION else "")
                for el in structs[name]["elements"]
            )
            buckets.setdefault(sig, []).append(name)

        added = False
        for _sig, group in buckets.items():
            if len(group) < 2:
                continue
            canon = _pick_canonical(group, order)
            for n in group:
                if n != canon and n not in alias:
                    alias[n] = canon
                    added = True
            groups_report.append((canon, [n for n in group if n != canon]))
        if not added:
            break

    # rut gon alias ve dang truc tiep ten -> ten cuoi cung
    alias = {k: resolve(k) for k in alias}
    return alias, groups_report


def apply_alias_to_structs(structs, order, alias):
    """Doi kieu cua cac element sang ten dai dien, va bo cac struct bi gop."""
    for st in structs.values():
        for el in st["elements"]:
            if el["type"] in alias:
                el["type"] = alias[el["type"]]
    new_order = [n for n in order if n not in alias]
    for n in alias:
        structs.pop(n, None)
    return new_order


def apply_alias_to_events(events, alias):
    for ev in events:
        for key in ("Serializer",):
            v = ev["main"].get(key, "")
            if v in alias:
                ev["main"][key] = alias[v]
        for p in ev["params"]:
            v = p.get("ParameterType", "")
            if v in alias:
                p["ParameterType"] = alias[v]


# =============================================================================
# Doc sheet Events
# =============================================================================

REQUIRED_EVENT_COLS = ["Name", "EventId", "ParameterType"]


def read_events(ws):
    """
    Tra ve: (events, cols, header_row, last_col)
      events: list dict {"main": {header: value}, "params": [dict], "row": row_dau}
    """
    header_row = None
    cols = {}
    for row in ws.iter_rows(min_row=1, max_row=min(20, ws.max_row)):
        m = {}
        for c in row:
            v = cell_str(c.value)
            if v:
                m[v] = c.column
        if all(k in m for k in REQUIRED_EVENT_COLS):
            header_row = row[0].row
            cols = m
            break
    if header_row is None:
        raise RuntimeError("Khong tim thay dong header cua sheet %s." % ws.title)

    last_col = max(cols.values())
    param_keys = [k for k in
                  ("ParameterIndex", "ParameterName", "ParameterType", "ParameterDescription")
                  if k in cols]
    main_keys = [k for k in cols if k not in param_keys]

    events = []
    cur = None
    for r in range(header_row + 1, ws.max_row + 1):
        name = cell_str(ws.cell(r, cols["Name"]).value)
        pname = cell_str(ws.cell(r, cols.get("ParameterName", cols["Name"])).value)
        if not name and not pname:
            continue
        if name:
            cur = {"main": {k: cell_str(ws.cell(r, cols[k]).value) for k in main_keys},
                   "params": [], "row": r}
            events.append(cur)
        if cur is None:
            continue
        if pname or any(cell_str(ws.cell(r, cols[k]).value) for k in param_keys):
            cur["params"].append({k: cell_str(ws.cell(r, cols[k]).value) for k in param_keys})
    return events, cols, header_row, last_col


# =============================================================================
# Logic tach
# =============================================================================

def parse_event_id(raw):
    """'0x8001' -> (32769, 'hex', 4).  '5' -> (5, 'dec', 0)."""
    s = (raw or "").strip()
    if not s:
        return None, "dec", 0
    if s.lower().startswith("0x"):
        return int(s, 16), "hex", len(s) - 2
    try:
        return int(float(s)), "dec", 0
    except ValueError:
        return None, "raw", 0


def format_event_id(value, style, width):
    if style == "hex":
        return "0x%0*X" % (width or 4, value)
    return str(value)


def build_description(orig_desc, can_msg, signals):
    """Dung lai o Description: 'CAN: <MSG>; <sig>; ...; ECU: <ECU>'."""
    ecu = ""
    m = re.search(r"ECU\s*:\s*(.*)$", orig_desc or "", re.IGNORECASE)
    if m:
        ecu = m.group(1).strip()
    parts = ["CAN: %s" % can_msg] if can_msg else []
    parts += signals
    if ecu:
        parts.append("ECU: %s" % ecu)
    return "; ".join(p for p in parts if p)


def child_event_name(orig_name, element, can_msg):
    base = orig_name[:-5] if orig_name.endswith("Event") else orig_name
    if NAME_STYLE == "canmsg" and can_msg:
        piece = pascal_from_can_name(can_msg)
    elif re.search(r"[^A-Za-z0-9]", element):   # element dang ACU_CRASH_INFO -> ACUCrashInfo
        piece = pascal_from_can_name(element)
    else:
        piece = upper_first(element)
    return "%s%sEvent" % (base, piece)


def child_param_name(orig_event_name, orig_param_name, new_event_name, element):
    """
    Giu nguyen quy uoc dat ten parameter cua khach.
    Vd: ACMIVA20msEvent / ACMIVA20msStatus -> hau to 'Status'
        -> ACMIVA20msAcuCrashInfoEvent -> ACMIVA20msAcuCrashInfoStatus
    """
    base_old = orig_event_name[:-5] if orig_event_name.endswith("Event") else orig_event_name
    base_new = new_event_name[:-5] if new_event_name.endswith("Event") else new_event_name
    if orig_param_name.startswith(base_old):
        suffix = orig_param_name[len(base_old):]
        if suffix and base_new.endswith(suffix):   # tranh lap: ...StatusStatus
            return base_new
        return base_new + suffix
    return upper_first(element)


def plan_split(events, structs, enums):
    """Tra ve (new_events, report, used_struct_names)."""
    ids = []
    for ev in events:
        v, _, _ = parse_event_id(ev["main"].get("EventId", ""))
        if v is not None:
            ids.append(v)
    next_id = (max(ids) + 1) if ids else 1
    _, id_style, id_width = parse_event_id(events[0]["main"].get("EventId", "")) if events else (None, "hex", 4)

    new_events = []
    report = []
    used_structs = set()

    for ev in events:
        name = ev["main"].get("Name", "")
        params = ev["params"]
        top_type = params[0].get("ParameterType", "") if params else ""
        struct = structs.get(top_type)

        # --- cac truong hop KHONG tach ---
        if len(params) != 1:
            report.append((name, "GIU NGUYEN", "event co %d parameter (chi xu ly 1)" % len(params)))
            new_events.append(dict(ev)); used_structs.add(top_type); continue
        if struct is None:
            report.append((name, "GIU NGUYEN", "khong tim thay struct '%s'" % top_type))
            new_events.append(dict(ev)); used_structs.add(top_type); continue
        if len(struct["elements"]) < 2:
            report.append((name, "GIU NGUYEN", "struct chi co %d element" % len(struct["elements"])))
            new_events.append(dict(ev)); used_structs.add(top_type); continue
        if not all(el["type"] in structs for el in struct["elements"]):
            report.append((name, "GIU NGUYEN (canh bao)",
                           "struct co %d element nhung element khong phai sub-struct "
                           "-> co the la 1 CAN message da flatten" % len(struct["elements"])))
            new_events.append(dict(ev)); used_structs.add(top_type); continue

        # --- tach ---
        orig_id_val, _, _ = parse_event_id(ev["main"].get("EventId", ""))
        if EVENT_ID_MODE == "offset" and orig_id_val is not None:
            max_child = 0xFFFF // EVENT_ID_CHILD_STEP - 1
            if len(struct["elements"]) > max_child:
                report.append((name, "CANH BAO",
                               "co %d event con, vuot qua buoc offset 0x%X -> EventId co the tran"
                               % (len(struct["elements"]), EVENT_ID_CHILD_STEP)))
        children = []
        for i, el in enumerate(struct["elements"]):
            sub = structs[el["type"]]
            can_msg = el["desc"] or el["type"]
            signals = []
            for se in sub["elements"]:
                d = se["desc"]
                signals.append(d.split(".")[-1] if "." in d else (d or se["name"]))

            new_name = child_event_name(name, el["name"], can_msg)

            if EVENT_ID_MODE == "offset" and orig_id_val is not None:
                # con thu k=i+1  ->  goc + k * step   (0x8002 -> 0x8102, 0x8202, ...)
                new_id = format_event_id(orig_id_val + (i + 1) * EVENT_ID_CHILD_STEP,
                                         id_style, id_width)
            elif EVENT_ID_MODE == "keep_first" and i == 0 and orig_id_val is not None:
                new_id = format_event_id(orig_id_val, id_style, id_width)
            else:
                new_id = format_event_id(next_id, id_style, id_width)
                next_id += 1

            main = dict(ev["main"])
            main["Name"] = new_name
            main["EventId"] = new_id
            if RECALC_PAYLOAD_LENGTH:
                size = type_size(el["type"], structs, enums)
                if size is not None:
                    main["PayloadLengthBytes"] = str(size)
            if main.get("Serializer", "") == top_type:
                main["Serializer"] = el["type"]
            if "Description" in main:
                main["Description"] = build_description(ev["main"].get("Description", ""),
                                                        can_msg, signals)

            p = dict(params[0])
            if "ParameterIndex" in p:
                p["ParameterIndex"] = "1"
            if "ParameterName" in p:
                p["ParameterName"] = child_param_name(
                    name, params[0].get("ParameterName", ""), new_name, el["name"])
            p["ParameterType"] = el["type"]

            children.append({"main": main, "params": [p], "row": ev["row"]})
            used_structs.add(el["type"])

        new_events.extend(children)
        report.append((name, "TACH -> %d event" % len(children),
                       ", ".join(c["main"]["Name"] for c in children)))

    # danh dau cac struct duoc dung gian tiep (de quy)
    def mark(t, seen=None):
        seen = seen or set()
        if t in seen or t not in structs:
            return
        seen.add(t)
        used_structs.add(t)
        for el in structs[t]["elements"]:
            mark(el["type"], seen)

    for t in list(used_structs):
        mark(t)

    return new_events, report


# =============================================================================
# Ghi ket qua
# =============================================================================

def write_events(ws, events, cols, header_row, last_col):
    template_row = header_row + 1
    styles = {c: ws.cell(template_row, c) for c in range(1, last_col + 1)}
    style_copy = {c: copy(styles[c]._style) for c in styles}

    unmerge_region(ws, header_row + 1, 1, last_col)
    for r in range(header_row + 1, ws.max_row + 1):
        for c in range(1, last_col + 1):
            ws.cell(r, c).value = None

    param_keys = [k for k in
                  ("ParameterIndex", "ParameterName", "ParameterType", "ParameterDescription")
                  if k in cols]
    main_keys = [k for k in cols if k not in param_keys]

    r = header_row + 1
    for i, ev in enumerate(events, start=1):
        first = True
        for p in (ev["params"] or [{}]):
            for c in range(1, last_col + 1):
                try:
                    ws.cell(r, c)._style = copy(style_copy[c])
                except Exception:
                    pass
            if first:
                for k in main_keys:
                    val = ev["main"].get(k, "")
                    if k == "Index" and RENUMBER_INDEX:
                        val = i
                    ws.cell(r, cols[k]).value = coerce(val) if val != "" else None
                first = False
            for k in param_keys:
                v = p.get(k, "")
                ws.cell(r, cols[k]).value = coerce(v) if v != "" else None
            r += 1
    return r - 1


def write_structs(ws, structs, order, layout, keep_names):
    c_idx, c_name = layout["col_index"], layout["col_name"]
    c_el, c_ty, c_de = layout["col_element"], layout["col_type"], layout["col_desc"]
    first = layout["first_data_row"]

    tmpl = {c: copy(ws.cell(first, c)._style) for c in (c_idx, c_name, c_el, c_ty, c_de)}

    unmerge_region(ws, first, c_idx, c_de)
    for r in range(first, ws.max_row + 1):
        for c in (c_idx, c_name, c_el, c_ty, c_de):
            ws.cell(r, c).value = None

    r = first
    n = 0
    for name in order:
        if name not in keep_names:
            continue
        n += 1
        st = structs[name]
        for i, el in enumerate(st["elements"]):
            for c in (c_idx, c_name, c_el, c_ty, c_de):
                try:
                    ws.cell(r, c)._style = copy(tmpl[c])
                except Exception:
                    pass
            if i == 0:
                ws.cell(r, c_idx).value = n if RENUMBER_INDEX else (st["index"] or n)
                ws.cell(r, c_name).value = name
            ws.cell(r, c_el).value = el["name"] or None
            ws.cell(r, c_ty).value = el["type"] or None
            ws.cell(r, c_de).value = el["desc"] or None
            r += 1
    return n


# =============================================================================
# main
# =============================================================================

OUTPUT_SUFFIX = "_split"


def process_one(in_path, out_path, dry_run=False):
    """Xu ly 1 file. Tra ve dict tom tat, raise neu file khong hop le."""
    wb = load_workbook(in_path)
    missing = [s for s in (SHEET_EVENTS, SHEET_DATASTRUCT) if s not in wb.sheetnames]
    if missing:
        raise RuntimeError("thieu sheet %s (dang co: %s)"
                           % (", ".join(missing), ", ".join(wb.sheetnames)))

    ws_ev = wb[SHEET_EVENTS]
    ws_ds = wb[SHEET_DATASTRUCT]

    structs, order, layout = read_structs(ws_ds)
    enums = read_enums(ws_ds)
    events, cols, header_row, last_col = read_events(ws_ev)

    n_struct_before = len(structs)
    print("  Doc duoc: %d event, %d struct, %d enum" % (len(events), len(structs), len(enums)))

    n_renamed, clashes = rename_elements(structs)
    if n_renamed:
        print("  Doi ten Element theo Description (style=%s): %d element"
              % (ELEMENT_NAME_STYLE, n_renamed))
    if clashes:
        print("  CANH BAO: element trung ten sau khi doi, da them hau to _2: %s"
              % ", ".join(clashes[:10]))

    n_merged = 0
    if DEDUP_STRUCTS:
        alias, groups = dedup_structs(structs, order)
        if alias:
            print("  GOP STRUCT TRUNG LAP:")
            for canon, dups in groups:
                print("    %-28s <- %s" % (canon, ", ".join(dups)))
            apply_alias_to_events(events, alias)
            order = apply_alias_to_structs(structs, order, alias)
            n_merged = len(alias)
            print("    => %d struct bi gop, con lai %d struct" % (n_merged, len(order)))
        else:
            print("  Khong tim thay struct trung lap.")

    new_events, report = plan_split(events, structs, enums)
    for name, action, detail in report:
        print("    %-28s %-20s %s" % (name, action, detail))
    print("  Ket qua: %d event  ->  %d event" % (len(events), len(new_events)))

    warnings = [r[0] for r in report if "CANH BAO" in r[1]]
    seen_names = {}
    for e in new_events:
        n = e["main"].get("Name", "")
        seen_names[n] = seen_names.get(n, 0) + 1
    dup_names = [n for n, c in seen_names.items() if c > 1]
    if dup_names:
        print("  CANH BAO: ten event bi trung sau khi tach: %s" % ", ".join(dup_names))

    seen_ids = {}
    for e in new_events:
        v = e["main"].get("EventId", "")
        seen_ids.setdefault(v, []).append(e["main"].get("Name", ""))
    dup_ids = {k: v for k, v in seen_ids.items() if len(v) > 1}
    if dup_ids:
        print("  CANH BAO: EventId bi trung: %s"
              % "; ".join("%s (%s)" % (k, ", ".join(v)) for k, v in dup_ids.items()))

    summary = {"events_in": len(events), "events_out": len(new_events),
               "structs_in": n_struct_before, "structs_merged": n_merged,
               "warnings": len(warnings) + len(dup_names) + len(dup_ids), "output": None}

    if dry_run:
        print("  (dry-run: khong ghi file)")
        return summary

    keep = {e["params"][0]["ParameterType"] for e in new_events if e["params"]}

    def mark(t, seen):
        if t in seen or t not in structs:
            return
        seen.add(t)
        for el in structs[t]["elements"]:
            mark(el["type"], seen)

    seen = set()
    for t in keep:
        mark(t, seen)
    keep_names = seen if REMOVE_UNUSED_WRAPPER_STRUCTS else set(order)

    write_events(ws_ev, new_events, cols, header_row, last_col)
    kept = write_structs(ws_ds, structs, order, layout, keep_names)

    removed = [n for n in order if n not in keep_names]
    if removed:
        print("  Da xoa %d struct khong con dung: %s" % (len(removed), ", ".join(removed)))
    print("  Bang Struct con lai: %d struct" % kept)

    out_dir = os.path.dirname(os.path.abspath(out_path))
    if out_dir and not os.path.isdir(out_dir):
        os.makedirs(out_dir)
    wb.save(out_path)
    summary["structs_out"] = kept
    summary["output"] = out_path
    print("  Da ghi: %s" % out_path)
    return summary


def collect_inputs(folder, recursive=False):
    """Liet ke cac file Excel dau vao trong folder, bo qua file tam va file da xuat."""
    found = []
    walker = os.walk(folder) if recursive else [(folder, [], os.listdir(folder))]
    for root, _dirs, files in walker:
        for f in sorted(files):
            if not f.lower().endswith((".xlsx", ".xlsm")):
                continue
            if f.startswith("~$"):                       # file tam cua Excel
                continue
            if os.path.splitext(f)[0].endswith(OUTPUT_SUFFIX):   # file da xuat lan truoc
                continue
            found.append(os.path.join(root, f))
    return found


def main():
    ap = argparse.ArgumentParser(
        description="Tach SOME/IP event gop thanh 1 event / 1 CAN message, "
                    "kem gop struct trung lap. Nhan 1 file hoac ca 1 thu muc.")
    ap.add_argument("input", help="File Excel, HOAC thu muc chua nhieu file Excel")
    ap.add_argument("-o", "--output",
                    help="File xuat (khi input la file) hoac thu muc xuat (khi input la folder). "
                         "Mac dinh: <ten>_split.xlsx, cung cho voi file goc")
    ap.add_argument("-r", "--recursive", action="store_true",
                    help="Quet ca thu muc con (chi dung khi input la folder)")
    ap.add_argument("--dry-run", action="store_true", help="Chi in bao cao, khong ghi file")
    args = ap.parse_args()

    # ---------- input la 1 file ----------
    if os.path.isfile(args.input):
        out = args.output or os.path.splitext(args.input)[0] + OUTPUT_SUFFIX + ".xlsx"
        if os.path.isdir(out):
            out = os.path.join(out, os.path.splitext(os.path.basename(args.input))[0]
                               + OUTPUT_SUFFIX + ".xlsx")
        if os.path.abspath(out) == os.path.abspath(args.input):
            sys.exit("File xuat trung file goc. Hay chon ten khac.")
        print("=" * 78)
        print("FILE: %s" % args.input)
        try:
            process_one(args.input, out, args.dry_run)
        except Exception as e:
            sys.exit("LOI: %s" % e)
        return

    # ---------- input la 1 thu muc ----------
    if not os.path.isdir(args.input):
        sys.exit("Khong tim thay file hoac thu muc: %s" % args.input)

    files = collect_inputs(args.input, args.recursive)
    if not files:
        sys.exit("Khong co file .xlsx/.xlsm nao trong: %s" % args.input)

    out_dir = args.output
    print("Tim thay %d file trong: %s" % (len(files), os.path.abspath(args.input)))
    if out_dir:
        print("Thu muc xuat: %s" % os.path.abspath(out_dir))

    ok, failed = [], []
    for i, f in enumerate(files, start=1):
        print("=" * 78)
        print("[%d/%d] %s" % (i, len(files), os.path.relpath(f, args.input)))
        base = os.path.splitext(os.path.basename(f))[0] + OUTPUT_SUFFIX + ".xlsx"
        if out_dir:
            rel = os.path.relpath(os.path.dirname(f), args.input)
            out = os.path.join(out_dir, rel, base) if rel != "." else os.path.join(out_dir, base)
        else:
            out = os.path.join(os.path.dirname(f), base)
        try:
            s = process_one(f, out, args.dry_run)
            ok.append((f, s))
        except Exception as e:
            print("  LOI: %s  -> BO QUA file nay" % e)
            failed.append((f, str(e)))

    # ---------- tong ket ----------
    print("=" * 78)
    print("TONG KET: %d file thanh cong, %d file loi" % (len(ok), len(failed)))
    if ok:
        print("%-40s %10s %10s %8s" % ("File", "Event", "Struct gop", "Canh bao"))
        for f, s in ok:
            print("%-40s %4d -> %-4d %10d %8d"
                  % (os.path.basename(f)[:40], s["events_in"], s["events_out"],
                     s["structs_merged"], s["warnings"]))
    for f, e in failed:
        print("  LOI  %-38s %s" % (os.path.basename(f)[:38], e))
    if failed:
        sys.exit(1)


if __name__ == "__main__":
    main()
