"""Rules that repair or complete an imported model - no project specifics.

Two situations come up with every customer workbook and neither can be fixed by
editing the Excel:

1. A struct member references a type whose declaration is spelled slightly
   differently (`PCUVehicleOperationStateType` vs `PCUVehiclOperationStateType`).
   `resolve_type_references` retargets the reference to the declaration it is
   closest to, so a one-character typo does not break the whole file.

2. Some facts simply are not in the workbook: the address of the ECU that offers
   a consumed service, and the `<VT>` texts / type names that the previous ARXML
   already shipped to the ECU code.  `carry_over` takes those from a base
   project (the ARXML or JSON you already have) whenever the freshly imported
   model leaves them empty.

Every change is returned as a log line, so nothing happens silently.
"""

from __future__ import annotations

import re
from typing import Dict, List, Optional, Tuple

from someip_model import Project, Service, base_type_name

# a reference is only retargeted when the two names are this close
MAX_EDIT_DISTANCE = 2


def normalize(name: str) -> str:
    return re.sub(r"[^a-z0-9]", "", (name or "").lower())


def edit_distance(a: str, b: str, limit: int = 4) -> int:
    if abs(len(a) - len(b)) > limit:
        return limit + 1
    prev = list(range(len(b) + 1))
    for i, ca in enumerate(a, 1):
        cur = [i]
        for j, cb in enumerate(b, 1):
            cur.append(min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + (ca != cb)))
        prev = cur
    return prev[-1]


def best_match(name: str, candidates: List[str]) -> Optional[str]:
    """Exact, then case/punctuation insensitive, then nearest within the limit."""
    if name in candidates:
        return name
    norm = {normalize(c): c for c in candidates}
    hit = norm.get(normalize(name))
    if hit is not None:
        return hit
    scored = sorted(((edit_distance(normalize(name), normalize(c)), c) for c in candidates),
                    key=lambda t: (t[0], t[1]))
    if scored and scored[0][0] <= MAX_EDIT_DISTANCE:
        if len(scored) == 1 or scored[1][0] > scored[0][0]:
            return scored[0][1]
    return None


# --------------------------------------------------------------------------
# 1. dangling type references
# --------------------------------------------------------------------------
def resolve_type_references(prj: Project) -> List[str]:
    """Point struct members and event serializers at a declaration that exists."""
    log: List[str] = []
    for s in prj.services:
        declared = ([st.name for st in s.structs] + [en.name for en in s.enums]
                    + [a.name for a in s.arrays])
        for st in s.structs:
            for m in st.members:
                if base_type_name(m.type) or m.type in declared:
                    continue
                hit = best_match(m.type, declared)
                if hit:
                    log.append("%s: %s.%s type '%s' -> '%s' (nearest declaration)"
                               % (s.tag, st.name, m.name, m.type, hit))
                    m.type = hit
        for a in s.arrays:
            if base_type_name(a.element_type) or a.element_type in declared:
                continue
            hit = best_match(a.element_type, declared)
            if hit:
                log.append("%s: array %s element type '%s' -> '%s' (nearest declaration)"
                           % (s.tag, a.name, a.element_type, hit))
                a.element_type = hit
        # an event may serialise a struct or a whole array
        top_names = [st.name for st in s.structs] + [a.name for a in s.arrays]
        for e in s.events:
            if not e.serializer or e.serializer in top_names:
                continue
            hit = best_match(e.serializer, top_names)
            if hit:
                log.append("%s: event %s serializer '%s' -> '%s' (nearest struct)"
                           % (s.tag, e.name, e.serializer, hit))
                e.serializer = hit
        group_names = [g.name for g in s.event_groups]
        for e in s.events:
            if not e.event_group or e.event_group in group_names:
                continue
            hit = best_match(e.event_group, group_names)
            if hit:
                log.append("%s: event %s group '%s' -> '%s' (nearest event group)"
                           % (s.tag, e.name, e.event_group, hit))
                e.event_group = hit
    return log


# --------------------------------------------------------------------------
# 2. carry over what the workbook cannot express
# --------------------------------------------------------------------------
def carry_over(new: Project, base: Optional[Project]) -> List[str]:
    """Fill the gaps of a freshly imported project from an existing one."""
    if base is None:
        return []
    log: List[str] = []
    for svc in new.services:
        old = base.find_service(svc.tag)
        if old is None:
            old = _match_service(svc, base)
        if old is None:
            continue
        log += _carry_service(svc, old)
    return log


def _match_service(svc: Service, base: Project) -> Optional[Service]:
    hit = best_match(svc.tag, [s.tag for s in base.services])
    return base.find_service(hit) if hit else None


def _carry_service(svc: Service, old: Service) -> List[str]:
    log: List[str] = []

    # the remote provider endpoint of a consumed service
    if not svc.is_provider:
        for field in ("zone", "ipv4", "mac"):
            if not getattr(svc.remote, field) and getattr(old.remote, field):
                setattr(svc.remote, field, getattr(old.remote, field))
                log.append("%s: remote provider %s = %s (kept from the base project)"
                           % (svc.tag, field, getattr(svc.remote, field)))
        if old.remote_udp_port and svc.remote_udp_port != old.remote_udp_port:
            svc.remote_udp_port = old.remote_udp_port
            log.append("%s: remote provider UDP port = %d (kept from the base project)"
                       % (svc.tag, svc.remote_udp_port))

    # type names and <VT> texts that the ECU code already uses.  A nested struct
    # is inlined in the ARXML, so its name there was invented by the reader and
    # carries no authority - only real declarations are carried over.
    old_structs = [st.name for st in old.structs if not st.synthetic]
    for st in svc.structs:
        if st.name in old_structs:
            continue
        hit = best_match(st.name, old_structs)
        if hit and hit != st.name:
            log.append("%s: struct '%s' -> '%s' (name kept from the base project)"
                       % (svc.tag, st.name, hit))
            _rename_type(svc, st.name, hit)

    old_enums = {en.name: en for en in old.enums}
    for en in svc.enums:
        hit = best_match(en.name, list(old_enums))
        if not hit:
            continue
        if hit != en.name:
            log.append("%s: enum '%s' -> '%s' (name kept from the base project)"
                       % (svc.tag, en.name, hit))
            _rename_type(svc, en.name, hit)
        by_value = {lit.value: lit.vt for lit in old_enums[hit].literals if lit.vt}
        for lit in en.literals:
            keep = by_value.get(lit.value)
            if keep and keep != lit.vt:
                log.append("%s: %s value 0x%X <VT> '%s' -> '%s' (kept from the base project)"
                           % (svc.tag, en.name, lit.value, lit.vt, keep))
                lit.vt = keep
    return log


def _rename_type(svc: Service, old_name: str, new_name: str) -> None:
    for st in svc.structs:
        if st.name == old_name:
            st.name = new_name
        for m in st.members:
            if m.type == old_name:
                m.type = new_name
    for en in svc.enums:
        if en.name == old_name:
            en.name = new_name
    for a in svc.arrays:
        if a.name == old_name:
            a.name = new_name
        if a.element_type == old_name:
            a.element_type = new_name
    for e in svc.events:
        if e.serializer == old_name:
            e.serializer = new_name


# --------------------------------------------------------------------------
def apply_all(new: Project, base: Optional[Project] = None) -> List[str]:
    """Carry over first (it may rename types), then repair what is still dangling."""
    log = carry_over(new, base)
    log += resolve_type_references(new)
    return log
