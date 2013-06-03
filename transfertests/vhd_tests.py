#!/usr/bin/python 

import base64
import httplib
import logging
import socket
import unittest
import urllib2
import urlparse
import random
import zlib
import time

import http_test
import moreasserts
import testsetup
import transferclient
import XenAPI  
import vhd
import bits
from xml.dom import minidom

M = 1024 * 1024

def remove_vids_by_name(hostname, vdi_name):
    target_commands = "xe vdi-list name-label='%s' --minimal | xargs -d, -ixx xe vdi-destroy uuid=xx" % vdi_name
    call_to_stderr(['ssh', 'root@' + hostname, target_commands])


def get_vhd_url(record):
    url_path = record['url_path'] + ".vhd"
    return url_path

def generate_vhd(vdi_mb, pattern, vhd_name="tmp.vhd"):
    REFERENCE_FILE = "reference.tmp"
    logging.debug("Creating VHD...")
    vhd.create(vhd_name, vdi_mb)
    logging.debug("Filling VHD...")
    vhd.fill(vhd_name, REFERENCE_FILE, vdi_mb, pattern)
    logging.debug("Generated %s" % vhd_name)
    return vhd_name

def get_encoded_bitmap_from_file(fn):
    vdi_mb = vhd.get_virtual_size(fn)
    blocks = vhd.get_allocated_blocks(fn)
    bitmap = vhd.to_bitmap(blocks, vdi_mb * M)
    return base64.b64encode(zlib.compress(bitmap))

def expose_vdi_as_vhd(hostname, vdi_uuid, bitmap):
    args = {}
    args['vhd_blocks'] = bitmap
    args['vhd_uuid'] = vdi_uuid #take anything, for test purposes
    args['vdi_uuid'] = vdi_uuid
    args['network_uuid'] = 'management'
    args['transfer_mode'] = 'bits'
    args['get_log'] = 'true'
    transferclient.expose(hostname, **args)
    record = transferclient.get_record(hostname, vdi_uuid=vdi_uuid)
    return record

def put_vhd(self, file_name, vdi_mb, vdi_raw):
    hostname, network, vdi = testsetup.setup_host_and_network(templates=1, vdi_mb=vdi_mb, vdi_raw=vdi_raw)    
    args = {'vdi_uuid': vdi, 'network_uuid':network, 'transfer_mode':'bits'}
    print "Putting %s"  % (file_name)
    #Calculate allocated blocks for the sake of sparseness
    args['vhd_blocks'] = get_encoded_bitmap_from_file(file_name)

    logging.debug(args['vhd_blocks'])
    args['vhd_uuid'] = vdi #just take anything for test purposes

    transferclient.expose(hostname, **args)
    record = transferclient.get_record(hostname, vdi_uuid=vdi)
    
    bits_upload_vhd(record, file_name)
    return record

def bits_upload_vhd(record, filename):
    protocol = "http"
    upload_path = protocol + "://" + record['username'] + ":" + record['password'] + "@" + record['ip'] + ":80" + record['url_path'] + ".vhd"
    logging.debug("Uploading %s to path %s" % (filename, upload_path))
    bits.upload(filename, protocol, record['ip'], "80", record['username'], record['password'], record['url_path'] + ".vhd")

def get_vhd_size(record):
    conn = httplib.HTTPConnection(record['username'] + ":" + record['password'] + "@" + record['ip'] + ":80")
    conn.request("HEAD", "/" + record['url_path'] + ".vhd")
    res = conn.getresponse()
    print res.status, res.reason
    print res.getheaders()

def bits_download_vhd(record, dest, req_size):
    chunksize = 1024
    protocol = "http"
    vhd_path = record['url_path'] + '.vhd'
    logging.debug("About to download %s" % vhd_path)
    #bits.download(protocol,record['ip'] + ":80" , vhd_path ,dest, record['username'], record['password'])
    url_path = protocol + "://" + record['ip'] + ":80" + vhd_path
    print url_path
    bits.download_by_range(url_path, record['username'], record['password'], dest, req_size)

def unexpose(hostname, record):
    args= {'record_handle': record['record_handle']}
    logging.debug("Unexposeing %s" % record['vdi_uuid'])
    startTime = time.time()
    transferclient.unexpose(hostname, **args)
    logging.debug("Unexpose took %.3f seconds" % (time.time() - startTime))

def assert_matching_bitmap(fn, bitmap):
    bitmap_from_file = get_encoded_bitmap_from_file(fn)
    assert(bitmap == bitmap_from_file)

def check_downloaded_bitmaps(fn):
    """Given the path to a downloaded VHD, check that each bitmap has been completely allocated"""
    """This is because when we allocated a block, we fill the whole bitmap and so a unfilled"""
    """Bitmap represents a bug"""

    non_filled_bitmaps = vhd.get_non_filled_blocks(fn)
    if non_filled_bitmaps:
	raise Exception("Bitmaps are corrupt for the blocks:\n%s" % (non_filled_bitmaps))

def download_range_of_vhd(record, dest, req_start, req_end):
    """Given a transfervm record for an exposed vdi, this function will make a partial request"""
    """For the rage specified"""
    url = "http://%s:%s%s.vhd" % (record['ip'], "80", record['url_path'])
    logging.debug(url)
    req = urllib2.Request(url)
    req.headers['Range'] = 'bytes=%s-%s' % (req_start, req_end)
    req.headers['Authorization'] = 'Basic %s' % base64.b64encode('%s:%s' % (record['username'], record['password']))
    f = urllib2.urlopen(req)
    file = open(dest, 'w')
    downloaded_length = 0
    while True:
	buf = f.read(2 * 1024 * 1024)
	if buf:
	    file.write(buf)
	    downloaded_length += len(buf)
        else:
	    break
    logging.debug("Downloaded %s bytes from a range of %s bytes" % (downloaded_length, str(int(req_end) - int(req_start))))

class ManualDownloadSparseVHDs(unittest.TestCase):
    """A Class of unit tests that are to be operated manually, and require the """
    """user to change the variables present in the unit case methods"""
    MS_BITS_DEFAULT_REQUEST_SIZE = 2147418111

    def _downloadFromVdi(self, vdi_uuid, dest, request_size):
	"""Given a vdi_uuid, the test case downloads the vdi as a VHD"""
	"""and compares the original bitmap with the downloaded bitmap"""

	hostname = testsetup.HOST
        bitmap = transferclient.get_vdi_bitmap(hostname, vdi_uuid)
	record = expose_vdi_as_vhd(hostname,vdi_uuid, bitmap)

	#Download VHD using the python bitsclient
	bits_download_vhd(record, dest, request_size)
	logging.debug("Downloaded %s" % dest)

	assert_matching_bitmap(dest, bitmap) #Check the block allocation table
	check_downloaded_bitmaps(dest)
	unexpose(hostname, record)

    def _downloadWin2k8SrvR2(self):
	"""Manual test for downloading a VDI with win2k8srvr2 - you must provision this first"""
	vdi_uuid = "35b420af-9fc1-48de-b0dd-13cb5c27828f"
	dest = "win2k8srvr2-download.vhd"
	request_size = self.MS_BITS_DEFAULT_REQUEST_SIZE
	self._downloadFromVdi(vdi_uuid, dest, request_size)

    def _downloadWin2k8SrvR2Range(self):
	"""Manual test for downloading a range of win2k8srvr2 - you must provision this first"""
	vdi_uuid = "35b420af-9fc1-48de-b0dd-13cb5c27828f"
	req_start = "6442254336"
	req_end   = "7050322431"
	dest = "win2k8srvr2-%s-%s-download.vhd" % (req_start, req_end)

	hostname = testsetup.HOST
        bitmap = transferclient.get_vdi_bitmap(hostname, vdi_uuid)
	record = expose_vdi_as_vhd(hostname,vdi_uuid, bitmap)

        download_range_of_vhd(record, dest, req_start, req_end)
        unexpose(hostname, record)

    def _downloadWin2k8SrvR2Whole(self):
	"""Manual test for downloading a VDI with win2k8srvr2 - you must provision this first"""
	vdi_uuid = "35b420af-9fc1-48de-b0dd-13cb5c27828f"
	dest = "win2k8srvr2-download.vhd"
	request_size = 0
	self._downloadFromVdi(vdi_uuid, dest, request_size)


    def _downloadDemoLinuxVM(self):
	"""Manual test for downloading a VDI with demolinuxvm installed - you must provision this first"""
	vdi_uuid = "bdf327e9-366e-4401-a735-870c9e4a1f1e"
	dest = "demolinux-download.vhd"
	request_size = 233531111
	self._downloadFromVdi(vdi_uuid, dest, request_size)
	
       
class FragmentOverlapTests(unittest.TestCase):
     """A class of unit tests to test the TransferVM copes with odd request chunk sizes"""
     VDI_RAW = False
     TMP_VHD = "tmp.vhd"
     
     def _testUploadDownload(self, vhd_filename, vdi_mb, chunksize):
        record = put_vhd(self, vhd_filename, vdi_mb, self.VDI_RAW)
        protocol = "http"
        dest = "download-frag-%s.vhd" % (vdi_mb)
        logging.debug("About to download " + record['url_path'])
	logging.debug("Fagment size is %d" % chunksize) 
      	bits.download(protocol,record['ip'] + ":80" , record['url_path'] + '.vhd' ,dest, record['username'], record['password'], chunksize)
        
	vhd.diff(vhd_filename, dest)
	return record

     def _testCustomVHD(self, vhd_filename, chunksize):
         vdi_mb = vhd.get_virtual_size(vhd_filename)
         self._testUploadDownload(vhd_filename, vdi_mb, chunksize)

     def chunksize_10013(self):
	 vhd_file = "vhd/random-full/download-512.vhd"
      	 self._testCustomVHD(vhd_file, 10013)

     def chunksize_519(self):
	 vhd_file = "vhd/random-full/download-512.vhd"
      	 self._testCustomVHD(vhd_file, 519)

     def chunksize_1049105(self):
	 vhd_file = "vhd/random-full/download-512.vhd"
      	 self._testCustomVHD(vhd_file, 1049105)


class TestUploadDownloads(unittest.TestCase):
    PATTERN = vhd.PATTERN_SHORT_STRING_BEGINNING
    VDI_RAW = False
    TMP_VHD = "tmp.vhd"
    def _testUploadDownload(self, vhd_filename, vdi_mb):
        #Setup record for the VDI we're wanting to download
	record = put_vhd(self, vhd_filename, vdi_mb, self.VDI_RAW) 

	protocol = "http"
	dest = "download-%s.vhd" % (vdi_mb)
	logging.debug("About to download " + record['url_path'])
	bits.download(protocol,record['ip'] + ":80" , record['url_path'] ,dest, record['username'], record['password'])
	
	vhd.diff(vhd_filename, dest)
        return record 

    def _testCustomVHD(self, vhd_filename):
        vdi_mb = vhd.get_virtual_size(vhd_filename)
        self._testUploadDownload(vhd_filename, vdi_mb)

    def _testGeneratedVHD(self, vdi_mb, pattern, vhd_filename):
        vhd_filename = generate_vhd(vdi_mb, pattern, vhd_filename)
        self._testUploadDownload(vhd_filename, vdi_mb)


    def testVdi8mb(self):
        self._testGeneratedVHD(8, vhd.PATTERN_SHORT_STRING_BEGINNING, self.TMP_VHD)

    def testVdi1Gb(self):
        self._testGeneratedVHD(1024, vhd.PATTERN_SHORT_STRING_BEGINNING, self.TMP_VHD)

    def testVdi512mb(self):
	self._testGeneratedVHD(512, vhd.PATTERN_BLOCKS_RANDOM, self.TMP_VHD)

    def testVdi1GbRandom(self):
	self._testGeneratedVHD(1024, vhd.PATTERN_BLOCKS_RANDOM, self.TMP_VHD)

    def testVdi4GbRandom(self):
	self._testGeneratedVHD(4096, vhd.PATTERN_BLOCKS_RANDOM, self.TMP_VHD)

    def _testCustom(self):
          self._testCustomVHD("vhd/winsrv2k8r2.vhd")

    def testVdi8Gb(self):
        self._testGeneratedVHD(8 * 1024, vhd.PATTERN_SHORT_STRING_BEGINNING, self.TMP_VHD)

    def testVdi10Gb(self):
	self._testGeneratedVHD(10 * 1024, vhd.PATTERN_SHORT_STRING_BEGINNING, self.TMP_VHD)

    def testVdi14Gb(self):
        self._testGeneratedVHD(14 * 1024, vhd.PATTERN_SHORT_STRING_BEGINNING, self.TMP_VHD)

    def testVdi24Gb(self):
	self._testGeneratedVHD(24 * 1024, vhd.PATTERN_SHORT_STRING_BEGINNING, self.TMP_VHD)
 
    def _testVdi14GbRandom(self):
	self._testGeneratedVHD(14 * 1024, vhd.PATTERN_BLOCKS_RANDOM, self.TMP_VHD)
