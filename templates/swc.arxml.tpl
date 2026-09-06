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

          </PORTS>
        </APPLICATION-SW-COMPONENT-TYPE>
      </ELEMENTS>
    </AR-PACKAGE>
  </AR-PACKAGES>
</AUTOSAR>
