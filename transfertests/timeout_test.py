
import time
import logging
import unittest
import urllib2
import sys

import testsetup
import transferclient

SLEEP_COUNTDOWN = True

def clean_up():
    hostname = testsetup.HOST
    testsetup.clean_host(hostname)

def record_opener(record):
    uri = 'http://%s:%s%s' % (record['ip'], record['port'], record['url_path'])
    logging.debug(uri)
    auth = urllib2.HTTPPasswordMgrWithDefaultRealm()
    auth.add_password(realm=None, uri=uri, user=record['username'], passwd=record['password'])
    opener = urllib2.build_opener(urllib2.HTTPBasicAuthHandler(auth))
    return opener.open(uri)

def assert_reachable(self, record):
    vdifile = record_opener(record)
    try:
        vdidata = vdifile.read()
    finally:
        vdifile.close()
    self.assert_(len(vdidata) > 0)
    logging.debug('Still reachable.')

def assert_unreachable(self, record):
    try:
        vdifile = record_opener(record)
        try:
            vdidata = vdifile.read()
        finally:
            vdifile.close()
    except urllib2.URLError:
        logging.debug('Unreachable.')
        return
    self.fail('Did not raise URLError')

def setup_and_get_record(timeout_minutes):
    hostname, network, vdi = testsetup.setup_host_and_network(templates=1, vdi_mb=16)
    if timeout_minutes is not None:
        transferclient.expose(hostname, vdi_uuid=vdi, network_uuid=network, transfer_mode='http', timeout_minutes=str(timeout_minutes))
	logging.debug('Timeout Minutes')
	logging.debug(timeout_minutes)
    else:
        transferclient.expose(hostname, vdi_uuid=vdi, network_uuid=network, transfer_mode='http')
    record = transferclient.get_record(hostname, vdi_uuid=vdi)
    return hostname, record

def sleep(minutes):
    logging.debug('Sleeping for %d minutes...' % minutes)
    if SLEEP_COUNTDOWN:
        for i in xrange(minutes * 60, 0, -1):
            print >> sys.stderr, '%5d\r' % i,
            time.sleep(1)
    else:
        time.sleep(minutes * 60)

class TimeoutTest(unittest.TestCase):
    def testTimeoutWithoutAnyConnections(self):
        logging.debug('Test for timeout without any connections')
        hostname, record = setup_and_get_record(2)
        sleep(4)
        assert_unreachable(self, record)
        clean_up()

    def testTimeoutKeepaliveWithGet(self):
        hostname, record = setup_and_get_record(2)
        sleep(1)
        assert_reachable(self, record)
        sleep(1)
        assert_reachable(self, record)
        sleep(1)
        assert_reachable(self, record)
        sleep(1)
	assert_reachable(self, record)
        sleep(4)
        assert_unreachable(self, record)
        clean_up()
