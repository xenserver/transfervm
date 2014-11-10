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

import array
import base64
import os.path
import subprocess
from xml.dom import minidom
import zlib

from pluginlib import *
from vhd import *
from copy import deepcopy

##### Code

def get_merged_bitmap(session, leaf_vdi_ref):
    """
    Returns the result of ORing all the bitmaps between
    the leaf VHD and the base VHD. This results is exposing
    the sparse version of a raw disk, and for a VHD tree removes
    the need for downloading all of the vhd chain.
    """

    leaf_vdi_uuid = session.xenapi.VDI.get_uuid(leaf_vdi_ref)
    write_sr_config(session, leaf_vdi_uuid)

    try:
        result = {}
        vdi_rec = session.xenapi.VDI.get_record(leaf_vdi_ref)
        sr_style = get_sr_style(session, vdi_rec['SR'])
        with_vhd_files(session, sr_style, leaf_vdi_ref, vdi_rec, True,
                       lambda paths: build_bitmap_map(paths, result))

        final_bitmap = None
        for _, (vdi_uuid, bitmap) in result.iteritems():
            log.debug("get_merged_bitmap vdi_uuid=%s bitmap=%s", vdi_uuid, bitmap)
            if not final_bitmap:
                final_bitmap = bitmap
            else:
                final_bitmap = or_bitmap(final_bitmap, bitmap)
    finally:
        remove_sr_config(session, leaf_vdi_uuid)

    return encode_bitmap(final_bitmap)

def get_all_bitmaps(session, leaf_vdi_refs):
    """
    Returns a dictionary of (VDI ref -> (VDI UUID, raw bitmap) for each
    VDI in a chain between one of the provided leaf_vdi_refs and a root VDI.
    """
    ####### Mark the SR and cancel current storage cleanup ops #######
    vdi_refs = list(leaf_vdi_refs) #convert dict-iterator to list

    for vdi_ref in vdi_refs:
        vdi_uuid = session.xenapi.VDI.get_uuid(vdi_ref)
        write_sr_config(session, vdi_uuid)

    try:
        result = {}
        for vdi_ref in vdi_refs:
            vdi_rec = session.xenapi.VDI.get_record(vdi_ref)
            sr_style = get_sr_style(session, vdi_rec['SR'])
            with_vhd_files(session, sr_style, vdi_ref, vdi_rec, True,
                           lambda paths: build_bitmap_map(paths, result))
    finally:
        for vdi_ref in vdi_refs:
            vdi_uuid = session.xenapi.VDI.get_uuid(vdi_ref)
            remove_sr_config(session, vdi_uuid)

    return result

def build_bitmap_map(paths, result):
    for vdi_ref, (vdi_rec, path) in paths.iteritems():
        vdi_uuid = vdi_rec['uuid']
        if path is None:
            log.warn(
                'Returning full bitmap for VDI %s; we cannot see the file',
                vdi_uuid)
            bitmap = full_bitmap(vdi_rec)
        else:
            bitmap = read_bitmap(vdi_rec, path)
        result[vdi_ref] = (vdi_uuid, bitmap)


def read_bitmap(vdi_rec, path):
    process = subprocess.Popen([VHD_UTIL, 'read', '-B', '-n', path],
                               stdout=subprocess.PIPE,
                               close_fds=True,
                               cwd='/',
                               env={})
    stdout, _ = process.communicate()
    if process.returncode == 0:
        log.debug('Read bitmap for VDI %s', vdi_rec['uuid'])
        return stdout
    else:
        log.warn(
            'Cannot read bitmap for VDI %s from %s: returning full bitmap',
            vdi_rec['uuid'], path)
        return full_bitmap(vdi_rec)


def full_bitmap(vdi_rec):
    bitmap_size = \
        long(vdi_rec['virtual_size']) / (8 * 2 * 1024 * 1024) # 2 MB per bit
    return '\xff' * bitmap_size


def compute_block_map(forest, leaf_vdis, vdi_ref):
    """
    Compute which leaf_vdis will allow us to read the contents of vdi_ref,
    and for each, which bitmap should be read from each leaf.
    Returns a dictionary of (leaf_vdi_ref -> encoded_bitmap).
    """
    log.debug('Computing block map for %s...', vdi_ref)
    bitmap = forest.decoded_bitmap(vdi_ref)
    #log.debug("Bitmap = " + bitmap)
    result = {}
    for leaf_vdi_ref in leaf_vdis.keys():
        shadow_bitmap = get_shadow_bitmap(forest, vdi_ref, leaf_vdi_ref, "")
        if shadow_bitmap is None:
            log.debug('No route from %s to %s', leaf_vdi_ref, vdi_ref)
            continue

        #log.debug("Shadow Bitmap = " + shadow_bitmap)
        # visible_bits tells us which blocks in bitmap we can read through
        # leaf_vdi_ref.
        visible_bits = hide_bits(bitmap, shadow_bitmap)
        #log.debug("Visible bits = " + visible_bits)
        if count_bits(visible_bits) > 0:
            log.debug('Leaf VDI %s(%s) lets us see %d of %d.  Shadow is %d',
                      leaf_vdi_ref, leaf_vdis[leaf_vdi_ref]['uuid'],
                      count_bits(visible_bits),
                      count_bits(bitmap),
                      count_bits(shadow_bitmap))
            result[leaf_vdi_ref] = encode_bitmap(visible_bits)
            bitmap = hide_bits(bitmap, visible_bits)
        else:
            log.debug("Leaf VDI %s(%s) doesn't let us see anything useful",
                      leaf_vdi_ref, leaf_vdis[leaf_vdi_ref]['uuid'])
    log.debug('%d of %s is completely shadowed.', count_bits(bitmap), vdi_ref)
    log.debug('Computing block map for %s done.', vdi_ref)
    return result


def get_shadow_bitmap(forest, target_vdi_ref, this_vdi_ref, bitmap_above):
    if this_vdi_ref == target_vdi_ref:
        return bitmap_above
    this_bitmap = forest.decoded_bitmap(this_vdi_ref)
    parent = forest.parent(this_vdi_ref)
    if parent is None:
        return None
    else:
        return get_shadow_bitmap(forest, target_vdi_ref, parent,
                                 or_bitmap(bitmap_above, this_bitmap))


def hide_bits(bitmap, shadow_bitmap):
    """
    Return bitmap & ~shadow_bitmap.
    """
    bitmap, shadow_bitmap, bitmap_len = expand_bitmaps(bitmap, shadow_bitmap)
    result = array.array('c', '\0' * bitmap_len)
    for i in xrange(bitmap_len):
        result[i] = chr(ord(bitmap[i]) & ~ord(shadow_bitmap[i]))
        #log.debug("%d bitmap = %d shadow_bitmap = %d Or = %d" % (i, ord(bitmap[i]), ~ord(shadow_bitmap[i]), (ord(bitmap[i]) & ~ord(shadow_bitmap[i]))))
    return result.tostring()


def or_bitmap(b1, b2):
    b1, b2, bitmap_len = expand_bitmaps(b1, b2)
    result = array.array('c', '\0' * bitmap_len)
    for i in xrange(bitmap_len):
        result[i] = chr(ord(b1[i]) | ord(b2[i]))
    return result.tostring()


def expand_bitmaps(b1, b2):
    len1 = len(b1)
    len2 = len(b2)
    if len1 > len2:
        b2 += '\0' * (len1 - len2)
    elif len2 > len1:
        b1 += '\0' * (len2 - len1)
        len1 = len2
    return b1, b2, len1


def decode_bitmap(bitmap):
    log.debug("Decoding %s ", bitmap)
    return zlib.decompress(base64.b64decode(bitmap))


def encode_bitmap(bitmap):
    return base64.b64encode(zlib.compress(bitmap))


def num_bits(val):
    count = 0
    while val:
        count += val & 1
        val = val >> 1
    return count


def count_bits(bitmap):
    count = 0
    for i in xrange(len(bitmap)):
        count += num_bits(ord(bitmap[i]))
    return count


def make_bitmap_xml(bitmap_map):
    impl = minidom.getDOMImplementation()
    doc = impl.createDocument(None, 'bitmaps', None)
    try:
        doc_el = doc.documentElement
        log.debug('%s', bitmap_map.items())
        for _, (vdi_uuid, bitmap) in bitmap_map.iteritems():
            doc_el.appendChild(make_bitmap_el(doc, vdi_uuid, bitmap))
        return doc.toxml()
    finally:
        doc.unlink()

def make_bitmap_el(doc, vdi_uuid, bitmap):
    result = doc.createElement('bitmap')
    result.setAttribute('vdi_uuid', vdi_uuid)
    text = doc.createTextNode(base64.b64encode(zlib.compress(bitmap)))
    result.appendChild(text)
    return result
