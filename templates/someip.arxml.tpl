<AUTOSAR t-attr-xmlns="http://autosar.org/schema/r4.0"
         t-attr-xmlns__xsi="http://www.w3.org/2001/XMLSchema-instance"
         t-attr-xsi__schemaLocation="http://autosar.org/schema/r4.0 ${project.schema}">

  <!-- ===================================================================
       Reusable fragments
       =================================================================== -->

  <!-- One IMPLEMENTATION-DATA-TYPE-ELEMENT; recurses for nested structs.
       Child order follows the AUTOSAR schema: ARRAY-SIZE* then SUB-ELEMENTS
       then SW-DATA-DEF-PROPS. -->
  <IMPLEMENTATION-DATA-TYPE-ELEMENT t-def="implElement" UUID="${uuid(node.path)}">
    <SHORT-NAME>${node.name}</SHORT-NAME>
    <CATEGORY>${node.category}</CATEGORY>
    <ARRAY-SIZE t-if="node.array_size" t-text="node.array_size"/>
    <ARRAY-SIZE-SEMANTICS t-if="node.array_size">${node.array_semantics}</ARRAY-SIZE-SEMANTICS>
    <SUB-ELEMENTS t-if="node.children">
      <ELEM t-foreach="node.children as child" t-with="child as node" t-call="implElement"/>
    </SUB-ELEMENTS>
    <SW-DATA-DEF-PROPS>
      <SW-DATA-DEF-PROPS-VARIANTS>
        <SW-DATA-DEF-PROPS-CONDITIONAL>
          <BASE-TYPE-REF t-if="node.base_ref" DEST="SW-BASE-TYPE">${node.base_ref}</BASE-TYPE-REF>
          <SW-CALIBRATION-ACCESS t-if="node.calibration">${node.calibration}</SW-CALIBRATION-ACCESS>
          <COMPU-METHOD-REF t-if="node.compu_ref" DEST="COMPU-METHOD">${node.compu_ref}</COMPU-METHOD-REF>
          <DATA-CONSTR-REF t-if="node.constr_ref" DEST="DATA-CONSTR">${node.constr_ref}</DATA-CONSTR-REF>
          <IMPLEMENTATION-DATA-TYPE-REF t-if="node.impl_ref" DEST="IMPLEMENTATION-DATA-TYPE">${node.impl_ref}</IMPLEMENTATION-DATA-TYPE-REF>
        </SW-DATA-DEF-PROPS-CONDITIONAL>
      </SW-DATA-DEF-PROPS-VARIANTS>
    </SW-DATA-DEF-PROPS>
  </IMPLEMENTATION-DATA-TYPE-ELEMENT>

  <!-- SD-SERVER-CONFIG / SD-CLIENT-CONFIG of a service instance. -->
  <SD-SERVER-CONFIG t-def="sdServerConfig">
    <INITIAL-OFFER-BEHAVIOR>
      <INITIAL-DELAY-MAX-VALUE t-text="sd.delay_max"/>
      <INITIAL-DELAY-MIN-VALUE t-text="sd.delay_min"/>
      <INITIAL-REPETITIONS-BASE-DELAY t-text="sd.base_delay"/>
      <INITIAL-REPETITIONS-MAX t-text="sd.repetitions"/>
    </INITIAL-OFFER-BEHAVIOR>
    <OFFER-CYCLIC-DELAY t-text="sd.cyclic_offer"/>
    <REQUEST-RESPONSE-DELAY>
      <MAX-VALUE t-text="sd.rr_max"/>
      <MIN-VALUE t-text="sd.rr_min"/>
    </REQUEST-RESPONSE-DELAY>
    <SERVER-SERVICE-MAJOR-VERSION t-text="sd.major"/>
    <SERVER-SERVICE-MINOR-VERSION t-text="sd.minor"/>
    <TTL t-text="sd.ttl"/>
  </SD-SERVER-CONFIG>

  <SD-CLIENT-CONFIG t-def="sdClientConfig">
    <CLIENT-SERVICE-MAJOR-VERSION t-text="sd.major"/>
    <CLIENT-SERVICE-MINOR-VERSION t-text="sd.minor"/>
    <INITIAL-FIND-BEHAVIOR>
      <INITIAL-DELAY-MAX-VALUE t-text="sd.delay_max"/>
      <INITIAL-DELAY-MIN-VALUE t-text="sd.delay_min"/>
      <INITIAL-REPETITIONS-BASE-DELAY t-text="sd.base_delay"/>
      <INITIAL-REPETITIONS-MAX t-text="sd.repetitions"/>
    </INITIAL-FIND-BEHAVIOR>
    <TTL t-text="sd.ttl"/>
  </SD-CLIENT-CONFIG>

  <!-- ===================================================================
       Document
       =================================================================== -->
  <ADMIN-DATA>
    <LANGUAGE>EN</LANGUAGE>
    <USED-LANGUAGES>
      <L-10 L="EN" t-attr-xml__space="default"/>
    </USED-LANGUAGES>
  </ADMIN-DATA>

  <AR-PACKAGES>

    <!-- ============================== Communication -->
    <AR-PACKAGE UUID="${uuid('/Communication')}">
      <SHORT-NAME>Communication</SHORT-NAME>
      <AR-PACKAGES>

        <AR-PACKAGE UUID="${uuid('/Communication/DataTransformation')}">
          <SHORT-NAME>DataTransformation</SHORT-NAME>
          <ELEMENTS>
            <DATA-TRANSFORMATION-SET UUID="${uuid(transformer_set)}">
              <SHORT-NAME>TransformerConfiguration</SHORT-NAME>
              <DATA-TRANSFORMATIONS>
                <DATA-TRANSFORMATION UUID="${uuid(transformation)}">
                  <SHORT-NAME>SomeIpDefaultTransformation</SHORT-NAME>
                  <EXECUTE-DESPITE-DATA-UNAVAILABILITY>false</EXECUTE-DESPITE-DATA-UNAVAILABILITY>
                  <TRANSFORMER-CHAIN-REFS>
                    <TRANSFORMER-CHAIN-REF DEST="TRANSFORMATION-TECHNOLOGY">${transformer}</TRANSFORMER-CHAIN-REF>
                  </TRANSFORMER-CHAIN-REFS>
                </DATA-TRANSFORMATION>
              </DATA-TRANSFORMATIONS>
              <TRANSFORMATION-TECHNOLOGYS>
                <TRANSFORMATION-TECHNOLOGY UUID="${uuid(transformer)}">
                  <SHORT-NAME>SomeIpDefaultTransformer</SHORT-NAME>
                  <BUFFER-PROPERTIES>
                    <HEADER-LENGTH>64</HEADER-LENGTH>
                    <IN-PLACE>false</IN-PLACE>
                  </BUFFER-PROPERTIES>
                  <PROTOCOL>SOMEIP</PROTOCOL>
                  <TRANSFORMATION-DESCRIPTIONS>
                    <SOMEIP-TRANSFORMATION-DESCRIPTION>
                      <ALIGNMENT>8</ALIGNMENT>
                      <BYTE-ORDER>MOST-SIGNIFICANT-BYTE-LAST</BYTE-ORDER>
                      <INTERFACE-VERSION t-text="interface_version"/>
                    </SOMEIP-TRANSFORMATION-DESCRIPTION>
                  </TRANSFORMATION-DESCRIPTIONS>
                  <TRANSFORMER-CLASS>SERIALIZER</TRANSFORMER-CLASS>
                  <VERSION>1.0.0</VERSION>
                </TRANSFORMATION-TECHNOLOGY>
              </TRANSFORMATION-TECHNOLOGYS>
            </DATA-TRANSFORMATION-SET>
          </ELEMENTS>
        </AR-PACKAGE>

        <AR-PACKAGE UUID="${uuid('/Communication/PDUs')}">
          <SHORT-NAME>PDUs</SHORT-NAME>
          <ELEMENTS>
            <GENERAL-PURPOSE-PDU t-foreach="sd.pdus as sdpdu" UUID="${uuid(sdpdu.path)}">
              <SHORT-NAME>${sdpdu.name}</SHORT-NAME>
              <CATEGORY>SD</CATEGORY>
              <LENGTH t-text="sd.length"/>
            </GENERAL-PURPOSE-PDU>

            <!-- A transmission timing only applies to a PDU this ECU sends;
                 a received one carries the unused bit pattern instead. -->
            <I-SIGNAL-I-PDU t-foreach="events as ev" UUID="${uuid(ev.pdu_path)}">
              <SHORT-NAME>${ev.pdu}</SHORT-NAME>
              <LENGTH t-text="ev.length"/>
              <I-PDU-TIMING-SPECIFICATIONS t-if="ev.direction == 'OUT'">
                <I-PDU-TIMING>
                  <TRANSMISSION-MODE-DECLARATION>
                    <TRANSMISSION-MODE-TRUE-TIMING>
                      <EVENT-CONTROLLED-TIMING>
                        <NUMBER-OF-REPETITIONS>0</NUMBER-OF-REPETITIONS>
                      </EVENT-CONTROLLED-TIMING>
                    </TRANSMISSION-MODE-TRUE-TIMING>
                  </TRANSMISSION-MODE-DECLARATION>
                </I-PDU-TIMING>
              </I-PDU-TIMING-SPECIFICATIONS>
              <I-SIGNAL-TO-PDU-MAPPINGS>
                <I-SIGNAL-TO-I-PDU-MAPPING UUID="${uuid(ev.pdu_path + '/' + ev.map)}">
                  <SHORT-NAME>${ev.map}</SHORT-NAME>
                  <I-SIGNAL-REF DEST="I-SIGNAL">${ev.sig_path}</I-SIGNAL-REF>
                  <PACKING-BYTE-ORDER>OPAQUE</PACKING-BYTE-ORDER>
                  <START-POSITION>0</START-POSITION>
                  <TRANSFER-PROPERTY>TRIGGERED-WITHOUT-REPETITION</TRANSFER-PROPERTY>
                </I-SIGNAL-TO-I-PDU-MAPPING>
              </I-SIGNAL-TO-PDU-MAPPINGS>
              <UNUSED-BIT-PATTERN t-if="ev.direction == 'IN'">0</UNUSED-BIT-PATTERN>
            </I-SIGNAL-I-PDU>
          </ELEMENTS>
        </AR-PACKAGE>

        <AR-PACKAGE UUID="${uuid('/Communication/Signals')}">
          <SHORT-NAME>Signals</SHORT-NAME>
          <ELEMENTS>
            <I-SIGNAL t-foreach="events as ev" UUID="${uuid(ev.sig_path)}">
              <SHORT-NAME>${ev.sig}</SHORT-NAME>
              <DATA-TRANSFORMATIONS>
                <DATA-TRANSFORMATION-REF-CONDITIONAL>
                  <DATA-TRANSFORMATION-REF DEST="DATA-TRANSFORMATION">${transformation}</DATA-TRANSFORMATION-REF>
                </DATA-TRANSFORMATION-REF-CONDITIONAL>
              </DATA-TRANSFORMATIONS>
              <DATA-TYPE-POLICY>TRANSFORMING-I-SIGNAL</DATA-TYPE-POLICY>
              <LENGTH t-text="ev.length"/>
              <SYSTEM-SIGNAL-REF DEST="SYSTEM-SIGNAL">${ev.sys_path}</SYSTEM-SIGNAL-REF>
              <TRANSFORMATION-I-SIGNAL-PROPSS>
                <SOMEIP-TRANSFORMATION-I-SIGNAL-PROPS>
                  <SOMEIP-TRANSFORMATION-I-SIGNAL-PROPS-VARIANTS>
                    <SOMEIP-TRANSFORMATION-I-SIGNAL-PROPS-CONDITIONAL>
                      <TRANSFORMER-REF DEST="TRANSFORMATION-TECHNOLOGY">${transformer}</TRANSFORMER-REF>
                      <INTERFACE-VERSION t-text="ev.interface_version"/>
                      <MESSAGE-TYPE>NOTIFICATION</MESSAGE-TYPE>
                    </SOMEIP-TRANSFORMATION-I-SIGNAL-PROPS-CONDITIONAL>
                  </SOMEIP-TRANSFORMATION-I-SIGNAL-PROPS-VARIANTS>
                </SOMEIP-TRANSFORMATION-I-SIGNAL-PROPS>
              </TRANSFORMATION-I-SIGNAL-PROPSS>
            </I-SIGNAL>
          </ELEMENTS>
        </AR-PACKAGE>

        <AR-PACKAGE UUID="${uuid('/Communication/SystemSignals')}">
          <SHORT-NAME>SystemSignals</SHORT-NAME>
          <ELEMENTS>
            <SYSTEM-SIGNAL t-foreach="events as ev" UUID="${uuid(ev.sys_path)}">
              <SHORT-NAME>${ev.sys}</SHORT-NAME>
              <DYNAMIC-LENGTH>false</DYNAMIC-LENGTH>
            </SYSTEM-SIGNAL>
          </ELEMENTS>
        </AR-PACKAGE>

      </AR-PACKAGES>
    </AR-PACKAGE>

    <!-- ============================== SoAd routing groups -->
    <AR-PACKAGE UUID="${uuid('/SoAdRoutingGroups')}">
      <SHORT-NAME>SoAdRoutingGroups</SHORT-NAME>
      <ELEMENTS>
        <SO-AD-ROUTING-GROUP t-foreach="routing_groups as rg" UUID="${uuid(rg.path)}">
          <SHORT-NAME>${rg.name}</SHORT-NAME>
          <EVENT-GROUP-CONTROL-TYPE>${rg.control_type}</EVENT-GROUP-CONTROL-TYPE>
        </SO-AD-ROUTING-GROUP>
      </ELEMENTS>
    </AR-PACKAGE>

    <!-- ============================== System -->
    <AR-PACKAGE UUID="${uuid('/System')}">
      <SHORT-NAME>System</SHORT-NAME>
      <ELEMENTS>
        <SYSTEM UUID="${uuid('/System/System')}">
          <SHORT-NAME>System</SHORT-NAME>
          <CATEGORY>ECU_SYSTEM_DESCRIPTION</CATEGORY>
          <FIBEX-ELEMENTS>
            <FIBEX-ELEMENT-REF-CONDITIONAL t-foreach="fibex as fx">
              <FIBEX-ELEMENT-REF DEST="${fx.dest}">${fx.path}</FIBEX-ELEMENT-REF>
            </FIBEX-ELEMENT-REF-CONDITIONAL>
          </FIBEX-ELEMENTS>
        </SYSTEM>
      </ELEMENTS>
    </AR-PACKAGE>

    <!-- ============================== Port interfaces -->
    <AR-PACKAGE UUID="${uuid('/PortInterfaces')}">
      <SHORT-NAME>PortInterfaces</SHORT-NAME>
      <ELEMENTS>
        <SENDER-RECEIVER-INTERFACE t-foreach="port_interfaces as pi" UUID="${uuid(pi.path)}">
          <SHORT-NAME>${pi.name}</SHORT-NAME>
          <IS-SERVICE>false</IS-SERVICE>
          <DATA-ELEMENTS>
            <VARIABLE-DATA-PROTOTYPE UUID="${uuid(pi.path + '/' + pi.element)}">
              <SHORT-NAME>${pi.element}</SHORT-NAME>
              <SW-DATA-DEF-PROPS>
                <SW-DATA-DEF-PROPS-VARIANTS>
                  <SW-DATA-DEF-PROPS-CONDITIONAL>
                    <SW-CALIBRATION-ACCESS>NOT-ACCESSIBLE</SW-CALIBRATION-ACCESS>
                  </SW-DATA-DEF-PROPS-CONDITIONAL>
                </SW-DATA-DEF-PROPS-VARIANTS>
              </SW-DATA-DEF-PROPS>
              <TYPE-TREF DEST="IMPLEMENTATION-DATA-TYPE">${pi.type_ref}</TYPE-TREF>
            </VARIABLE-DATA-PROTOTYPE>
          </DATA-ELEMENTS>
        </SENDER-RECEIVER-INTERFACE>
      </ELEMENTS>
    </AR-PACKAGE>

    <!-- ============================== Data types -->
    <AR-PACKAGE UUID="${uuid('/DataTypes')}">
      <SHORT-NAME>DataTypes</SHORT-NAME>
      <ELEMENTS>
        <IMPLEMENTATION-DATA-TYPE t-foreach="impl_types as idt" UUID="${uuid(idt.path)}">
          <SHORT-NAME>${idt.name}</SHORT-NAME>
          <CATEGORY>${idt.category}</CATEGORY>
          <SW-DATA-DEF-PROPS>
            <SW-DATA-DEF-PROPS-VARIANTS>
              <SW-DATA-DEF-PROPS-CONDITIONAL>
                <SW-CALIBRATION-ACCESS>${idt.calibration}</SW-CALIBRATION-ACCESS>
              </SW-DATA-DEF-PROPS-CONDITIONAL>
            </SW-DATA-DEF-PROPS-VARIANTS>
          </SW-DATA-DEF-PROPS>
          <SUB-ELEMENTS>
            <ELEM t-foreach="idt.children as child" t-with="child as node" t-call="implElement"/>
          </SUB-ELEMENTS>
          <TYPE-EMITTER>${idt.type_emitter}</TYPE-EMITTER>
        </IMPLEMENTATION-DATA-TYPE>
      </ELEMENTS>

      <AR-PACKAGES>
        <AR-PACKAGE UUID="${uuid('/DataTypes/BaseTypes')}">
          <SHORT-NAME>BaseTypes</SHORT-NAME>
          <ELEMENTS>
            <SW-BASE-TYPE t-foreach="base_types as bt" UUID="${uuid(bt.path)}">
              <SHORT-NAME>${bt.name}</SHORT-NAME>
              <CATEGORY>FIXED_LENGTH</CATEGORY>
              <BASE-TYPE-SIZE t-text="bt.size"/>
              <BASE-TYPE-ENCODING>${bt.encoding}</BASE-TYPE-ENCODING>
              <NATIVE-DECLARATION t-if="bt.native">${bt.native}</NATIVE-DECLARATION>
            </SW-BASE-TYPE>
          </ELEMENTS>
        </AR-PACKAGE>

        <AR-PACKAGE UUID="${uuid('/DataTypes/CompuMethods')}">
          <SHORT-NAME>CompuMethods</SHORT-NAME>
          <ELEMENTS>
            <COMPU-METHOD t-foreach="compu_methods as cm" UUID="${uuid(cm.path)}">
              <SHORT-NAME>${cm.name}</SHORT-NAME>
              <CATEGORY>TEXTTABLE</CATEGORY>
              <COMPU-INTERNAL-TO-PHYS>
                <COMPU-SCALES>
                  <COMPU-SCALE t-foreach="cm.scales as scale">
                    <SHORT-LABEL>${scale.label}</SHORT-LABEL>
                    <LOWER-LIMIT INTERVAL-TYPE="CLOSED" t-text="scale.lower"/>
                    <UPPER-LIMIT INTERVAL-TYPE="CLOSED" t-text="scale.upper"/>
                    <COMPU-CONST>
                      <VT>${scale.vt}</VT>
                    </COMPU-CONST>
                  </COMPU-SCALE>
                </COMPU-SCALES>
              </COMPU-INTERNAL-TO-PHYS>
            </COMPU-METHOD>
          </ELEMENTS>
        </AR-PACKAGE>

        <AR-PACKAGE UUID="${uuid('/DataTypes/DataConstraints')}">
          <SHORT-NAME>DataConstraints</SHORT-NAME>
          <ELEMENTS>
            <DATA-CONSTR t-foreach="data_constrs as dc" UUID="${uuid(dc.path)}">
              <SHORT-NAME>${dc.name}</SHORT-NAME>
              <DATA-CONSTR-RULES>
                <DATA-CONSTR-RULE>
                  <INTERNAL-CONSTRS>
                    <LOWER-LIMIT INTERVAL-TYPE="CLOSED" t-text="dc.lower"/>
                    <UPPER-LIMIT INTERVAL-TYPE="CLOSED" t-text="dc.upper"/>
                  </INTERNAL-CONSTRS>
                </DATA-CONSTR-RULE>
              </DATA-CONSTR-RULES>
            </DATA-CONSTR>
          </ELEMENTS>
        </AR-PACKAGE>
      </AR-PACKAGES>
    </AR-PACKAGE>

    <!-- ============================== Topology -->
    <AR-PACKAGE UUID="${uuid('/Topology')}">
      <SHORT-NAME>Topology</SHORT-NAME>
      <AR-PACKAGES>

        <AR-PACKAGE UUID="${uuid('/Topology/Clusters')}">
          <SHORT-NAME>Clusters</SHORT-NAME>
          <ELEMENTS>
            <ETHERNET-CLUSTER UUID="${uuid(names.cluster)}">
              <SHORT-NAME>${project.cluster_name}</SHORT-NAME>
              <ETHERNET-CLUSTER-VARIANTS>
                <ETHERNET-CLUSTER-CONDITIONAL>
                  <BAUDRATE t-text="project.baudrate"/>
                  <PHYSICAL-CHANNELS>
                    <ETHERNET-PHYSICAL-CHANNEL UUID="${uuid(names.chan)}">
                      <SHORT-NAME>${project.channel_name}</SHORT-NAME>
                      <CATEGORY>WIRED</CATEGORY>
                      <COMM-CONNECTORS>
                        <COMMUNICATION-CONNECTOR-REF-CONDITIONAL>
                          <COMMUNICATION-CONNECTOR-REF DEST="ETHERNET-COMMUNICATION-CONNECTOR">${names.connector}</COMMUNICATION-CONNECTOR-REF>
                        </COMMUNICATION-CONNECTOR-REF-CONDITIONAL>
                      </COMM-CONNECTORS>

                      <I-SIGNAL-TRIGGERINGS>
                        <I-SIGNAL-TRIGGERING t-foreach="events as ev" UUID="${uuid(ev.st_path)}">
                          <SHORT-NAME>${ev.st}</SHORT-NAME>
                          <I-SIGNAL-PORT-REFS>
                            <I-SIGNAL-PORT-REF DEST="I-SIGNAL-PORT">${ev.sp_path}</I-SIGNAL-PORT-REF>
                          </I-SIGNAL-PORT-REFS>
                          <I-SIGNAL-REF DEST="I-SIGNAL">${ev.sig_path}</I-SIGNAL-REF>
                        </I-SIGNAL-TRIGGERING>
                      </I-SIGNAL-TRIGGERINGS>

                      <PDU-TRIGGERINGS>
                        <PDU-TRIGGERING t-foreach="pdu_triggerings as pt" UUID="${uuid(pt.path)}">
                          <SHORT-NAME>${pt.name}</SHORT-NAME>
                          <I-PDU-PORT-REFS>
                            <I-PDU-PORT-REF DEST="I-PDU-PORT">${pt.port_ref}</I-PDU-PORT-REF>
                          </I-PDU-PORT-REFS>
                          <I-PDU-REF DEST="${pt.pdu_dest}">${pt.pdu_ref}</I-PDU-REF>
                          <I-SIGNAL-TRIGGERINGS t-if="pt.signal_triggering_ref">
                            <I-SIGNAL-TRIGGERING-REF-CONDITIONAL>
                              <I-SIGNAL-TRIGGERING-REF DEST="I-SIGNAL-TRIGGERING">${pt.signal_triggering_ref}</I-SIGNAL-TRIGGERING-REF>
                            </I-SIGNAL-TRIGGERING-REF-CONDITIONAL>
                          </I-SIGNAL-TRIGGERINGS>
                        </PDU-TRIGGERING>
                      </PDU-TRIGGERINGS>

                      <NETWORK-ENDPOINTS>
                        <NETWORK-ENDPOINT t-foreach="endpoints as nep" UUID="${uuid(nep.path)}">
                          <SHORT-NAME>${nep.name}</SHORT-NAME>
                          <NETWORK-ENDPOINT-ADDRESSES>
                            <IPV-4-CONFIGURATION>
                              <IPV-4-ADDRESS>${nep.ipv4}</IPV-4-ADDRESS>
                              <IPV-4-ADDRESS-SOURCE t-if="nep.fixed">FIXED</IPV-4-ADDRESS-SOURCE>
                              <NETWORK-MASK t-if="nep.mask">${nep.mask}</NETWORK-MASK>
                            </IPV-4-CONFIGURATION>
                            <MAC-MULTICAST-CONFIGURATION t-if="nep.multicast">
                              <MAC-MULTICAST-GROUP-REF DEST="MAC-MULTICAST-GROUP">${nep.multicast_group_ref}</MAC-MULTICAST-GROUP-REF>
                            </MAC-MULTICAST-CONFIGURATION>
                          </NETWORK-ENDPOINT-ADDRESSES>
                        </NETWORK-ENDPOINT>
                      </NETWORK-ENDPOINTS>

                      <SO-AD-CONFIG>
                        <CONNECTION-BUNDLES>
                          <!-- Neither a bundle nor an event handler is
                               Identifiable in the 4.4 schema, so they take no
                               UUID.  One bundle holds every peer that talks to
                               the same server socket. -->
                          <SOCKET-CONNECTION-BUNDLE t-foreach="bundles as scb">
                            <SHORT-NAME>${scb.name}</SHORT-NAME>
                            <BUNDLED-CONNECTIONS>
                              <SOCKET-CONNECTION t-foreach="scb.connections as conn">
                                <CLIENT-IP-ADDR-FROM-CONNECTION-REQUEST t-if="conn.from_request" t-text="conn.from_request"/>
                                <CLIENT-PORT-FROM-CONNECTION-REQUEST t-if="conn.from_request" t-text="conn.from_request"/>
                                <CLIENT-PORT-REF DEST="SOCKET-ADDRESS">${conn.client_ref}</CLIENT-PORT-REF>
                                <PDUS t-if="conn.pdus">
                                  <SOCKET-CONNECTION-IPDU-IDENTIFIER t-foreach="conn.pdus as sp">
                                    <HEADER-ID t-text="sp.header_id"/>
                                    <PDU-TRIGGERING-REF DEST="PDU-TRIGGERING">${sp.pt_ref}</PDU-TRIGGERING-REF>
                                    <ROUTING-GROUP-REFS t-if="sp.routing_group_ref">
                                      <ROUTING-GROUP-REF DEST="SO-AD-ROUTING-GROUP">${sp.routing_group_ref}</ROUTING-GROUP-REF>
                                    </ROUTING-GROUP-REFS>
                                  </SOCKET-CONNECTION-IPDU-IDENTIFIER>
                                </PDUS>
                                <SHORT-LABEL t-if="conn.label">${conn.label}</SHORT-LABEL>
                              </SOCKET-CONNECTION>
                            </BUNDLED-CONNECTIONS>
                            <SERVER-PORT-REF DEST="SOCKET-ADDRESS">${scb.server_ref}</SERVER-PORT-REF>
                          </SOCKET-CONNECTION-BUNDLE>
                        </CONNECTION-BUNDLES>

                        <SOCKET-ADDRESSS>
                          <SOCKET-ADDRESS t-foreach="sockets as sa" UUID="${uuid(sa.path)}">
                            <SHORT-NAME>${sa.name}</SHORT-NAME>
                            <APPLICATION-ENDPOINT UUID="${uuid(sa.aep_path)}">
                              <SHORT-NAME>${sa.aep}</SHORT-NAME>

                              <CONSUMED-SERVICE-INSTANCES t-if="sa.consumed" t-with="sa.consumed as csi">
                                <CONSUMED-SERVICE-INSTANCE UUID="${uuid(csi.path)}">
                                  <SHORT-NAME>${csi.name}</SHORT-NAME>
                                  <ROUTING-GROUP-REFS>
                                    <ROUTING-GROUP-REF t-foreach="csi.routing_group_refs as rgref" DEST="SO-AD-ROUTING-GROUP">${rgref}</ROUTING-GROUP-REF>
                                  </ROUTING-GROUP-REFS>
                                  <CONSUMED-EVENT-GROUPS>
                                    <CONSUMED-EVENT-GROUP t-foreach="csi.groups as ceg" UUID="${uuid(ceg.path)}">
                                      <SHORT-NAME>${ceg.name}</SHORT-NAME>
                                      <APPLICATION-ENDPOINT-REF DEST="APPLICATION-ENDPOINT">${ceg.aep_ref}</APPLICATION-ENDPOINT-REF>
                                      <EVENT-GROUP-IDENTIFIER t-text="ceg.group_id"/>
                                      <ROUTING-GROUP-REFS>
                                        <ROUTING-GROUP-REF DEST="SO-AD-ROUTING-GROUP">${ceg.routing_group_ref}</ROUTING-GROUP-REF>
                                      </ROUTING-GROUP-REFS>
                                      <SD-CLIENT-CONFIG>
                                        <REQUEST-RESPONSE-DELAY>
                                          <MAX-VALUE t-text="ceg.rr_max"/>
                                          <MIN-VALUE t-text="ceg.rr_min"/>
                                        </REQUEST-RESPONSE-DELAY>
                                        <TTL t-text="ceg.ttl"/>
                                      </SD-CLIENT-CONFIG>
                                    </CONSUMED-EVENT-GROUP>
                                  </CONSUMED-EVENT-GROUPS>
                                  <PROVIDED-SERVICE-INSTANCE-REF DEST="PROVIDED-SERVICE-INSTANCE">${csi.psi_ref}</PROVIDED-SERVICE-INSTANCE-REF>
                                  <CFG t-with="csi.sd as sd" t-call="sdClientConfig"/>
                                </CONSUMED-SERVICE-INSTANCE>
                              </CONSUMED-SERVICE-INSTANCES>

                              <NETWORK-ENDPOINT-REF DEST="NETWORK-ENDPOINT">${sa.nep_ref}</NETWORK-ENDPOINT-REF>

                              <PROVIDED-SERVICE-INSTANCES t-if="sa.provided" t-with="sa.provided as psi">
                                <PROVIDED-SERVICE-INSTANCE UUID="${uuid(psi.path)}">
                                  <SHORT-NAME>${psi.name}</SHORT-NAME>
                                  <ROUTING-GROUP-REFS>
                                    <ROUTING-GROUP-REF t-foreach="psi.routing_group_refs as rgref" DEST="SO-AD-ROUTING-GROUP">${rgref}</ROUTING-GROUP-REF>
                                  </ROUTING-GROUP-REFS>
                                  <EVENT-HANDLERS>
                                    <EVENT-HANDLER t-foreach="psi.handlers as eh">
                                      <SHORT-NAME>${eh.name}</SHORT-NAME>
                                      <APPLICATION-ENDPOINT-REF t-if="not eh.offered" DEST="APPLICATION-ENDPOINT">${eh.aep_ref}</APPLICATION-ENDPOINT-REF>
                                      <CONSUMED-EVENT-GROUP-REFS>
                                        <CONSUMED-EVENT-GROUP-REF DEST="CONSUMED-EVENT-GROUP">${eh.ceg_ref}</CONSUMED-EVENT-GROUP-REF>
                                      </CONSUMED-EVENT-GROUP-REFS>
                                      <MULTICAST-THRESHOLD t-if="eh.offered">0</MULTICAST-THRESHOLD>
                                      <ROUTING-GROUP-REFS t-if="eh.offered">
                                        <ROUTING-GROUP-REF DEST="SO-AD-ROUTING-GROUP">${eh.routing_group_ref}</ROUTING-GROUP-REF>
                                      </ROUTING-GROUP-REFS>
                                      <SD-SERVER-CONFIG t-if="eh.offered">
                                        <REQUEST-RESPONSE-DELAY>
                                          <MAX-VALUE t-text="eh.rr_max"/>
                                          <MIN-VALUE t-text="eh.rr_min"/>
                                        </REQUEST-RESPONSE-DELAY>
                                        <TTL t-text="eh.ttl"/>
                                      </SD-SERVER-CONFIG>
                                    </EVENT-HANDLER>
                                  </EVENT-HANDLERS>
                                  <INSTANCE-IDENTIFIER t-text="psi.instance_id"/>
                                  <CFG t-with="psi.sd as sd" t-call="sdServerConfig"/>
                                  <SERVICE-IDENTIFIER t-text="psi.service_id"/>
                                </PROVIDED-SERVICE-INSTANCE>
                              </PROVIDED-SERVICE-INSTANCES>

                              <TP-CONFIGURATION>
                                <UDP-TP>
                                  <UDP-TP-PORT>
                                    <DYNAMICALLY-ASSIGNED t-if="sa.dynamic">true</DYNAMICALLY-ASSIGNED>
                                    <PORT-NUMBER t-if="not sa.dynamic" t-text="sa.port"/>
                                  </UDP-TP-PORT>
                                </UDP-TP>
                              </TP-CONFIGURATION>
                            </APPLICATION-ENDPOINT>
                            <MULTICAST-CONNECTOR-REFS t-if="sa.multicast_connector_ref">
                              <MULTICAST-CONNECTOR-REF DEST="ETHERNET-COMMUNICATION-CONNECTOR">${sa.multicast_connector_ref}</MULTICAST-CONNECTOR-REF>
                            </MULTICAST-CONNECTOR-REFS>
                            <CONNECTOR-REF t-if="sa.connector_ref" DEST="ETHERNET-COMMUNICATION-CONNECTOR">${sa.connector_ref}</CONNECTOR-REF>
                          </SOCKET-ADDRESS>
                        </SOCKET-ADDRESSS>
                      </SO-AD-CONFIG>

                      <VLAN UUID="${uuid(names.chan + '/' + project.vlan_name)}">
                        <SHORT-NAME>${project.vlan_name}</SHORT-NAME>
                        <VLAN-IDENTIFIER t-text="project.vlan_id"/>
                      </VLAN>
                    </ETHERNET-PHYSICAL-CHANNEL>
                  </PHYSICAL-CHANNELS>
                  <MAC-MULTICAST-GROUPS>
                    <MAC-MULTICAST-GROUP UUID="${uuid(names.multicast_group)}">
                      <SHORT-NAME>MulticastMacAddress</SHORT-NAME>
                      <MAC-MULTICAST-ADDRESS>${project.multicast_mac}</MAC-MULTICAST-ADDRESS>
                    </MAC-MULTICAST-GROUP>
                  </MAC-MULTICAST-GROUPS>
                </ETHERNET-CLUSTER-CONDITIONAL>
              </ETHERNET-CLUSTER-VARIANTS>
            </ETHERNET-CLUSTER>
          </ELEMENTS>
        </AR-PACKAGE>

        <AR-PACKAGE UUID="${uuid('/Topology/HardwareComponents')}">
          <SHORT-NAME>HardwareComponents</SHORT-NAME>
          <ELEMENTS>
            <ECU-INSTANCE UUID="${uuid(ecu.path)}">
              <SHORT-NAME>${ecu.name}</SHORT-NAME>
              <COM-CONFIGURATION-TX-TIME-BASE t-text="project.com_tx_time_base"/>
              <COMM-CONTROLLERS>
                <ETHERNET-COMMUNICATION-CONTROLLER UUID="${uuid(ecu.controller_path)}">
                  <SHORT-NAME>${ecu.controller}</SHORT-NAME>
                  <CATEGORY>WIRED</CATEGORY>
                  <ETHERNET-COMMUNICATION-CONTROLLER-VARIANTS>
                    <ETHERNET-COMMUNICATION-CONTROLLER-CONDITIONAL>
                      <COUPLING-PORTS>
                        <COUPLING-PORT UUID="${uuid(ecu.controller_path + '/' + ecu.coupling_port)}">
                          <SHORT-NAME>${ecu.coupling_port}</SHORT-NAME>
                          <PHYSICAL-LAYER-TYPE>${project.physical_layer_type}</PHYSICAL-LAYER-TYPE>
                          <VLAN-MEMBERSHIPS>
                            <VLAN-MEMBERSHIP>
                              <DEFAULT-PRIORITY t-text="project.vlan_priority"/>
                              <VLAN-REF DEST="ETHERNET-PHYSICAL-CHANNEL">${names.chan}</VLAN-REF>
                            </VLAN-MEMBERSHIP>
                          </VLAN-MEMBERSHIPS>
                        </COUPLING-PORT>
                      </COUPLING-PORTS>
                      <MAC-UNICAST-ADDRESS>${project.ecu_mac_unicast}</MAC-UNICAST-ADDRESS>
                    </ETHERNET-COMMUNICATION-CONTROLLER-CONDITIONAL>
                  </ETHERNET-COMMUNICATION-CONTROLLER-VARIANTS>
                </ETHERNET-COMMUNICATION-CONTROLLER>
              </COMM-CONTROLLERS>
              <CONNECTORS>
                <ETHERNET-COMMUNICATION-CONNECTOR UUID="${uuid(ecu.connector_path)}">
                  <SHORT-NAME>${ecu.connector}</SHORT-NAME>
                  <CATEGORY>WIRED</CATEGORY>
                  <COMM-CONTROLLER-REF DEST="ETHERNET-COMMUNICATION-CONTROLLER">${ecu.controller_path}</COMM-CONTROLLER-REF>
                  <ECU-COMM-PORT-INSTANCES>
                    <I-PDU-PORT t-foreach="[p for p in ecu.ports if p.kind == 'I-PDU-PORT'] as port" UUID="${uuid(port.path)}">
                      <SHORT-NAME>${port.name}</SHORT-NAME>
                      <COMMUNICATION-DIRECTION>${port.direction}</COMMUNICATION-DIRECTION>
                    </I-PDU-PORT>
                    <I-SIGNAL-PORT t-foreach="[p for p in ecu.ports if p.kind == 'I-SIGNAL-PORT'] as port" UUID="${uuid(port.path)}">
                      <SHORT-NAME>${port.name}</SHORT-NAME>
                      <COMMUNICATION-DIRECTION>${port.direction}</COMMUNICATION-DIRECTION>
                    </I-SIGNAL-PORT>
                  </ECU-COMM-PORT-INSTANCES>
                  <NETWORK-ENDPOINT-REFS>
                    <NETWORK-ENDPOINT-REF t-foreach="ecu.network_endpoint_refs as nref" DEST="NETWORK-ENDPOINT">${nref}</NETWORK-ENDPOINT-REF>
                  </NETWORK-ENDPOINT-REFS>
                </ETHERNET-COMMUNICATION-CONNECTOR>
              </CONNECTORS>
              <SLEEP-MODE-SUPPORTED>false</SLEEP-MODE-SUPPORTED>
              <WAKE-UP-OVER-BUS-SUPPORTED>false</WAKE-UP-OVER-BUS-SUPPORTED>
            </ECU-INSTANCE>
          </ELEMENTS>
        </AR-PACKAGE>

      </AR-PACKAGES>
    </AR-PACKAGE>

  </AR-PACKAGES>
</AUTOSAR>
