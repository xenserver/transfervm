#!/usr/bin/python

import XenAPI
import transferclient
import testsetup
import logging
import unittest
import subprocess

def setup_and_get_record(vdi_mb, trans_mode, hostname, vdi_uuid):
    logging.debug("starting function")
    if hostname and vdi_uuid:
        logging.debug("%s %s" % (hostname, vdi_uuid))
        transferclient.expose(hostname, vdi_uuid=vdi_uuid, network_uuid="management", transfer_mode=trans_mode)
    else:
        hostname, network, vdi_uuid = testsetup.setup_host_and_network(templates=1, vdi_mb=vdi_mb)
        transferclient.expose(hostname, vdi_uuid=vdi_uuid, network_uuid=network, transfer_mode=trans_mode)
    record = transferclient.get_record(hostname, vdi_uuid=vdi_uuid)
    return record, hostname

@transferclient.xenapi_session
def isVdiKeyOnSR(session, hostname, vdi_uuid):
    """ Checks that the SR on which the VDI resides has an other-config key
        with the vdi_uuid the TVM is exposing. In the case that multiple 
        identical keys are found, an exception is raised.
    """
    key = "tvm_%s" % vdi_uuid
    logging.debug("Looking for key %s on SR" % key)
    host = testsetup.HOST #Can't use hostname above because of decorator
    sr = get_sr(host, vdi_uuid)
    other_config = session.xenapi.SR.get_other_config(sr)
    
    key_count = 0
    for pair in other_config:
        if pair.startswith(key):
            key_count = key_count + 1

    if key_count == 0:
        return False
    elif key_count > 1:
        raise Exception("Multiple identical keys found! %s on %s" % (key, sr))
    else:
        return True

@transferclient.xenapi_session
def get_sr(session, hostname, vdi_uuid):
    vdi_ref = session.xenapi.VDI.get_by_uuid(vdi_uuid)
    return session.xenapi.VDI.get_SR(vdi_ref)

@transferclient.xenapi_session
def delete_vdi(session, hostname, vdi_uuid):
    vdi_ref = session.xenapi.VDI.get_by_uuid(vdi_uuid)
    session.xenapi.VDI.destroy(vdi_ref)

def assertVdiKeyOnSR(hostname, vdi_uuid):
    if isVdiKeyOnSR(hostname, vdi_uuid):
        return True
    else:
        raise Exception("SR other-config signal is not present for VDI_UUID %s" % vdi_uuid)

def assertVdiKeyNotOnSR(hostname, vdi_uuid):
    if isVdiKeyOnSR(hostname, vdi_uuid):
        raise Exception("The VDI_UUID key %s is still present on it's SR and has not been correctly removed." % vdi_uuid)
    else:
        return True        

def check_gc_status(hostname, sr_uuid):
    sm_script = "/opt/xensource/sm/cleanup.py"
    target_commands = "/opt/xensource/sm/cleanup.py -q -u %s" % sr_uuid
    remote_command  = "ssh root@%s %s" % (hostname, target_commands)
    logging.debug("Making remote call: %s" % remote_command)
    
    process = subprocess.Popen(["ssh", "root@" + hostname, sm_script, "-q", "-u", sr_uuid],
                               stdout=subprocess.PIPE)
    stdout, _ = process.communicate()
    if process.returncode == 0:
        return stdout
    else:
        raise Exception("There was an error attempting to check the status of GC")

def get_GC_status(hostname, sr_uuid):
    gc_status = check_gc_status(hostname, sr_uuid)
    rc = gc_status.find("True")
    gc_status = "Current Status: True"
    return (rc != -1) #Testing for not being able to find false

def assertGCIsRunning(hostname, sr_uuid):
    if not get_GC_status(hostname, sr_uuid):
        raise Exception("The GC script in Dom0 is NOT running when assumed it should not be!")

def assertGCIsNotRunning(hostname, sr_uuid):
    if get_GC_status(hostname, sr_uuid):
        raise Exception("The GC script in Dom0 IS running when assumed it should not be!")

class TestSRConfigSignals(unittest.TestCase):
    VDI_MB = 10
    TRANSFER_MODE = "http"

    def _expose_vdi(self, transfer_mode, hostname=None, vdi_uuid=None):
        if hostname and vdi_uuid:
            record, host = setup_and_get_record(self.VDI_MB, transfer_mode, hostname, vdi_uuid)
        else:
            record, host = setup_and_get_record(self.VDI_MB, transfer_mode, None, None)
        logging.debug(host)
        assertVdiKeyOnSR(host, record['vdi_uuid'])
        return record, host
        
    def _unexpose_vdi(self, hostname, record):
        transferclient.unexpose(hostname, vdi_uuid=record['vdi_uuid'])
        assertVdiKeyNotOnSR(hostname, record['vdi_uuid'])

    def testExposeUnexpose(self):
        record, hostname = self._expose_vdi(self.TRANSFER_MODE)
        sr_uuid = get_sr(hostname, record['vdi_uuid'])
        assertGCIsNotRunning(hostname, sr_uuid)
        self._unexpose_vdi(hostname, record)
        delete_vdi(hostname, record['vdi_uuid'])

    def testExposeShutdownExposeUnexpose(self):
        logging.debug("First Expose...")
        record, hostname = self._expose_vdi(self.TRANSFER_MODE)
        logging.debug("TransferVM shutdown")
        testsetup.clean_vms(hostname)
        logging.debug("Second Expose for same disk")
        #For the second expose, we must use the same vdi
        record, hostname = self._expose_vdi(self.TRANSFER_MODE, hostname, record['vdi_uuid'])
        logging.debug("Second unexpose")
        self._unexpose_vdi(hostname, record)
        delete_vdi(hostname, record['vdi_uuid'])
        
    def testExposeShutdown(self):
        record, hostname = self._expose_vdi(self.TRANSFER_MODE)
        testsetup.clean_vms(hostname)
        assertVdiKeyNotOnSR(hostname, record['vdi_uuid'])
        delete_vdi(hostname, record['vdi_uuid'])
        
        



