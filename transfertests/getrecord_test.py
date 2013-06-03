
import base64
import httplib
import logging
import unittest

import testsetup
import transferclient
import moreasserts

def clean_up():
    hostname = testsetup.HOST
    testsetup.clean_host(hostname)

class GetRecordTest(unittest.TestCase):

    def assertRecordFields(self, record, fields):
        for field in fields:
            self.assert_(field in record.keys())
            self.assert_(len(str(record[field])) > 0)

    def assertStandardFields(self, record):
        self.assertRecordFields(
            record,
            ['vdi_uuid', 'status', 'transfer_mode', 'ip', 'port', 'use_ssl', 'username', 'password'])

    def assertVdiStatus(self, record, vdi_uuid, status):
        self.assertEqual(vdi_uuid, record['vdi_uuid'])
        self.assertEqual(status, record['status'])

    def testGetRecordRaisesArgumentErrorIfVdiUuidIsMissing(self):
        hostname, network, vdi = testsetup.setup_host_and_network(templates=1, vdi_mb=10)
        moreasserts.assertRaisesXenapiFailure(self, 'ArgumentError', transferclient.get_record, hostname)
        clean_up()

    def testGetRecordRaisesVDINotFoundIfThereIsNoSuchVDIOnTheHost(self):
        hostname, network, vdi = testsetup.setup_host_and_network(templates=1, vdi_mb=10)
        invalidvdi = vdi[:-6] + 'abcdef'
        moreasserts.assertRaisesXenapiFailure(self, 'VDINotFound', transferclient.get_record,
                                              hostname, vdi_uuid=invalidvdi)
        clean_up()

    def testGetRecordWithUnusedVDI(self):
        hostname, network, vdi = testsetup.setup_host_and_network(templates=1, vdi_mb=10)
        # No expose called.
        record = transferclient.get_record(hostname, vdi_uuid=vdi)
        self.assertRecordFields(record, ['status', 'vdi_uuid'])
        self.assertVdiStatus(record, vdi, 'unused')
        clean_up()

    def testGetRecordWithHTTPExposedVDI(self):
        hostname, network, vdi = testsetup.setup_host_and_network(templates=1, vdi_mb=10)
        transferclient.expose(hostname, vdi_uuid=vdi, network_uuid=network, transfer_mode='http')
        record = transferclient.get_record(hostname, vdi_uuid=vdi)
        self.assertStandardFields(record)
        self.assertVdiStatus(record, vdi, 'exposed')
        self.assertRecordFields(record, ['url_path', 'url_full'])
        self.assertEqual('http', record['transfer_mode'])
        self.assertEqual('80', record['port'])  # Standard HTTP port
        clean_up()

    def testGetRecordWithHTTPSExposedVDI(self):
        hostname, network, vdi = testsetup.setup_host_and_network(templates=1, vdi_mb=10)
        transferclient.expose(hostname, vdi_uuid=vdi, network_uuid=network, transfer_mode='http', use_ssl='true')
        record = transferclient.get_record(hostname, vdi_uuid=vdi)
        self.assertStandardFields(record)
        self.assertVdiStatus(record, vdi, 'exposed')
        self.assertRecordFields(record, ['url_path', 'url_full', 'ssl_cert'])
        self.assertEqual('http', record['transfer_mode'])
        self.assertEqual('443', record['port'])  # Standard HTTPS port
        clean_up()

    def testGetRecordWithBITSExposedVDI(self):
        hostname, network, vdi = testsetup.setup_host_and_network(templates=1, vdi_mb=10)
        transferclient.expose(hostname, vdi_uuid=vdi, network_uuid=network, transfer_mode='bits')
        record = transferclient.get_record(hostname, vdi_uuid=vdi)
        self.assertStandardFields(record)
        self.assertVdiStatus(record, vdi, 'exposed')
        self.assertRecordFields(record, ['url_path', 'url_full'])
        self.assertEqual('bits', record['transfer_mode'])
        self.assertEqual('80', record['port'])  # Standard HTTP port
        clean_up()

    def testGetRecordWithISCSIExposedVDI(self):
        hostname, network, vdi = testsetup.setup_host_and_network(templates=1, vdi_mb=10)
        transferclient.expose(hostname, vdi_uuid=vdi, network_uuid=network, transfer_mode='iscsi')
        record = transferclient.get_record(hostname, vdi_uuid=vdi)
        self.assertStandardFields(record)
        self.assertVdiStatus(record, vdi, 'exposed')
        self.assertRecordFields(record, ['iscsi_iqn', 'iscsi_lun', 'iscsi_sn'])
        self.assertEqual('iscsi', record['transfer_mode'])
        self.assertEqual('3260', record['port'])  # Standard iSCSI port
        clean_up()

    def testGetRecordWorksWhenMultipleVDIsAreExposed(self):
        hostname, network, vdi1 = testsetup.setup_host_and_network(templates=1, vdi_mb=10)
        vdi2 = transferclient.create_vdi(hostname, 'Second Test VDI', 12 * 1024 * 1024)
        vdi3 = transferclient.create_vdi(hostname, 'Third Test VDI', 14 * 1024 * 1024)
        vdi4 = transferclient.create_vdi(hostname, 'Fourth Test VDI', 16 * 1024 * 1024)
        transferclient.expose(hostname, vdi_uuid=vdi2, network_uuid=network, transfer_mode='http')
        transferclient.expose(hostname, vdi_uuid=vdi3, network_uuid=network, transfer_mode='http')
        record1 = transferclient.get_record(hostname, vdi_uuid=vdi1)
        record2 = transferclient.get_record(hostname, vdi_uuid=vdi2)
        record3 = transferclient.get_record(hostname, vdi_uuid=vdi3)
        record4 = transferclient.get_record(hostname, vdi_uuid=vdi4)
        self.assertVdiStatus(record1, vdi1, 'unused')
        self.assertVdiStatus(record2, vdi2, 'exposed')
        self.assertVdiStatus(record3, vdi3, 'exposed')
        self.assertVdiStatus(record4, vdi4, 'unused')
        clean_up()

    def testGetRecordWorksWhenReexposingVDIMultipleTimes(self):
        hostname, network, vdi = testsetup.setup_host_and_network(templates=1, vdi_mb=10)

        transferclient.expose(hostname, vdi_uuid=vdi, network_uuid=network, transfer_mode='http')
        retval = transferclient.unexpose(hostname, vdi_uuid=vdi)
        self.assertEquals(retval, 'OK', 'Unexpose failed, never got to get_record testing.')
        transferclient.expose(hostname, vdi_uuid=vdi, network_uuid=network, transfer_mode='http')

        record = transferclient.get_record(hostname, vdi_uuid=vdi)
        self.assertVdiStatus(record, vdi, 'exposed')
        clean_up()












