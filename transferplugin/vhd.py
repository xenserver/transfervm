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

import os.path
import subprocess

from pluginlib import *


VHD_UTIL = '/usr/bin/vhd-util'
SR_MOUNT = '/var/run/sr-mount'
SR_MOUNT_VDI_PATTERN = SR_MOUNT + '/%s/%s.vhd'
LOCAL_VDI_PATTERN = '/dev/VG_XenStorage-%s/VHD-%s'


# VHD SRs that are mounted at /var/run/sr-mount.
VHD_STYLE_SR_MOUNT = 1
# VHD SRs that are LVM volumes that show up as local devices.
VHD_STYLE_LOCAL_DEV = 2
# File SRs, with VHDs in a local directory.
VHD_STYLE_LOCAL_DIR = 3
# SRs which don't use VHDs at all.
VHD_STYLE_NOT_VHD = 4


def get_sr_style(session, sr_ref):
    typ = session.xenapi.SR.get_type(sr_ref)
    if (typ == 'nfs' or
            typ == 'ext'):
        return VHD_STYLE_SR_MOUNT
    elif (typ == 'lvm' or
          typ == 'lvmohba' or
          typ == 'lvmoiscsi'):
        return VHD_STYLE_LOCAL_DEV
    elif typ == 'file':
        return VHD_STYLE_LOCAL_DIR
    else:
        # netapp equal cslg hba iscsi iso udev dummy
        return VHD_STYLE_NOT_VHD


def with_vhd_files(session, sr_style, leaf_vdi_ref, leaf_vdi_rec, read_only,
                   f):
    """
    """
    if sr_style == VHD_STYLE_SR_MOUNT:
        with_vhd_files_mounted(SR_MOUNT_VDI_PATTERN, session,
                               leaf_vdi_ref, leaf_vdi_rec, f)
    elif sr_style == VHD_STYLE_LOCAL_DEV:
        with_vdi_in_dom0(
            session, leaf_vdi_ref, read_only,
            lambda _: with_vhd_files_mounted(LOCAL_VDI_PATTERN, session,
                                             leaf_vdi_ref, leaf_vdi_rec, f))
    elif sr_style == VHD_STYLE_LOCAL_DIR:
        with_vhd_files_local(session, leaf_vdi_ref, leaf_vdi_rec, f)
    else:
        with_vhd_files_no_file(session, leaf_vdi_ref, leaf_vdi_rec, f)


def with_vhd_files_mounted(path_pattern, session, leaf_vdi_ref, leaf_vdi_rec,
                           f):
    sr_uuid = session.xenapi.SR.get_uuid(leaf_vdi_rec['SR'])
    f(make_vhd_path_map(session, leaf_vdi_ref, leaf_vdi_rec,
                        lambda vdi_rec: \
                        make_vhd_path_mounted(path_pattern, sr_uuid,
                                              vdi_rec)))


def with_vhd_files_local(session, leaf_vdi_ref, leaf_vdi_rec, f):
    f(make_vhd_path_map(session, leaf_vdi_ref, leaf_vdi_rec,
                        lambda vdi_rec: \
                        make_vhd_path_local(session, vdi_rec)))


def with_vhd_files_no_file(session, leaf_vdi_ref, leaf_vdi_rec, f):
    f(make_vhd_path_map(session, leaf_vdi_ref, leaf_vdi_rec,
                        lambda _: None))


def make_vhd_path_map(session, leaf_vdi_ref, leaf_vdi_rec, f):
    result = {}
    make_vhd_path_map_(session, leaf_vdi_ref, leaf_vdi_rec, f, result)
    return result


def make_vhd_path_map_(session, vdi_ref, vdi_rec, f, result):
    result[vdi_ref] = (vdi_rec, f(vdi_rec))

    parent = get_vhd_parent(session, vdi_rec)
    if parent is not None and parent[0] not in result:
        make_vhd_path_map_(session, parent[0], parent[1], f, result)


def make_vhd_path_mounted(path_pattern, sr_uuid, vdi_rec):
    return path_pattern % (sr_uuid, vdi_rec['uuid'])


def make_vhd_path_local(session, vdi_rec):
    vdi_uuid = vdi_rec['uuid']
    pbd = get_local_pbd(session, vdi_rec['SR'])
    if not pbd or 'location' not in pbd[1]['device_config']:
        return None
    else:
        return os.path.join(pbd[1]['device_config']['location'],
                            '%s.vhd' % vdi_uuid)


def set_vhd_parent(path, parent):
    process = subprocess.Popen([VHD_UTIL, 'modify', '-p', parent, '-n', path],
                               stdout=subprocess.PIPE,
                               close_fds=True,
                               cwd='/',
                               env={})
    _, _ = process.communicate()
    if process.returncode == 0:
        log.debug('Set parent for %s to %s', path, parent)
    else:
        raise Exception('Failed to set parent for %s to %s', path, parent)
