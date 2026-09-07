# Excel → ARXML mapping (ZAFL SOME/IP)

How `PCU_Provider.xlsx` + `RMCU_Consumer.xlsx` become `ZA_someip.arxml`.
This is the rule set the generator implements; the GUI edits the same model.

Notation used below:

| Symbol | Meaning | Example |
|---|---|---|
| `T` | service short tag = `ServiceInstanceName` minus the `Service` suffix | `PCU`, `RMCU` |
| `E` | event name from `Events!Name` | `PCUIVA10msEvent` |
| `G` | event group name from `EventGroups!Name` | `PCUIVAEvents` |
| `Z` | a peer zone name (`EventGroups!DestinationZone`) | `IVA` |
| `LOCAL` | tag used for the local ECU endpoint, defaults to the first provider's `T` | `PCU` |

---

## 1. The two derived numbers everything hangs off

```
SERVICE-IDENTIFIER   = SomeipServiceDeployment.ServiceInterfaceId     0x500D → 20493
INSTANCE-IDENTIFIER  = ServiceInstanceId                              0x600D → 24589
HEADER-ID (per event)= (ServiceInterfaceId << 16) | EventId
                       0x500D << 16 | 0x8001 = 0x500D8001 = 1343062017
EVENT-GROUP-IDENTIFIER = EventGroups.EventGroupId                     0x01 → 1
```

Service Discovery PDUs always use the fixed header id `0xFFFF8100` = `4294934784`.

---

## 2. Configuration sheet → ARXML

| Excel (`Configuration`) | ARXML element | Path |
|---|---|---|
| `ServiceInstanceName` | derives `T`, and all the `SA_/PSI_/CSI_/SCB_` short names | – |
| `ServiceInstanceId` | `INSTANCE-IDENTIFIER` | `.../PROVIDED-SERVICE-INSTANCE` |
| `SomeipServiceDeployment.ServiceInterfaceId` | `SERVICE-IDENTIFIER` | `.../PROVIDED-SERVICE-INSTANCE` |
| `Someip Interface Major/Minor Version` | `SERVER-SERVICE-MAJOR/MINOR-VERSION`, `CLIENT-SERVICE-MAJOR/MINOR-VERSION`, `INTERFACE-VERSION` | SD configs + `SOMEIP-TRANSFORMATION-DESCRIPTION` |
| `SomeipServiceDiscovery.UdpPort` | `PORT-NUMBER` of every `SD_SA_*` socket | `SOCKET-ADDRESSS` |
| `SomeipServiceDiscovery.TTL` etc. | `TTL`, `INITIAL-OFFER-BEHAVIOR`, `OFFER-CYCLIC-DELAY` | `SD-SERVER-CONFIG` / `SD-CLIENT-CONFIG` |
| `LocalMcuEndpoint.Ipv4Address` | `IPV-4-ADDRESS` of `NEP_LOCAL` | `NETWORK-ENDPOINTS` |
| `LocalMcuEndpoint.MacAddress` | reference only – ARXML carries the controller MAC instead | – |
| `SomeipServiceInstanceToMachineMapping.UdpPort` | `PORT-NUMBER` of `SA_T` | `SOCKET-ADDRESS/APPLICATION-ENDPOINT/TP-CONFIGURATION` |
| `ProvidedSomeipServiceInstance` present | role = **provider** → local socket gets `PROVIDED-SERVICE-INSTANCE` | – |
| `ConsumedSomeipServiceInstance` present | role = **consumer** → local socket gets `CONSUMED-SERVICE-INSTANCE` | – |
| `StaticEventRouting.Mode` | `EVENT-GROUP-CONTROL-TYPE` (`StaticUnicast` → `ACTIVATION-UNICAST`) | `SO-AD-ROUTING-GROUP` |
| `TSN.VLAN ID` | `VLAN-IDENTIFIER` | `ETHERNET-PHYSICAL-CHANNEL/VLAN` |
| `TSN.VLAN Priority` | `DEFAULT-PRIORITY` | `COUPLING-PORT/VLAN-MEMBERSHIP` |
| `TSN.TrafficClass`, `TrafficProfile`, `LocalTsnSwitch.*` | **not represented** in this ARXML – kept in the model for the switch configuration | – |

---

## 3. Events sheet → ARXML

One row of `Events` produces **eight** elements:

| # | Element | Short name | Key content |
|---|---|---|---|
| 1 | `SYSTEM-SIGNAL` | `sys_E` | `DYNAMIC-LENGTH = false` |
| 2 | `I-SIGNAL` | `sig_E` | `LENGTH = pdu length`, `DATA-TYPE-POLICY = TRANSFORMING-I-SIGNAL`, SOME/IP transformer ref, `MESSAGE-TYPE = NOTIFICATION` |
| 3 | `I-SIGNAL-I-PDU` | `pdu_E` | `LENGTH`, `I-SIGNAL-TO-I-PDU-MAPPING map_sig_E` |
| 4 | `I-SIGNAL-TRIGGERING` | `ST_E` | refs `sig_E` and `SP_E` |
| 5 | `PDU-TRIGGERING` | `PT_E` | refs `pdu_E`, `PP_E`, `ST_E` |
| 6 | `I-SIGNAL-PORT` | `SP_E` | direction `OUT` (provider) / `IN` (consumer) |
| 7 | `I-PDU-PORT` | `PP_E` | same direction |
| 8 | `SENDER-RECEIVER-INTERFACE` | `SoIp_I_Server_E` / `SoIp_I_E` | `VARIABLE-DATA-PROTOTYPE E` typed with the serializer struct |

plus one `SOCKET-CONNECTION-IPDU-IDENTIFIER` inside `SCB_T` carrying the header id.

The two prefixes of row 8 are the project settings *Port iface prefix
(provider)* and *(consumer)*.  They are **read back out of the file**: the
reader takes each `SENDER-RECEIVER-INTERFACE` short name, strips the name of the
`VARIABLE-DATA-PROTOTYPE` it contains, and uses what is left - so a file that
follows its own convention (`SoIp_I_Srv_`, `IF_`, or no prefix at all) keeps it
when the tool regenerates it, instead of being silently renamed to the default.
Because the `UUID` is the MD5 of the element path, losing the prefix would also
change every port interface UUID and break the DaVinci import.

### PDU length

```
LENGTH = PayloadLengthBytes + 8
```

The 8 bytes are the part of the SOME/IP header that AUTOSAR counts inside the
PDU: RequestID (4) + ProtocolVersion (1) + InterfaceVersion (1) + MessageType (1)
+ ReturnCode (1).  The GUI has a per-event override field if a specific event
has to keep a different value.

### Column mapping

| Excel column | Used for |
|---|---|
| `Name` | `E` – drives all eight short names above |
| `EventId` | lower half of the header id |
| `PayloadLengthBytes` | `LENGTH` (+8) of the PDU and the I-Signal |
| `Serializer` | the top level struct → `TYPE-TREF` of the port interface |
| `TransportProtocol` | UDP → `UDP-TP`. **TCP is rejected** by the validator: the generator only emits UDP sockets, so a TCP event would silently be put on a UDP one |
| `EventGroup` | the `CEG_G` / `EH_G` the event belongs to |
| `MaximumSegmentLength`, `SeparationTime` | SOME/IP-TP segmentation – **not used** by this file |
| `ParameterName/Type/Description` | documentation only |

> **Note on `PCU_Provider.xlsx!Events`:** the data row is shifted two columns to
> the left of the header row (`Serializer` sits under `MaximumSegmentLength`).
> The importer detects this by locating the `UDP`/`TCP` cell and re-aligns the
> tail columns, so both workbook layouts read correctly.

---

## 4. EventGroups sheet → ARXML

| Excel column | ARXML |
|---|---|
| `Name` | `CEG_G` (consumer side) and `EH_G` (provider side) |
| `EventGroupId` | `EVENT-GROUP-IDENTIFIER` |
| `DestinationIpv4Address` | `IPV-4-ADDRESS` of the peer `NEP_Z` |
| `DestinationUdpPort` | `PORT-NUMBER` of the peer socket `SA_Z_T` |
| several groups with different destinations | one peer socket `SA_Z_T` and one bundle `SCB_T_Z` per distinct `(zone, address, port)`; with a single destination the bundle keeps the shorter name `SCB_T` |
| `DestinationZone` | `Z`, i.e. the `NEP_Z` / `SA_Z_T` / `SD_SA_Z` short names |
| `RoutingMode` | `EVENT-GROUP-CONTROL-TYPE` of `SoAdRG_T_*_EventGroup` |

For a **consumer**, `DestinationIpv4Address` equals the local MCU address (the
events are delivered *to us*), so it maps onto the local socket instead of a
peer socket.  The address of the ECU that *offers* the service is not in the
workbook at all – set it on the GUI **Services** tab under *Remote provider*.

---

## 5. DataStructures sheet → ARXML

### Struct block (`Index / Name / Element / Type / Description`)

Each top level struct becomes one `IMPLEMENTATION-DATA-TYPE` with
`CATEGORY = STRUCTURE` and `TYPE-EMITTER = RTE` under `/DataTypes`.
Members are emitted as `IMPLEMENTATION-DATA-TYPE-ELEMENT`:

| Member type | `CATEGORY` | Content |
|---|---|---|
| base type (`float`, `uint8_t`, `uint32_t`, …) | `VALUE` | `BASE-TYPE-REF /AUTOSAR_Platform/BaseTypes/<float32\|uint8\|uint32>` |
| an enum name | `VALUE` | `BASE-TYPE-REF` + `COMPU-METHOD-REF` + `DATA-CONSTR-REF` |
| another struct name | `STRUCTURE` | the referenced struct is **inlined** as nested `SUB-ELEMENTS` |
| an array name | `TYPE_REFERENCE` | `IMPLEMENTATION-DATA-TYPE-REF /DataTypes/<array name>` |

Type name translation: `float → float32`, `double → float64`, `uint8_t → uint8`,
`uint32_t → uint32`, `int8_t → sint8`, `boolean → boolean`.

#### Bit fields → one member per packed run

A Type cell written as `<type> : <n>` - `uint8_t : 4`, `ACUCrashStsType : 2` -
declares a field `n` bits wide.  This is what `dbc_bitfield_excel.py` writes
when it turns a CAN message into a struct that maps 1:1 onto the frame,
padding included (`Reserved_1`, `Reserved_2`, …).

**These do not become C bit fields in the ARXML, and must not.**  Three
independent constraints say so:

| | |
|---|---|
| DaVinci Developer | A Record Element has no bit width attribute at all (Technical Reference *AUTOSAR 4.4 - Data Types*, §2.2.2 lists every attribute; `DaVinciDEV01.chm` never mentions one either).  Its RTE always emits a plain `typedef` (§6, §7.4), never `x : 4`. |
| `SW-BIT-REPRESENTATION` | Schema-valid (it sits right after `BASE-TYPE-REF` in `AUTOSAR_4-0-0-DAI-1.xsd`) but nothing in DaVinci Developer reads it - a file carrying it imports cleanly and comes out looking like plain bytes. |
| SOME/IP | The transformer serializes every primitive member at its full base type width.  Sub-byte packing does not exist on the wire, so a member per signal could never reproduce the CAN byte layout anyway. |

The one bit-level construct DaVinci Developer really supports is a compu method
of category `BITFIELD_TEXTTABLE` on a **whole byte** - exactly what
`/Predefined_DEV/CompuMethods/Dem_UdsStatusByteType` in this project's own
`DataTypes.arxml` does.  So a run of consecutive bit fields is packed here into
**one member as wide as the run**, and each named sub-value becomes one compu
scale carrying the field's `MASK`:

```xml
<IMPLEMENTATION-DATA-TYPE-ELEMENT>
  <SHORT-NAME>Byte2</SHORT-NAME>
  <CATEGORY>VALUE</CATEGORY>
  <SW-DATA-DEF-PROPS><SW-DATA-DEF-PROPS-VARIANTS><SW-DATA-DEF-PROPS-CONDITIONAL>
    <BASE-TYPE-REF DEST="SW-BASE-TYPE">/AUTOSAR_Platform/BaseTypes/uint8</BASE-TYPE-REF>
    <COMPU-METHOD-REF DEST="COMPU-METHOD">/DataTypes/CompuMethods/ACUCrashInfoStruct_Byte2</COMPU-METHOD-REF>
    <DATA-CONSTR-REF DEST="DATA-CONSTR">/DataTypes/DataConstraints/ACUCrashInfoStruct_Byte2</DATA-CONSTR-REF>
  </SW-DATA-DEF-PROPS-CONDITIONAL></SW-DATA-DEF-PROPS-VARIANTS></SW-DATA-DEF-PROPS>
</IMPLEMENTATION-DATA-TYPE-ELEMENT>
```

```xml
<COMPU-METHOD>
  <SHORT-NAME>ACUCrashInfoStruct_Byte2</SHORT-NAME>
  <CATEGORY>BITFIELD_TEXTTABLE</CATEGORY>
  ...
    <COMPU-SCALE>                              <!-- ACU_Crash_Sts, byte2 [2:1] -->
      <SHORT-LABEL>ACUCrashInfoStruct_ACU_CRASH_STS_CRASH_DETECTED</SHORT-LABEL>
      <SYMBOL>ACUCrashInfoStruct_ACU_CRASH_STS_CRASH_DETECTED</SYMBOL>
      <MASK>6</MASK>                           <!-- 0b00000110: which bits -->
      <LOWER-LIMIT INTERVAL-TYPE="CLOSED">2</LOWER-LIMIT>   <!-- value in place -->
      <UPPER-LIMIT INTERVAL-TYPE="CLOSED">2</UPPER-LIMIT>
    </COMPU-SCALE>
```

**Naming.** The label is `<struct>_<the literal's VT>`, not the bare VT.  It
becomes a global C constant, and DaVinci refuses the same `SHORT-LABEL` twice
in one workspace - which may hold several separately generated ARXMLs, so a
counter that only sees the file being written is not enough: a provider and a
consumer would each emit `ACU_CRASH_STS_CRASH_DETECTED` for their own struct.
Deriving it from the struct makes it deterministic instead: the same input
gives the same name whatever is generated beside it, and two services that
really share a struct share the constants too, so DaVinci merges them.

An enum's own `TEXTTABLE` compu method is emitted only when some member still
points at it.  A bit field's enum is folded into its byte, so emitting the
enum as well would leave an enumeration in the workspace that nothing uses.

`MASK` is the field's bit range (`((1 << width) - 1) << shift`), shared by every
scale of that field; `LOWER-LIMIT` = `UPPER-LIMIT` is the literal value shifted
into position.  The RTE turns each scale into a `#define`, so application code
masks and shifts to read a signal.  Bits are filled MSB first, matching the
Motorola order the DBC importer writes.

**Where a run ends.**  At the first *byte boundary*, not after eight bits.  A
CAN signal may be wider than a byte and still not fill whole ones: `UBatt` is
14 bits over byte2..byte3, and the two padding bits behind it belong to the
same two byte unit.  That run becomes one `uint16` named `Bytes2_3`, with the
masks measured across all 16 bits.  A one byte run keeps the name `Byte<n>`; a
wider one is `Bytes<first>_<last>`.

No integer is three or five bytes wide, so a run of that size falls back to one
plain `uint8` per byte: the struct still measures what the frame does, which
matters more than naming the fields inside it.

**Which members stay whole.** A member with no width, or one exactly `: 8` wide,
keeps its own name and type - only sub-byte fields are merged.  So
`ACUCrashInfoStruct` becomes `CRC_ACU_CRASH_INFO`, `Byte1` … `Byte4`,
`Reserved_4` … `Reserved_6`: **8 members, 8 bytes, the CAN frame unchanged.**

**Size.** A run of consecutive bit fields counts as `ceil(sum of bits / 8)`
bytes, not one storage unit per member; a non bit field member closes the run.
So the 16 rows of `ACUCrashInfoStruct` (8+4+4+3+2+2+1+2+2+2+2+6+2+8+8+8 = 64
bits) are 8 bytes, which is what `PayloadLengthBytes` must say.

**Checks** (`validate.py`): a width wider than its storage type, a bit field
over a float or over a struct or array, and a run whose bits do not add up to
whole bytes are reported.  The length of the *generated* struct is checked
against the model too - it is computed twice by two different pieces of code,
and when those drift the data type silently stops matching the DLC.  A sub-byte field with no enum gets an INFO: it has no
named values, so it gets no compu scale and its name does not reach the ARXML -
only its bits are held.

### Array block (**Data Types** tab → *Arrays*)

Unlike a nested struct, an array is never inlined: it becomes an
`IMPLEMENTATION-DATA-TYPE` of its own with `CATEGORY = ARRAY` and
`TYPE-EMITTER = RTE` under `/DataTypes`, holding exactly one
`IMPLEMENTATION-DATA-TYPE-ELEMENT` that carries `ARRAY-SIZE` and
`ARRAY-SIZE-SEMANTICS`.  Whatever refers to the array - a struct member, another
array, or an event serializer - points at it with an
`IMPLEMENTATION-DATA-TYPE-REF`.

| Field | Goes to | Example |
|---|---|---|
| Name | `SHORT-NAME` of the array type | `array_u8_16` |
| Element short name | `SHORT-NAME` of the sub element (blank = `<abbrev>_data`) | `u8_data` |
| Array size | `ARRAY-SIZE` | `16` |
| Size semantics | `ARRAY-SIZE-SEMANTICS` | `FIXED-SIZE` |

The sub element is rendered from the **element type**:

| Element type | `CATEGORY` | Content |
|---|---|---|
| base type | `TYPE_REFERENCE` | `IMPLEMENTATION-DATA-TYPE-REF /AUTOSAR_Platform/ImplementationDataTypes/<uint8\|…>` |
| an enum name | `VALUE` | `BASE-TYPE-REF` + `COMPU-METHOD-REF` + `DATA-CONSTR-REF` |
| a struct or array name | `TYPE_REFERENCE` | `IMPLEMENTATION-DATA-TYPE-REF /DataTypes/<name>` |

Arrays are emitted **before** whatever refers to them, and an array of a struct
or of another array drags that type into the file too, so no reference dangles.
Every `UUID` is the deterministic MD5 of the element's absolute path
(`/DataTypes/array_u8_16/u8_data` for the sub element above), which keeps them
unique across the file and stable when the file is regenerated.

The serialized size of an array is `size × size of the element type`, so the
**Bytes** column and the `PayloadLengthBytes` check of section 6 cover arrays
like any other type.

### Enum block (`Index / Name / Type / Enumerate|Enumeral / Value / Description`)

Each enum produces two elements:

| Element | Short name | Content |
|---|---|---|
| `COMPU-METHOD` | the enum name, e.g. `CrashOtptStsType` | `CATEGORY = TEXTTABLE`, one `COMPU-SCALE` per literal with `LOWER-LIMIT = UPPER-LIMIT = Value` and `<VT>` |
| `DATA-CONSTR` | enum name with `Type` stripped + `const`, e.g. `CrashOtptStsconst` | `INTERNAL-CONSTRS 0 .. 2^bits-1` |

The `<VT>` text is the RTE enum constant.  The tool generates a default by
converting the type and literal names to `UPPER_SNAKE_CASE`
(`CrashOtptStsType` + `NoEvent` → `CRASH_OTPT_STS_NO_EVENT`) and appending
`_2`, `_3` … to duplicates (`Reserved` at 0x5 and 0x6 → `..._RESERVED`,
`..._RESERVED_2`).  Because the hand written file uses abbreviations that no
rule can guess (`PCU_BCM_REMOTE_FUNC_*`), the `<VT>` is a normal editable field
on the **Data Types** tab, and the *carry over* rule of section 7 keeps the
texts an existing ARXML already shipped, so the ECU code keeps compiling.

---

## 6. Topology derived from the two workbooks

### Network endpoints

| Short name | Address source |
|---|---|
| `NEP_ANY_SD` | literal `ANY` |
| `NEP_MC` | project multicast address `239.192.255.251` + `MAC-MULTICAST-GROUP` |
| `NEP_LOCAL` | `LocalMcuEndpoint.Ipv4Address` + network mask |
| `NEP_Z` | `EventGroups.DestinationIpv4Address` (provider) or the remote provider address (consumer) |

A destination whose IPv4 equals the local address reuses `NEP_LOCAL` instead of
getting its own endpoint.

### Sockets

| Role | Socket | Instance | Content |
|---|---|---|---|
| provider | `SA_T` (local, has `CONNECTOR-REF`) | `PSI_T` | `EH_G` per event group, `SERVICE-IDENTIFIER`, `INSTANCE-IDENTIFIER`, `SD-SERVER-CONFIG` |
| provider | `SA_Z_T` (peer) | `CSI_Z_T` | `CEG_G` with the event group id, `SD-CLIENT-CONFIG` |
| consumer | `SA_T` (local, has `CONNECTOR-REF`) | `CSI_T` | `CEG_G`, `SD-CLIENT-CONFIG` |
| consumer | `SA_Z_T` (remote provider) | `PSI_Z_T` | `EH_G`, `SERVICE-IDENTIFIER`, `INSTANCE-IDENTIFIER`, `SD-SERVER-CONFIG` |

`SCB_T` bundles the two sockets: `SERVER-PORT-REF` points at the offering side,
`CLIENT-PORT-REF` at the requesting side, and its `PDUS` list carries one
`SOCKET-CONNECTION-IPDU-IDENTIFIER` per event (header id + `PT_E` + routing group).

### Service discovery infrastructure

Independent of the services, one set per ECU:

* PDUs `SD_Ctrl_Rx_LOCAL`, `SD_Ctrl_Tx_LOCAL`, `SD_Ctrl_Rx_Multicast`
  (`GENERAL-PURPOSE-PDU`, `CATEGORY = SD`, `LENGTH = 1500`)
* triggerings `PT_SD_Ctrl_LOCAL_Rx/_Tx`, `PT_SD_Ctrl_Rx_Multicast`
* ports `SD_Ctrl_*_CN`
* sockets `SD_SA_ANY` (dynamic port), `SD_SA_LOCAL`, `SD_SA_Z`, `SD_SA_MC`, all on
  `SomeipServiceDiscovery.UdpPort` (30490)
* bundles `SD_SCB_LOCAL`, `SD_SCB_Z`, `SD_SCB_MC`, all with `SD_SA_ANY` as client

---

## 6b. The SWC file (generated separately)

*Generate SWC* writes a second, independent file: an
`APPLICATION-SW-COMPONENT-TYPE` under `/ComponentTypes`, holding one port per
event.  It declares no data type and no port interface of its own - every port
is a reference into the SOME/IP file, so **that file has to be imported
first**.  Nothing in section 2-6 changes when this button is pressed;
`swc_gen.py` and `templates/swc.arxml.tpl` are a separate pair beside
`arxml_gen.py` and `someip.arxml.tpl`, sharing only the model.

| Service role | Port | Direction |
|---|---|---|
| provider | `P-PORT-PROTOTYPE`, `PROVIDED-INTERFACE-TREF` | sends the event |
| consumer | `R-PORT-PROTOTYPE`, `REQUIRED-INTERFACE-TREF` | receives it |

Port name: `SoIp_P_<event>` / `SoIp_R_<event>`, beside the interface names
`SoIp_I_P_<event>` / `SoIp_I_C_<event>` the SOME/IP file uses.

A receiver has to start from a defined value, so an R-Port carries a
`NONQUEUED-RECEIVER-COM-SPEC` with an `INIT-VALUE`.  A sender does not: the
application writes before it sends.

**The init value is shaped like the emitted type, not like the workbook.**  It
is built by walking the `IMPLEMENTATION-DATA-TYPE` tree the SOME/IP file really
carries, so a struct whose bit fields were packed into `Byte<n>` members
(section 5) is initialised with one field per byte, not one per CAN signal:

| Type | Value specification |
|---|---|
| struct | `RECORD-VALUE-SPECIFICATION` / `FIELDS`, one entry per sub element |
| array | `ARRAY-VALUE-SPECIFICATION` / `ELEMENTS`, `ARRAY-SIZE` entries |
| base type or enum | `NUMERICAL-VALUE-SPECIFICATION`, `VALUE` 0 |

Each field carries the sub element's name as `SHORT-LABEL`; array elements are
indistinguishable, so they carry none.

## 7. Where the rules live

Nothing about this project is hard coded.  The pipeline is three separable pieces:

```
*.xlsx  ──►  excel_io.py   ──►  model  ──►  view_model.py  ──►  templates/someip.arxml.tpl  ──►  ARXML
                 │                 ▲              │                        │
             reads by         resolve.py     computes header ids,     decides which AUTOSAR
             header name      fills gaps     lengths, short names     elements exist and how
                              (see below)    (naming.py)              they nest
```

| Question | Answered by |
|---|---|
| Which cell means what? | `excel_io.py` + section 2-5 above |
| What is an element called? | `naming.py` |
| What is its value? | `view_model.py` |
| **Which XML elements are written and how they nest** | **`templates/someip.arxml.tpl`** |

### Editing the template

The template is ordinary XML with a handful of directives, so adding a field is
a one line change and needs no Python:

| Directive | Meaning |
|---|---|
| `${expression}` | substitute a value in text or in an attribute |
| `t-foreach="events as ev"` | repeat this element once per item |
| `t-if="expr"` | emit this element only when `expr` is truthy |
| `t-text="expr"` | take the element text from `expr` |
| `t-def="name"` / `t-call="name"` | define / expand a reusable fragment (recursion allowed - that is how nested structs are inlined) |
| `t-with="expr as var"` | bind an extra variable |
| `t-strip="1"` | emit the children, drop the wrapper |
| `t-attr-NAME` | emit an attribute literally named `NAME` (`__` becomes `:`) |

Example - adding `SEPARATION-TIME` to every PDU is just:

```xml
<SEPARATION-TIME t-if="ev.event.separation_time" t-text="ev.event.separation_time"/>
```

Pick a different template per project with `Project.template` (the *ARXML
template* field on the GUI's Project tab), `--template` on the CLI, or
`someip_cli.py templates` to list what is available.

### Rules that repair or complete the import (`resolve.py`)

| Rule | What it does |
|---|---|
| **Nearest declaration** | a struct member, event serializer or event group name that matches no declaration is retargeted to the closest one (edit distance <= 2, must be unambiguous).  This is what turns the workbook's `PCUVehiclOperationStateType` typo into a warning instead of a broken file. |
| **Carry over** | when workbooks are imported *on top of* an existing project, the base supplies what a workbook cannot express: a consumer's remote provider endpoint, and the type names and `<VT>` texts the ECU code already uses.  Names invented while reading an ARXML (nested structs are inlined there and have no name of their own) are never carried over. |

Both rules report every single change - the CLI prints them, the GUI shows them
in an *Import adjustments* window.  Nothing is changed silently.

---

## 8. Where `ZA_someip.arxml` (hand made) differs from the workbooks

The tool regenerates the file from the Excel, so these hand-editing drifts show
up as differences.  All of them were reviewed:

| # | Item | Hand made ARXML | Excel / generated | Verdict |
|---|---|---|---|---|
| 1 | Local / peer IPv4 | `172.16.10.2` / `172.16.10.1` | `192.168.1.2` / `192.168.1.1` | leftover from `Template.arxml`; Excel wins |
| 2 | `pdu_PCUIVA50msEvent` LENGTH | `24` | `20` (12 + 8) | hand value did not follow the +8 rule |
| 3 | `pdu_RMCUZALeft10msEvent` LENGTH | `18` | `26` (18 + 8) | same |
| 4 | `PCUIVA50msStruct` element names | `EmsReqSensorInfo2`, `AccelPdlPos`, … | `emsReqSensorInfo2`, `accelPdlPos`, … | **check your RTE code** – these become C struct member names |
| 5 | `propSysASta` | `propSysASta` | `propSysAsta` | Excel spelling; same caveat as #4 |
| 6 | `PCUCVCACTGearType` | 4 literals (P/R/N/D) | 8 literals (+ 3× Reserved, Fault) | Excel is more complete |
| 7 | Consumer event group short name | `CEG_RMCUZALeft10msEvent` | `CEG_RMCUZALeftEvents` | generator uses the event **group** name consistently |
| 8 | `SoAdRG_Method`, `PT_GetPCUIVA10ms_call/_return` | referenced but never defined | not generated | dangling references removed |
| 9 | Enum name | `PCUVehicleOperationStateType` | workbook says `PCUVehiclOperationStateType` | the *carry over* rule keeps the ARXML spelling; without a base project the *nearest declaration* rule links the member to the workbook spelling and warns |

Items 4, 5 and 7 change generated names.  If the ECU application code already
uses the old spelling, edit them back on the **Data Types** tab before
generating - the model, not the workbook, is what the generator reads.

Item 1 needs a decision: the workbooks put the ECU on `192.168.1.2`, but the
remote provider address of the consumed RMCU service is in no workbook at all,
so it is carried over from the old file as `172.16.10.1`.  The subnet check
flags it; set the right address on the **Services** tab.
