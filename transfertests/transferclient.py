#!/usr/bin/python

import time, logging, os
import subprocess
from xml.dom import minidom

import XenAPI

USERNAME='root'
PASSWORD='xenroot'


def xenapi_session(func):
    """A decorator for functions using XenAPI sessions.

    Passes the authenticated session as the first and the host reference as the second argument,
    followed by the original arguments except the hostname.
    Example:
    call expose(hostname, vdi_uuid=....)
    expose method gets called as expose(session, host, vdi_uuid=....).
    """
    def decorated(hostname, *args, **kwargs):
        session = XenAPI.Session('https://' + hostname)
        session.xenapi.login_with_password(USERNAME, PASSWORD)
        try:
            # Assuming the first host in the set is the currently connected host.
            # TODO: Does this work on XenServer pools??
            host = session.xenapi.host.get_all()[0]
            return func(session, host, *args, **kwargs)
        finally:
            session.xenapi.session.logout()
    return decorated


@xenapi_session
def network_by_name(session, host, name):
    for net in session.xenapi.network.get_all():
        record = session.xenapi.network.get_record(net)
        if name in record['name_label']:
            return record['uuid']
    return None

@xenapi_session
def vdi_by_name(session, host, name):
    for vdi in session.xenapi.VDI.get_all():
        record = session.xenapi.VDI.get_record(vdi)
        if name in record['name_label']:
            return record['uuid']
    return None

@xenapi_session
def create_vdi(session, host, name_label, size, sm_config = {}):
    """Creates a VDI on the host's default SR.
    """
    pools = session.xenapi.pool.get_all_records()
    assert len(pools) == 1, '0 or more than 1 pools found, strange.'
    sr = pools.values()[0]['default_SR']

    vdi = session.xenapi.VDI.create({'name_label': name_label,
                                     'name_description': 'Test useful VDI',
                                     'SR': sr,
                                     'virtual_size': str(size),
                                     'type': 'user',
                                     'sharable': False,
                                     'read_only': False,
                                     'other_config': {'test_vdi': 'true'},
                                     'xenstore_data': {},
                                     'sm_config': sm_config,
                                     'tags': []})
    return session.xenapi.VDI.get_uuid(vdi)

@xenapi_session
def remove_vdi(session, host, vdi_uuid):
    """Destroys the specified VDI"""
    vdi_ref = session.xenapi.VDI.get_by_uuid(vdi_uuid)
    return session.xenapi.VDI.destroy(vdi_ref)


@xenapi_session
def call_method(session, host, method, args):
    return session.xenapi.host.call_plugin(host, 'transfer', method, args)

@xenapi_session
def call_method_and_expect_OK(session, host, method, args):
    ret = session.xenapi.host.call_plugin(host, 'transfer', method, args)
    if ret == 'OK':
        return ret
    else:
        raise RuntimeError('Unexpected %s response %r' % (method, ret))

def expose(hostname, **args):
    return call_method(hostname, 'expose', args)

def unexpose(hostname, **args):
    return call_method_and_expect_OK(hostname, 'unexpose', args)

@xenapi_session
def get_record(session, host, **args):
    strrecord = session.xenapi.host.call_plugin(host, 'transfer', 'get_record', args)
    logging.debug('Got record %r' % strrecord)
    return record_to_dict(strrecord)

def record_to_dict(xml):
    result = {}
    doc = minidom.parseString(xml)
    try:
        el = doc.getElementsByTagName('transfer_record')[0]
        # Note that we have to convert this dictionary to non-unicode
        # strings, because we're being casual elsewhere.  That's why we're
        # not just returning dict(el.attributes.items()).
        for k, v in el.attributes.items():
            result[str(k)] = str(v)
    finally:
        doc.unlink()
    return result


def cleanup(hostname):
    return call_method_and_expect_OK(hostname, 'cleanup', {})

def expose_vdi_on_defaulthttp(hostname, vdi_uuid):
    return expose(hostname, {'transfer_mode': 'http',
                             'vdi_uuid': vdi_uuid,
                             'network_uuid': network_by_name(hostname, '0')})

def get_vdi_bitmap(hostname, vdi_uuid):
    args = {'leaf_vdi_uuids': vdi_uuid}
    bitmap_xml = call_method(hostname, 'get_bitmaps', args)
    xmldoc = minidom.parseString(bitmap_xml)
    bitmaps = xmldoc.getElementsByTagName('bitmap')
    for node in bitmaps:
	if node.attributes['vdi_uuid'].value == vdi_uuid:
		return node.firstChild.data
    return bitmaps
