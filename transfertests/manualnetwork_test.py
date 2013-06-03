
import httplib
import logging
import unittest
import urllib2

import testsetup
import transferclient
import moreasserts

M = 1024 * 1024

def assertVdiZero(self, ip, port, record, vdi_mb):
    # Make a new record with the IP and port fields updated
    r = dict(record, ip=ip, port=port)
    moreasserts.assertVdiIsZeroUsingHttpGet(self, r, vdi_mb)


class StaticIpTest(unittest.TestCase):
    ip = '10.80.237.211'  # Hopefully this is free at the moment!
    mask = '255.255.240.0'
    gw = '10.80.224.1'

    def testConfiguration(self):
        hostname, network, vdi = testsetup.setup_host_and_network(templates=1, vdi_mb=10, dangerous_test=True)
        transferclient.expose(hostname, vdi_uuid=vdi, network_uuid=network, transfer_mode='http', network_mode='manual', network_ip=self.ip, network_mask=self.mask, network_gateway=self.gw)
        record = transferclient.get_record(hostname, vdi_uuid=vdi)
        self.assertEquals(self.ip, record['ip'])

    def testConnection(self):
        hostname, network, vdi = testsetup.setup_host_and_network(templates=1, vdi_mb=10, dangerous_test=True)
        transferclient.expose(hostname, vdi_uuid=vdi, network_uuid=network, transfer_mode='http', network_mode='manual', network_ip=self.ip, network_mask=self.mask, network_gateway=self.gw)
        record = transferclient.get_record(hostname, vdi_uuid=vdi)
        # Test GET to the ip
        assertVdiZero(self, self.ip, record['port'], record, 10)


class CustomPortTest(unittest.TestCase):
    def testGetOnPort123(self):
        hostname, network, vdi = testsetup.setup_host_and_network(templates=1, vdi_mb=10)
        transferclient.expose(hostname, vdi_uuid=vdi, network_uuid=network, transfer_mode='http', network_port='123')
        record = transferclient.get_record(hostname, vdi_uuid=vdi)
        assertVdiZero(self, record['ip'], '123', record, 10)
