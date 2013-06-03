#!/usr/bin/python

import bits
import os
import unittest
import testsetup
import transferclient
import logging
import vhd
import time
import random
import gc
import vhd_tests

G = 1024 * 1024 * 1024
M = 1024 * 1024
K = 1024

#Response Headers

BITS_RECEIVED_CONTENT_RANGE = "bits-received-content-range"

def create_and_expose(vdi_mb):
    hostname, network, vdi = testsetup.setup_host_and_network(templates=1, vdi_mb=vdi_mb)
    args = {}
    args['vdi_uuid'] = vdi
    args['network_uuid'] = 'management'
    args['transfer_mode'] = 'bits'
    transferclient.expose(hostname, **args)
    return transferclient.get_record(hostname, vdi_uuid=vdi), hostname

def get_proto(record):
    if record['use_ssl'] == "true":
        logging.debug("using https")
        return "https"
    else:
        logging.debug("using http")
        return "http"

def create_BITS_session(record):
    conn = bits.open_connection(get_proto(record), record['ip'], record['port'])
    bits_sid = bits.create_session(conn, record['url_path'] + ".vhd", record['username'], record['password'])
    return conn, bits_sid

class FragmentTransientErrorTests(unittest.TestCase):
    """A class to test our handling of Transient Errors"""
    FILENAME = "test.vhd"
    FRAG_SIZE = 400*M
    SLEEP_TIME = 10
    DELTA_SMALL = 133127
    def _doTestAlreadyReceivedFragSubset(self, src, frag_size, sleep_time, randomise_delta=False):
        """Test that we handle a missing fragment appropriately - 416"""
        physize = os.stat(src).st_size
        vdi_mb = vhd.get_virtual_size(src)

        #Expose a new VDI
        record, hostname = create_and_expose(vdi_mb)
        url_path = record['url_path'] + ".vhd"

        #Create BITS Session
        conn, session = create_BITS_session(record)

        fh = open(src, 'r')

        #Read initial 50M
        data = fh.read(50*M)

        #Send Initial Request
        rheaders = bits.fragment(conn, session, url_path, data, 0, 50*M, physize)
        print "Initial Request:\n %s" % rheaders

        #Read 25M overlap
        fh.seek(25*M)
        data = fh.read(20)
        
        #Send Second Request (expect failure)
        try:
            rheaders = bits.fragment(conn, session,url_path, data, 25*M, 25*M + 20, physize)
            print "Second Request:\n %s" % rheaders

        except bits.Http416Exception as instance:
            logging.debug(instance.msg)
            logging.debug(instance.headers)
        
            #assert that we return the following values:
            if BITS_RECEIVED_CONTENT_RANGE not in instance.headers:
                raise Exception("BITS-Received-Content-Range header should be in repsonse for an overlapping fragement!")
            else:
                assert int(instance.headers[BITS_RECEIVED_CONTENT_RANGE]) == 50*M


    def _doTestOverlapFrag(self, src, frag_size, sleep_time, randomise_delta=False):
        """Test that we handle a missing fragment appropriately - 416"""
        physize = os.stat(src).st_size
        vdi_mb = vhd.get_virtual_size(src)

        #Expose a new VDI
        record, hostname = create_and_expose(vdi_mb)
        url_path = record['url_path'] + ".vhd"

        #Create BITS Session
        conn, session = create_BITS_session(record)

        fh = open(src, 'r')

        #Read initial 50M
        data = fh.read(50*M)

        #Send Initial Request
        rheaders = bits.fragment(conn, session, url_path, data, 0, 50*M, physize)
        print "Initial Request:\n %s" % rheaders

        #Read 25M overlap
        fh.seek(45*M)
        data = fh.read(10*M)
        
        #Send Second Request (expect failure)

        rheaders = bits.fragment(conn, session,url_path, data, 45*M, 45*M + 10*M, physize)
        print "Second Request:\n %s" % rheaders



    def _doTest(self, src, frag_size, sleep_time, delta, randomise_delta=False):
        """Tests how we handle the client droping/losing packets
        when they are POSTing a BITS request"""

        physize = os.stat(src).st_size                
        vdi_mb = vhd.get_virtual_size(src)
        
        #Expose a new VDI
        record, hostname = create_and_expose(vdi_mb)
        url_path = record['url_path'] + ".vhd"

        #Create BITS Session
        conn, session = create_BITS_session(record)
        
        logging.debug("Frag_Size = %d" % frag_size)
        
        #Adjust frag size for the case we have small disks
        if physize < frag_size:
            frag_size = physize

        #Initialise Upload variables
        range_start = 0
        range_end = frag_size
        file_offset = 0
        fh = open(src, 'r')
        count = 0
        while file_offset < physize:
            if randomise_delta:
                #Generate a random number within the request range
                delta = random.randint(0, range_end - range_start)
                logging.debug("Random Delta = %d" % delta)

            if range_end == physize:
                delta = 0

            logging.debug("Uploading %d-%d/%d" % (range_start, range_end, physize))
            data_size = (range_end - range_start - delta)

            if count == 1:
                data_size = 10
            logging.debug("Actually uploading %d bytes" % data_size)
            data = fh.read(data_size)
            logging.debug("Data Read")
            try:
                bits.fragment(conn, session, url_path, data, range_start, range_end, physize)
            except:
                logging.debug("Fragment Sent partially %d-%d/%d" % (range_start, range_end, physize))

            file_offset += (range_end - range_start - delta)
            range_start = file_offset + 1

            count += 1

            if count > 1:
                sys.exit(1)
    
            #Condition for last frag upload
            range_end = file_offset + frag_size
            if physize < range_end:
                range_end = physize

            #Sleep before creating new connection 
            logging.debug("Sleeping for %d seconds" % sleep_time)
            time.sleep(sleep_time)

            #Garbage Collect to make sure we don't run out of memory
            data = ''
            gc.collect()
            
            #Create new connection
            logging.debug("Get a new connection...")
            conn = bits.open_connection(get_proto(record), record['ip'], record['port'])

        #Close file handle
        fh.close()
        
        #Unexpose the transfervm
        logging.debug("Unexposing the Transfer VM for vdi %s" % record['vdi_uuid'])
        transferclient.unexpose(hostname, vdi_uuid=record['vdi_uuid'])

        #Retrieve the blockmap to expose the VDI as a vhd
        bitmap = transferclient.get_vdi_bitmap(hostname, record['vdi_uuid'])
        logging.debug("Got bitmap %s" % bitmap)

        #Expose disk with vhd_block_map
        args = {'transfer_mode': 'bits',
                'vdi_uuid': record['vdi_uuid'],
                'network_uuid': 'management',
                'vhd_blocks': bitmap,
                'vhd_uuid': record['vdi_uuid']}

        transferclient.expose(hostname, **args)

        record = transferclient.get_record(hostname, vdi_uuid=record['vdi_uuid'])
        logging.debug("Got new record: %s" % record)

        dst = 'test-download.vhd'
        logging.debug("Destination file will be %s" % dst)
        request_size = 200*M
        vhd_tests.bits_download_vhd(record, dst, request_size)
        
        #Compare the two VHDs to check they are identical
        rc = vhd.diff(src, dst)
        logging.debug("Return Code %s" % rc)
        
        #Unexpose the transfervm
        logging.debug("Unexposing the Transfer VM for vdi %s" % record['vdi_uuid'])
        transferclient.unexpose(hostname, vdi_uuid=record['vdi_uuid'])
        
        #Cleanup Disks
        transferclient.remove_vdi(hostname, record['vdi_uuid'])
        
        #Remove Downloaded File
        os.unlink(dst)

    def testFrag50Sleep10DeltaSmall(self):
        self._doTest(self.FILENAME, 50*M, 10, self.DELTA_SMALL)

    def testFrag400Sleep10DeltaSmall(self):
        self._doTest(self.FILENAME, 400*M, 10, self.DELTA_SMALL)

    def testFrag500Sleep10DeltaSmall(self):
        self._doTest(self.FILENAME, 500*M, 10, self.DELTA_SMALL)

    def testFrag400Sleep2DeltaSmall(self):
        self._doTest(self.FILENAME, 400*M, 2 , self.DELTA_SMALL)


    def testAlreadyReceivedFragSusbset(self):
        self._doTestAlreadyReceivedFragSubset(self.FILENAME, 400*M, 10)

    def testFragmentOverlap(self):
        self._doTestOverlapFrag(self.FILENAME, 400*M, 10)
