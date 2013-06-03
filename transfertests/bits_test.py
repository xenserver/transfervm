#!/usr/bin/python

import base64
import httplib
import logging
import socket
import unittest
import urllib2
import random

import http_test
import moreasserts
import testsetup
import transferclient
import XenAPI
import vhd


K = 1024
M = 1024*1024
VDI_MB = 16

BITS_CONTEXT_SERVER = '0x7'
BITS_E_INVALIDARG = '0x80070057'
BITS_BG_E_TOO_LARGE = '0x80200020'
BITS_PROTOCOL = '{7df0354d-249b-430f-820D-3D2A9BEF4931}'

def clean_up():
    hostname = testsetup.HOST
    testsetup.clean_host(hostname)

def setup_and_get_record(vdi_mb=VDI_MB, vdi_raw=False):
    hostname, network, vdi = testsetup.setup_host_and_network(templates=1, vdi_mb=vdi_mb, vdi_raw=vdi_raw)
    transferclient.expose(hostname, vdi_uuid=vdi, network_uuid=network, transfer_mode='bits')
    return transferclient.get_record(hostname, vdi_uuid=vdi)

def assertHeaderIfValueSet(self, headers, name, value):
    name = name.lower()
    if value is None:
        self.assert_(name not in headers)
    else:
        self.assert_(name in headers)
        self.assertEqual(headers[name], value)

def do_test(self, packet_type=None, session_id=None, data=None, headers=None, expected_status=0, expected_session_id=None, expected_error_code=None, expected_error_context=None, expected_headers=None, connection=None, record=None, vhd=False, vdi_raw=False, ret_headers=False):
    # Setup the host if a record was not passed in
    if not record:
        record = setup_and_get_record(vdi_raw=vdi_raw)

    # Create a new connection if one was not passed in
    if connection:
        conn = connection
    else:
        conn = httplib.HTTPConnection(record['ip'], record['port'])

    reqheaders = {'Authorization': http_test.auth_header(record['username'], record['password'])}
    if packet_type is not None: reqheaders['BITS-Packet-Type'] = packet_type
    logging.debug(session_id)
    if session_id is not None: reqheaders['BITS-Session-Id'] = session_id
    if headers:
        for k, v in headers.iteritems():
            reqheaders[k] = v
    try:
        url_path = record['url_path']
        if vhd:
            url_path = record['url_path'] + ".vhd"
        conn.request('BITS_POST', url_path, data, reqheaders)
        resp = conn.getresponse()
        respheaders = dict((k.lower(), v) for (k, v) in resp.getheaders())
        logging.debug('Got Response headers %r' % respheaders)
	assertHeaderIfValueSet(self, respheaders, 'Content-Length', '0')  # All BITS Acks must have no data.
        resp.read(0)
    finally:
        # Close the connection only if we created it
        if connection:
            conn.close()

    self.assertEqual(expected_status, resp.status)
    assertHeaderIfValueSet(self, respheaders, 'BITS-Packet-Type', 'Ack')
    if expected_session_id:
        assertHeaderIfValueSet(self, respheaders, 'BITS-Session-Id', expected_session_id)
    assertHeaderIfValueSet(self, respheaders, 'BITS-Error-Code', expected_error_code)
    assertHeaderIfValueSet(self, respheaders, 'BITS-Error-Context', expected_error_context)
    if expected_headers:
        for k, v in expected_headers.iteritems():
            assertHeaderIfValueSet(self, respheaders, k, v)

    if ret_headers:
        return (record, respheaders)
    return record


def assertVdiData(self, record, data):
    uri = 'http://%s:%s%s' % (record['ip'], record['port'], record['url_path'])
    auth = urllib2.HTTPPasswordMgrWithDefaultRealm()
    auth.add_password(realm=None, uri=uri, user=record['username'], passwd=record['password'])
    opener = urllib2.build_opener(urllib2.HTTPBasicAuthHandler(auth))
    logging.debug(uri)
    vdifile = opener.open(uri)
    try:
        vdidata = vdifile.read()
    finally:
        vdifile.close()
    self.assertEqual(len(data), len(vdidata))
    #self.assertEqual(data, vdidata) # TODO: failure causes too much output
    if data != vdidata:
        f = open("check.tmp", 'w')
        f.write(vdidata)
        f.close()
        self.assertEqual("data", "mismatch")


class FragmentTest(unittest.TestCase):

    def testMissingContentRangeResultsIn400BadRequest(self):
        data = 'a' * (5*K)
        record = do_test(self, packet_type='FRAGMENT',
                               session_id='{00000000-0000-0000-0000-000000000111}',
                               data=data,
                               headers=None,
                               expected_status=400,
                               expected_error_code=BITS_E_INVALIDARG,
                               expected_error_context=BITS_CONTEXT_SERVER)
        moreasserts.assertVdiIsZeroUsingHttpGet(self, record, VDI_MB)
        clean_up()

    def testInvalidContentRangeResultsIn400BadRequest(self):
        data = 'a' * (5*K)
        rangeheader = http_test.content_range_header(1*M, 1*M + len(data), 2 * VDI_MB*M)
        record = do_test(self, packet_type='FRAGMENT',
                               session_id='{00000000-0000-0000-0000-000000000222}',
                               data=data,
                               headers={'Content-Range': rangeheader},
                               expected_status=400,
                               expected_error_code=BITS_E_INVALIDARG,
                               expected_error_context=BITS_CONTEXT_SERVER)
        moreasserts.assertVdiIsZeroUsingHttpGet(self, record, VDI_MB)
        clean_up()

    def testMissingBitsSessionIdResultsIn400BadRequest(self):
        data = 'a' * (5*K)
        rangeheader = http_test.content_range_header(1*M, 1*M + len(data), VDI_MB*M)
        record = do_test(self, packet_type='FRAGMENT',
                               session_id=None,
                               data=data,
                               headers={'Content-Range': rangeheader},
                               expected_status=400,
                               expected_error_code=BITS_E_INVALIDARG,
                               expected_error_context=BITS_CONTEXT_SERVER)
        logging.debug('record')
	logging.debug(record)
	moreasserts.assertVdiIsZeroUsingHttpGet(self, record, VDI_MB)
        clean_up()

    def test5KBFragment(self):
        data = 'a' * (5*K)
        rangeheader = http_test.content_range_header(1*M, 1*M + len(data), VDI_MB*M)
        record = do_test(self, packet_type='FRAgmENT',
                               session_id='{00000000-0000-0000-0000-000000000333}',
                               data=data,
                               headers={'Content-Range': rangeheader},
                               expected_status=200,
                               expected_session_id='{00000000-0000-0000-0000-000000000333}',
                               expected_headers={'BITS-Received-Content-Range': str(1*M + len(data)),
                                                 'BITS-Reply-URL': None})
        assertVdiData(self, record, ('\0'*(1*M)) + data + ('\0'*(VDI_MB*M - 1*M - len(data))))
        clean_up()

    def test4MBFragment(self):
	logging.debug('Begining test4MBFragment')
        data = 'a' * (4*M)
        rangeheader = http_test.content_range_header(1*M, 1*M + len(data), VDI_MB*M)
        record = do_test(self, packet_type='FRAGment',
                               session_id='{00000000-0000-0000-0000-000000000555}',
                               data=data,
                               headers={'Content-Range': rangeheader},
                               expected_status=200,
                               expected_session_id='{00000000-0000-0000-0000-000000000555}',
                               expected_headers={'BITS-Received-Content-Range': str(1*M + len(data)),
                                                 'BITS-Reply-URL': None})
        logging.debug('DEVICE NUMBER:')
	logging.debug(record['vdi_uuid'])
	assertVdiData(self, record, ('\0'*(1*M)) + data + ('\0'*(VDI_MB*M - 1*M - len(data))))
        clean_up()

    def testMultipleFragmentsInOneHttpSession(self):
        record = setup_and_get_record()
        conn = httplib.HTTPConnection(record['ip'], record['port'])

        expectedvdi = '\0' * (VDI_MB*M)
        try:
            for i in xrange(1, 6):
                data = ("xabcde"[i]) * M  # 1MB string of one character
                offset = i * M / 2
                rangeheader = http_test.content_range_header(offset, offset + len(data), VDI_MB*M)
                record = do_test(self, packet_type='fragMENT',
                                       session_id='{00000000-0000-0000-0000-000000000333}',
                                       data=data,
                                       headers={'Content-Range': rangeheader},
                                       expected_status=200,
                                       expected_session_id='{00000000-0000-0000-0000-000000000333}',
                                       expected_headers={'BITS-Received-Content-Range': str(offset + len(data)),
                                                         'BITS-Reply-URL': None},
                                       connection=conn,
                                       record=record)

                # Do a local expected data write
                expectedvdi = expectedvdi[:offset] + data + expectedvdi[offset + len(data):]
                assertVdiData(self, record, expectedvdi)
        finally:
            conn.close()
            clean_up()


class VHDFragmentTest(unittest.TestCase):
    VDI_RAW = False

    def _testFragment(self, pattern, frag_size):
        TMP_RAW_RESPONSE_FILE = "response.tmp"
        TMP_VHD_RESPONSE_FILE = "response.vhd"
        REFERENCE_FILE = "reference.tmp"
        VHD_FILE = "tmp.vhd"
        VDI_MB = 16
        frag_variable = False

        if not frag_size:
            frag_variable = True
            frag_size = random.randint(1, 100*K)

        vdi_mb = VDI_MB
        vhd.create(VHD_FILE, vdi_mb)
        vhd.fill(VHD_FILE, REFERENCE_FILE, vdi_mb, pattern)
        f = open(VHD_FILE, 'r')
        data = f.read()
        f.close()

        record, resp = do_test(self, packet_type='CREATE-SESSION',
                      headers={'BITS-Supported-Protocols': BITS_PROTOCOL},
                      expected_status=200,
                      expected_headers={'BITS-Protocol': BITS_PROTOCOL.lower(),
                                        'BITS-Host-ID': None,
                                        'BITS-Host-Id-Fallback-Timeout': None},
                      vhd=True, vdi_raw=self.VDI_RAW, ret_headers=True)

        session_id = resp['bits-session-id']
        
        range_start = 0
        range_end = frag_size
        total = len(data)
        while (range_start < total):
            if range_end > total:
                range_end = total
            rangeheader = http_test.content_range_header(range_start, range_end, total)
            record = do_test(self, packet_type='FRAGMENT',
                                   session_id=session_id,
                                   data=data[range_start:range_end],
                                   headers={'Content-Range': rangeheader},
                                   expected_status=200,
                                   expected_headers={'BITS-Received-Content-Range': str(range_end),
                                                     'BITS-Reply-URL': None},
                                   record=record, vhd=True)
            range_start = range_end
            if frag_variable:
                frag_size = random.randint(1, 100*K)
            range_end += frag_size

        f = open(REFERENCE_FILE, 'r')
        data = f.read()
        f.close()
        assertVdiData(self, record, data)
        clean_up()

    def testFragmentWhole(self):
        self._testFragment(vhd.PATTERN_BLOCKS_RANDOM, 16*M)

    def testFragment16K(self):
        self._testFragment(vhd.PATTERN_BLOCKS_RANDOM, 16*K)

    def testFragmentNonstandard(self):
        self._testFragment(vhd.PATTERN_BLOCKS_RANDOM, 16*K - 1)

    def testFragmentVariable(self):
        self._testFragment(vhd.PATTERN_BLOCKS_RANDOM, 0)

class VHDFragmentTestNonsparse(VHDFragmentTest):
    VDI_RAW = True


class InvalidMessageTest(unittest.TestCase):
    def testMissingBitsPacketTypeResultsIn400BadRequest(self):
        do_test(self, packet_type=None,
                      expected_status=400,
                      expected_error_code=BITS_E_INVALIDARG,
                      expected_error_context=BITS_CONTEXT_SERVER)

    def testUnknownBitsPacketTypeResultsIn400BadRequest(self):
        do_test(self, packet_type='AWESOME-MESSAGE',
                      expected_status=400,
                      expected_error_code=BITS_E_INVALIDARG,
                      expected_error_context=BITS_CONTEXT_SERVER)


class CreateSessionTest(unittest.TestCase):
    def testNonZeroContentLengthResultsIn400BadRequest(self):
        do_test(self, packet_type='CREATE-SESSION',
                      data='abcdefgh',
                      headers={'BITS-Supported-Protocols': BITS_PROTOCOL},
                      expected_status=400,
                      expected_error_code=BITS_E_INVALIDARG,
                      expected_error_context=BITS_CONTEXT_SERVER)

    def testMissingBitsSupportedProtocolsResultsIn400BadRequest(self):
        do_test(self, packet_type='CREATE-SESSION',
                      headers=None,
                      expected_status=400,
                      expected_error_code=BITS_E_INVALIDARG,
                      expected_error_context=BITS_CONTEXT_SERVER)

    def testUnknownBitsSupportedProtocolsValueResultsIn400BadRequest(self):
        do_test(self, packet_type='CREATE-SESSION',
                      headers={'BITS-Supported-Protocols': BITS_PROTOCOL[:-6] + 'abcdef'},
                      expected_status=400,
                      expected_error_code=BITS_E_INVALIDARG,
                      expected_error_context=BITS_CONTEXT_SERVER)

    def testCreateSession(self):
        do_test(self, packet_type='CreatE-SEssION',
                      headers={'BITS-Supported-Protocols': BITS_PROTOCOL},
                      expected_status=200,
                      expected_headers={'BITS-Protocol': BITS_PROTOCOL.lower(),
                                        'BITS-Host-ID': None,
                                        'BITS-Host-Id-Fallback-Timeout': None})


class PingTest(unittest.TestCase):
    def testNonZeroContentLengthResultsIn400BadRequest(self):
        do_test(self, packet_type='PING',
                      data='abcdefgh',
                      expected_status=400,
                      expected_error_code=BITS_E_INVALIDARG,
                      expected_error_context=BITS_CONTEXT_SERVER)

    def testPing(self):
        do_test(self, packet_type='pinG',
                      expected_status=200)


class CloseSessionTest(unittest.TestCase):
    def testNonZeroContentLengthResultsIn400BadRequest(self):
        do_test(self, packet_type='CLOSE-SESSION',
                      session_id='{00000000-0000-0000-0000-000000000123}',
                      data='abcdefgh',
                      expected_status=400,
                      expected_session_id='{00000000-0000-0000-0000-000000000123}',
                      expected_error_code=BITS_E_INVALIDARG,
                      expected_error_context=BITS_CONTEXT_SERVER)

    def testMissingBitsSessionIdResultsIn400BadRequest(self):
        do_test(self, packet_type='CLOSE-SESSION',
                      session_id=None,
                      expected_status=400,
                      expected_error_code=BITS_E_INVALIDARG,
                      expected_error_context=BITS_CONTEXT_SERVER)

    def testCloseSession(self):
        do_test(self, packet_type='CLOSE-SESSION',
                      session_id='{00000000-0000-0000-0000-000000000456}',
                      expected_status=200,
                      expected_session_id='{00000000-0000-0000-0000-000000000456}')


class CancelSessionTest(unittest.TestCase):
    def testNonZeroContentLengthResultsIn400BadRequest(self):
        do_test(self, packet_type='CANCEL-SESSION',
                      session_id='{00000000-0000-0000-0000-000000000789}',
                      data='abcdefgh',
                      expected_status=400,
                      expected_session_id='{00000000-0000-0000-0000-000000000789}',
                      expected_error_code=BITS_E_INVALIDARG,
                      expected_error_context=BITS_CONTEXT_SERVER)

    def testMissingBitsSessionIdResultsIn400BadRequest(self):
        do_test(self, packet_type='CANCEL-SESSION',
                      session_id=None,
                      expected_status=400,
                      expected_error_code=BITS_E_INVALIDARG,
                      expected_error_context=BITS_CONTEXT_SERVER)

    def testCloseSession(self):
        do_test(self, packet_type='cANcel-sesSION',
                      session_id='{00000000-0000-0000-0000-000000000222}',
                      expected_status=200,
                      expected_session_id='{00000000-0000-0000-0000-000000000222}')



