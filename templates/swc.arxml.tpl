<AUTOSAR t-attr-xmlns="http://autosar.org/schema/r4.0"
         t-attr-xmlns__xsi="http://www.w3.org/2001/XMLSchema-instance"
         t-attr-xsi__schemaLocation="http://autosar.org/schema/r4.0 ${project.schema}">

  <!-- ===================================================================
       The application software component, in a file of its own.

       It declares no type and no interface: every port points at a
       SENDER-RECEIVER-INTERFACE the SOME/IP file already carries, so import
       that file first and this one second.

       A provider service sends its event, so it gets a P-PORT (sender); a
       consumer receives, so it gets an R-PORT with an INIT-VALUE shaped like
       the data type behind the interface.
       =================================================================== -->

  <!-- One INIT-VALUE node; recurses for a record or an array. -->
  <ELEM t-def="valueSpec" t-strip="1">
    <RECORD-VALUE-SPECIFICATION t-if="v.kind == 'record'">
      <SHORT-LABEL t-if="v.label">${v.label}</SHORT-LABEL>
      <FIELDS>
        <ELEM t-foreach="v.children as child" t-with="child as v" t-call="valueSpec"/>
      </FIELDS>
    </RECORD-VALUE-SPECIFICATION>
    <ARRAY-VALUE-SPECIFICATION t-if="v.kind == 'array'">
      <SHORT-LABEL t-if="v.label">${v.label}</SHORT-LABEL>
      <ELEMENTS>
        <ELEM t-foreach="v.children as child" t-with="child as v" t-call="valueSpec"/>
      </ELEMENTS>
    </ARRAY-VALUE-SPECIFICATION>
    <NUMERICAL-VALUE-SPECIFICATION t-if="v.kind == 'numerical'">
      <SHORT-LABEL t-if="v.label">${v.label}</SHORT-LABEL>
      <VALUE t-text="v.value"/>
    </NUMERICAL-VALUE-SPECIFICATION>
  </ELEM>

  <AR-PACKAGES>
    <AR-PACKAGE UUID="${uuid(package_path)}">
      <SHORT-NAME>${package}</SHORT-NAME>
      <ELEMENTS>
        <APPLICATION-SW-COMPONENT-TYPE UUID="${uuid(swc.path)}">
          <SHORT-NAME>${swc.name}</SHORT-NAME>
          <PORTS>

            <P-PORT-PROTOTYPE t-foreach="ports as port" t-if="port.provided"
                              UUID="${uuid(port.path)}">
              <SHORT-NAME>${port.name}</SHORT-NAME>
              <PROVIDED-COM-SPECS>
                <NONQUEUED-SENDER-COM-SPEC>
                  <DATA-ELEMENT-REF DEST="VARIABLE-DATA-PROTOTYPE">${port.data_element_ref}</DATA-ELEMENT-REF>
                  <INIT-VALUE>
                    <ELEM t-with="port.init as v" t-call="valueSpec"/>
                  </INIT-VALUE>
                </NONQUEUED-SENDER-COM-SPEC>
              </PROVIDED-COM-SPECS>
              <PROVIDED-INTERFACE-TREF DEST="SENDER-RECEIVER-INTERFACE">${port.iface_ref}</PROVIDED-INTERFACE-TREF>
            </P-PORT-PROTOTYPE>

            <R-PORT-PROTOTYPE t-foreach="ports as port" t-if="not port.provided"
                              UUID="${uuid(port.path)}">
              <SHORT-NAME>${port.name}</SHORT-NAME>
              <REQUIRED-COM-SPECS>
                <NONQUEUED-RECEIVER-COM-SPEC>
                  <DATA-ELEMENT-REF DEST="VARIABLE-DATA-PROTOTYPE">${port.data_element_ref}</DATA-ELEMENT-REF>
                  <ALIVE-TIMEOUT>0</ALIVE-TIMEOUT>
                  <ENABLE-UPDATE>false</ENABLE-UPDATE>
                  <FILTER>
                    <DATA-FILTER-TYPE>ALWAYS</DATA-FILTER-TYPE>
                  </FILTER>
                  <HANDLE-NEVER-RECEIVED>false</HANDLE-NEVER-RECEIVED>
                  <INIT-VALUE>
                    <ELEM t-with="port.init as v" t-call="valueSpec"/>
                  </INIT-VALUE>
                </NONQUEUED-RECEIVER-COM-SPEC>
              </REQUIRED-COM-SPECS>
              <REQUIRED-INTERFACE-TREF DEST="SENDER-RECEIVER-INTERFACE">${port.iface_ref}</REQUIRED-INTERFACE-TREF>
            </R-PORT-PROTOTYPE>

            <!-- The other half of the gateway's trigger: one R-Port per CAN
                 message, so the two components can be connected. -->
            <R-PORT-PROTOTYPE t-foreach="trigger_ports as tp" UUID="${uuid(tp.path)}">
              <SHORT-NAME>${tp.name}</SHORT-NAME>
              <ADMIN-DATA>
                <SDGS>
                  <SDG GID="DV:DEV">
                    <SD GID="DV:ImportModePreset">Keep</SD>
                  </SDG>
                </SDGS>
              </ADMIN-DATA>
              <REQUIRED-COM-SPECS>
                <NONQUEUED-RECEIVER-COM-SPEC>
                  <DATA-ELEMENT-REF DEST="VARIABLE-DATA-PROTOTYPE">${trigger.element_ref}</DATA-ELEMENT-REF>
                  <ALIVE-TIMEOUT>0</ALIVE-TIMEOUT>
                  <ENABLE-UPDATE>false</ENABLE-UPDATE>
                  <FILTER>
                    <DATA-FILTER-TYPE>ALWAYS</DATA-FILTER-TYPE>
                  </FILTER>
                  <HANDLE-NEVER-RECEIVED>false</HANDLE-NEVER-RECEIVED>
                  <INIT-VALUE>
                    <NUMERICAL-VALUE-SPECIFICATION>
                      <VALUE>0</VALUE>
                    </NUMERICAL-VALUE-SPECIFICATION>
                  </INIT-VALUE>
                </NONQUEUED-RECEIVER-COM-SPEC>
              </REQUIRED-COM-SPECS>
              <REQUIRED-INTERFACE-TREF DEST="SENDER-RECEIVER-INTERFACE">${trigger.interface}</REQUIRED-INTERFACE-TREF>
            </R-PORT-PROTOTYPE>

          </PORTS>

          <!-- Receiving a trigger starts the runnable that sends that CAN
               message on every SOME/IP port carrying it. -->
          <INTERNAL-BEHAVIORS t-if="runnables">
            <SWC-INTERNAL-BEHAVIOR UUID="${uuid(behavior.path)}">
              <SHORT-NAME>${behavior.name}</SHORT-NAME>
              <EVENTS>
                <DATA-RECEIVED-EVENT t-foreach="runnables as r" UUID="${uuid(r.event.path)}">
                  <SHORT-NAME>${r.event.name}</SHORT-NAME>
                  <START-ON-EVENT-REF DEST="RUNNABLE-ENTITY">${r.path}</START-ON-EVENT-REF>
                  <DATA-IREF>
                    <CONTEXT-R-PORT-REF DEST="R-PORT-PROTOTYPE">${r.rport_ref}</CONTEXT-R-PORT-REF>
                    <TARGET-DATA-ELEMENT-REF DEST="VARIABLE-DATA-PROTOTYPE">${trigger.element_ref}</TARGET-DATA-ELEMENT-REF>
                  </DATA-IREF>
                </DATA-RECEIVED-EVENT>
              </EVENTS>
              <RUNNABLES>
                <RUNNABLE-ENTITY t-foreach="runnables as r" UUID="${uuid(r.path)}">
                  <SHORT-NAME>${r.name}</SHORT-NAME>
                  <DATA-SEND-POINTS>
                    <VARIABLE-ACCESS t-foreach="r.sends as send" UUID="${uuid(send.path)}">
                      <SHORT-NAME>${send.name}</SHORT-NAME>
                      <ACCESSED-VARIABLE>
                        <AUTOSAR-VARIABLE-IREF>
                          <PORT-PROTOTYPE-REF DEST="P-PORT-PROTOTYPE">${send.port_ref}</PORT-PROTOTYPE-REF>
                          <TARGET-DATA-PROTOTYPE-REF DEST="VARIABLE-DATA-PROTOTYPE">${send.target_ref}</TARGET-DATA-PROTOTYPE-REF>
                        </AUTOSAR-VARIABLE-IREF>
                      </ACCESSED-VARIABLE>
                    </VARIABLE-ACCESS>
                  </DATA-SEND-POINTS>
                </RUNNABLE-ENTITY>
              </RUNNABLES>
              <SUPPORTS-MULTIPLE-INSTANTIATION>false</SUPPORTS-MULTIPLE-INSTANTIATION>
            </SWC-INTERNAL-BEHAVIOR>
          </INTERNAL-BEHAVIORS>
        </APPLICATION-SW-COMPONENT-TYPE>
        <SWC-IMPLEMENTATION t-if="runnables" UUID="${uuid(implementation.path)}">
          <SHORT-NAME>${implementation.name}</SHORT-NAME>
          <BEHAVIOR-REF DEST="SWC-INTERNAL-BEHAVIOR">${behavior.path}</BEHAVIOR-REF>
        </SWC-IMPLEMENTATION>
      </ELEMENTS>
    </AR-PACKAGE>
  </AR-PACKAGES>
</AUTOSAR>
