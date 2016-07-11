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

import logging
import logging.handlers
import re
import time
import xmlrpclib

import XenAPI


##### Logging setup

log = None
def configure_logging(name):
    global log
    log = logging.getLogger(name)
    log.setLevel(logging.DEBUG)
    sysh = logging.handlers.SysLogHandler('/dev/log')
    sysh.setLevel(logging.DEBUG)
    formatter = logging.Formatter('%s: %%(levelname)-8s %%(message)s' % name)
    sysh.setFormatter(formatter)
    log.addHandler(sysh)


##### Exceptions

class PluginError(Exception):
    """Base Exception class for all plugin errors."""
    def __init__(self, *args):
        Exception.__init__(self, *args)

class ArgumentError(PluginError):
    """Raised when required arguments are missing, argument values are invalid,
    or incompatible arguments are given.
    """
    def __init__(self, *args):
        PluginError.__init__(self, *args)

class InvalidIPError(PluginError):
    """Raised when an IP address supplied to the plugin is invalid"""
    def __init__(self, *args):
        PluginError.__init__(self, *args)

class InvalidIPAddressRange(PluginError):
    """Raised when an IP address range supplied to the plugin is shorter or longer than required."""
    def __init__(self, *args):
        PluginError.__init__(self, *args)

class TaskCancelled(PluginError):
    """Raised when a task is cancelled."""
    def __init__(self, *args):
        PluginError.__init__(self, *args)

def log_exceptions(func):
    def decorated(*args, **kwargs):
        try:
            return func(*args, **kwargs)
        except XenAPI.Failure, e:
            log.error('%s: XenAPI.Failure: %s', func.__name__, str(e))
            raise
        except PluginError, e:
            log.error('%s: %s: %s', func.__name__, e.__class__.__name__, str(e))
            raise
        except Exception, e:
            log.error('%s: %s: %s', func.__name__, e.__class__.__name__, str(e))
            raise
    return decorated


##### Helpers

def ignore_failure(func, *args, **kwargs):
    try:
        return func(*args, **kwargs)
    except XenAPI.Failure, e:
        log.error('Ignoring XenAPI.Failure %s', e)
        return None


def unwrap_plugin_exceptions(func, *args, **kwargs):
    try:
        return func(*args, **kwargs)
    except XenAPI.Failure, exn:
        log.debug("Got exception: %s", exn)
        if (len(exn.details) == 4 and
                exn.details[0] == 'XENAPI_PLUGIN_EXCEPTION' and
                exn.details[2] == 'Failure'):
            params = None
            try:
                params = eval(exn.details[3])
            except:
                raise exn
            raise XenAPI.Failure(params)
        else:
            raise
    except xmlrpclib.ProtocolError, exn:
        log.debug("Got exception: %s", exn)
        raise


def call_plugin(session, plugin, fn, args):
    host_ref = get_this_host(session)
    return unwrap_plugin_exceptions(
        session.xenapi.host.call_plugin,
        host_ref, plugin, fn, args)


##### Argument validation

ARGUMENT_PATTERN = re.compile(r'^[a-zA-Z0-9_:\.\-,]+$')
#Base64 allows the '=' symbol for padding - which is disallowed in shell-safe regex
#Extra symbols: '=', '/', '+'
ARGUMENT_PATTERN_BASE64 = re.compile(r'^[a-zA-Z0-9_:\.\-\=\/\+,]+$')
def validate_exists(args, key, default=None):
    """Validates that a string argument to a RPC method call is given, and
    matches the shell-safe regex, with an optional default value in case it
    does not exist.

    Returns the string.
    """
    if key in args:
        if len(args[key]) == 0:
            raise ArgumentError('Argument %r value %r is too short.' % (key, args[key]))
        if key == "vhd_blocks":
            if not ARGUMENT_PATTERN_BASE64.match(args[key]):
                raise ArgumentError('Argument %r value %r contains invalid characters for Base64.' % (key, args[key]))
        elif not ARGUMENT_PATTERN.match(args[key]):
            raise ArgumentError('Argument %r value %r contains invalid characters.' % (key, args[key]))
        if args[key][0] == '-':
            raise ArgumentError('Argument %r value %r starts with a hyphen.' % (key, args[key]))
        return args[key]
    elif default is not None:
        return default
    else:
        raise ArgumentError('Argument %s is required.' % key)

def validate_ip_(ip_address, max_digit):
    valid_ip = re.compile(r"\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}$")
    if not valid_ip.match(ip_address):
        raise InvalidIPError("The supplied IP address: %s is invalid" % ip_address)
    segment = re.compile(r"\d{1,3}")
    segments = segment.findall(ip_address)

    for x in segments:
        if int(x) > int(max_digit):
            raise InvalidIPError("The supplied IP address: %s is invalid" % ip_address)

def validate_ip(ip_address):
    validate_ip_(ip_address, 254)
    last_segment = re.compile(r"\d{1,3}$")
    first_segment = re.compile(r"^\d{1,3}")
    x = int(first_segment.search(ip_address).group(0))
    y = int(last_segment.search(ip_address).group(0))
    if x == 0 or y == 0:
        raise InvalidIPError("The supplied IP address: %s is invalid" % ip_address)

def validate_netmask(netmask):
    validate_ip_(netmask, 255)

def validate_ip_range(start, end, length_required):
    validate_ip(start)
    validate_ip(end)

    last_segment = re.compile(r"\d{1,3}$")
    x = int((last_segment.search(start)).group(0))
    y = int((last_segment.search(end)).group(0))

    if (y - x + 1) != length_required:
        raise InvalidIPAddressRange("The IP address range is of length %d, however a range of length %d is required" % ((y - x + 1), length_required))

def validate_in_list(args, key, values, default=None):
    """Validates that a string argument to a RPC method call is one of the listed values,
    with an optional default value in case it does not exist.

    Returns the string.
    """
    value = validate_exists(args, key, default).lower()
    if value not in values:
        raise ArgumentError('Argument %s may not take value %r. Valid values are %r.' % (key, value, values))
    else:
        return value

def validate_bool(args, key, default=None):
    """Validates that a string argument to a RPC method call is a boolean string,
    with an optional default value in case it does not exist.

    Returns the python boolean value.
    """
    value = validate_exists(args, key, default)
    if value.lower() == 'true':
        return True
    elif value.lower() == 'false':
        return False
    else:
        raise ArgumentError("Argument %s may not take value %r. Valid values are ['true', 'false']." % (key, value))

def validate_nonnegative_int(args, key, default=None):
    """Validates that a string argument to a RPC method call is a nonnegative integer,
    with an optional default value in case it does not exist.

    Returns the python integer.
    """
    value = validate_exists(args, key, default)
    try:
        intvalue = int(value)
        if intvalue < 0:
            raise ValueError('Must be nonnegative.')
        return intvalue
    except ValueError:
        raise ArgumentError("Argument %s may not take value %r. Valid values are strings containing nonnegative integers." % (key, value))


def exists(args, key):
    """Validates that a freeform string argument to a RPC method call is given.
    Returns the string.
    """
    if key in args:
        return args[key]
    else:
        raise ArgumentError('Argument %s is required.' % key)

def optional(args, key):
    """If the given key is in args, return the corresponding value, otherwise
    return None"""
    return key in args and args[key] or None


def wait_for_task_complete(session, task_ref):
    while True:
        status = session.xenapi.task.get_status(task_ref)
        if status in ['success', 'failure', 'cancelled']:
            return status
        time.sleep(1)


def wait_for_task_success(session, task_ref):
    status = wait_for_task_complete(session, task_ref)
    if status == 'success':
        return session.xenapi.task.get_result(task_ref)
    elif status == 'cancelled':
        log.debug('Task %s cancelled', task_ref)
        raise TaskCancelled()
    else:
        error_info = session.xenapi.task.get_error_info(task_ref)
        log.debug('Task %s failed: %s', task_ref, error_info)
        raise XenAPI.Failure(error_info)


def parse_xmlrpc_value(val):
    """Parse the given value as if it were an XML-RPC value.  This is
    sometimes used as the format for the task.result field."""
    x = xmlrpclib.loads(
        '<?xml version="1.0"?><methodResponse><params><param>' +
        val +
        '</param></params></methodResponse>')
    return x[0][0]


def get_this_host(session):
    return session.xenapi.session.get_this_host(session.handle)


def get_domain_0(session):
    host_ref = get_this_host(session)
    vm_ref = session.xenapi.host.get_control_domain(host_ref)
    return vm_ref


def get_local_pbd(session, sr_ref):
    """
    Returns the unique PBD ((ref, rec) pair) joining the given SR with the
    current host.
    Returns None if no such thing can be found.
    """
    this_host_ref = get_this_host(session)
    expr = \
        'field "host" = "%s" and field "SR" = "%s"' % (this_host_ref, sr_ref)
    pbds = session.xenapi.PBD.get_all_records_where(expr).items()
    if len(pbds) == 1:
        return pbds[0]
    else:
        return None


def create_vdi(session, sr_ref, name_label, virtual_size, read_only):
    vdi_ref = session.xenapi.VDI.create(
        {'name_label': name_label,
         'name_description': '',
         'SR': sr_ref,
         'virtual_size': str(virtual_size),
         'type': 'User',
         'sharable': False,
         'read_only': read_only,
         'xenstore_data': {},
         'other_config': {},
         'sm_config': {},
         'tags': []})
    log.debug('Created VDI %s (%s, %s, %s) on %s.', vdi_ref, name_label,
              virtual_size, read_only, sr_ref)
    return vdi_ref


def with_vdi_in_dom0(session, vdi, read_only, f):
    dom0 = get_domain_0(session)
    vbd_rec = {}
    vbd_rec['VM'] = dom0
    vbd_rec['VDI'] = vdi
    vbd_rec['userdevice'] = 'autodetect'
    vbd_rec['bootable'] = False
    vbd_rec['mode'] = read_only and 'RO' or 'RW'
    vbd_rec['type'] = 'disk'
    vbd_rec['unpluggable'] = True
    vbd_rec['empty'] = False
    vbd_rec['other_config'] = {}
    vbd_rec['qos_algorithm_type'] = ''
    vbd_rec['qos_algorithm_params'] = {}
    vbd_rec['qos_supported_algorithms'] = []
    log.debug('Creating VBD for VDI %s ... ', vdi)
    vbd = session.xenapi.VBD.create(vbd_rec)
    log.debug('Creating VBD for VDI %s done.', vdi)
    try:
        log.debug('Plugging VBD %s ... ', vbd)
        session.xenapi.VBD.plug(vbd)
        log.debug('Plugging VBD %s done.', vbd)
        return f(session.xenapi.VBD.get_device(vbd))
    finally:
        log.debug('Destroying VBD for VDI %s ... ', vdi)
        vbd_unplug_with_retry(session, vbd)
        ignore_failure(session.xenapi.VBD.destroy, vbd)
        log.debug('Destroying VBD for VDI %s done.', vdi)


def vbd_unplug_with_retry(session, vbd):
    """Call VBD.unplug on the given VBD, with a retry if we get
    DEVICE_DETACH_REJECTED.  For reasons which I don't understand, we're
    seeing the device still in use, even when all processes using the device
    should be dead."""
    while True:
        try:
            session.xenapi.VBD.unplug(vbd)
            log.debug('VBD.unplug successful first time.')
            return
        except XenAPI.Failure, e:
            if (len(e.details) > 0 and
                    e.details[0] == 'DEVICE_DETACH_REJECTED'):
                log.debug('VBD.unplug rejected: retrying...')
                time.sleep(1)
            elif (len(e.details) > 0 and
                  e.details[0] == 'DEVICE_ALREADY_DETACHED'):
                log.debug('VBD.unplug successful eventually.')
                return
            else:
                log.error('Ignoring XenAPI.Failure in VBD.unplug: %s', e)
                return


def get_vhd_parent(session, vdi_rec):
    """
    Returns the VHD parent of the given VDI record, as a (ref, rec) pair.
    Returns None if we're at the root of the tree.
    """
    if 'vhd-parent' in vdi_rec['sm_config']:
        parent_uuid = vdi_rec['sm_config']['vhd-parent']
        parent_ref = session.xenapi.VDI.get_by_uuid(parent_uuid)
        parent_rec = session.xenapi.VDI.get_record(parent_ref)
        log.debug("VHD %s has parent %s", vdi_rec['uuid'], parent_ref)
        return parent_ref, parent_rec
    else:
        return None

def get_sr_master(session, sr_ref):
    """
    Returns the SR master for a given SR reference. If there is only one pbd then
    the SR is Local Storage, otherwise the SR is shared storage - and in which case
    the SR master is the pool master.
    """
    pbds = session.xenapi.SR.get_PBDs(sr_ref)

    if len(pbds) == 1:
        log.debug("SR is Local Storage - Getting Master")
        host = session.xenapi.PBD.get_host(pbds[0])
        log.debug("SR Master is %s", host)
        return host
    else:
        log.debug("SR is shared storage - getting pool master")
        pools = session.xenapi.pool.get_all()
        assert len(pools) == 1
        pool_master = session.xenapi.pool.get_master(pools[0])
        log.debug("SR Master is %s", pool_master)
        return pool_master

def get_sr_ref(session, vdi_uuid):
    """
    Returns the reference to the SR that the given VDI_UUID lives on.
    """
    vdi_ref = session.xenapi.VDI.get_by_uuid(vdi_uuid)
    sr = session.xenapi.VDI.get_SR(vdi_ref)
    return sr

def write_sr_config(session, vdi_uuid):
    remove_sr_config(session, vdi_uuid) #Removing config for VDI if it wasn't removed properly
    log.debug("Writing SR Config..%s", vdi_uuid)
    key = "tvm_%s" % (vdi_uuid)
    sr = get_sr_ref(session, vdi_uuid)
    log.debug("Adding key value pair %s=%s for SR %s", key, vdi_uuid, sr)
    session.xenapi.SR.add_to_other_config(sr, key, 'true')
    host_sr_master = get_sr_master(session, sr)
    args = {}
    args['sr_uuid'] = session.xenapi.SR.get_uuid(sr)
    session.xenapi.host.call_plugin(host_sr_master, 'transfer', 'abort_sr_ops', args)

def remove_sr_config(session, vdi_uuid):
    """For a given vdi_uuid, this function checks if there exists an other-config
       key on the disks SR. If there is, then it removes it to allow GC and other
       storage scripts to run when started.
    """
    sr = get_sr_ref(session, vdi_uuid)
    key = "tvm_%s" % (vdi_uuid)
    other_config = session.xenapi.SR.get_other_config(sr)
    for pair in other_config:
        if pair.startswith(key):
            session.xenapi.SR.remove_from_other_config(sr, pair)
