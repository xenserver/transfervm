
import logging
import urllib2

import XenAPI


M = 1024 * 1024


def assertRaisesXenapiFailure(self, exception_name, call, *args, **kwargs):
    try:
        call(*args, **kwargs)
        self.fail('Called function %r did not raise an exception.' % call)
    except XenAPI.Failure, e:
        logging.debug('Got XenAPI Failure %s' % e)
        self.assertEquals(e.details[2], exception_name)

def assertVdiIsZeroUsingHttpGet(self, record, vdi_mb):
    # Create an URL without the HTTP username and password.
    self.assertEqual('false', record['use_ssl'], 'This assert method does not support SSL connections')

    uri = 'http://%s:%s%s' % (record['ip'], record['port'], record['url_path'])
    logging.debug('URI:') 
    logging.debug(uri)
    logging.debug('Sleeping....')
    

    auth = urllib2.HTTPPasswordMgrWithDefaultRealm()
    auth.add_password(realm=None, uri=uri, user=record['username'], passwd=record['password'])
    opener = urllib2.build_opener(urllib2.HTTPBasicAuthHandler(auth))
    vdifile = opener.open(uri)
    try:
        vdidata = vdifile.read()
    finally:
        vdifile.close()
    logging.debug('Asserting A=B')
    logging.debug(vdi_mb * M)
    logging.debug(len(vdidata))
    self.assertEqual(vdi_mb * M, len(vdidata))
    #self.assertEqual('\0' * (vdi_mb*M), vdidata) causes too much output
    if '\0' * (vdi_mb*M) != vdidata:
        f = open("check.tmp", 'w')
        f.write(vdidata)
        f.close()
        self.assertEqual("%d MB of zeros" % vdi_mb,
                         "Data downloaded with HTTP GET")
