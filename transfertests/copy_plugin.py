#!/usr/bin/python

import XenAPI
import unittest
import testsetup
import threading
import moreasserts
import exportimport

from xml.dom import minidom
from snapshot_utils import *

#Credentials for working in a test environment
USERNAME = "root"
PASSWORD = "xenroot"

def get_vm_copy(session, vm_uuid, src_host, dst_host_ref, local_sr_uuid, op="get_vm"):
    """A Utility method for calling the XAPI plugin copy to move a VM between hosts
    The 'get_vm' plugin call is made against the destination host.
    The source host is the 'remote' host.
    The destination host is the local host.
    """

    if op == "get_vm_forest":
        remote_vm_label = "remote_vm_uuids"
    else:
        remote_vm_label = "remote_vm_uuid"

    args = {'remote_host': src_host,
            'remote_username': USERNAME,
            'remote_password': PASSWORD,
            remote_vm_label: vm_uuid,
            'local_sr_uuid': local_sr_uuid}

    session.xenapi.host.call_plugin(dst_host_ref, 'copy', op, args)
            

def get_local_sr_uuid(session):
    local_sr = session.xenapi.SR.get_by_name_label('Local storage')
    if len(local_sr):
        return session.xenapi.SR.get_uuid(local_sr[0])
    else:
        raise "Error - no storage found"

def get_remote_host(dst_host):
    session = XenAPI.Session("http://%s" % dst_host)
    session.login_with_password(USERNAME, PASSWORD)
    return session.xenapi.host.get_all()[0], session
    

class HostToHostPull(unittest.TestCase):
    """A class of tests for exporting a VM from one host, directly to another"""
    #These variable must be updated with the correct host information
    SRC_HOST = "dt12.uk.xensource.com"
    DST_HOST = "sunburn"
    TEMPLATE = "Demo Linux VM"
    OPERATION = "get_vm"
    
    def testBasic(self):
        """A test that simply calls the copy plugin to initiate a transfer"""
        remote_session = exportimport.get_test_session()
        #Create a VM on src host
        vm_ref = exportimport.clone_from_template(remote_session, self.TEMPLATE)
        vm_uuid = remote_session.xenapi.VM.get_uuid(vm_ref)

        #Connect to the remote host
        dst_host, local_session = get_remote_host(self.DST_HOST)
        local_sr_uuid = get_local_sr_uuid(local_session)
        
        get_vm_copy(remote_session, vm_uuid, self.SRC_HOST, dst_host, local_sr_uuid, self.OPERATION)
        
    
class HostToHostTreePull(HostToHostPull):
    OPERATION = "get_vm_forest"
