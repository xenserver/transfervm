import base64
import httplib
import os
import sys
import urllib2
import logging

BITS_PROTOCOL = '{7df0354d-249b-430f-820D-3D2A9BEF4931}'
DOWNLOAD_CHUNK_SIZE = 2 * 1024 * 1024


def auth_header(username, password):
    return 'Basic ' + base64.encodestring('%s:%s' %
                                          (username, password)).strip()


def content_range_header(range_start, range_above, total):
    return 'bytes %d-%d/%d' % (range_start, range_above - 1, total)


def send_packet(conn, url_path, reqheaders, packet_type,
                session_id = None, data = None):
    reqheaders['BITS-Supported-Protocols'] = BITS_PROTOCOL
    reqheaders['BITS-Packet-Type'] = packet_type
    if session_id is not None:
        reqheaders['BITS-Session-Id'] = session_id

    conn.request('BITS_POST', url_path, data, reqheaders)
    resp = conn.getresponse()
    try:
        respheaders = dict((k.lower(), v) for (k, v) in resp.getheaders())
        #print >>sys.stderr, ('Got Response headers %r' % respheaders)

        # All BITS Acks must have no data.
        resp.read(0)

        if resp.status != 200:
            raise Exception('Request failed with status %d', resp.status)

        if 'bits-error-code' in respheaders:
            raise Exception('Request failed with BITS error %s in %s',
                            respheaders['bits-error-code'],
                            respheaders['bits-error-context'])

        return respheaders
    finally:
        resp.close()


def create_session(conn, url_path, username, password):
    reqheaders = { 'Authorization': auth_header(username, password) }
    resp = send_packet(conn, url_path, reqheaders, 'Create-Session')
    return resp['bits-session-id']


def fragment(conn, session, url_path, data, range_start, range_end,
             range_total):
    reqheaders = { 'Content-Range':
                   content_range_header(range_start, range_end, range_total),
                   'Content-Length': range_end - range_start }
    send_packet(conn, url_path, reqheaders, 'Fragment', session, data)


def close_session(conn, url_path, session):
    send_packet(conn, url_path, {}, 'Close-Session', session)


def with_session(conn, url_path, username, password, f):
    session = create_session(conn, url_path, username, password)
    try:
        return f(session)
    finally:
        close_session(conn, url_path, session)


def open_connection(proto, host, port):
    """proto: must be 'http' or 'https'"""
    port = int(port)
    return (
        proto == 'http' and
            httplib.HTTPConnection(host, port) or
            httplib.HTTPSConnection(host, port))


def close_connection(conn):
    """Nothrow guarantee."""
    try:
        conn.close()
    except Exception, exn:
        print >>sys.stderr, ('Exception when closing connection: %s' % exn)


def with_connection(proto, host, port, f):
    conn = open_connection(proto, host, port)
    try:
        return f(conn)
    finally:
        close_connection(conn)


def upload(src, proto, host, port, username, password, url_path):
    with_connection(proto, host, port,
                    lambda conn: with_session(
                        conn, url_path, username, password,
                        lambda sess: upload_(src, url_path, conn, sess)))


def upload_(src, url_path, conn, sess):
    range_total = os.stat(src).st_size
    with_file(src, 'r',
              lambda src_file: upload__(url_path, conn, sess, range_total,
                                        src_file))


def upload__(url_path, conn, sess, range_total, src_file):
    def frag_end(s, t):
        e = s + (2 << 20)
        if e > t:
            e = t
        return e

    range_start = 0
    while range_start < range_total:
        range_end = frag_end(range_start, range_total)
        data = src_file.read(range_end - range_start)
        fragment(conn, sess, url_path, data, range_start, range_end,
                 range_total)
        range_start = range_end

def download_by_range(url, username, password, dest, req_size):
    #Initial request to determine the size of the vhd
    req = urllib2.Request(url)
    req.headers['Range'] = 'bytes=%s-%s' % (0, 1)
    req.headers['Authorization'] = 'Basic %s' % base64.b64encode('%s:%s' % (username, password))
    f = urllib2.urlopen(req)
    content_range = f.headers.get('Content-Range').split('/')
    length = int(content_range[1])
    logging.debug("Length of file =%s bytes" % length)

    #Download the file in the specified request sizes where possible
    if req_size == 0:
        req_size = length
    remaining = length
    start_req = 0
    file = open(dest,'w')
    while start_req < length:
        if req_size > length - start_req:
            req_size = length - start_req
        req.headers['Range'] = 'bytes=%s-%s' % (start_req, start_req + req_size)
        logging.debug(req.headers['Range'])
        f = urllib2.urlopen(req)
        #Read into a buffer and then write to file in Chunksizes
	downloaded_length = 0
        while True:
            buf = f.read(DOWNLOAD_CHUNK_SIZE)
            if buf:
                file.write(buf)
		downloaded_length += len(buf)
            else:
                break
	logging.debug("Downloaded %s bytes" % downloaded_length)
        start_req += req_size + 1


    logging.debug("Length of file = %s" % length)




def download(proto, netloc, url_path, dest, username = None, password = None):
    with_http_connection(
        proto, netloc,
        lambda conn: download_(url_path, dest, username, password, conn))


def download_(url_path, dest, username, password, conn):
    headers = {}
    if username:
        headers['Authorization'] = \
            'Basic %s' % base64.b64encode('%s:%s' % (username, password))
    conn.request('GET', url_path, None, headers)
    response = conn.getresponse()
    if response.status != 200:
        raise Exception('%d %s' % (response.status, response.reason))

    length = response.getheader('Content-Length', -1)

    with_file(
        dest, 'w',
        lambda dest_file: download_all(response, length, dest_file))


def download_all(response, length, dest_file):
    i = 0
    while True:
        buf = response.read(DOWNLOAD_CHUNK_SIZE)
        if buf:
            dest_file.write(buf)
        else:
            return
        i += len(buf)
        if length != -1 and i >= length:
            return


def with_http_connection(proto, netloc, f):
    conn = (proto == 'https' and
            httplib.HTTPSConnection(netloc) or
            httplib.HTTPConnection(netloc))
    try:
        f(conn)
    finally:
        conn.close()


def with_file(dest_path, mode, f):
    dest = open(dest_path, mode)
    try:
        return f(dest)
    finally:
        dest.close()
