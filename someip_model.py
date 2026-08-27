"""Data model for the SOME/IP configuration database.

The model is the single source of truth used by every part of the tool:

    Excel (*.xlsx)  --import-->  Model  --generate-->  ARXML
    ARXML           --import-->  Model  --save------->  *.someip.json

Everything the generator needs is stored explicitly, so a model loaded from
JSON regenerates the same ARXML without touching the Excel again.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field, asdict, fields, is_dataclass
from typing import Any, Dict, List, Optional

# --------------------------------------------------------------------------
# Base type catalogue
# --------------------------------------------------------------------------
# excel type -> (AUTOSAR SW-BASE-TYPE name, bit size, encoding, native decl)
BASE_TYPES: Dict[str, tuple] = {
    "boolean":  ("boolean",  8,  "BOOLEAN", None),
    "bool":     ("boolean",  8,  "BOOLEAN", None),
    "uint8_t":  ("uint8",    8,  "NONE",    "uint8"),
    "uint16_t": ("uint16",   16, "NONE",    "uint16"),
    "uint32_t": ("uint32",   32, "NONE",    "uint32"),
    "uint64_t": ("uint64",   64, "NONE",    "uint64"),
    "int8_t":   ("sint8",    8,  "2C",      "sint8"),
    "int16_t":  ("sint16",   16, "2C",      "sint16"),
    "int32_t":  ("sint32",   32, "2C",      "sint32"),
    "int64_t":  ("sint64",   64, "2C",      "sint64"),
    "float":    ("float32",  32, "IEEE754", "float32"),
    "float32":  ("float32",  32, "IEEE754", "float32"),
    "double":   ("float64",  64, "IEEE754", "float64"),
    "float64":  ("float64",  64, "IEEE754", "float64"),
}

# SOME/IP header bytes counted inside the AUTOSAR I-PDU length: RequestID(4) +
# ProtocolVersion(1) + InterfaceVersion(1) + MessageType(1) + ReturnCode(1)
SOMEIP_HEADER_IN_PDU = 8

SD_HEADER_ID = 4294934784  # 0xFFFF8100 - fixed Service Discovery header id


def base_type_name(t: str) -> Optional[str]:
    e = BASE_TYPES.get(t)
    return e[0] if e else None


def base_type_size_bytes(t: str) -> int:
    e = BASE_TYPES.get(t)
    return (e[1] // 8) if e else 0


def parse_int(v: Any, default: int = 0) -> int:
    """Accept 0x8001, '0x8001', 32769, '1', '', '-' ..."""
    if v is None:
        return default
    if isinstance(v, bool):
        return int(v)
    if isinstance(v, (int, float)):
        return int(v)
    s = str(v).strip()
    if not s or s == "-":
        return default
    try:
        return int(s, 16) if s.lower().startswith("0x") else int(s, 0)
    except ValueError:
        return default


def hex4(v: Any) -> str:
    return "0x%04X" % parse_int(v)


def hex2(v: Any) -> str:
    return "0x%02X" % parse_int(v)


# --------------------------------------------------------------------------
# Data types
# --------------------------------------------------------------------------
@dataclass
class EnumLiteral:
    name: str = ""            # Excel "Enumerate / Literal", e.g. NoEvent
    value: int = 0            # numeric value
    vt: str = ""              # AUTOSAR <VT> text, e.g. CRASH_OTPT_STS_NO_EVENT
    description: str = ""


@dataclass
class EnumType:
    name: str = ""            # e.g. CrashOtptStsType
    base_type: str = "uint8_t"
    description: str = ""
    literals: List[EnumLiteral] = field(default_factory=list)

    @property
    def compu_method(self) -> str:
        return self.name

    @property
    def data_constr(self) -> str:
        n = self.name[:-4] if self.name.endswith("Type") else self.name
        return n + "const"


# short tag used when inventing the name of an array and of its sub element,
# so `uint8_t x 16` becomes the conventional array_u8_16 / u8_data pair
ARRAY_ABBREV: Dict[str, str] = {
    "boolean": "bool", "bool": "bool",
    "uint8_t": "u8", "uint16_t": "u16", "uint32_t": "u32", "uint64_t": "u64",
    "int8_t": "s8", "int16_t": "s16", "int32_t": "s32", "int64_t": "s64",
    "float": "f32", "float32": "f32", "double": "f64", "float64": "f64",
}


def array_abbrev(element_type: str) -> str:
    return ARRAY_ABBREV.get(element_type, element_type or "elem")


def default_array_name(element_type: str, size: int) -> str:
    return "array_%s_%d" % (array_abbrev(element_type), size)


def default_array_element_name(element_type: str) -> str:
    return array_abbrev(element_type) + "_data"


@dataclass
class ArrayType:
    """A named fixed size array, emitted as its own IMPLEMENTATION-DATA-TYPE.

    Struct members and other arrays refer to it by name; the generator turns
    that into a TYPE_REFERENCE, which is what DaVinci expects for an array.
    """
    name: str = ""                        # e.g. array_u8_16
    element_type: str = "uint8_t"         # base type, enum, struct or array name
    element_name: str = ""                # SHORT-NAME of the sub element, e.g. u8_data
    size: int = 1
    size_semantics: str = "FIXED-SIZE"    # FIXED-SIZE | VARIABLE-SIZE
    description: str = ""

    @property
    def element(self) -> str:
        return self.element_name or default_array_element_name(self.element_type)


@dataclass
class StructMember:
    name: str = ""            # Excel "Element", e.g. crashOtptSts
    type: str = ""            # base type, enum, nested struct or array name
    description: str = ""


@dataclass
class StructType:
    name: str = ""            # e.g. PCUIVA10msStruct
    description: str = ""
    members: List[StructMember] = field(default_factory=list)
    # True when the name was invented while reading an ARXML: a nested struct is
    # inlined there, so its type name is not part of the file and must not be
    # carried over onto a workbook that does name it.
    synthetic: bool = False


# --------------------------------------------------------------------------
# Events / event groups
# --------------------------------------------------------------------------
@dataclass
class EventParam:
    index: int = 1
    name: str = ""
    type: str = ""
    description: str = ""


@dataclass
class Event:
    index: int = 1
    name: str = ""                  # e.g. PCUIVA10msEvent
    event_id: str = "0x8001"
    payload_length: int = 0         # bytes, from Excel PayloadLengthBytes
    pdu_length_override: int = 0    # 0 = auto (payload + 8)
    max_segment_length: str = ""
    separation_time: str = ""
    serializer: str = ""            # top level struct name
    transport: str = "UDP"
    event_group: str = ""           # event group short name
    params: List[EventParam] = field(default_factory=list)

    def pdu_length(self) -> int:
        if self.pdu_length_override:
            return self.pdu_length_override
        return self.payload_length + SOMEIP_HEADER_IN_PDU


@dataclass
class EventGroup:
    index: int = 1
    name: str = ""                  # e.g. PCUIVAEvents
    group_id: str = "0x01"
    dest_zone: str = ""             # e.g. IVA
    dest_ipv4: str = ""
    dest_mac: str = ""
    dest_udp_port: int = 0
    transport: str = "UDP"
    routing_mode: str = "StaticUnicast"


# --------------------------------------------------------------------------
# Service
# --------------------------------------------------------------------------
@dataclass
class SdTiming:
    ttl: int = 3
    initial_delay_min: float = 0.05
    initial_delay_max: float = 0.05
    repetition_base_delay: float = 0.1
    repetition_max: int = 3
    cyclic_offer_delay: float = 2.0
    request_response_delay_min: float = 0.02
    request_response_delay_max: float = 0.2


@dataclass
class Endpoint:
    """A named IPv4/MAC endpoint on the ethernet channel."""
    zone: str = ""
    ipv4: str = ""
    mac: str = ""


@dataclass
class TsnSwitch:
    model: str = ""
    bridge_mac: str = ""
    ring_port_cw_neighbor: str = ""
    ring_port_ccw_neighbor: str = ""


@dataclass
class TsnStream:
    zone: str = ""
    topology: str = "Ring"
    vlan_id: int = 5
    vlan_priority: int = 6
    traffic_class: str = "TC6"
    traffic_profile: str = ""


@dataclass
class Service:
    role: str = "provider"                 # "provider" | "consumer"
    tag: str = ""                          # short tag, e.g. PCU / RMCU
    instance_name: str = ""                # PCUService
    interface_name: str = ""               # PCUServiceInterface
    instance_id: str = "0x600D"
    major_version: int = 1
    minor_version: int = 0

    sd_udp_port: int = 30490
    sd: SdTiming = field(default_factory=SdTiming)

    local: Endpoint = field(default_factory=Endpoint)
    tsn_switch: TsnSwitch = field(default_factory=TsnSwitch)
    tsn: TsnStream = field(default_factory=TsnStream)

    deployment_name: str = ""              # PCUServiceInterface_Deployment
    interface_id: str = "0x500D"           # ServiceInterfaceId

    service_instance_name: str = ""        # ProvidedSomeipPCUServiceInstance
    load_balancing_priority: str = "-"
    load_balancing_weight: str = "-"

    mapping_name: str = ""                 # PCUServiceInstanceToMachineMapping
    communication_connector: str = "-"
    secoc_com_props_multicast: str = "-"
    secure_com_props_tcp: str = "-"
    secure_com_props_udp: str = "-"
    tcp_port: str = "-"
    udp_port: int = 0                      # local application UDP port
    udp_collection_buffer_size_threshold: str = "-"

    routing_mode: str = "StaticUnicast"

    # For a consumer the remote provider endpoint is NOT described in the
    # customer Excel, so it is kept here and edited in the GUI.
    remote: Endpoint = field(default_factory=Endpoint)
    remote_udp_port: int = 30500

    events: List[Event] = field(default_factory=list)
    event_groups: List[EventGroup] = field(default_factory=list)
    structs: List[StructType] = field(default_factory=list)
    enums: List[EnumType] = field(default_factory=list)
    arrays: List[ArrayType] = field(default_factory=list)

    source_file: str = ""

    # -- helpers ----------------------------------------------------------
    @property
    def is_provider(self) -> bool:
        return self.role == "provider"

    @property
    def routing_group(self) -> str:
        return "SoAdRG_%s_%s_EventGroup" % (self.tag, "P" if self.is_provider else "C")

    def find_event_group(self, name: str) -> Optional[EventGroup]:
        for g in self.event_groups:
            if g.name == name:
                return g
        return self.event_groups[0] if self.event_groups else None

    def find_struct(self, name: str) -> Optional[StructType]:
        for s in self.structs:
            if s.name == name:
                return s
        return None

    def find_enum(self, name: str) -> Optional[EnumType]:
        for e in self.enums:
            if e.name == name:
                return e
        return None

    def find_array(self, name: str) -> Optional[ArrayType]:
        for a in self.arrays:
            if a.name == name:
                return a
        return None

    def struct_size(self, name: str, _seen=None) -> int:
        """Serialized size in bytes of a struct (SOME/IP, no padding)."""
        _seen = _seen or set()
        if name in _seen:
            return 0
        _seen = _seen | {name}
        st = self.find_struct(name)
        if st is None:
            arr = self.find_array(name)
            if arr:
                return max(0, arr.size) * self.struct_size(arr.element_type, _seen)
            en = self.find_enum(name)
            if en:
                return base_type_size_bytes(en.base_type)
            return base_type_size_bytes(name)
        total = 0
        for m in st.members:
            if base_type_name(m.type):
                total += base_type_size_bytes(m.type)
            else:
                total += self.struct_size(m.type, _seen)
        return total


# --------------------------------------------------------------------------
# Project
# --------------------------------------------------------------------------
@dataclass
class Project:
    name: str = "ZA_someip"
    ecu_name: str = "ZAFL"
    autosar_release: str = "R4.4.0"
    schema: str = "AUTOSAR_00046.xsd"

    cluster_name: str = "EthernetCluster"
    channel_name: str = "ChannelCommunication"
    baudrate: int = 100000000
    physical_layer_type: str = "100BASE-T1"

    vlan_name: str = "Vlan"
    vlan_id: int = 5
    vlan_priority: int = 6

    ecu_mac_unicast: str = "02:20:00:00:00:02"
    network_mask: str = "255.255.255.0"
    multicast_ipv4: str = "239.192.255.251"
    multicast_mac: str = "01:00:5E:00:00:00"
    com_tx_time_base: float = 0.01

    base_type_package: str = "/AUTOSAR_Platform/BaseTypes"
    # where the platform IMPLEMENTATION-DATA-TYPEs live; an array sub element
    # references its element type there instead of a SW-BASE-TYPE
    platform_type_package: str = "/AUTOSAR_Platform/ImplementationDataTypes"
    local_endpoint_tag: str = ""   # short name used for NEP_<tag>; "" = first provider tag
    template: str = "someip.arxml.tpl"   # file in templates/, or an absolute path
    port_iface_prefix_provider: str = "SoIp_I_Server_"
    port_iface_prefix_consumer: str = "SoIp_I_"

    services: List[Service] = field(default_factory=list)

    # -- helpers ----------------------------------------------------------
    def local_tag(self) -> str:
        if self.local_endpoint_tag:
            return self.local_endpoint_tag
        for s in self.services:
            if s.is_provider:
                return s.tag
        return self.services[0].tag if self.services else "ECU"

    def local_endpoint(self) -> Endpoint:
        for s in self.services:
            if s.local.ipv4:
                return s.local
        return Endpoint()

    def find_service(self, tag: str) -> Optional[Service]:
        for s in self.services:
            if s.tag == tag:
                return s
        return None

    # -- (de)serialisation ------------------------------------------------
    def to_json(self, path: str) -> None:
        with open(path, "w", encoding="utf-8") as fh:
            json.dump(asdict(self), fh, indent=2, ensure_ascii=False)

    @staticmethod
    def from_json(path: str) -> "Project":
        with open(path, "r", encoding="utf-8") as fh:
            return build_dataclass(Project, json.load(fh))


def build_dataclass(cls, data):
    """Rebuild nested dataclasses from a plain dict (json round trip)."""
    if not is_dataclass(cls) or data is None:
        return data
    kwargs = {}
    for f in fields(cls):
        if f.name not in data:
            continue
        val = data[f.name]
        tname = f.type if isinstance(f.type, str) else getattr(f.type, "__name__", "")
        if tname.startswith("List["):
            inner = tname[5:-1]
            sub = _REGISTRY.get(inner)
            kwargs[f.name] = [build_dataclass(sub, v) for v in val] if sub else val
        elif tname in _REGISTRY:
            kwargs[f.name] = build_dataclass(_REGISTRY[tname], val)
        else:
            kwargs[f.name] = val
    return cls(**kwargs)


_REGISTRY = {
    "EnumLiteral": EnumLiteral, "EnumType": EnumType,
    "StructMember": StructMember, "StructType": StructType, "ArrayType": ArrayType,
    "EventParam": EventParam, "Event": Event, "EventGroup": EventGroup,
    "SdTiming": SdTiming, "Endpoint": Endpoint, "TsnSwitch": TsnSwitch,
    "TsnStream": TsnStream, "Service": Service, "Project": Project,
}
