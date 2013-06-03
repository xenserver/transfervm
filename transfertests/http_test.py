#!/usr/bin/python

import base64
import httplib
import logging
import socket
import unittest
import os
import zlib
import random

import testsetup
import transferclient
import XenAPI
import util
import vhd
import time

K = 1024
M = 1024*1024

def clean_up():
    hostname = testsetup.HOST
    testsetup.clean_host(hostname)

def auth_header(username, password):
    return 'Basic ' + base64.encodestring('%s:%s' % (username, password)).strip()

def range_header(range_start, range_above):
    return 'bytes=%d-%d' % (range_start, range_above - 1)

def content_range_header(range_start, range_above, total):
    return 'bytes %d-%d/%d' % (range_start, range_above - 1, total)

def http_get(exposerecord, rangebounds=None, content_range=None):
    headers = {'Authorization': auth_header(exposerecord['username'], exposerecord['password'])}
    if rangebounds:
        headers['Range'] = range_header(*rangebounds)
    if content_range:
        headers['Content-Range'] = content_range_header(*content_range)

    conn = httplib.HTTPConnection(exposerecord['ip'], exposerecord['port'])
    try:
        conn.request('GET', exposerecord['url_path'], None, headers)
        resp = conn.getresponse()
        return resp.status, dict(resp.getheaders()), resp.read()
    finally:
        conn.close()

def http_head(exposerecord, rangebounds=None, content_range=None):
    headers = {'Authorization': auth_header(exposerecord['username'], exposerecord['password'])}
    if rangebounds:
        headers['Range'] = range_header(*rangebounds)
    if content_range:
        headers['Content-Range'] = content_range_header(*content_range)

    conn = httplib.HTTPConnection(exposerecord['ip'], exposerecord['port'])
    try:
        conn.request('HEAD', exposerecord['url_path'], None, headers)
        resp = conn.getresponse()
        return resp.status, dict(resp.getheaders())
    finally:
        conn.close()


def http_put_request(connection, record, data, offset, vdi_size):
    headers = {'Authorization': auth_header(record['username'], record['password'])}
    if offset is not None:
        headers['Content-Range']= content_range_header(offset, offset + len(data), vdi_size)
    connection.request('PUT', record['url_path'], data, headers)
    resp = connection.getresponse()
    resp.read(0)
    return resp.status, resp.getheaders()

def http_put(exposerecord, data, range_start=None, vdi_size=None):
    connection = httplib.HTTPConnection(exposerecord['ip'], exposerecord['port'])
    try:
        return http_put_request(connection, exposerecord, data, range_start, vdi_size)
    finally:
        connection.close()


class NewVdiGetZerosTest(unittest.TestCase):
    """Tests GET on fresh VDIs (which will contain all zeros)."""

    def dotest(self, vdi_mb, responselength, rangebounds):
        hostname, network, vdi = testsetup.setup_host_and_network(templates=1, vdi_mb=vdi_mb)
        transferclient.expose(hostname, vdi_uuid=vdi, network_uuid=network, transfer_mode='http')
        record = transferclient.get_record(hostname, vdi_uuid=vdi)
        status, headers, data = http_get(record, rangebounds)

        if rangebounds is None:
            self.assertEqual(status, httplib.OK)
        else:
            self.assertEqual(status, httplib.PARTIAL_CONTENT)
            self.assert_('content-range' in map(str.lower, headers.iterkeys()))
        self.assertEquals(responselength, len(data))
        self.assertEquals('\0' * responselength, data)
        clean_up()  

    def testGetWholeSmallVdi(self):
        self.dotest(vdi_mb=10, responselength=10*M, rangebounds=None)

    def testGetLowRangeOfSmallVdi(self):
        self.dotest(vdi_mb=10, responselength=1*M, rangebounds=(2*M,3*M))

    def testGetLowRangeOfLargeVdi(self):
        self.dotest(vdi_mb=6000, responselength=1*M, rangebounds=(2*M,3*M))

    def testGetAbove4GbRangeOfLargeVdi(self):
        self.dotest(vdi_mb=6000, responselength=1*M, rangebounds=(5678*M,5679*M))


def do_put_test(self, vdi_mb, put_data_size, put_offset, check_border_size, unexpose_reexpose=False):
    self.assert_(put_data_size + put_offset <= vdi_mb * M, 'Test has invalid data offsets.')

    lower_border_size = min(put_offset, check_border_size)
    upper_border_size = min(vdi_mb * M - put_offset - put_data_size, check_border_size)

    put_data = 'abcdefgh' * (put_data_size / 8)
    expect_data = ('\0' * lower_border_size) + put_data + ('\0' * upper_border_size)

    hostname, network, vdi = testsetup.setup_host_and_network(templates=1, vdi_mb=vdi_mb)
    transferclient.expose(hostname, vdi_uuid=vdi, network_uuid=network, transfer_mode='http')
    record = transferclient.get_record(hostname, vdi_uuid=vdi)

    put_status, put_headers = http_put(record, put_data, put_offset, vdi_mb * M)
    self.assertEqual(put_status, 200)
    if unexpose_reexpose:
        transferclient.unexpose(hostname, vdi_uuid=vdi)
        transferclient.expose(hostname, vdi_uuid=vdi, network_uuid=network, transfer_mode='http')
        record = transferclient.get_record(hostname, vdi_uuid=vdi)

    get_status, get_headers, get_respdata = http_get(record, (put_offset - lower_border_size, put_offset + put_data_size + upper_border_size))
    self.assert_(get_status == 200 or get_status == 206, 'GET status code %d is not success.' % get_status)
    self.assertEquals(len(get_respdata), len(expect_data))
    self.assertEquals(get_respdata, expect_data)
    clean_up()


def do_vhd_put_get_test(self, vdi_mb, vdi_raw, pattern, blocks = None):
    MAX_FRAG_SIZE = 100*K
    TMP_RAW_RESPONSE_FILE = "response.tmp"
    TMP_VHD_RESPONSE_FILE = "response.vhd"
    REFERENCE_FILE = "reference.tmp"
    VHD_FILE = "tmp.vhd"
    bitmap = None

    vhd.create(VHD_FILE, vdi_mb)
    vhd.fill(VHD_FILE, REFERENCE_FILE, vdi_mb, pattern)
    hostname, network, vdi = testsetup.setup_host_and_network(templates=1, vdi_mb=vdi_mb, vdi_raw=vdi_raw)
    args = {'vdi_uuid': vdi, 'network_uuid': network, 'transfer_mode': 'http'}
    if blocks:
        bitmap = vhd.to_bitmap(blocks, vdi_mb * M)
        args['vhd_blocks'] = base64.b64encode(zlib.compress(bitmap))
	args['vhd_uuid'] = vdi #vhd uuid needed for get - using vdi value for test purposes
    transferclient.expose(hostname, **args)
    record = transferclient.get_record(hostname, vdi_uuid=vdi)
    url_path = record['url_path']

    # test "put"
    f = open(VHD_FILE, 'r')
    put_data = f.read()
    f.close()

    record['url_path'] = url_path + ".vhd"
    put_status, put_headers = http_put(record, put_data, None, vdi_mb * M)
    self.assertEqual(put_status, 200)

    record['url_path'] = url_path
    get_status, get_headers, get_respdata = http_get(record)
    if len(get_respdata) > vdi_mb * M:
        # raw VDIs can be larger than requested size
        get_respdata = get_respdata[:vdi_mb * M]
    f = open(TMP_RAW_RESPONSE_FILE, 'w')
    f.write(get_respdata)
    f.close()

    cmd = "diff %s %s" % (TMP_RAW_RESPONSE_FILE, REFERENCE_FILE)
    util.doexec(cmd, 0)

    # test "get"
    record['url_path'] = url_path + ".vhd"
    frag_size = random.randint(1, MAX_FRAG_SIZE)
    range_start = 0
    range_end = frag_size
    head_status, head_headers = http_head(record)
    vhd_size = int(head_headers['content-length'])
    total = vhd_size 
    total_received = 0
    total_chunks = 0
    f = open(TMP_VHD_RESPONSE_FILE, 'w')
    while range_start < total:
        if range_end > total:
            range_end = total
        
        #print "Getting range %d-%d" % (range_start, range_end)
        get_status, get_headers, get_respdata = http_get(record, content_range=(range_start, range_end, total))
        self.assertEquals(get_status, 200)
        #print "Got response of length %d" % len(get_respdata)
        total_received += len(get_respdata)
        total_chunks += 1
        f.write(get_respdata)

        range_start = range_end
        frag_size = random.randint(1, MAX_FRAG_SIZE)
        range_end += frag_size

    f.close()
    #print "Got total length %d in %d chunks" % (total_received, total_chunks)

    if blocks:
        vhd.mask(REFERENCE_FILE, vdi_mb * M, blocks)
        vhd.extract(TMP_VHD_RESPONSE_FILE, TMP_RAW_RESPONSE_FILE)
        cmd = "diff %s %s" % (TMP_RAW_RESPONSE_FILE, REFERENCE_FILE)
        util.doexec(cmd, 0)
    else:
        vhd.diff(TMP_VHD_RESPONSE_FILE, VHD_FILE)

    clean_up()
    #os.unlink(VHD_FILE)
    #os.unlink(TMP_RAW_RESPONSE_FILE)
    #os.unlink(TMP_VHD_RESPONSE_FILE)
    #os.unlink(REFERENCE_FILE)


class VHDTest(unittest.TestCase):
    VDI_MB = 12
    VDI_RAW = False

    def testEmpty(self):
        do_vhd_put_get_test(self, self.VDI_MB, self.VDI_RAW, vhd.PATTERN_EMPTY)

    def testShortStringBeginning(self):
        do_vhd_put_get_test(self, self.VDI_MB, self.VDI_RAW, vhd.PATTERN_SHORT_STRING_BEGINNING)

    def testShortStringMiddle(self):
        do_vhd_put_get_test(self, self.VDI_MB, self.VDI_RAW, vhd.PATTERN_SHORT_STRING_MIDDLE)

    def testShortStringEnd(self):
        do_vhd_put_get_test(self, self.VDI_MB, self.VDI_RAW, vhd.PATTERN_SHORT_STRING_END)

    def testBlocksSequential(self):
        do_vhd_put_get_test(self, self.VDI_MB, self.VDI_RAW, vhd.PATTERN_BLOCKS_SEQUENTIAL)

    def testBlocksReverse(self):
        do_vhd_put_get_test(self, self.VDI_MB, self.VDI_RAW, vhd.PATTERN_BLOCKS_REVERSE)

    def testBlocksRandom(self):
        do_vhd_put_get_test(self, self.VDI_MB, self.VDI_RAW, vhd.PATTERN_BLOCKS_RANDOM)


class VHDBackendNonSparseTest(VHDTest):
    VDI_RAW = True


class VHDBitmapTest(unittest.TestCase):
    VDI_MB = 12
    VDI_RAW = False

    def testVHDEmptyBitmapEmpty(self):
        do_vhd_put_get_test(self, self.VDI_MB, self.VDI_RAW, vhd.PATTERN_EMPTY, [])

    def testVHDEmptyBitmapEverySecond(self):
        blocks = range(0, self.VDI_MB * M / vhd.VHD_BLOCK_SIZE, 2)
        do_vhd_put_get_test(self, self.VDI_MB, self.VDI_RAW, vhd.PATTERN_EMPTY, blocks)

    def testVHDFullBitmapEmpty(self):
        do_vhd_put_get_test(self, self.VDI_MB, self.VDI_RAW, vhd.PATTERN_BLOCKS_SEQUENTIAL, [])

    def testVHDFullBitmapEverySecond(self):
        blocks = range(0, self.VDI_MB * M / vhd.VHD_BLOCK_SIZE, 2)
        do_vhd_put_get_test(self, self.VDI_MB, self.VDI_RAW, vhd.PATTERN_BLOCKS_SEQUENTIAL, blocks)

    def testVHDDataOverlaps(self):
        do_vhd_put_get_test(self, self.VDI_MB, self.VDI_RAW, vhd.PATTERN_SHORT_STRING_BEGINNING, [0])

    def testVHDDataNotOverlaps(self):
	#Returns an empty disk because the BAT doesn't allocate the block with data written to it
        do_vhd_put_get_test(self, self.VDI_MB, self.VDI_RAW, vhd.PATTERN_SHORT_STRING_BEGINNING, [1])


class VHDBitmapBackendNonSparseTest(VHDBitmapTest):
    VDI_RAW = True


class PutAndImmediateGetTest(unittest.TestCase):

    def testPut16KBLowRangeOfSmallVdi(self):
        do_put_test(self,
                    vdi_mb=10,
                    put_data_size=16*K,
                    put_offset=1*M + 123*K,
                    check_border_size=3*K,
                    unexpose_reexpose=False)

    def testPut16KBLowRangeOfLargeVdi(self):
        do_put_test(self,
                    vdi_mb=6000,
                    put_data_size=16*K,
                    put_offset=3*M + 456*K,
                    check_border_size=3*K,
                    unexpose_reexpose=False)

    def testPut16KBAbove4GbRangeOfLargeVdi(self):
        do_put_test(self,
                    vdi_mb=6000,
                    put_data_size=16*K,
                    put_offset=5500*M + 678*K,
                    check_border_size=3*K,
                    unexpose_reexpose=False)

    def testPut16KBAtStartOfLargeVdi(self):
        do_put_test(self,
                    vdi_mb=6000,
                    put_data_size=16*K,
                    put_offset=0,
                    check_border_size=3*K,
                    unexpose_reexpose=False)

    def testPut16KBAtEndOfLargeVdi(self):
        do_put_test(self,
                    vdi_mb=6000,
                    put_data_size=16*K,
                    put_offset=6000*M - 16*K,
                    check_border_size=3*K,
                    unexpose_reexpose=False)

    def testPut4MBLowRangeOfSmallVdi(self):
        do_put_test(self,
                    vdi_mb=10,
                    put_data_size=4*M,
                    put_offset=1*M + 456*K,
                    check_border_size=3*K,
                    unexpose_reexpose=False)

    def testPut4MBLowRangeOfLargeVdi(self):
        do_put_test(self,
                    vdi_mb=6000,
                    put_data_size=4*M,
                    put_offset=3*M + 789*K,
                    check_border_size=3*K,
                    unexpose_reexpose=False)

    def testPut4MBAbove4GbRangeOfLargeVdi(self):
        do_put_test(self,
                    vdi_mb=6000,
                    put_data_size=4*M,
                    put_offset=5500*M + 678*K,
                    check_border_size=3*K,
                    unexpose_reexpose=False)

class PutAndAfterUnexposeReexposeGetTest(unittest.TestCase):

    def testPut16KBLowRangeOfSmallVdi(self):
        do_put_test(self,
                    vdi_mb=10,
                    put_data_size=16*K,
                    put_offset=1*M + 123*K,
                    check_border_size=3*K,
                    unexpose_reexpose=True)

    def testPut16KBLowRangeOfLargeVdi(self):
        do_put_test(self,
                    vdi_mb=6000,
                    put_data_size=16*K,
                    put_offset=3*M + 456*K,
                    check_border_size=3*K,
                    unexpose_reexpose=True)

    def testPut16KBAbove4GbRangeOfLargeVdi(self):
        do_put_test(self,
                    vdi_mb=6000,
                    put_data_size=16*K,
                    put_offset=5500*M + 678*K,
                    check_border_size=3*K,
                    unexpose_reexpose=True)

    def testPut16KBAtStartOfLargeVdi(self):
        do_put_test(self,
                    vdi_mb=6000,
                    put_data_size=16*K,
                    put_offset=0,
                    check_border_size=3*K,
                    unexpose_reexpose=True)

    def testPut16KBAtEndOfLargeVdi(self):
        do_put_test(self,
                    vdi_mb=6000,
                    put_data_size=16*K,
                    put_offset=6000*M - 16*K,
                    check_border_size=3*K,
                    unexpose_reexpose=True)

    def testPut4MBLowRangeOfSmallVdi(self):
        do_put_test(self,
                    vdi_mb=10,
                    put_data_size=4*M,
                    put_offset=1*M + 456*K,
                    check_border_size=3*K,
                    unexpose_reexpose=True)

    def testPut4MBLowRangeOfLargeVdi(self):
        do_put_test(self,
                    vdi_mb=6000,
                    put_data_size=4*M,
                    put_offset=3*M + 789*K,
                    check_border_size=3*K,
                    unexpose_reexpose=True)

    def testPut4MBAbove4GbRangeOfLargeVdi(self):
        do_put_test(self,
                    vdi_mb=6000,
                    put_data_size=4*M,
                    put_offset=5500*M + 678*K,
                    check_border_size=3*K,
                    unexpose_reexpose=True)


class HttpKeepaliveTest(unittest.TestCase):

    def testSendMultiplePutRequestsInOneHttpSession(self):
        hostname, network, vdi = testsetup.setup_host_and_network(templates=1, vdi_mb=16)
        transferclient.expose(hostname, vdi_uuid=vdi, network_uuid=network, transfer_mode='http')
        record = transferclient.get_record(hostname, vdi_uuid=vdi)

        conn = httplib.HTTPConnection(record['ip'], record['port'])
        try:
            for i in xrange(1, 5):
                data = 'a' * (i * 100*K)
                status, headers = http_put_request(conn, record, data, i * M * 2 + 234*K, 16*M)
                self.assertEqual(status, 200)
        finally:
            conn.close()
            clean_up()
      

class PutContentRangeHeaderFormatTest(unittest.TestCase):

    def assertPutContentRangeResponse(self, vdi_mb, data_size, range_str, response_status):
        hostname, network, vdi = testsetup.setup_host_and_network(templates=1, vdi_mb=vdi_mb)
        transferclient.expose(hostname, vdi_uuid=vdi, network_uuid=network, transfer_mode='http')
        record = transferclient.get_record(hostname, vdi_uuid=vdi)

        headers = {'Authorization': auth_header(record['username'], record['password']),
                   'Content-Range': range_str}
        data = 'a' * data_size
        conn = httplib.HTTPConnection(record['ip'], record['port'])
        try:
            conn.request('PUT', record['url_path'], data, headers)
            resp = conn.getresponse()
            resp.read(0)
            self.assertEquals(resp.status, response_status)
        finally:
            conn.close()
            clean_up()

    def testInvalidPrefixResultsIn400BadRequest(self):
        self.assertPutContentRangeResponse(10, 2, 'bqqqs 0-1/10485760', 400)

    def testInvalidNumbersResultsIn400BadRequest(self):
        self.assertPutContentRangeResponse(10, 2, 'bytes 01/10485760', 400)

    def testWildcardsResultIn501NotImplemented(self):
        self.assertPutContentRangeResponse(10, 2, 'bytes *-1/10485760', 501)
        self.assertPutContentRangeResponse(10, 2, 'bytes 0-*/10485760', 501)
        self.assertPutContentRangeResponse(10, 2, 'bytes 0-1/*', 501)

    def testTooLargeTotalLengthResultsIn416RequestedRangeNotSatisfiable(self):
        self.assertPutContentRangeResponse(10, 2, 'bytes 0-1/100000000000', 416)

    def testUpperRangeAboveTotalLengthResultsIn400BadRequest(self):
        self.assertPutContentRangeResponse(10, 2, 'bytes 0-100000000000/10485760', 400)

    def testLowerRangeAboveUpperRangeResultsIn400BadRequest(self):
        self.assertPutContentRangeResponse(10, 2, 'bytes 1000-1/10485760', 400)
