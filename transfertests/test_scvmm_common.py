import sys
from xml.dom import minidom
import xmlrpclib

import XenAPI

sys.path.append("/etc/xapi.d/plugins")
from pluginlib import *
configure_logging('test_scvmm')
from pluginlib import log


def get_expose_record(session, record_handle):
    return record_to_dict(call_plugin(session, 'transfer', 'get_record',
                                      { 'record_handle': record_handle }))


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
        call_plugin(session, 'transfer', 'unexpose',
                    { 'record_handle': record_handle })
    except Exception, exn:
        pass
