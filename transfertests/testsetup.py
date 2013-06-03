#!/usr/bin/python
"""Provides helper functions for setting up a Hyde VDI transfer test environment."""

import subprocess
import sys

import transferclient


HOST = None
PLUGIN = None
XENAPI = None
VMTEMPLATE = None
WIPE_HOST = False

def call_to_stderr(args):
    proc = subprocess.Popen(args, stdin=None, stdout=sys.stderr, stderr=subprocess.PIPE)
    proc.wait()

def wipe_host(hostname):
    """Wipes the host database to remove all VMs, VDIs and other virtual components."""
    target_commands = ('xe vm-shutdown power-state=running is-control-domain=false --multiple --force; ' +
                       'service xapi stop; ' +
                       'rm -f /var/xapi/*.db; ' +
                       'rm -f /etc/firstboot.d/state/*; ' +
                       'echo master > /etc/xensource/pool.conf; ' +
                       'service xapi start; ' +
                       'service firstboot start; ')
    call_to_stderr(['ssh', 'root@' + hostname, target_commands])

def clean_host(hostname):
    clean_vms(hostname)
    clean_disks(hostname)

def clean_vms(hostname):
    target_commands = ('xe vm-shutdown power-state=running other-config:transfervm_clone=true --multiple --force')
    call_to_stderr(['ssh', 'root@' + hostname, target_commands])

def clean_disks(hostname):
    target_commands = ('xe vdi-list other-config:test_vdi=true --minimal | xargs -d, -iXX xe vdi-destroy uuid=XX')
    call_to_stderr(['ssh','root@' + hostname, target_commands])

def deploy_plugin(hostname):
    if XENAPI:
        call_to_stderr(['scp', XENAPI, 'root@' + hostname + ':/usr/lib/python2.4/site-packages'])
    if PLUGIN:
        call_to_stderr(['scp', PLUGIN, 'root@' + hostname + ':/etc/xapi.d/plugins'])

def deploy_vm_template(hostname):
    if VMTEMPLATE:
        call_to_stderr(['scp', VMTEMPLATE, 'root@' + hostname + ':/root/transfervm.xva'])
        target_commands = ('UUID=$(xe vm-import filename=/root/transfervm.xva); ' +
                       'xe vm-param-set uuid=$UUID is-a-template=true; ' +
                       'xe vm-param-add uuid=$UUID param-name=other-config transfervm=true; ')
        call_to_stderr(['ssh', 'root@' + hostname, target_commands])

def remove_tvm_template(hostname):
    target_commands = ('xe template-list other-config:transfervm=true --minimal | xargs -d, -Ixx xe template-uninstall template-uuid=xx --force')
    call_to_stderr(['ssh', 'root@' + hostname, target_commands])

# These static variables are a hack to speed up tests:
# The XenServer host is only wiped of all VMs and VDIs when
# a different number of VM templates or NO VDIs are requested,
# and after every 10 setup calls.
VM_TEMPLATES_INSTALLED = -1
VDIS_CREATED = False
TIMES_CALLED = 0
LAST_TEST_WAS_DANGEROUS = False


class Skipped(Exception):
    pass

# skipTest is defined in Python 2.7.  Given that we're not using that version,
# we'll just fail the test instead.
def skipTest(reason):
    raise Skipped(reason)

def setup_host_and_network(templates=1, vdi_mb=None, dangerous_test=False, vdi_raw=False):
    """Sets up the test host with Transfer utility VM templates.
    If vdi_mb is given, a VDI is created as well.

    The host is wiped of all VMs, VDIs and other XenDB data:
    * every 10 setup calls,
    * when a different number of templates is requested,
    * before and after a dangerous_test,
    * when no VDI is requested, but some VDIs have been created already.

    Returns the hostname, a virtual network uuid, and if created, a vdi uuid.
    """
    global VM_TEMPLATES_INSTALLED
    global VDIS_CREATED
    global TIMES_CALLED
    global LAST_TEST_WAS_DANGEROUS

    hostname = HOST

    if templates != 1 and not VMTEMPLATE:
        skipTest("Non-standard configuration")

    if (dangerous_test or
            LAST_TEST_WAS_DANGEROUS or
            TIMES_CALLED >= 10 or
            VM_TEMPLATES_INSTALLED != templates or
            (not vdi_mb and VDIS_CREATED)):
        TIMES_CALLED = 0
        VDIS_CREATED = False
        if WIPE_HOST:
            wipe_host(hostname)
        else:
            clean_vms(hostname)
        deploy_plugin(hostname)
        for i in xrange(templates):
            deploy_vm_template(hostname)

    TIMES_CALLED += 1
    VM_TEMPLATES_INSTALLED = templates
    LAST_TEST_WAS_DANGEROUS = dangerous_test

    if vdi_mb:
        sm_config = {}
        if vdi_raw:
            sm_config["type"] = "raw"
        vdi_uuid = transferclient.create_vdi(hostname, 'ABCDEF Test VDI', vdi_mb * 1024 * 1024, sm_config)
        VDIS_CREATED = True
        return hostname, transferclient.network_by_name(hostname, '0'), vdi_uuid
    else:
        return hostname, transferclient.network_by_name(hostname, '0')
