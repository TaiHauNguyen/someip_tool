"""Consistency checks over the model.

These run before every ARXML generation and are shown in the GUI's Check tab,
so problems that only exist in the customer workbook (a mistyped enum name, a
payload length that does not match the struct, ...) surface early instead of
becoming a broken DaVinci import.
"""

from __future__ import annotations

from typing import List, Tuple

from someip_model import Project, Service, base_type_name, parse_int

ERROR, WARN, INFO = "ERROR", "WARNING", "INFO"


def validate(prj: Project) -> List[Tuple[str, str, str]]:
    """Return [(severity, where, message)]."""
    out: List[Tuple[str, str, str]] = []

    if not prj.services:
        out.append((ERROR, "Project", "No service defined - import an Excel file first."))
        return out

    # -- project wide ----------------------------------------------------
    local_ips = {s.local.ipv4 for s in prj.services if s.local.ipv4}
    if len(local_ips) > 1:
        out.append((ERROR, "Project",
                    "Services disagree on the local MCU IPv4 address: %s" % ", ".join(sorted(local_ips))))

    seen_iface, seen_inst = {}, {}
    for s in prj.services:
        iid, inst = parse_int(s.interface_id), parse_int(s.instance_id)
        if iid in seen_iface:
            out.append((ERROR, s.tag, "ServiceInterfaceId %s already used by %s"
                        % (s.interface_id, seen_iface[iid])))
        seen_iface[iid] = s.tag
        if inst in seen_inst:
            out.append((ERROR, s.tag, "ServiceInstanceId %s already used by %s"
                        % (s.instance_id, seen_inst[inst])))
        seen_inst[inst] = s.tag

    ports = {}
    for s in prj.services:
        if not s.udp_port:
            out.append((ERROR, s.tag, "SomeipServiceInstanceToMachineMapping.UdpPort is empty."))
        elif s.udp_port in ports:
            out.append((ERROR, s.tag, "Local UDP port %d already used by %s" % (s.udp_port, ports[s.udp_port])))
        else:
            ports[s.udp_port] = s.tag

    for s in prj.services:
        out.extend(_validate_service(prj, s))
    return out


def _validate_service(prj: Project, s: Service) -> List[Tuple[str, str, str]]:
    out: List[Tuple[str, str, str]] = []
    where = s.tag or s.instance_name or "?"

    if not s.tag:
        out.append((ERROR, where, "ServiceInstanceName is empty - cannot derive a short tag."))
    if not parse_int(s.interface_id):
        out.append((ERROR, where, "ServiceInterfaceId is 0."))
    if not parse_int(s.instance_id):
        out.append((ERROR, where, "ServiceInstanceId is 0."))

    group_names = {g.name for g in s.event_groups}
    if not s.event_groups:
        out.append((ERROR, where, "No event group defined."))

    if not s.is_provider and not s.remote.ipv4:
        out.append((WARN, where,
                    "Consumer has no remote provider IPv4 address; set it on the Service tab "
                    "(the customer workbook does not contain it)."))

    # all endpoints of one physical channel have to sit in the same subnet; an
    # address that does not is almost always a value left over from a template
    for peer_ip, label in _peer_addresses(s):
        if peer_ip and s.local.ipv4 and not _same_subnet(s.local.ipv4, peer_ip, prj.network_mask):
            out.append((WARN, where,
                        "%s %s is not in the subnet of the local MCU %s (mask %s) - "
                        "check whether it is a leftover value."
                        % (label, peer_ip, s.local.ipv4, prj.network_mask)))

    header_ids = {}
    for e in s.events:
        w = "%s / %s" % (where, e.name)
        if e.event_group and e.event_group not in group_names:
            out.append((ERROR, w, "EventGroup '%s' is not defined in the EventGroups sheet." % e.event_group))
        hid = (parse_int(s.interface_id) << 16) | parse_int(e.event_id)
        if hid in header_ids:
            out.append((ERROR, w, "EventId %s collides with %s (header id 0x%08X)"
                        % (e.event_id, header_ids[hid], hid)))
        header_ids[hid] = e.name
        if (e.transport or "UDP").upper() != "UDP":
            out.append((ERROR, w, "TransportProtocol '%s' is not supported - the generator "
                                  "only emits UDP sockets (UDP-TP).  Emitting this event "
                                  "would silently put it on a UDP socket." % e.transport))
        if parse_int(e.event_id) < 0x8000:
            out.append((WARN, w, "EventId %s is below 0x8000 - notification events normally start at 0x8000."
                        % e.event_id))

        if not e.serializer:
            out.append((ERROR, w, "No Serializer struct given."))
        elif s.find_struct(e.serializer) is None and s.find_array(e.serializer) is None:
            out.append((ERROR, w, "Serializer struct '%s' is not defined in DataStructures." % e.serializer))
        else:
            computed = s.struct_size(e.serializer)
            if computed and e.payload_length and computed != e.payload_length:
                out.append((WARN, w, "PayloadLengthBytes=%d but '%s' serialises to %d bytes."
                            % (e.payload_length, e.serializer, computed)))
        out.append((INFO, w, "PDU length = %d bytes (payload %d + 8 SOME/IP header), header id 0x%08X"
                    % (e.pdu_length(), e.payload_length, hid)))

    # -- data types ------------------------------------------------------
    known = {st.name for st in s.structs} | {en.name for en in s.enums} | {a.name for a in s.arrays}

    type_names = [st.name for st in s.structs] + [en.name for en in s.enums] + \
                 [a.name for a in s.arrays]
    dup = {n for n in type_names if type_names.count(n) > 1}
    for n in sorted(dup):
        out.append((ERROR, "%s / %s" % (where, n),
                    "Several data types share this name - AUTOSAR short names must be unique."))

    for ar in s.arrays:
        w = "%s / %s" % (where, ar.name)
        if not ar.name:
            out.append((ERROR, where, "Array has no name."))
        if ar.size < 1:
            out.append((ERROR, w, "ARRAY-SIZE is %d - it has to be at least 1." % ar.size))
        if ar.size_semantics not in ("FIXED-SIZE", "VARIABLE-SIZE"):
            out.append((ERROR, w, "ARRAY-SIZE-SEMANTICS '%s' is neither FIXED-SIZE nor "
                                  "VARIABLE-SIZE." % ar.size_semantics))
        if not ar.element:
            out.append((ERROR, w, "The array sub element has no short name."))
        if base_type_name(ar.element_type) is None and ar.element_type not in known:
            out.append((ERROR, w, "Unknown element type '%s' - it is neither a base type, "
                                  "a struct, an enum nor an array of this service."
                        % ar.element_type))
        if ar.element_type == ar.name:
            out.append((ERROR, w, "Array is its own element type."))

    for st in s.structs:
        if not st.members:
            out.append((WARN, "%s / %s" % (where, st.name), "Struct has no member."))
        seen = set()
        for m in st.members:
            w = "%s / %s.%s" % (where, st.name, m.name)
            if m.name in seen:
                out.append((ERROR, w, "Duplicate member name."))
            seen.add(m.name)
            if base_type_name(m.type) is None and m.type not in known:
                out.append((ERROR, w, "Unknown type '%s' - it is neither a base type, "
                                      "a struct nor an enum of this service." % m.type))

    for en in s.enums:
        values = {}
        for lit in en.literals:
            w = "%s / %s" % (where, en.name)
            if lit.value in values:
                out.append((WARN, w, "Value 0x%X used by both '%s' and '%s'."
                            % (lit.value, values[lit.value], lit.name)))
            values[lit.value] = lit.name
        vts = [l.vt for l in en.literals]
        if len(set(vts)) != len(vts):
            out.append((ERROR, "%s / %s" % (where, en.name),
                        "Duplicate <VT> text - AUTOSAR requires unique text table entries."))
        if base_type_name(en.base_type) is None:
            out.append((ERROR, "%s / %s" % (where, en.name), "Unknown base type '%s'." % en.base_type))

    used = set()
    for e in s.events:
        _collect(s, e.serializer, used)
    for st in s.structs:
        if st.name not in used:
            out.append((INFO, "%s / %s" % (where, st.name), "Struct is not referenced by any event."))
    for en in s.enums:
        if en.name not in used:
            out.append((INFO, "%s / %s" % (where, en.name), "Enum is not referenced by any struct member."))
    for ar in s.arrays:
        if ar.name not in used:
            out.append((INFO, "%s / %s" % (where, ar.name),
                        "Array is not referenced by any struct member or event."))
    return out


def _peer_addresses(s: Service):
    """Every remote IPv4 this service talks to, with a label for the message."""
    out = []
    if not s.is_provider and s.remote.ipv4:
        out.append((s.remote.ipv4, "Remote provider address"))
    for g in s.event_groups:
        if g.dest_ipv4:
            out.append((g.dest_ipv4, "Destination of event group '%s'" % g.name))
    return out


def _ipv4(text: str):
    parts = (text or "").split(".")
    if len(parts) != 4:
        return None
    try:
        octets = [int(p) for p in parts]
    except ValueError:
        return None
    if any(o < 0 or o > 255 for o in octets):
        return None
    return (octets[0] << 24) | (octets[1] << 16) | (octets[2] << 8) | octets[3]


def _same_subnet(a: str, b: str, mask: str) -> bool:
    ia, ib, im = _ipv4(a), _ipv4(b), _ipv4(mask)
    if ia is None or ib is None or im is None:
        return True   # cannot tell - do not cry wolf
    return (ia & im) == (ib & im)


def _collect(s: Service, type_name: str, acc: set) -> None:
    if not type_name or type_name in acc:
        return
    acc.add(type_name)
    arr = s.find_array(type_name)
    if arr is not None:
        _collect(s, arr.element_type, acc)
        return
    st = s.find_struct(type_name)
    if st is None:
        return
    for m in st.members:
        _collect(s, m.type, acc)


def summary(issues) -> str:
    n_err = sum(1 for sev, _, _ in issues if sev == ERROR)
    n_warn = sum(1 for sev, _, _ in issues if sev == WARN)
    return "%d error(s), %d warning(s)" % (n_err, n_warn)
