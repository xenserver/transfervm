# Transfer VM - VPX for exposing VDIs on XenServer
# Copyright (C) Citrix Systems, Inc.
#
# This program is free software; you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation; either version 2 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License along
# with this program; if not, write to the Free Software Foundation, Inc.,
# 51 Franklin Street, Fifth Floor, Boston, MA 02110-1301 USA.
#

import cStringIO
import httplib
import tarfile
from xml.dom import minidom

from pluginlib import *


class MetadataDownloadFailed(PluginError):
    """We failed to download the specified VM's metadata."""
    def __init__(self, *args):
        PluginError.__init__(self, *args)


class MetadataUploadFailed(PluginError):
    """We failed to upload the specified VM's metadata."""
    def __init__(self, *args):
        PluginError.__init__(self, *args)


class InvalidOVAXML(PluginError):
    """The ova.xml file we received for the VM is invalid."""
    def __init__(self, *args):
        PluginError.__init__(self, *args)


def import_vm_metadata(protocol, host, port, session, tarball):
    name = 'VM metadata import'
    task_ref = session.xenapi.task.create(name, '')
    url = ('/import_metadata?session_id=%s&task_id=%s&force=true' %
           (session.handle, task_ref))
    log.debug('Uploading metadata to %s://%s:%s%s (len %d)', protocol, host,
              port, url, len(tarball))
    try:
        if protocol == 'https':
            conn = httplib.HTTPSConnection(host, port)
        else:
            conn = httplib.HTTPConnection(host, port)
        try:
            conn.request('PUT', url, tarball)
            response = conn.getresponse()
            log.debug('Upload response is %s', response.status)
            if response.status != 200:
                raise MetadataUploadFailed(url)
        finally:
            conn.close()

        result = wait_for_task_success(session, task_ref)
        log.debug('Metadata upload result: %s', result)
        return parse_xmlrpc_value(result)[0]
    finally:
        ignore_failure(session.xenapi.task.destroy, task_ref)


def make_new_vm_metadata(vm_metadata, vdi_map, sr_uuid):
    ova_xml = parse_ova_xml(vm_metadata)
    try:
        update_vdi_locations(ova_xml, vdi_map, sr_uuid)
        return make_vm_metadata_tarball(ova_xml.toxml())
    finally:
        ova_xml.unlink()


def parse_ova_xml(vm_metadata):
    """
    Take the given VM export tarball, extract ova.xml, and parse it.  Returns
    a minidom document.
    """
    tf = tarfile.open(mode='r:', fileobj=vm_metadata)
    try:
        ova_xml_file = tf.extractfile('ova.xml')
        try:
            return minidom.parse(ova_xml_file)
        finally:
            ova_xml_file.close()
    finally:
        tf.close()


def make_vm_metadata_tarball(ova_xml):
    ova_xml = ova_xml.encode('UTF-8')
    out_file = cStringIO.StringIO()
    ova_xml_file = cStringIO.StringIO(ova_xml)
    try:
        tf = tarfile.open(mode='w:', fileobj=out_file, bufsize=512)
        try:
            ti = tarfile.TarInfo(name='ova.xml')
            ti.size = len(ova_xml)
            tf.addfile(ti, fileobj=ova_xml_file)
        finally:
            tf.close()
        return out_file.getvalue()
    finally:
        ova_xml_file.close()
        out_file.close()


def update_vdi_locations(ova_xml, vdi_map, sr_uuid):
    array_node = get_objects_value(ova_xml)
    for val in array_node.childNodes[0].childNodes: # Skipped array/data
        struct = val.childNodes[0]
        if has_member(struct, 'class', 'VDI'):
            update_vdi_location(struct, vdi_map)
        elif has_member(struct, 'class', 'SR'):
            update_sr_uuid(struct, sr_uuid)


def get_objects_value(ova_xml):
    struct = ova_xml.childNodes[0].childNodes[0] # value/struct
    for member in struct.childNodes: # member
        if is_member(member, 'objects'):
            return get_value(member)
    raise InvalidOVAXML()


def foreach_instance(ova_xml, cls, f):
    array_node = get_objects_value(ova_xml)
    for val in array_node.childNodes[0].childNodes: # Skipped array/data
        struct = val.childNodes[0]
        if has_member(struct, 'class', cls):
            do_for_snapshot(struct, f)


def do_for_snapshot(struct, f):
    for member in struct.childNodes:
        if is_member(member, 'snapshot'):
            f(get_value(member))
            return


def update_vdi_location(struct, vdi_map):
    do_for_snapshot(struct, lambda v: replace_location(v, vdi_map))


def update_sr_uuid(struct, sr_uuid):
    do_for_snapshot(struct, lambda v: replace_uuid(v, sr_uuid))


def replace_location(snap, vdi_map):
    for member in snap.childNodes:
        if is_member(member, 'location'):
            val = get_value(member)
            old_location = val.wholeText
            new_location = \
                old_location in vdi_map and \
                    vdi_map[old_location] or \
                    'OpaqueRef:NULL'
            val.replaceWholeText(new_location)
            return
    log.warn("Failed to find location")
    raise InvalidOVAXML()


def replace_uuid(snap, uuid):
    for member in snap.childNodes:
        if is_member(member, 'uuid'):
            val = get_value(member)
            val.replaceWholeText(uuid)
            return
    log.warn("Failed to find uuid")
    raise InvalidOVAXML()

def get_networks(ova_xml):
    result = []

    def get_networks_(snap):
        arr = {}
        arr['uuid'] = get_value_from(snap, 'uuid').wholeText
        arr['name_label'] = get_value_from(snap, 'name_label').wholeText
        arr['name_description'] = "New network created on Import"
        oc = {}
        oc['created_on_import'] = "true"
        arr['other_config'] = oc
        arr['bridge'] = get_value_from(snap, 'bridge').wholeText
        arr['MTU'] = get_value_from(snap, 'MTU').wholeText
        result.append(arr)

    foreach_instance(ova_xml, 'network', get_networks_)
    return result

def get_vdis(ova_xml):
    """
    Parse the given ova.xml, and return a dictionary from VDI location to a
    triple of (parent, virtual_size, is_a_snapshot), for all VDIs in the XML.
    """
    result = {}

    def get_vdis_(snap):
        result[get_location(snap)] = \
            (get_parent(snap), get_virtual_size(snap),
             get_is_a_snapshot(snap))

    foreach_instance(ova_xml, 'VDI', get_vdis_)
    return result


def get_location(snap):
    return get_value_from(snap, 'location').wholeText


def get_parent(snap):
    struct = get_value_from(snap, 'sm_config')
    for member in struct.childNodes:
        if not is_member(member, 'vhd-parent'):
            continue
        return get_value(member).wholeText
    return None


def get_virtual_size(snap):
    return long(get_value_from(snap, 'virtual_size').wholeText)


def get_is_a_snapshot(snap):
    return get_bool(get_value_from(snap, 'is_a_snapshot'))


def get_bool(node):
    return node.childNodes[0].wholeText == "1"


def get_value_from(snap, mem):
    for member in snap.childNodes:
        if is_member(member, mem):
            val = get_value(member)
            return val
    log.warn("Failed to find %s", mem)
    raise InvalidOVAXML()


def has_member(node, k, v):
    if node.localName != 'struct':
        return False
    for member in node.childNodes:
        if is_member(member, k, v):
            return True
    return False


def is_member(node, k, v = None):
    if node.localName != 'member':
        return False
    cn = node.childNodes
    if len(cn) != 2:
        return False
    return (cn[0].localName == 'name' and
            cn[0].childNodes[0].wholeText == k and
            (v is None or
             (cn[1].localName == 'value' and
              cn[1].childNodes[0].wholeText == v)))


def get_value(member):
    """Get bar from <member><name>foo</name><value>bar</value>"""
    for n in member.childNodes:
        if n.localName == 'value':
            return n.childNodes[0]
    raise InvalidOVAXML()
