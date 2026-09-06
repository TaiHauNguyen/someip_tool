#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
dbc_struct.py - Doc file CAN .dbc, lay datatype cua mot message bat ky
                va sinh ra C struct map 1:1 (giu nguyen thu tu va do dai bit).

Usage:
    python dbc_struct.py SCAN.dbc ACU_CRASH_INFO
    python dbc_struct.py SCAN.dbc 133 --c-out ACU_CRASH_INFO.h
    python dbc_struct.py SCAN.dbc --list
    python dbc_struct.py SCAN.dbc ACU_CRASH_INFO --json
"""

import argparse
import json
import re
import sys

# ---------------------------------------------------------------------------
# Data model
# ---------------------------------------------------------------------------


class Signal(object):
    __slots__ = ("name", "start_bit", "length", "byte_order", "is_signed",
                 "factor", "offset", "minimum", "maximum", "unit",
                 "receivers", "mux", "comment", "values", "attrs", "is_float")

    def __init__(self, **kw):
        for s in self.__slots__:
            setattr(self, s, kw.get(s))
        if self.values is None:
            self.values = {}
        if self.attrs is None:
            self.attrs = {}
        if self.is_float is None:
            self.is_float = False

    # ---- bit layout ------------------------------------------------------
    @property
    def is_motorola(self):
        return self.byte_order == 0

    def wire_bits(self):
        """Chi so bit theo thu tu tren duong truyen (byte0 truoc, trong byte MSB truoc).

        Motorola: tra ve MSB -> LSB.  Intel: tra ve LSB -> MSB.
        """
        if self.is_motorola:
            w0 = (self.start_bit // 8) * 8 + (7 - self.start_bit % 8)
            return list(range(w0, w0 + self.length))
        out = []
        for i in range(self.length):
            b = self.start_bit + i
            out.append((b // 8) * 8 + (7 - b % 8))
        return out

    def wire_span(self):
        w = self.wire_bits()
        return min(w), max(w)

    def is_contiguous(self):
        w = sorted(self.wire_bits())
        return w[-1] - w[0] + 1 == len(w)

    # ---- datatype --------------------------------------------------------
    @property
    def raw_ctype(self):
        """Kieu C cho gia tri RAW (chua ap dung factor/offset)."""
        if self.is_float:
            return "float" if self.length == 32 else "double"
        for n in (8, 16, 32, 64):
            if self.length <= n:
                return ("int%d_t" % n) if self.is_signed else ("uint%d_t" % n)
        return "uint64_t"

    @property
    def phys_ctype(self):
        """Kieu C cho gia tri VAT LY (da ap dung factor/offset)."""
        if self.is_float:
            return self.raw_ctype
        if self.factor == 1 and self.offset == 0:
            return self.raw_ctype
        if float(self.factor).is_integer() and float(self.offset).is_integer():
            lo = self.minimum if self.minimum is not None else 0
            hi = self.maximum if self.maximum is not None else 0
            signed = lo < 0 or self.is_signed
            span = max(abs(lo), abs(hi))
            for n, half in ((8, 1 << 7), (16, 1 << 15), (32, 1 << 31), (64, 1 << 63)):
                limit = half if signed else half * 2
                if span < limit:
                    return ("int%d_t" % n) if signed else ("uint%d_t" % n)
            return "int64_t"
        return "double" if self.length > 23 else "float"

    @property
    def raw_range(self):
        if self.is_float:
            return None
        if self.is_signed:
            return (-(1 << (self.length - 1)), (1 << (self.length - 1)) - 1)
        return (0, (1 << self.length) - 1)


class Message(object):
    __slots__ = ("frame_id", "name", "dlc", "sender", "signals", "comment", "attrs")

    def __init__(self, **kw):
        for s in self.__slots__:
            setattr(self, s, kw.get(s))
        if self.signals is None:
            self.signals = []
        if self.attrs is None:
            self.attrs = {}

    @property
    def is_extended(self):
        return bool(self.frame_id & 0x80000000)

    @property
    def can_id(self):
        return self.frame_id & 0x1FFFFFFF


# ---------------------------------------------------------------------------
# Parser
# ---------------------------------------------------------------------------

RE_BO = re.compile(r'^BO_\s+(\d+)\s+([A-Za-z_]\w*)\s*:\s*(\d+)\s+(\S+)')
RE_SG = re.compile(
    r'^\s*SG_\s+([A-Za-z_]\w*)\s*(?:(M|m\d+M?)\s+)?:\s*'
    r'(\d+)\|(\d+)@([01])([+-])\s*'
    r'\(\s*([-+0-9.eE]+)\s*,\s*([-+0-9.eE]+)\s*\)\s*'
    r'\[\s*([-+0-9.eE]*)\s*\|\s*([-+0-9.eE]*)\s*\]\s*'
    r'"([^"]*)"\s*(.*)$')
RE_CM_SG = re.compile(r'^CM_\s+SG_\s+(\d+)\s+([A-Za-z_]\w*)\s+"(.*)"\s*;\s*$', re.S)
RE_CM_BO = re.compile(r'^CM_\s+BO_\s+(\d+)\s+"(.*)"\s*;\s*$', re.S)
RE_VAL = re.compile(r'^VAL_\s+(\d+)\s+([A-Za-z_]\w*)\s+(.*?);\s*$', re.S)
RE_VAL_ITEM = re.compile(r'(-?\d+)\s+"([^"]*)"')
RE_BA_SG = re.compile(r'^BA_\s+"([^"]+)"\s+SG_\s+(\d+)\s+([A-Za-z_]\w*)\s+(.*?);\s*$')
RE_BA_BO = re.compile(r'^BA_\s+"([^"]+)"\s+BO_\s+(\d+)\s+(.*?);\s*$')
RE_SIGVALTYPE = re.compile(r'^SIG_VALTYPE_\s+(\d+)\s+([A-Za-z_]\w*)\s*:?\s*(\d+)\s*;')


def _num(s, default=None):
    if s is None or s == "":
        return default
    f = float(s)
    return int(f) if f.is_integer() else f


def _logical_lines(text):
    """Gop cac dong bi ngat giua chuoi (CM_ nhieu dong)."""
    out = []
    pending = None
    for raw in text.splitlines():
        line = raw.rstrip("\r\n")
        if pending is not None:
            pending += "\n" + line
            if pending.count('"') % 2 == 0 and pending.rstrip().endswith(";"):
                out.append(pending)
                pending = None
            continue
        if line.startswith("CM_") and line.count('"') % 2 == 1:
            pending = line
            continue
        out.append(line)
    if pending is not None:
        out.append(pending)
    return out


def parse_dbc(path):
    with open(path, "r", encoding="utf-8", errors="replace") as fh:
        text = fh.read()
    if text[:1] == "﻿":
        text = text[1:]

    messages = []
    by_id = {}
    cur = None

    lines = _logical_lines(text)

    # pass 1: BO_ / SG_
    for line in lines:
        stripped = line.lstrip()
        m = RE_BO.match(line)
        if m:
            cur = Message(frame_id=int(m.group(1)), name=m.group(2),
                          dlc=int(m.group(3)), sender=m.group(4), signals=[])
            messages.append(cur)
            by_id[cur.frame_id] = cur
            continue
        if stripped.startswith("SG_"):
            m = RE_SG.match(line)
            if m and cur is not None:
                rest = m.group(12).strip()
                recv = [r for r in re.split(r'[,\s]+', rest) if r] if rest else []
                cur.signals.append(Signal(
                    name=m.group(1), mux=m.group(2),
                    start_bit=int(m.group(3)), length=int(m.group(4)),
                    byte_order=int(m.group(5)), is_signed=(m.group(6) == "-"),
                    factor=_num(m.group(7), 1), offset=_num(m.group(8), 0),
                    minimum=_num(m.group(9)), maximum=_num(m.group(10)),
                    unit=m.group(11), receivers=recv))
            elif cur is not None:
                sys.stderr.write("WARN: khong parse duoc SG_: %s\n" % line.strip())
            continue
        if stripped and not stripped.startswith("SG_"):
            cur = None if RE_BO.match(line) is None and stripped[0] not in " \t" else cur

    def sig_of(mid, sname):
        msg = by_id.get(mid)
        if msg is None:
            return None
        for s in msg.signals:
            if s.name == sname:
                return s
        return None

    # pass 2: CM_ / VAL_ / BA_ / SIG_VALTYPE_
    for line in lines:
        if line.startswith("CM_ SG_"):
            m = RE_CM_SG.match(line)
            if m:
                s = sig_of(int(m.group(1)), m.group(2))
                if s is not None:
                    s.comment = m.group(3)
        elif line.startswith("CM_ BO_"):
            m = RE_CM_BO.match(line)
            if m and int(m.group(1)) in by_id:
                by_id[int(m.group(1))].comment = m.group(2)
        elif line.startswith("VAL_ "):
            m = RE_VAL.match(line)
            if m:
                s = sig_of(int(m.group(1)), m.group(2))
                if s is not None:
                    s.values = dict((int(v), n) for v, n in RE_VAL_ITEM.findall(m.group(3)))
        elif line.startswith("BA_ "):
            m = RE_BA_SG.match(line)
            if m:
                s = sig_of(int(m.group(2)), m.group(3))
                if s is not None:
                    s.attrs[m.group(1)] = m.group(4).strip().strip('"')
                continue
            m = RE_BA_BO.match(line)
            if m and int(m.group(2)) in by_id:
                by_id[int(m.group(2))].attrs[m.group(1)] = m.group(3).strip().strip('"')
        elif line.startswith("SIG_VALTYPE_"):
            m = RE_SIGVALTYPE.match(line)
            if m and m.group(3) in ("1", "2"):
                s = sig_of(int(m.group(1)), m.group(2))
                if s is not None:
                    s.is_float = True

    return messages


# ---------------------------------------------------------------------------
# Layout 1:1
# ---------------------------------------------------------------------------


class Field(object):
    def __init__(self, name, width, wire_start, signal=None):
        self.name = name
        self.width = width
        self.wire_start = wire_start
        self.signal = signal

    @property
    def is_reserved(self):
        return self.signal is None


def build_layout(msg):
    """Phu kin dlc*8 bit bang cac Field theo dung thu tu wire.

    Khong doi thu tu, khong doi do dai -> map 1:1 voi khung CAN.
    """
    total = msg.dlc * 8
    owner = [None] * total
    for s in msg.signals:
        for b in s.wire_bits():
            if b >= total:
                raise ValueError("Signal %s vuot ngoai DLC (%d byte)" % (s.name, msg.dlc))
            if owner[b] is not None:
                raise ValueError("Bit %d chong lan: %s vs %s" % (b, owner[b].name, s.name))
            owner[b] = s

    fields = []
    rsv = 0
    i = 0
    while i < total:
        s = owner[i]
        if s is None:
            j = i
            while j < total and owner[j] is None:
                j += 1
            # Cat khoang trong theo bien byte de bitfield luon gon trong 1 byte.
            while i < j:
                k = min(j, (i // 8 + 1) * 8)
                rsv += 1
                fields.append(Field("Reserved_%d" % rsv, k - i, i))
                i = k
        else:
            lo, hi = s.wire_span()
            fields.append(Field(s.name, s.length, lo, s))
            i = hi + 1
    return fields


def bf_ctype(field):
    """Kieu nen cho bitfield: nho nhat ma van chua tron field."""
    first = field.wire_start // 8
    last = (field.wire_start + field.width - 1) // 8
    span = last - first + 1
    for n in (1, 2, 4, 8):
        if span <= n and field.width <= n * 8:
            return "uint%d_t" % (n * 8)
    return "uint64_t"


# ---------------------------------------------------------------------------
# Report
# ---------------------------------------------------------------------------


def print_report(msg, fields):
    line = "=" * 110
    print(line)
    print("MESSAGE : %s" % msg.name)
    print("CAN ID  : %d (0x%X)  %s" % (msg.can_id, msg.can_id,
                                       "extended" if msg.is_extended else "standard"))
    print("DLC     : %d byte (%d bit)" % (msg.dlc, msg.dlc * 8))
    print("Sender  : %s" % msg.sender)
    if msg.comment:
        print("Comment : %s" % msg.comment)
    if msg.attrs:
        print("Attrs   : %s" % ", ".join("%s=%s" % kv for kv in sorted(msg.attrs.items())))
    print(line)
    print("DATATYPE")
    print("-" * 110)
    print("%-34s %5s %4s %-9s %-9s %-10s %-10s %s"
          % ("SIGNAL", "START", "LEN", "ENDIAN", "SIGN", "RAW TYPE", "PHYS TYPE", "RAW RANGE"))
    print("-" * 110)
    for s in msg.signals:
        rr = s.raw_range
        print("%-34s %5d %4d %-9s %-9s %-10s %-10s %s"
              % (s.name, s.start_bit, s.length,
                 "Motorola" if s.is_motorola else "Intel",
                 "signed" if s.is_signed else "unsigned",
                 s.raw_ctype, s.phys_ctype,
                 ("%d..%d" % rr) if rr else "-"))
    print("-" * 110)

    print()
    print("SCALING")
    print("-" * 110)
    print("%-34s %-24s %-20s %s" % ("SIGNAL", "phys = raw*F+O", "PHYS RANGE", "UNIT"))
    print("-" * 110)
    for s in msg.signals:
        print("%-34s %-24s %-20s %s"
              % (s.name, "raw*%g%+g" % (s.factor, s.offset),
                 ("%g .. %g" % (s.minimum, s.maximum)) if s.minimum is not None else "-",
                 s.unit or "-"))
    print("-" * 110)

    print()
    print("BIT LAYOUT 1:1   (wire order: byte0 truoc, trong moi byte MSB truoc)")
    print("-" * 110)
    print("%-6s %-34s %-6s %-15s %-10s %s"
          % ("WIRE", "FIELD", "WIDTH", "POSITION", "TYPE", "NOTE"))
    print("-" * 110)
    for f in fields:
        b0 = f.wire_start // 8
        p0 = 7 - (f.wire_start % 8)
        p1 = p0 - f.width + 1
        if p1 >= 0:
            pos = "byte%d [%d:%d]" % (b0, p0, p1)
        else:
            pos = "byte%d..byte%d" % (b0, (f.wire_start + f.width - 1) // 8)
        note = "<< padding >>" if f.is_reserved else ("dbc start=%d" % f.signal.start_bit)
        print("%-6d %-34s %-6d %-15s %-10s %s"
              % (f.wire_start, f.name, f.width, pos, bf_ctype(f), note))
    print("-" * 110)
    used = sum(f.width for f in fields if not f.is_reserved)
    print("%d bit signal + %d bit reserved = %d bit = %d byte  -> khop DLC"
          % (used, msg.dlc * 8 - used, msg.dlc * 8, msg.dlc))

    vt = [s for s in msg.signals if s.values]
    if vt:
        print()
        print("VALUE TABLES")
        print("-" * 110)
        for s in vt:
            print("  %s:" % s.name)
            for k in sorted(s.values):
                print("      %-5d = %s" % (k, s.values[k]))
        print("-" * 110)
    print()


# ---------------------------------------------------------------------------
# Bit chunking (dung cho pack/unpack, khong phu thuoc compiler)
# ---------------------------------------------------------------------------


def _chunks(s):
    """Chia signal thanh cac mieng nam gon trong 1 byte.

    Tra ve (byte_index, shift_in_byte, nbits, shift_in_value).
    """
    bits = s.wire_bits()
    if not s.is_motorola:
        bits = list(reversed(bits))        # dua ve thu tu MSB -> LSB
    out = []
    i = 0
    n = len(bits)
    while i < n:
        byte = bits[i] // 8
        j = i
        while (j < n and bits[j] // 8 == byte and bits[j] == bits[i] + (j - i)):
            j += 1
        cnt = j - i
        lsb_wire = bits[j - 1]
        out.append((byte, 7 - (lsb_wire % 8), cnt, n - j))
        i = j
    return out


def _extract_expr(s):
    parts = []
    for byte, shb, cnt, shv in _chunks(s):
        e = "src[%d]" % byte
        if shb:
            e = "(%s >> %d)" % (e, shb)
        e = "((uint32_t)(%s) & 0x%XU)" % (e, (1 << cnt) - 1)
        if shv:
            e = "(%s << %d)" % (e, shv)
        parts.append(e)
    expr = " | ".join(parts)
    if s.is_signed:
        half = 1 << (s.length - 1)
        expr = "(int32_t)(((%s) ^ 0x%XU)) - (int32_t)0x%XU" % (expr, half, half)
    return expr


def _insert_stmts(s):
    stmts = []
    for byte, shb, cnt, shv in _chunks(s):
        e = "(uint32_t)src->%s" % s.name
        if shv:
            e = "((%s) >> %d)" % (e, shv)
        e = "((%s) & 0x%XU)" % (e, (1 << cnt) - 1)
        if shb:
            e = "((%s) << %d)" % (e, shb)
        stmts.append("dst[%d] |= (uint8_t)%s;" % (byte, e))
    return stmts


# ---------------------------------------------------------------------------
# C code generation
# ---------------------------------------------------------------------------


def gen_c(msg, fields):
    out = []
    add = out.append
    guard = re.sub(r'\W', '_', msg.name).upper() + "_H"
    up = msg.name.upper()

    add("/* -------------------------------------------------------------------")
    add(" * Auto-generated by dbc_struct.py -- DO NOT EDIT BY HAND")
    add(" * Message : %s" % msg.name)
    add(" * CAN ID  : %d (0x%X) %s"
        % (msg.can_id, msg.can_id, "extended" if msg.is_extended else "standard"))
    add(" * DLC     : %d byte / %d bit" % (msg.dlc, msg.dlc * 8))
    add(" * Sender  : %s" % msg.sender)
    add(" * ------------------------------------------------------------------- */")
    add("#ifndef %s" % guard)
    add("#define %s" % guard)
    add("")
    add("#include <stdint.h>")
    add("")
    add("#define %s_ID    (0x%03XU)" % (up, msg.can_id))
    add("#define %s_DLC   (%dU)" % (up, msg.dlc))
    add("")

    for s in msg.signals:
        if not s.values:
            continue
        add("/* %s */" % (s.comment or s.name))
        add("typedef enum")
        add("{")
        items = sorted(s.values.items())
        for i, (v, n) in enumerate(items):
            nm = "%s_%s" % (s.name.upper(), re.sub(r'\W', '_', n).upper())
            add("    %-62s = %du%s" % (nm, v, "," if i < len(items) - 1 else ""))
        add("} %s_E;" % s.name)
        add("")

    add("/* ---------------------------------------------------------------")
    add(" * Bitfield struct - map 1:1 voi khung CAN.")
    add(" * Thu tu khai bao = thu tu tren duong truyen (byte0 truoc, MSB truoc),")
    add(" * do rong = do dai bit trong DBC. Cac khoang trong duoc chen Reserved_n")
    add(" * de tong luon bang %d bit.")
    add(" *")
    add(" * LUU Y: cach cap phat bitfield la implementation-defined. Struct nay")
    add(" * dung khi trinh bien dich cap phat MSB-first (vd: GHS/TI/IAR o che do")
    add(" * big-endian bitfield). Neu khong chac chan, hay dung")
    add(" * %s_Raw_t + %s_Unpack()/%s_Pack() ben duoi." % (msg.name, msg.name, msg.name))
    add(" * --------------------------------------------------------------- */")
    add("#pragma pack(push, 1)")
    add("typedef struct")
    add("{")
    cur_byte = -1
    for f in fields:
        b = f.wire_start // 8
        if b != cur_byte:
            if cur_byte != -1:
                add("")
            add("    /* ---- byte %d ---- */" % b)
            cur_byte = b
        if f.is_reserved:
            cmt = "  /* padding */"
        else:
            s = f.signal
            bits = []
            if s.comment:
                bits.append(s.comment)
            if s.unit:
                bits.append("[%s]" % s.unit)
            if s.factor != 1 or s.offset != 0:
                bits.append("phys=raw*%g%+g" % (s.factor, s.offset))
            if s.minimum is not None:
                bits.append("range %g..%g" % (s.minimum, s.maximum))
            cmt = ("  /* %s */" % " ".join(bits)) if bits else ""
        add("    %-9s %-36s : %d;%s" % (bf_ctype(f), f.name, f.width, cmt))
    add("} %s_t;" % msg.name)
    add("#pragma pack(pop)")
    add("")

    add("/* ---------------------------------------------------------------")
    add(" * Ban 'phang': moi signal mot field rieng, gia tri RAW.")
    add(" * Thu tu field giu nguyen thu tu trong DBC.")
    add(" * --------------------------------------------------------------- */")
    add("typedef struct")
    add("{")
    for s in msg.signals:
        add("    %-10s %-37s /* start=%d len=%d %s */"
            % (s.raw_ctype, s.name + ";", s.start_bit, s.length,
               "Motorola" if s.is_motorola else "Intel"))
    add("} %s_Raw_t;" % msg.name)
    add("")

    add("/* Giai ma %d byte CAN -> gia tri raw. Khong phu thuoc endianness CPU. */"
        % msg.dlc)
    add("static inline void %s_Unpack(%s_Raw_t *dst, const uint8_t *src)"
        % (msg.name, msg.name))
    add("{")
    for s in msg.signals:
        add("    dst->%s = (%s)(%s);" % (s.name, s.raw_ctype, _extract_expr(s)))
    add("}")
    add("")
    add("/* Ma hoa gia tri raw -> %d byte CAN. */" % msg.dlc)
    add("static inline void %s_Pack(uint8_t *dst, const %s_Raw_t *src)"
        % (msg.name, msg.name))
    add("{")
    add("    uint8_t i;")
    add("    for (i = 0U; i < %dU; i++)" % msg.dlc)
    add("    {")
    add("        dst[i] = 0U;")
    add("    }")
    for s in msg.signals:
        for st in _insert_stmts(s):
            add("    " + st)
    add("}")
    add("")
    add("#endif /* %s */" % guard)
    add("")
    return "\n".join(out).replace(
        "de tong luon bang %d bit.", "de tong luon bang %d bit." % (msg.dlc * 8))


# ---------------------------------------------------------------------------
# JSON
# ---------------------------------------------------------------------------


def to_json(msg, fields):
    return {
        "message": msg.name,
        "can_id": msg.can_id,
        "can_id_hex": "0x%X" % msg.can_id,
        "extended": msg.is_extended,
        "dlc": msg.dlc,
        "sender": msg.sender,
        "comment": msg.comment,
        "attributes": msg.attrs,
        "signals": [{
            "name": s.name,
            "start_bit": s.start_bit,
            "length": s.length,
            "byte_order": "motorola" if s.is_motorola else "intel",
            "signed": s.is_signed,
            "raw_ctype": s.raw_ctype,
            "phys_ctype": s.phys_ctype,
            "raw_min": s.raw_range[0] if s.raw_range else None,
            "raw_max": s.raw_range[1] if s.raw_range else None,
            "factor": s.factor,
            "offset": s.offset,
            "minimum": s.minimum,
            "maximum": s.maximum,
            "unit": s.unit,
            "receivers": s.receivers,
            "comment": s.comment,
            "values": s.values,
            "attributes": s.attrs,
        } for s in msg.signals],
        "layout": [{
            "wire_start": f.wire_start,
            "name": f.name,
            "width": f.width,
            "reserved": f.is_reserved,
            "ctype": bf_ctype(f),
        } for f in fields],
    }


# ---------------------------------------------------------------------------
# main
# ---------------------------------------------------------------------------


def main(argv=None):
    ap = argparse.ArgumentParser(
        description="Doc DBC, lay datatype cua message, sinh C struct map 1:1")
    ap.add_argument("dbc")
    ap.add_argument("message", nargs="?", help="ten message hoac CAN id (dec hoac 0x..)")
    ap.add_argument("--list", action="store_true", help="liet ke tat ca message")
    ap.add_argument("--json", action="store_true", help="xuat JSON")
    ap.add_argument("--c", action="store_true", help="in C code ra stdout")
    ap.add_argument("--c-out", metavar="FILE", help="ghi C header ra file")
    a = ap.parse_args(argv)

    msgs = parse_dbc(a.dbc)

    if a.list or not a.message:
        print("%-6s %-8s %-36s %-4s %-9s %s"
              % ("ID", "HEX", "NAME", "DLC", "SENDER", "SIGNALS"))
        print("-" * 80)
        for m in msgs:
            print("%-6d 0x%-6X %-36s %-4d %-9s %d"
                  % (m.can_id, m.can_id, m.name, m.dlc, m.sender, len(m.signals)))
        print("-" * 80)
        print("Tong: %d message" % len(msgs))
        return 0

    msg = None
    for m in msgs:
        if m.name == a.message:
            msg = m
            break
    if msg is None:
        try:
            wanted = int(a.message, 0)
        except ValueError:
            wanted = None
        if wanted is not None:
            for m in msgs:
                if m.can_id == wanted:
                    msg = m
                    break
    if msg is None:
        sys.stderr.write("Khong tim thay message '%s'. Dung --list de xem.\n" % a.message)
        return 1

    fields = build_layout(msg)

    if a.json:
        print(json.dumps(to_json(msg, fields), indent=2, ensure_ascii=False))
        return 0

    print_report(msg, fields)

    code = gen_c(msg, fields)
    if a.c_out:
        with open(a.c_out, "w", encoding="utf-8", newline="\n") as fh:
            fh.write(code)
        print("Da ghi C header -> %s" % a.c_out)
    if a.c or not a.c_out:
        print(code)
    return 0


if __name__ == "__main__":
    sys.exit(main())
