#!/usr/bin/python

import XenAPI
import time
import bits
import os
import logging
from xml.dom import minidom 
import testsetup

ON_TIME = 15 #specifies how long a VM should be left on in between snaps

"""A file to handle snapshot creating, exporting and importing"""

def start_vm(session, vm_ref, start_paused=False, force=False):
    """Check a VM is shutdown, and if so, start"""
    if session.xenapi.VM.get_power_state(vm_ref) == "Running":
        return #no work to do
    session.xenapi.VM.start(vm_ref, start_paused, force)
    time.sleep(ON_TIME)

def shutdown_vm(session, vm_ref):
    """Check if a VM is running, and if so, shutdown"""
    if session.xenapi.VM.get_power_state(vm_ref) == "Running":
        session.xenapi.VM.clean_shutdown(vm_ref)

def snapshot(session, vm_ref, name):
    """Take a single snapshot of a VM"""
    return session.xenapi.VM.snapshot(vm_ref, name)

def revert(session, snapshot_ref):
    """Revert a VM to a previous snapshot"""
    return session.xenapi.VM.revert(snapshot_ref)

def execute_snapshot(session, snapshots):
    """Take a snapshot of current VM - 0 in list"""
    return snapshots.append(snapshot(session, snapshots[0], "Snap %d" % len(snapshots)))

def execute_revert(session, cmd, snapshots):
    _, num = cmd.split()
    return snapshots.append(revert(session, snapshots[int(num)]))

def execute_snap_instructions(session, vm_ref, instructions):
    """Method for creating an arbitary snapshot tree for instructions
    of the form: "snap, snap, revert 1, snap, snap, revert 5"""
    snapshots = []
    #Append the initial ref as '0' in array
    snapshots.append(vm_ref)
    cmds = instructions.split(',')
    print cmds
    for cmd in cmds:
        shutdown_vm(session, snapshots[0])
        if (cmd.strip()).startswith('snap'):
            execute_snapshot(session, snapshots)
        elif (cmd.strip()).startswith('revert'):
            execute_revert(session, cmd, snapshots)
        start_vm(session, snapshots[0])
    shutdown_vm(session, snapshots[0])
    return vm_ref
################ TVM Common Methods ###########################
def get_expose_record(session, record_handle):
    print "Record handle %s" % record_handle
    return record_to_dict(call_plugin(session, 'transfer', 'get_record',
                                      { 'record_handle': record_handle }))

def call_plugin(session, plugin, method, args):
    host = get_this_host(session)
    return session.xenapi.host.call_plugin(host, plugin, method, args)

def record_to_dict(xml):
    result = {}
    doc = minidom.parseString(xml)
    try:
        el = doc.getElementsByTagName('transfer_record')[0]
        for k, v in el.attributes.items():
            result[k] = v
    finally:
        doc.unlink()
    return result

def unexpose(session, record_handle):
    """Nothrow guarantee."""
    try:
        host = get_this_host(session)
        call_plugin(session, "transfer", "unexpose", {'record_handle': record_handle})
    except Exception, exn:
        print "Exception shutting down...%s" % exn
        pass

def get_this_host(session):
    return session.xenapi.session.get_this_host(session.handle)

def create_vdi(session, sr_ref, name_label, virtual_size, read_only):
    vdi_ref = session.xenapi.VDI.create(
        { 'name_label': name_label,
          'name_description': '',
          'SR': sr_ref,
          'virtual_size': str(virtual_size),
          'type': 'User',
          'sharable': False,
          'read_only': read_only,
          'xenstore_data': {},
          'other_config': {},
          'sm_config': {},
          'tags': [] })
    print 'Created VDI %s (%s, %s, %s) on %s.' % (vdi_ref, name_label,
              virtual_size, read_only, sr_ref)
    return vdi_ref

################# Snapshot Export Methods #####################
def export_vm(remote_session, host, remote_vm_ref):
    remote_vm_uuid = remote_session.xenapi.VM.get_uuid(remote_vm_ref)
    print "Getting metadata..."
    get_metadata(remote_session, host, remote_vm_uuid)
    print "Getting disks..."
    get_disks(remote_session, remote_vm_uuid)
    print "Export Complete"

def get_metadata(remote_session, host, remote_vm_uuid):
    url_path = export_url_path(remote_session, remote_vm_uuid)

    dest = 'metadata-%s.raw' % remote_vm_uuid
    print ("*** Client must download from %s://%s%s into %s" %
           ("http", host, url_path, dest))

    bits.download("http", host, url_path, dest)
    print 'Downloaded metadata file %s' % dest

    
def export_url_path(session, vm_uuid):
    vm_ref = session.xenapi.VM.get_by_uuid(vm_uuid)
    return ('/export_metadata?session_id=%s&ref=%s&include_vhd_parents=true' %
            (session.handle, vm_ref))

def all_snapshots(remote_session, remote_vm_uuid):
    r = remote_session.xenapi.VM.get_by_uuid(remote_vm_uuid)
    return [remote_session.xenapi.VM.get_uuid(x)
            for x in remote_session.xenapi.VM.get_snapshots(r)]


def get_disks(remote_session, remote_vm_uuid):    
    record_handles = expose_forest(remote_session,
                                   [remote_vm_uuid] + all_snapshots(remote_session, remote_vm_uuid)).split(',')
    print "Record Handles %s" % record_handles
    try:
        for record_handle in record_handles:
            record = get_expose_record(remote_session, record_handle)
            vdi_uuids = record['vdi_uuid'].split(',')
            if 'non_leaf_vdi_uuids' in record:
                vdi_uuids.extend(record['non_leaf_vdi_uuids'].split(','))
            for vdi_uuid in vdi_uuids:
                url_full = '%s.vhd' % record['url_full_%s' % vdi_uuid]
                url_path = '%s.vhd' % record['url_path_%s' % vdi_uuid]
                dest = '%s.vhd' % vdi_uuid
                print ("*** Client must download from %s into %s" %
                       (url_full, dest))
                if not os.access(dest, os.F_OK):
                    bits.download(
                        record['use_ssl'] == False,
                        '%s:%s' % (record['ip'], record['port']),
                        url_path,
                        dest,
                        record['username'],
                        record['password'])
                    size = os.stat(dest).st_size
    finally:
        for record_handle in record_handles:
            unexpose(remote_session, record_handle)


def expose_forest(session, vm_uuids):
    args = {}
    args['vm_uuids'] = ','.join(vm_uuids)
    args['network_uuid'] = 'management'
    args['read_only'] = 'true'
    args['get_log'] = 'true'
    host = get_this_host(session)
    print "Host %s" %host
    print "Args %s" % args
    result = session.xenapi.host.call_plugin(host, 'transfer', 'expose_forest',
                                             args)
    return result

################# Snapshot Import Methods #####################

def import_vm(session, vm_uuid, sr_ref=None):
    if not sr_ref:
        sr_ref = (session.xenapi.SR.get_by_name_label("Local storage"))[0]
        
    print "Put metadata..."
    metadata_vdi_uuid = put_metadata(session, vm_uuid, sr_ref)
    print "Put disks..."
    new_vm = put_disks(session, metadata_vdi_uuid, sr_ref)
    return new_vm

def expose_vdi(session, extra_args, metadata_vdi_uuid):
    args = dict(extra_args)
    args['vdi_uuid'] = metadata_vdi_uuid
    args['network_uuid'] = 'management'
    args['read_only'] = 'false'
    args['transfer_mode'] = 'bits'
    args['use_ssl'] = 'false'

    return call_plugin(session, 'transfer', 'expose', args)

def put_metadata(remote_session, remote_vm_uuid, remote_sr_ref):
    src = 'metadata-%s.raw' % remote_vm_uuid
    vdi_size = os.stat(src).st_size
    print "*** Client must create metadata VDI of size %ld" % vdi_size

    metadata_vdi = create_vdi(remote_session, remote_sr_ref,
                              'Remote metadata for %s' % remote_vm_uuid,
                              vdi_size, False)
    metadata_vdi_uuid = remote_session.xenapi.VDI.get_uuid(metadata_vdi)

    print "*** Client must expose metadata VDI %s" % metadata_vdi_uuid

    record_handle = expose_vdi(remote_session, {}, metadata_vdi_uuid)

    try:
        record = get_expose_record(remote_session, record_handle)

        print ("*** Client must upload from %s into %s" %
               (src, record['url_full']))

        bits_upload(src, record, record['url_path'])
        os.unlink(src)
    finally:
        unexpose(remote_session, record_handle)
    return metadata_vdi_uuid


def put_disks(remote_session, metadata_vdi_uuid, remote_sr_ref):
    print "*** Client must get instructions"
    instructions = get_import_instructions(remote_session, metadata_vdi_uuid)
    print instructions
    vdi_map = {}
    try:
        print "*** Client must execute instructions"
        execute_instructions(remote_session, instructions, vdi_map, remote_sr_ref)
        print "*** Client must remap VM"
        new_vm_uuid = remap_vm(remote_session, metadata_vdi_uuid,
                        convert_map_to_locations(remote_session, vdi_map), remote_sr_ref)
        new_vm_ref = remote_session.xenapi.VM.get_by_uuid(new_vm_uuid)
        cur_label = remote_session.xenapi.VM.get_name_label(new_vm_ref)
        remote_session.xenapi.VM.set_name_label(new_vm_ref, "%s copy" % cur_label)
        return new_vm_ref
    except:
        #TODO: Implement cleanup call
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

def execute_instructions(remote_session, instructions, vdi_map, remote_sr_ref):
    for instruction in instructions:
        print 'Instruction is %s' % instruction
        if instruction.startswith('create '):
            execute_create(remote_session, instruction, vdi_map, remote_sr_ref)
        elif instruction.startswith('clone '):
            execute_clone(remote_session, instruction, vdi_map, remote_sr_ref)
        elif instruction.startswith('reuse '):
            execute_reuse(remote_session, instruction, vdi_map, remote_sr_ref)
        elif instruction.startswith('snap '):
            execute_snap(remote_session, instruction, vdi_map)
        elif instruction.startswith('leaf '):
            execute_leaf(remote_session, instruction, vdi_map)
        elif instruction == 'pass':
            pass
        else:
            raise InvalidInstructions(
                "Invalid instruction '%s'" % instruction)

def execute_create(remote_session, instruction, vdi_map, remote_sr_ref):
    _, vdi_uuid, virtual_size = instruction.split(' ')
    dest_ref = create_vdi(remote_session, remote_sr_ref,
                          'Copy of %s' % vdi_uuid,
                          long(virtual_size), False)
    dest_uuid = remote_session.xenapi.VDI.get_uuid(dest_ref)

    put_vhd(remote_session, vdi_uuid, dest_uuid, remote_sr_ref)

    vdi_map[vdi_uuid] = dest_uuid


def execute_clone(remote_session, instruction, vdi_map, remote_sr_ref):
    _, child_uuid, parent_uuid = instruction.split(' ')

    dest_uuid = vdi_map[parent_uuid]
    dest_ref = remote_session.xenapi.VDI.get_by_uuid(dest_uuid)
    
    new_dest_ref = remote_session.xenapi.VDI.clone(dest_ref)
    new_dest_uuid = remote_session.xenapi.VDI.get_uuid(new_dest_ref)

    put_vhd(remote_session, child_uuid, new_dest_uuid, remote_sr_ref)

    vdi_map[child_uuid] = new_dest_uuid


def execute_reuse(local_session, instruction, vdi_map, remote_sr_ref):
    _, child_uuid, parent_uuid = instruction.split(' ')

    dest_uuid = vdi_map[parent_uuid]
    
    put_vhd(local_session, child_uuid, dest_uuid, remote_sr_ref)
    
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

def put_vhd(remote_session, src_uuid, dest_uuid, remote_sr_ref):
    print "*** Client must put VHD %s into %s" % (src_uuid, dest_uuid)

    print "*** Client must expose VDI %s" % dest_uuid

    record_handle = expose_vdi(remote_session, {}, dest_uuid)

    try:
        record = get_expose_record(remote_session, record_handle)

        url_full = '%s.vhd' % record['url_full']
        url_path = '%s.vhd' % record['url_path']

        print "*** Client must upload from %s into %s" % (src_uuid, url_full)

        bits_upload('%s.vhd' % src_uuid, record, url_path)
        os.unlink('%s.vhd' % src_uuid)
    finally:
        unexpose(remote_session, record_handle)
        

def bits_upload(src, record, url_path):
    bits.upload(src,
                'http',
                record['ip'],
                record['port'],
                record['username'],
                record['password'],
                url_path)
    print "Upload of %s complete." % src

def remap_vm(session, metadata_vdi_uuid, vdi_map, remote_sr_ref):
    def vdi_map_to_string(vdi_map):
        result = []
        for k, v in vdi_map.iteritems():
            result.append('%s=%s' % (k, v))
        return ','.join(result)

    remote_sr_uuid = session.xenapi.SR.get_uuid(remote_sr_ref)
    args = {}
    args['vm_metadata_vdi_uuid'] = metadata_vdi_uuid
    args['vdi_map'] = vdi_map_to_string(vdi_map)
    args['sr_uuid'] = remote_sr_uuid
    return call_plugin(session, 'transfer', 'remap_vm', args)


def get_import_instructions(session, metadata_vdi_uuid):
    return \
        call_plugin(session, 'transfer', 'get_import_instructions',
                    { 'vm_metadata_vdi_uuid': metadata_vdi_uuid }).split('\n')
