
import httplib
import logging
import unittest
import subprocess
import re

import http_test
import moreasserts
import testsetup
import transferclient

K = 1024
M = 1024*1024


def assertVdiEqualsUsingHttps(self, record, data):
    headers = {'Authorization': http_test.auth_header(record['username'], record['password'])}
    conn = httplib.HTTPSConnection(record['ip'], int(record['port']))
    try:
        conn.request('GET', record['url_path'], None, headers)
        resp = conn.getresponse()
        respdata = resp.read()

        self.assertEqual(resp.status, 200)
        self.assertEqual(len(data), len(respdata))
        self.assertEqual(data, respdata)
    finally:
        conn.close()


def https_put(exposerecord, data, range_start=None, vdi_size=None):
    connection = httplib.HTTPSConnection(exposerecord['ip'], int(exposerecord['port']))
    try:
        return http_test.http_put_request(connection, exposerecord, data, range_start, vdi_size)
    finally:
        connection.close()


def get_server_cert(hostname, port):
    # Uses OpenSSL command-line tool to get the server cert.
    # Python2.4 does not have support for this in the standard library.
    openssl = subprocess.Popen(['openssl', 's_client', '-showcerts', '-connect', '%s:%s' % (hostname, port)], stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
    output = openssl.communicate()
    match = re.search(r'-----BEGIN CERTIFICATE-----.*-----END CERTIFICATE-----', output[0], re.DOTALL)
    if match:
        return match.group(0)
    else:
        return None


class SSLTest(unittest.TestCase):

    def testGet(self):
        hostname, network, vdi = testsetup.setup_host_and_network(templates=1, vdi_mb=2)
        transferclient.expose(hostname, vdi_uuid=vdi, network_uuid=network, transfer_mode='http', use_ssl='true')
        record = transferclient.get_record(hostname, vdi_uuid=vdi)
        assertVdiEqualsUsingHttps(self, record, '\0'*(2*M))

    def testPut(self):
        hostname, network, vdi = testsetup.setup_host_and_network(templates=1, vdi_mb=16)
        transferclient.expose(hostname, vdi_uuid=vdi, network_uuid=network, transfer_mode='http', use_ssl='true')
        record = transferclient.get_record(hostname, vdi_uuid=vdi)

        data = 'a' * (1*M)
        putstatus, putheaders = https_put(record, data, 2*M, 16*M)
        self.assertEqual(putstatus, 200)

        expecteddata = ('\0' * (2*M)) + data + ('\0' * (13*M))
        assertVdiEqualsUsingHttps(self, record, expecteddata)

    def testSendMultiplePutRequestsInOneHttpsSession(self):
        hostname, network, vdi = testsetup.setup_host_and_network(templates=1, vdi_mb=16)
        transferclient.expose(hostname, vdi_uuid=vdi, network_uuid=network, transfer_mode='http', use_ssl='true')
        record = transferclient.get_record(hostname, vdi_uuid=vdi)

        conn = httplib.HTTPSConnection(record['ip'], int(record['port']))
        try:
            for i in xrange(1, 5):
                data = 'a' * (i * 100*K)
                status, headers = http_test.http_put_request(conn, record, data, i * M * 2 + 234*K, 16*M)
                self.assertEqual(status, 200)
        finally:
            conn.close()

    def testHttpServerSSLCertificateMatchesTheOneReturnedByGetRecord(self):
        hostname, network, vdi = testsetup.setup_host_and_network(templates=1, vdi_mb=16)
        transferclient.expose(hostname, vdi_uuid=vdi, network_uuid=network, transfer_mode='http', use_ssl='true')
        record = transferclient.get_record(hostname, vdi_uuid=vdi)
        self.assert_('ssl_cert' in record)
        servercert = get_server_cert(record['ip'], record['port'])
        #Translating '\n' for '|' because newlines won't pass through XenStore - '|' used instead
        translated_cert = servercert.replace("\n","|") + "|"
        self.assertEqual(translated_cert, record['ssl_cert'])

