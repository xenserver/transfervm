
import logging
import unittest

import moreasserts
import testsetup
import transferclient
import XenAPI



@transferclient.xenapi_session
def vbd_uuids_and_attached_flags_by_vdi_uuid(session, host, vdi_uuid):
    vdi = session.xenapi.VDI.get_by_uuid(vdi_uuid)
    vbds = session.xenapi.VDI.get_VBDs(vdi)
    records = [session.xenapi.VBD.get_record(vbd) for vbd in vbds]
    return [(r['uuid'], r['currently_attached']) for r in records]


class UnexposeTest(unittest.TestCase):

    def testThereAreNoPluggedInVbdsAfterUnexpose(self):
        hostname, network, vdi = testsetup.setup_host_and_network(templates=1, vdi_mb=10)
        transferclient.expose(hostname, vdi_uuid=vdi, network_uuid=network, transfer_mode='http')
        transferclient.unexpose(hostname, vdi_uuid=vdi)
        vbds = vbd_uuids_and_attached_flags_by_vdi_uuid(hostname, vdi)
        for vbd, attached in vbds:
            self.assertFalse(attached, 'VBD %s is still attached' % vbd)
        if vbds:
            logging.info('testThereAreNoPluggedInVbdsAfterUnexpose passed because all %d VBDs are unattached.' % len(vbds))
        else:
            logging.info('testThereAreNoPluggedInVbdsAfterUnexpose passed because there are no VBDs.')

    def testVdiRecordStatusIsUnusedAfterUnexpose(self):
        hostname, network, vdi = testsetup.setup_host_and_network(templates=1, vdi_mb=10)
        transferclient.expose(hostname, vdi_uuid=vdi, network_uuid=network, transfer_mode='http')
        transferclient.unexpose(hostname, vdi_uuid=vdi)
        record = transferclient.get_record(hostname, vdi_uuid=vdi)
        self.assertEqual(record['status'], 'unused')

    def testUnexposeOfUnknownVDIFailsWithVDINotFound(self):
        hostname, network, vdi = testsetup.setup_host_and_network(templates=1, vdi_mb=10)
        invalid_vdi = vdi[:-6] + 'abcdef'
        moreasserts.assertRaisesXenapiFailure(self, 'VDINotFound', transferclient.unexpose, hostname, vdi_uuid=invalid_vdi)

    def testUnexposeOfUnmountedVDIFailsWithVDINotInUse(self):
        hostname, network, vdi = testsetup.setup_host_and_network(templates=1, vdi_mb=10)
        moreasserts.assertRaisesXenapiFailure(self, 'VDINotInUse', transferclient.unexpose, hostname, vdi_uuid=vdi)
