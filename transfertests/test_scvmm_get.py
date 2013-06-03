#!/usr/bin/env python

import os
import os.path
import sys
import time
import urlparse

import XenAPI

import bits
from test_scvmm_common import *


remote_url = sys.argv[1]
remote_username = sys.argv[2] 
remote_password = sys.argv[3]
remote_vm_uuid = sys.argv[4]
extra_args = list(sys.argv)
del extra_args[0:5]
extra_args = dict([a.split('=') for a in extra_args])

(protocol, remote_netloc, _, _, _, _) = urlparse.urlparse(remote_url)

remote_session = XenAPI.Session(remote_url)
remote_session.login_with_password(remote_username, remote_password)

total_download_size = 0
total_download_time = 0


def get_metadata():
    url_path = export_url_path(remote_session, remote_vm_uuid)

    dest = 'metadata-%s.raw' % remote_vm_uuid
    print ("*** SCVMM must download from %s://%s%s into %s" %
           (protocol, remote_netloc, url_path, dest))

    if protocol == 'https':
        remote_host_ref = get_this_host(remote_session)
        ssl_cert = \
            remote_session.xenapi.host.get_server_certificate(remote_host_ref)
        print "*** SSL cert is %s" % ssl_cert

    bits.download(protocol, remote_netloc, url_path, dest)
    print 'Got metadata file %s' % dest


def export_url_path(session, vm_uuid):
    vm_ref = session.xenapi.VM.get_by_uuid(vm_uuid)
    return ('/export_metadata?session_id=%s&ref=%s&include_vhd_parents=true' %
            (session.handle, vm_ref))


def get_disks():
    global total_download_time
    global total_download_size
    
    record_handles = expose_forest(remote_session, extra_args,
                                   [remote_vm_uuid] + all_snapshots())
    try:
        for record_handle in record_handles:
            record = get_expose_record(remote_session, record_handle)
            print "*** SSL cert is %s" % record['ssl_cert'].replace('|', '\n')
            vdi_uuids = record['vdi_uuid'].split(',')
            if 'non_leaf_vdi_uuids' in record:
                vdi_uuids.extend(record['non_leaf_vdi_uuids'].split(','))
            for vdi_uuid in vdi_uuids:
                url_full = '%s.vhd' % record['url_full_%s' % vdi_uuid]
                url_path = '%s.vhd' % record['url_path_%s' % vdi_uuid]
                dest = '%s.vhd' % vdi_uuid
                print ("*** SCVMM must download from %s into %s" %
                       (url_full, dest))
                if not os.access(dest, os.F_OK):
                    start = time.time()
                    bits.download(
                        record['use_ssl'] == 'true' and 'https' or 'http',
                        '%s:%s' % (record['ip'], record['port']),
                        url_path,
                        dest,
                        record['username'],
                        record['password'])
                    end = time.time()
                    size = os.stat(dest).st_size
                    print ("Downloaded %d MB in %d secs = %d Mbit/s" %
                           (int(size) >> 20, int(end - start),
                            int(size / (end - start)) >> 17))
                    total_download_time += (end - start)
                    total_download_size += size
    finally:
        for record_handle in record_handles:
            unexpose(remote_session, record_handle)


def all_snapshots():
    r = remote_session.xenapi.VM.get_by_uuid(remote_vm_uuid)
    return [remote_session.xenapi.VM.get_uuid(x)
            for x in remote_session.xenapi.VM.get_snapshots(r)]


def expose_forest(session, extra_args, vm_uuids):
    args = dict(extra_args)
    args['vm_uuids'] = ','.join(vm_uuids)
    args['network_uuid'] = 'management'
    args['read_only'] = 'true'
    args['use_ssl'] = protocol == 'https' and 'true' or 'false'

    start = time.time()
    result = call_plugin(remote_session, 'transfer', 'expose_forest',
                         args).split(',')
    end = time.time()
    print "Exposing forest took %d seconds." % int(end - start)
    return result


get_metadata()
get_disks()

print ("Total download: %d MB in %d secs = %d Mbit/s" %
       (int(total_download_size) >> 20, int(total_download_time),
        int(total_download_size / total_download_time) >> 17))
