#!/usr/bin/python

import XenAPI
import unittest
import testsetup
import threading
import moreasserts

from xml.dom import minidom
from snapshot_utils import *

def destroy_vm(session, vm_ref):
    vbds = session.xenapi.VM.get_VBDs(vm_ref)
    for vbd in vbds:
        vdi_ref = session.xenapi.VBD.get_VDI(vbd)
        session.xenapi.VDI.destroy(vdi_ref)
    session.xenapi.VM.destroy(vm_ref)

def get_test_session():
    host = testsetup.HOST
    session = XenAPI.Session("http://%s" % host)
    session.login_with_password('root', 'xenroot')
    return session

def set_vm_xml(session, vm_ref, sr_ref):
    """Re-write the xml for provisioning disks to set a SR"""
    other_config = session.xenapi.VM.get_other_config(vm_ref)
    disks_xml = minidom.parseString(other_config['disks'])
    sr_uuid = session.xenapi.SR.get_uuid(sr_ref)
    disks = disks_xml.getElementsByTagName("disk")
    for disk in disks:
        if "sr" in disk.attributes.keys():
            print "SR"
            disk.attributes["sr"].value = sr_uuid
            print disk.attributes["sr"].value
    other_config['disks'] = disks_xml.toxml()
    session.xenapi.VM.set_other_config(vm_ref, other_config)

def clone_from_template(session, template_name, vm_name="Test VM", provision=False, sr=None):
    if not sr:
        sr_ref = (session.xenapi.SR.get_by_name_label('Local storage'))[0]
    template_ref = (session.xenapi.VM.get_by_name_label(template_name))[0]
    vm_ref = session.xenapi.VM.copy(template_ref, vm_name, sr_ref)
    if provision:
        set_vm_xml(session, vm_ref, sr_ref)
    session.xenapi.VM.provision(vm_ref)
    return vm_ref

def convert_to_template(session, vm_ref):
    return session.xenapi.VM.set_is_a_template(vm_ref, True)

def export_import_vm(session, vm_ref):
    #Export the VM
    vm_uuid = session.xenapi.VM.get_uuid(vm_ref)
    export_vm(session, testsetup.HOST, vm_ref)
    #Destroy the VM on the host, before import
    destroy_vm(session, vm_ref)
    #Import the VM
    new_vm = import_vm(session, vm_uuid)
    return new_vm

class SnapshotExportImportTest(unittest.TestCase):
    """A class of tests for exporting and importing snapshot trees"""
    TEMPLATE = "Demo Linux VM"
    
    def _doExportImportTest(self, instructions, template=None):
        session = get_test_session()
        if not template:
            template = self.TEMPLATE

        vm_ref = clone_from_template(session, template, "ImportExport Test VM", provision=True)
        vm_uuid = session.xenapi.VM.get_uuid(vm_ref)
        #vm_uuid = "cb198171-399e-7042-928e-9da990fd506a"
        #vm_ref = session.xenapi.VM.get_by_uuid(vm_uuid)
        execute_snap_instructions(session, vm_ref, instructions)
        export_import_vm(session, vm_ref)
        
    def testNoSnapshot(self):
        self._doExportImportTest("")
    
    def testSingleSnapshot(self):
        self._doExportImportTest("snap")
    
    def testLinearSnapshot(self):
        self._doExportImportTest("snap, snap, snap, snap, snap")
    
    def testNonLinearSnapshot(self):
        self._doExportImportTest("snap, snap, snap, revert 1, snap, snap, snap, revert 5, snap")

    def testNonLinearSnapshot1(self):
        self._doExportImportTest("snap, snap, revert 1, snap, snap, snap, revert 4, snap, snap")

class ThinCloneSnapshotExportImportTest(unittest.TestCase):
    """Tests are run using a template that was created from the base template.
    This means that we test a thin clone base which may expose errors in our
    shadowing code.
    """
    TEMPLATE = "Demo Linux VM"

    def _doTest(self):
        session = get_test_session()
        #Create a template from which the above tests will be run
        new_template_label = "Demo VM Template"
        vm_ref = clone_from_template(session, self.TEMPLATE, new_template_label, provision=True)
        convert_to_template(session, vm_ref)
        vm_ref = clone_from_template(session, new_template_label, "ThinClone")
        export_import_vm(session, vm_ref)

    def testSingleCloneExportImport(self):
        self._doTest()


class ConfigurationExportImportTest(unittest.TestCase):
    """A class of tests to check configurations that have caused problems previously
    don't regress."""
    TEMPLATE = "Demo Linux VM"
    
    def _addDummyNetwork(self, session, vm_ref):
        """Add a new network and connect it to the VM - this is to test the behaviour of the vm
        on import - and ensure it copes with the network not existing on that end."""
        network = session.xenapi.network.create({'name_label': 'Test Network',
                                         'name_description': 'Test',
                                         'other_config': {},
                                         'bridge': '',
                                         'MTU': '1500'})

        vif = session.xenapi.VIF.create({'network': network,
                                         'MTU': '1500',
                                         'other_config': {},
                                         'qos_algorithm_params': {},
                                         'qos_algorithm_type': '',
                                         'VM': vm_ref,
                                         'MAC': '00:00:00:00:00:00',
                                         'device': '3' })
        return network

    
    def _doNetworkTest(self):
        session = get_test_session()
        vm_ref = clone_from_template(session, self.TEMPLATE, "NewtorkTest VM", provision=True)
        vm_uuid = session.xenapi.VM.get_uuid(vm_ref)
        self._addDummyNetwork(session, vm_ref)
        export_vm(session, testsetup.HOST, vm_ref)
        destroy_vm(session, vm_ref)
        new_vm = import_vm(session, vm_uuid)


    def testNetworkConfig(self):
        self._doNetworkTest()


class StorageLevelTests(unittest.TestCase):
    """A test class for ensuring that we handle storage level operations
    such as snapshoting in a correct way. This is mainly because we go beneath
    the API to get at the VHDs BAT."""
    TEMPLATE = "Demo Linux VM"
    def _assertRaisesVMChangeError(self, method, *args, **kwargs):
        moreasserts.assertRaisesXenapiFailure(self, 'VMChangedDuringExport', method, *args, **kwargs)

    def _testSnapshotDuringBatRead(self, seconds):
        session = get_test_session()
        #vm_ref = clone_from_template(session, self.TEMPLATE, "SnapshotDuringBatRead Test", provision=True)
        #vm_uuid = session.xenapi.VM.get_uuid(vm_ref)
        vm_uuid = "a1cb4724-930f-cc8f-6249-dee975545902"
        vm_ref = session.xenapi.VM.get_by_uuid(vm_uuid)

        t = threading.Timer(seconds, snapshot, [session, vm_ref, "1"])
        t.start()
        self._assertRaisesVMChangeError(export_vm, session, testsetup.HOST, vm_ref)

    def testSnapshotDuringBatReadOneSecond(self):
        self._testSnapshotDuringBatRead(1)

    def testSnapshotDuringBatReadThreeSeconds(self):
        self._testSnapshotDuringBatRead(3)
        
    def testSnapshotDuringBatReadFiveSeconds(self):
        self._testSnapshotDuringBatRead(5)        

    def testSnapshotDuringBatReadTenSeconds(self):
        self._testSnapshotDuringBatRead(10)
