<AUTOSAR t-attr-xmlns="http://autosar.org/schema/r4.0"
         t-attr-xmlns__xsi="http://www.w3.org/2001/XMLSchema-instance"
         t-attr-xsi__schemaLocation="http://autosar.org/schema/r4.0 ${project.schema}">

  <!-- ===================================================================
       The CAN to SOME/IP gateway component, in a file of its own.

       One P-Port per CAN message it forwards - the events that carry the same
       serializer are that one message on its way to several zones, so they
       share a port.  Every port points at the same trigger interface, which
       holds a single primitive and is NOT generated here: it belongs to the
       workspace, so it has to exist before this file is imported.

       The runnable sends on all of them, driven by one timing event.
       =================================================================== -->

  <AR-PACKAGES>
    <AR-PACKAGE UUID="${uuid(package_path)}">
      <SHORT-NAME>${package}</SHORT-NAME>
      <ELEMENTS>
        <APPLICATION-SW-COMPONENT-TYPE UUID="${uuid(swc.path)}">
          <SHORT-NAME>${swc.name}</SHORT-NAME>
          <PORTS>
            <P-PORT-PROTOTYPE t-foreach="ports as port" UUID="${uuid(port.path)}">
              <SHORT-NAME>${port.name}</SHORT-NAME>
              <ADMIN-DATA>
                <SDGS>
                  <SDG GID="DV:DEV">
                    <SD GID="DV:ImportModePreset">Keep</SD>
                  </SDG>
                </SDGS>
              </ADMIN-DATA>
              <PROVIDED-COM-SPECS>
                <NONQUEUED-SENDER-COM-SPEC>
                  <DATA-ELEMENT-REF DEST="VARIABLE-DATA-PROTOTYPE">${trigger.element_ref}</DATA-ELEMENT-REF>
                  <INIT-VALUE>
                    <NUMERICAL-VALUE-SPECIFICATION>
                      <VALUE>0</VALUE>
                    </NUMERICAL-VALUE-SPECIFICATION>
                  </INIT-VALUE>
                </NONQUEUED-SENDER-COM-SPEC>
              </PROVIDED-COM-SPECS>
              <PROVIDED-INTERFACE-TREF DEST="SENDER-RECEIVER-INTERFACE">${trigger.interface}</PROVIDED-INTERFACE-TREF>
            </P-PORT-PROTOTYPE>
          </PORTS>
          <INTERNAL-BEHAVIORS>
            <SWC-INTERNAL-BEHAVIOR UUID="${uuid(behavior.path)}">
              <SHORT-NAME>${behavior.name}</SHORT-NAME>
              <EVENTS>
                <TIMING-EVENT UUID="${uuid(timing.path)}">
                  <SHORT-NAME>${timing.name}</SHORT-NAME>
                  <START-ON-EVENT-REF DEST="RUNNABLE-ENTITY">${runnable.path}</START-ON-EVENT-REF>
                  <PERIOD t-text="timing.period"/>
                </TIMING-EVENT>
              </EVENTS>
              <RUNNABLES>
                <RUNNABLE-ENTITY UUID="${uuid(runnable.path)}">
                  <SHORT-NAME>${runnable.name}</SHORT-NAME>
                  <DATA-SEND-POINTS>
                    <VARIABLE-ACCESS t-foreach="ports as port" UUID="${uuid(port.access_path)}">
                      <SHORT-NAME>${port.access}</SHORT-NAME>
                      <ACCESSED-VARIABLE>
                        <AUTOSAR-VARIABLE-IREF>
                          <PORT-PROTOTYPE-REF DEST="P-PORT-PROTOTYPE">${port.path}</PORT-PROTOTYPE-REF>
                          <TARGET-DATA-PROTOTYPE-REF DEST="VARIABLE-DATA-PROTOTYPE">${trigger.element_ref}</TARGET-DATA-PROTOTYPE-REF>
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
        <SWC-IMPLEMENTATION UUID="${uuid(implementation.path)}">
          <SHORT-NAME>${implementation.name}</SHORT-NAME>
          <BEHAVIOR-REF DEST="SWC-INTERNAL-BEHAVIOR">${behavior.path}</BEHAVIOR-REF>
        </SWC-IMPLEMENTATION>
      </ELEMENTS>
    </AR-PACKAGE>
  </AR-PACKAGES>
</AUTOSAR>
