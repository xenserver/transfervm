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

import pluginlib
from pluginlib import *
import vhd_bitmaps


class Forest(object):
    """
    A forest of VHD files.  Create one using Forest.build(session, leaf_vdis).
    """
    
    def __init__(self, all_vdis, child_map, parent_map, bitmap_map, roots):
        self._all_vdis = all_vdis
        self._child_map = child_map
        self._parent_map = parent_map
        self._bitmap_map = bitmap_map
        self._roots = roots

    def all_vdis(self):
        return self._all_vdis

    def vdi_record(self, vdi_ref):
        """Returns the VDI record corresponding to the given reference."""
        return self._all_vdis[vdi_ref]
        
    def parent(self, vdi_ref):
        """Returns a VDI reference giving the parent of the given vdi_ref,
        or None if vdi_ref is a root."""
        return self._parent_map[vdi_ref]

    def children(self, vdi_ref):
        """Returns a VDI reference list giving the children of the given
        vdi_ref.  May be an empty list, if vdi_ref is a leaf."""
        return self._child_map[vdi_ref]

    def encoded_bitmap(self, vdi_ref):
        """Returns a string containing the compressed, base64-encoded
        bitmap for the given vdi_ref."""
        return vhd_bitmaps.encode_bitmap(self.decoded_bitmap(vdi_ref))

    def decoded_bitmap(self, vdi_ref):
        """Returns a string containing the decompressed, decoded
        bitmap for the given vdi_ref."""
        return self._bitmap_map[vdi_ref][1]

    def roots(self):
        return self._roots


    def build(session, leaf_vdis, include_bitmaps = True):
        srs = set([session.xenapi.VDI.get_SR(vdi_ref) for
                   vdi_ref in leaf_vdis.iterkeys()])
        for sr in srs:
            session.xenapi.SR.scan(sr)
        
        parent_map, roots, all_vdis = \
            Forest.build_parent_map(session, leaf_vdis)
        child_map = {}
        for child_ref, parent_ref in parent_map.iteritems():
            if child_ref not in child_map:
                child_map[child_ref] = []
            if parent_ref is not None and parent_ref not in child_map:
                child_map[parent_ref] = []
            if parent_ref is None:
                continue
            child_map[parent_ref].append(child_ref)
        bitmap_map = \
            include_bitmaps and \
            vhd_bitmaps.get_all_bitmaps(session, leaf_vdis.iterkeys()) or \
            {}
        for node in child_map.iteritems():
            log.debug('%s%s has children %s',
                      node[0] in roots and '*' or '',
                      node[0], node[1])
        return Forest(all_vdis, child_map, parent_map, bitmap_map, roots)
    build = staticmethod(build)


    def build_parent_map(session, leaf_vdis):
        result = {}
        roots = []
        all_vdis = {}
        pending = leaf_vdis.items()
        while True:
            if not pending:
                return result, roots, all_vdis
            vdi_ref, vdi_rec = vdi = pending[0]
            pending.remove(vdi)
            if vdi_ref in all_vdis:
                continue
            all_vdis[vdi_ref] = vdi_rec
            parent = get_vhd_parent(session, vdi_rec)
            if parent is None:
                log.debug("VHD %s has no parent", vdi_ref)
                roots.append(vdi_ref)
                result[vdi_ref] = None
            else:
                result[vdi_ref] = parent[0]
                pending.append(parent)
    build_parent_map = staticmethod(build_parent_map)
