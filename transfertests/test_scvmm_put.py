#!/usr/bin/env python

import os
import os.path
import sys
import time
import urlparse
from xml.dom import minidom
import xmlrpclib

import XenAPI

import bits
from test_scvmm_common import *


class InvalidInstructions(Exception):
    def __init__(self, *args):
        Exception.__init__(self, *args)


remote_url = sys.argv[1]
remote_username = sys.argv[2] 
remote_password = sys.argv[3]
remote_vm_uuid = sys.argv[4]
remote_sr_uuid = sys.argv[5]
extra_args = list(sys.argv)
del extra_args[0:6]
extra_args = dict([a.split('=') for a in extra_args])

(protocol, remote_netloc, _, _, _, _) = urlparse.urlparse(remote_url)

remote_session = XenAPI.Session(remote_url)
remote_session.login_with_password(remote_username, remote_password)

metadata_vdi_uuid = None
total_upload_size = 0
total_upload_time = 0


def put_metadata():
    global metadata_vdi_uuid

    src = 'metadata-%s.raw' % remote_vm_uuid
    vdi_size = os.stat(src).st_size
    print "*** SCVMM must create metadata VDI of size %ld" % vdi_size

    remote_sr_ref = remote_session.xenapi.SR.get_by_uuid(remote_sr_uuid)
    metadata_vdi = create_vdi(remote_session, remote_sr_ref,
                              'Remote metadata for %s' % remote_vm_uuid,
                              vdi_size, False)
    metadata_vdi_uuid = remote_session.xenapi.VDI.get_uuid(metadata_vdi)

    print "*** SCVMM must expose metadata VDI %s" % metadata_vdi_uuid

    record_handle = expose_vdi(remote_session, extra_args, metadata_vdi_uuid)

    try:
        record = get_expose_record(remote_session, record_handle)

        print ("*** SCVMM must upload from %s into %s" %
               (src, record['url_full']))

        if record['use_ssl'] == 'true':
            print "*** SSL cert is %s" % record['ssl_cert'].replace('|', '\n')

        bits_upload(src, record, record['url_path'])
    finally:
        unexpose(remote_session, record_handle)


def put_disks():
    print "*** SCVMM must get instructions"
    instructions = get_import_instructions(remote_session, metadata_vdi_uuid)

    vdi_map = {}
    try:
        print "*** SCVMM must execute instructions"
        execute_instructions(instructions, vdi_map)
        print "*** SCVMM must remap VM"
        return remap_vm(remote_session, metadata_vdi_uuid,
                        convert_map_to_locations(remote_session, vdi_map))
    except:
        destroy_all_vdis(remote_session, vdi_map)
        raise


def convert_map_to_locations(session, vdi_map):
    """
    Convert a UUID -> UUID VDI map into the form that remap_vm wants.
    """
    result = {}
    for k, v in vdi_map.iteritems():
        new_ref = session.xenapi.VDI.get_by_uuid(v)
        result[k] = session.xenapi.VDI.get_location(new_ref)
    return result


def destroy_all_vdis(session, vdi_map):
    """Nothrow guarantee."""
    for vdi_uuid in vdi_map.itervalues():
        destroy_vdi(session, vdi_uuid)


def destroy_vdi(session, vdi_ref):
    """Nothrow guarantee."""
    vdi_ref = ignore_failure(session.xenapi.VDI.get_by_uuid, vdi_ref)
    if vdi_ref is not None:
        ignore_failure(session.xenapi.VDI.destroy, vdi_ref)


def execute_instructions(instructions, vdi_map):
    for instruction in instructions:
        print 'Instruction is %s' % instruction
        if instruction.startswith('create '):
            execute_create(instruction, vdi_map)
        elif instruction.startswith('clone '):
            execute_clone(instruction, vdi_map)
        elif instruction.startswith('reuse '):
            execute_reuse(remote_session, instruction, vdi_map)
        elif instruction.startswith('snap '):
            execute_snap(remote_session, instruction, vdi_map)
        elif instruction.startswith('leaf '):
            execute_leaf(remote_session, instruction, vdi_map)
        elif instruction == 'pass':
            pass
        else:
            raise InvalidInstructions(
                "Invalid instruction '%s'" % instruction)
        

def execute_create(instruction, vdi_map):
    _, vdi_uuid, virtual_size = instruction.split(' ')
    remote_sr_ref = remote_session.xenapi.SR.get_by_uuid(remote_sr_uuid)
    dest_ref = create_vdi(remote_session, remote_sr_ref,
                          'Copy of %s' % vdi_uuid,
                          long(virtual_size), False)
    dest_uuid = remote_session.xenapi.VDI.get_uuid(dest_ref)

    put_vhd(vdi_uuid, dest_uuid)

    vdi_map[vdi_uuid] = dest_uuid


def execute_clone(instruction, vdi_map):
    _, child_uuid, parent_uuid = instruction.split(' ')

    dest_uuid = vdi_map[parent_uuid]
    dest_ref = remote_session.xenapi.VDI.get_by_uuid(dest_uuid)
    
    new_dest_ref = remote_session.xenapi.VDI.clone(dest_ref)
    new_dest_uuid = remote_session.xenapi.VDI.get_uuid(new_dest_ref)

    put_vhd(child_uuid, new_dest_uuid)

    vdi_map[child_uuid] = new_dest_uuid


def execute_reuse(local_session, instruction, vdi_map):
    _, child_uuid, parent_uuid = instruction.split(' ')

    dest_uuid = vdi_map[parent_uuid]
    
    put_vhd(child_uuid, dest_uuid)
    
    del vdi_map[parent_uuid]
    vdi_map[child_uuid] = dest_uuid


def execute_snap(session, instruction, vdi_map):
    _, vdi_uuid = instruction.split(' ')
    dest_uuid = vdi_map[vdi_uuid]
    dest_ref = session.xenapi.VDI.get_by_uuid(dest_uuid)
    sr_ref = session.xenapi.VDI.get_SR(dest_ref)
    new_dest_ref, new_dest_uuid = \
        snapshot_leaf(session, dest_ref, dest_uuid)
    session.xenapi.SR.scan(sr_ref)

    session.xenapi.VDI.set_name_label(new_dest_ref, 'Copy of %s' % vdi_uuid)
    vdi_map[vdi_uuid] = new_dest_uuid


def snapshot_leaf(session, dest_ref, dest_uuid):
    new_dest_ref = session.xenapi.VDI.snapshot(dest_ref)
    session.xenapi.VDI.destroy(dest_ref)
    new_dest_uuid = session.xenapi.VDI.get_uuid(new_dest_ref)
    return new_dest_ref, new_dest_uuid


def execute_leaf(session, instruction, vdi_map):
    _, vdi_uuid = instruction.split(' ')
    dest_uuid = vdi_map[vdi_uuid]
    dest_ref = session.xenapi.VDI.get_by_uuid(dest_uuid)

    session.xenapi.VDI.set_name_label(dest_ref, 'Copy of %s' % vdi_uuid)
    vdi_map[vdi_uuid] = dest_uuid


def put_vhd(src_uuid, dest_uuid):
    print "*** SCVMM must put VHD %s into %s" % (src_uuid, dest_uuid)

    remote_sr_ref = remote_session.xenapi.SR.get_by_uuid(remote_sr_uuid)

    print "*** SCVMM must expose VDI %s" % dest_uuid

    record_handle = expose_vdi(remote_session, extra_args, dest_uuid)

    try:
        record = get_expose_record(remote_session, record_handle)

        url_full = '%s.vhd' % record['url_full']
        url_path = '%s.vhd' % record['url_path']

        print "*** SCVMM must upload from %s into %s" % (src_uuid, url_full)

        if record['use_ssl'] == 'true':
            print "*** SSL cert is %s" % record['ssl_cert'].replace('|', '\n')

        bits_upload('%s.vhd' % src_uuid, record, url_path)
    finally:
        unexpose(remote_session, record_handle)


def get_import_instructions(session, metadata_vdi_uuid):
    return \
        call_plugin(session, 'transfer', 'get_import_instructions',
                    { 'vm_metadata_vdi_uuid': metadata_vdi_uuid }).split('\n')


def bits_upload(src, record, url_path):
    global total_upload_time
    global total_upload_size

    start = time.time()
    bits.upload(src,
                record['use_ssl'] and 'https' or 'http',
                record['ip'],
                record['port'],
                record['username'],
                record['password'],
                url_path)
    end = time.time()
    size = os.stat(src).st_size
    print ("Uploaded %d MB in %d secs = %d Mbit/s" %
           (int(size) >> 20, int(end - start),
            int(size / (end - start)) >> 17))
    total_upload_time += (end - start)
    total_upload_size += size


def expose_vdi(session, extra_args, metadata_vdi_uuid):
    args = dict(extra_args)
    args['vdi_uuid'] = metadata_vdi_uuid
    args['network_uuid'] = 'management'
    args['read_only'] = 'false'
    args['transfer_mode'] = 'bits'
    args['use_ssl'] = protocol == 'https' and 'true' or 'false'

    return call_plugin(session, 'transfer', 'expose', args)


def remap_vm(session, metadata_vdi_uuid, vdi_map):
    def vdi_map_to_string(vdi_map):
        result = []
        for k, v in vdi_map.iteritems():
            result.append('%s=%s' % (k, v))
        return ','.join(result)

    args = {}
    args['vm_metadata_vdi_uuid'] = metadata_vdi_uuid
    args['vdi_map'] = vdi_map_to_string(vdi_map)
    args['sr_uuid'] = remote_sr_uuid
    return call_plugin(session, 'transfer', 'remap_vm', args)


put_metadata()
put_disks()

print ("Total upload: %d MB in %d secs = %d Mbit/s" %
       (int(total_upload_size) >> 20, int(total_upload_time),
        int(total_upload_size / total_upload_time) >> 17))
