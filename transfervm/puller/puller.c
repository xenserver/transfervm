/* Transfer VM - VPX for exposing VDIs on XenServer 
 * Copyright (C) Citrix Systems, Inc.
 * 
 * This program is free software; you can redistribute it and/or modify
 * it under the terms of the GNU General Public License as published by
 * the Free Software Foundation; either version 2 of the License, or
 * (at your option) any later version.
 * 
 * This program is distributed in the hope that it will be useful,
 * but WITHOUT ANY WARRANTY; without even the implied warranty of
 * MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
 * GNU General Public License for more details.
 *
 * You should have received a copy of the GNU General Public License along
 * with this program; if not, write to the Free Software Foundation, Inc.,
 * 51 Franklin Street, Fifth Floor, Boston, MA 02110-1301 USA.
 */

#include <assert.h>
#include <errno.h>
#include <fcntl.h>
#include <inttypes.h>
#include <netdb.h>
#include <netinet/in.h>
#include <netinet/tcp.h>
#include <signal.h>
#include <stdbool.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <strings.h>
#include <sys/socket.h>
#include <sys/types.h>
#include <unistd.h>

#include <openssl/err.h>
#include <openssl/ssl.h>

#include <base64.h>

#define BITS_PROTOCOL "{7df0354d-249b-430f-820D-3D2A9BEF4931}"

#define LITTLE_BUFSIZE 1024
#define BIG_BUFSIZE (2 << 20)

static char err_buf[LITTLE_BUFSIZE];
static BIO *bio_err = NULL;

static char *bits_session_id = NULL;


static SSL_CTX *make_ctx()
{
    SSL_library_init();
    SSL_load_error_strings();

    bio_err = BIO_new_fp(stderr, BIO_NOCLOSE);

    return SSL_CTX_new(SSLv23_method());
}


static void print_ssl_errors(char *string)
{
    BIO_printf(bio_err, "%s\n", string);
    ERR_print_errors(bio_err);
}


/*
 * Returns the fd, or -1 on failure.  Sets err_buf.
 */
static int tcp_connect(char *host, int port)
{
    struct sockaddr_in addr;
    int sock;
    struct hostent *hp = gethostbyname(host);

    if (!hp)
    {
        snprintf(err_buf, LITTLE_BUFSIZE,
                 "<value><array><data>"
                 "<value>PULLER_NO_SUCH_HOST</value>"
                 "<value>%s</value>"
                 "<value>%d</value>"
                 "</data></array></value>", host, errno);
        return -1;
    }

    memset(&addr, 0, sizeof(addr));
    addr.sin_addr = *(struct in_addr *)hp->h_addr_list[0];
    addr.sin_family = AF_INET;
    addr.sin_port = htons(port);

    if ((sock = socket(AF_INET,SOCK_STREAM, IPPROTO_TCP)) < 0)
    {
        snprintf(err_buf, LITTLE_BUFSIZE,
                 "<value><array><data>"
                 "<value>PULLER_SOCKET_FAILED</value>"
                 "<value>%s</value>"
                 "<value>%d</value>"
                 "</data></array></value>", host, errno);
        return -1;
    }
    if (connect(sock, (struct sockaddr *)&addr, sizeof(addr)) < 0)
    {
        snprintf(err_buf, LITTLE_BUFSIZE,
                 "<value><array><data>"
                 "<value>PULLER_CONNECT_FAILED</value>"
                 "<value>%s</value>"
                 "<value>%d</value>"
                 "</data></array></value>", host, errno);
        return -1;
    }
    
//    fprintf(stderr, "Connected to %s.\n", host);

    return sock;
}


/*
 * Returns an errno.  Sets err_buf.
 */
static int check_cert(SSL *ssl, char *host)
{
    long result = SSL_get_verify_result(ssl);
    
    if (result != X509_V_OK)
    {
        print_ssl_errors("check_cert");
        snprintf(err_buf, LITTLE_BUFSIZE,
                 "<value><array><data>"
                 "<value>PULLER_CERT_VERIFY_FAILED</value>"
                 "<value>%ld</value>"
                 "</data></array></value>", result);
        return EIO;
    }

    X509 *peer_cert = SSL_get_peer_certificate(ssl);
    char peer_cn[LITTLE_BUFSIZE];
    X509_NAME_get_text_by_NID(X509_get_subject_name(peer_cert),
                              NID_commonName, peer_cn, LITTLE_BUFSIZE);
    if (strcasecmp(peer_cn, host))
    {
        snprintf(err_buf, LITTLE_BUFSIZE,
                 "<value><array><data>"
                 "<value>PULLER_COMMON_NAMES_DO_NOT_MATCH</value>"
                 "<value>%s</value>"
                 "<value>%s</value>"
                 "</data></array></value>", peer_cn, host);
        return EIO;
    }

    return 0;
}


/*
 * Returns number of bytes written, or negative errno.
 */
static ssize_t write_all(int fd, char *buf, size_t len)
{
    size_t i = 0;
    while (i < len)
    {
        //fprintf(stderr, "Printing to %d %d %d %.*s.\n", fd, i, len, len - i,
        //        buf + i);
        int j = write(fd, buf + i, len - i);
        //fprintf(stderr, "Printing done %d.\n", j);
        if (j <= 0)
            return j;
        i += j;
    }
    return len;
}


/*
 * result will be malloc'd into, and must be freed by the caller.
 * Returns an errno.
 */
static int make_auth(char *username, char *password, char **result,
                     size_t *result_len)
{
    base64_encodestate state;
    size_t len = strlen(username) + strlen(password) + 2;
    char *plain = (char *)malloc(sizeof(char) * len);
    if (plain == NULL)
        return ENOMEM;
    snprintf(plain, len, "%s:%s", username, password);
    base64_init_encodestate(&state);
	
    *result = (char *)malloc(sizeof(char) * len * 2);
    if (*result == NULL)
        return ENOMEM;
    //fprintf(stderr, "Encoding %.*s\n", len - 1, plain);
    *result_len = base64_encode_block(plain, len - 1, *result, &state);
    *result_len += base64_encode_blockend(*result + *result_len, &state);
    //fprintf(stderr, "Encoded to %d %.*s\n", *result_len, *result_len, *result);

    free(plain);
	
    return 0;
}


/*
 * Returns an errno.
 */
static int make_request(char *path, char *username, char *password, char *buf,
                        size_t *len)
{
    char *auth;
    size_t auth_len;
    int err = make_auth(username, password, &auth, &auth_len);
    if (err != 0)
        return err;
    
    *len = snprintf(buf, BIG_BUFSIZE,
                    "GET %s HTTP/1.0\r\nAuthorization: Basic %.*s\r\n\r\n",
                    path, auth_len, auth);

    free(auth);

    return 0;
}


/*
 * Returns an errno.
 */
static int send_request(char *path, char *username, char *password,
                        char *buf, int src_fd)
{
    size_t len;
    int err = make_request(path, username, password, buf, &len);
    if (err != 0)
        return err;

    ssize_t slen = write_all(src_fd, buf, len);
    if (slen < 0)
    {
        return -slen;
    }
    else
    {
        return 0;
    }
}


#define INITIAL 0
#define STATUS_OK 1
#define STREAMING_NEXT 2
#define STREAMING 3

#define HTTP_200_OK "HTTP/1.0 200 OK\r\n"

/*
 * Returns an errno.  Sets err_buf.
 */
static int 
parse_response(char *buf, size_t len, int *state, off64_t *content_length,
               bool eof)
{
    if (*state == INITIAL)
    {
        if (len < strlen(HTTP_200_OK))
        {
            if (eof)
            {
                snprintf(err_buf, LITTLE_BUFSIZE,
                         "<value><array><data>"
                         "<value>PULLER_SHORT_RESPONSE</value>"
                         "<value>%.*s</value>"
                         "</data></array></value>", len, buf);
                return EIO;
            }
            else
            {
                return 0;
            }
        }

        if (0 == strncmp(buf, HTTP_200_OK, strlen(HTTP_200_OK)))
        {
            *state = STATUS_OK;
        }
        else
        {
            snprintf(err_buf, LITTLE_BUFSIZE,
                     "<value><array><data>"
                     "<value>PULLER_BAD_RESPONSE</value>"
                     "<value>%.*s</value>"
                     "</data></array></value>", len, buf);
            return EIO;
        }
    }
    
    if (*state == STATUS_OK)
    {
        if (buf[len - 4] == '\r' && buf[len - 3] == '\n' &&
            buf[len - 2] == '\r' && buf[len - 1] == '\n')
        {
            if (content_length != NULL)
            {
                buf[len - 4] = '\0';
                char *clen = strstr(buf, "Content-Length: ");
                if (clen == NULL)
                {
                    clen = strstr(buf, "content-length: ");
                }
                if (clen == NULL)
                {
                    *content_length = (off64_t)-1;
                }
                else
                {
                    *content_length =
                        (off64_t)strtoll(clen + strlen("Content-Length: "),
                                       NULL, 10);
                    fprintf(stderr, "Content-Length is %" PRIu64 ".\n",
                            *content_length);
                }
            }
            *state = STREAMING_NEXT;
        }
    }
    else if (*state == STREAMING)
    {
    }
    else
    {
        assert(false);
    }

    return 0;
}


/*
 * Returns number of bytes written, or negative errno.
 * headers may be null.
 * data may be null.
 */
static ssize_t bits_send_packet(int fd, char *path, char *packet_type,
                                char *headers, char *data, size_t data_len)
{
    char buf[LITTLE_BUFSIZE];

    size_t len =
        snprintf(buf, LITTLE_BUFSIZE,
                 "BITS_POST %s HTTP/1.0\r\n"
                 "BITS-Supported-Protocols: " BITS_PROTOCOL "\r\n"
                 "BITS-Packet-Type: %s\r\n"
                 "%s%s%s"
                 "%s"
                 "\r\n",
                 path, packet_type,
                 bits_session_id == NULL ? "" : "BITS-Session-Id: ",
                 bits_session_id == NULL ? "" : bits_session_id,
                 bits_session_id == NULL ? "" : "\r\n",
                 headers == NULL ? "" : headers);

    //fprintf(stderr, "Sending BITS: %.*s.\n", len, buf);

    int err = write_all(fd, buf, len);
    if (err < 0)
        return err;
    if (data != NULL)
    {
        int new_err = write_all(fd, data, data_len);
        if (new_err < 0)
            return new_err;
        else
            err += new_err;
    }
    return err;
}


static long bits_read_error_code(char *buf)
{
    char *code = strstr(buf, "BITS-Error-Code: ");
    if (code == NULL)
    {
        return 0;
    }
    else
    {
        long result = strtol(code + strlen("BITS-Error-Code: "), NULL, 0);
        fprintf(stderr, "BITS-Error-Code: %ld.\n", result);
        return result;
    }
}


static void bits_read_session_id(char *buf)
{
    char *id = strstr(buf, "BITS-Session-Id: ");
    if (id != NULL)
    {
        char *start = id + strlen("BITS-Session-Id: ");
        char *end = strchr(id, '\r');
        *end = '\0';
        size_t len = strlen(start) + 1;
        bits_session_id = malloc(sizeof(char) * len);
        strncpy(bits_session_id, start, len);
    }
}


/*
 * Returns an errno / BITS error code.  Sets bits_session_id on success if
 * get_session is true.
 */
static long bits_parse_ack(int fd, bool get_session)
{
    char *buf = (char *)malloc(sizeof(char) * BIG_BUFSIZE);
    size_t buf_off = 0;
    int state = INITIAL;
    long err = 0;
    while (true)
    {
        if (buf_off >= BIG_BUFSIZE - 1)
        {
            fprintf(stderr, "Overflow reading Ack\n");
            err = EIO;
            goto out;
        }

        ssize_t slen = read(fd, buf + buf_off, 1);
        if (slen < 0)
        {
            fprintf(stderr, "Reading Ack failed: %s\n", strerror(errno));
            err = errno;
            goto out;
        }

        buf_off += slen;

        err = parse_response(buf, buf_off, &state, NULL, slen == 0);
        if (err != 0)
        {
            fprintf(stderr, "Response %ld state %d.\n", err, state);
            goto out;
        }
        if (state == STREAMING_NEXT)
        {
            //fprintf(stderr, "Ack response was good.\n");
            buf[buf_off - 1] = '\0';
            err = bits_read_error_code(buf);
            if (err != 0)
                goto out;

            if (get_session)
            {
                bits_read_session_id(buf);
                if (bits_session_id == NULL)
                {
                    fprintf(stderr, "BITS-Session-Id missing\n");
                    err = EIO;
                    goto out;
                }
            }

            break;
        }
    }

out:
    free(buf);
    return err;
}


/*
 * Returns errno / BITS error code.  Sets bits_session_id on success.
 */
static long bits_create_session(int fd, char *path)
{
    ssize_t slen =
        bits_send_packet(fd, path, "Create-Session", NULL, NULL, 0);
    if (slen < 0)
        return -slen;

    return bits_parse_ack(fd, true);
}


/*
 * Returns errno / BITS error code.  Clears bits_session_id on success.
 */
static long bits_close_session(int fd, char *path)
{
    ssize_t slen =
        bits_send_packet(fd, path, "Close-Session", NULL, NULL, 0);
    if (slen < 0)
        return -slen;

    long err = bits_parse_ack(fd, false);

    free(bits_session_id);
    bits_session_id = NULL;

    return err;
}


/*
 * Returns errno / BITS error code.
 */
static long bits_send_fragment(int fd, char *path,
                               off64_t off, off64_t content_length,
                               char *chunk, size_t chunk_length)
{
    char buf[LITTLE_BUFSIZE];
    snprintf(buf, LITTLE_BUFSIZE,
             "Content-Length: %zd\r\n"
             "Content-Range: bytes %" PRId64 "-%" PRId64 "/%" PRId64 "\r\n",
             chunk_length,
             off, off + chunk_length - 1, content_length);

    ssize_t slen =
        bits_send_packet(fd, path, "Fragment", buf, chunk, chunk_length);
    if (slen < 0)
        return -slen;

    return bits_parse_ack(fd, false);
}


/*
 * Returns an errno.  Sets err_buf.  Sets bits_session_id on success.
 */
static int create_bits_session(char *dest_path)
{
    int fd = tcp_connect("localhost", 80);
    if (fd == -1)
        return EIO;
    long err = bits_create_session(fd, dest_path);
    if (err != 0)
    {
        snprintf(err_buf, LITTLE_BUFSIZE,
                 "<value><array><data>"
                 "<value>PULLER_BITS_CREATE_SESSION_FAILED</value>"
                 "<value>%lx</value>"
                 "</data></array></value>", err);
    }

    close(fd);
    return (int)err;
}


/*
 * Returns an errno.  Sets err_buf if it's not set already.  Clears
 * bits_session_id on success.
 */
static int close_bits_session(char *dest_path)
{
    if (bits_session_id == NULL)
        return 0;

    int fd = tcp_connect("localhost", 80);
    if (fd == -1)
        return EIO;
    long err = bits_close_session(fd, dest_path);
    if (err != 0 && err_buf[0] == '\0')
    {
        snprintf(err_buf, LITTLE_BUFSIZE,
                 "<value><array><data>"
                 "<value>PULLER_BITS_CLOSE_SESSION_FAILED</value>"
                 "<value>%lx</value>"
                 "</data></array></value>", err);
    }

    close(fd);
    return (int)err;
}


/*
 * Returns an errno.  Sets err_buf.
 */
static int send_bits_fragment(char *dest_path,
                              off64_t dest_off, off64_t content_length,
                              char *chunk, size_t chunk_length)
{
    int dest_fd = tcp_connect("localhost", 80);
    if (dest_fd == -1)
        return EIO;

    long err = bits_send_fragment(dest_fd, dest_path,
                                  dest_off, content_length,
                                  chunk, chunk_length);
    if (err != 0)
    {
        snprintf(err_buf, LITTLE_BUFSIZE,
                 "<value><array><data>"
                 "<value>PULLER_SEND_FRAGMENT_FAILED</value>"
                 "<value>%lx</value>"
                 "</data></array></value>", err);
    }

    close(dest_fd);
    return (int)err;
}


/*
 * Returns an errno.  Sets err_buf.
 */
static int handle_read(char *buf, char *dest_path, bool eof,
                       int *state, off64_t *content_length,
                       size_t *buf_len, off64_t *dest_off)
{
    int err;

    err = parse_response(buf, *buf_len, state, content_length, eof);
    if (err != 0)
        return err;

    if (*state == STREAMING_NEXT)
    {
        *state = STREAMING;
        *buf_len = 0;
        return 0;
    }

    if (*content_length == (off64_t)-1)
    {
        if (eof)
        {
            *content_length = *buf_len;
        }
        else
        {
            return 0;
        }
    }

    if (*state == STREAMING && *buf_len > 0)
    {
        err = send_bits_fragment(dest_path, *dest_off, *content_length,
                                 buf, *buf_len);
        if (err != 0)
            return err;

        *dest_off += *buf_len;
        *buf_len = 0;

        //fprintf(stderr, "dest_off is now %" PRId64 ".\n", *dest_off);
    }

    return err;
}


static size_t calc_to_read(int state, off64_t content_length,
                           size_t buf_off, off64_t dest_off)
{
    if (state == STREAMING)
    {
        size_t to_read = BIG_BUFSIZE - buf_off;
        if (content_length > (off64_t)-1 &&
            to_read > content_length - dest_off)
        {
            return content_length - dest_off;
        }
        else
        {
            return to_read;
        }
    }
    else
    {
        return 1;
    }
}


/*
 * Returns an errno.  Sets err_buf.
 */
static int stream_file_no_ssl(int src_fd, char *path, char *username,
                              char *password, char *dest_path)
{
    char *buf = malloc(sizeof(char) * BIG_BUFSIZE);
    int err;
    ssize_t slen;

    err = send_request(path, username, password, buf, src_fd);
    if (err != 0)
    {
        snprintf(err_buf, LITTLE_BUFSIZE,
                 "<value><array><data>"
                 "<value>PULLER_GET_WRITE_FAILED</value>"
                 "<value>%d</value>"
                 "</data></array></value>", err);
        goto out;
    }

    int state = INITIAL;
    off64_t content_length = (off64_t)-1;
    size_t buf_off = 0;
    off64_t dest_off = 0;
    while (true)
    {
        size_t to_read = calc_to_read(state, content_length,
                                      buf_off, dest_off);

        slen = read(src_fd, buf + buf_off, to_read);
        if (slen < 0)
        {
            snprintf(err_buf, LITTLE_BUFSIZE,
                     "<value><array><data>"
                     "<value>PULLER_GET_READ_FAILED</value>"
                     "<value>%d</value>"
                     "</data></array></value>", errno);
            err = errno;
            goto out;
        }
        buf_off += slen;
        if (slen == 0 || slen == to_read)
        {
            err = handle_read(buf, dest_path, slen == 0,
                              &state, &content_length,
                              &buf_off, &dest_off);
            if (err != 0)
            {
                fprintf(stderr, "handle_read failed\n");
                goto out;
            }
            if (slen == 0)
            {
                fprintf(stderr, "Complete\n");
                goto out;
            }
        }
    }

out:
    free(buf);
    return err;
}


/*
 * Returns an errno.  Sets err_buf.
 */
static int stream_file_ssl(SSL *ssl, char *path, char *username,
                           char *password, char *dest_path)
{
    char *buf = malloc(sizeof(char) * BIG_BUFSIZE);
    int err = 0;
    int n;
    size_t len;

    err = make_request(path, username, password, buf, &len);
    if (err != 0)
        goto done;

    n = SSL_write(ssl, buf, len);
    switch (SSL_get_error(ssl, n))
    {
    case SSL_ERROR_NONE:
        break;
    default:
        print_ssl_errors("SSL_write");
        snprintf(err_buf, LITTLE_BUFSIZE,
                 "<value><array><data>"
                 "<value>PULLER_SSL_WRITE_FAILED</value>"
                 "</data></array></value>");
        err = EIO;
        goto done;
    }

    int state = INITIAL;
    off64_t content_length = (off64_t)-1;
    size_t buf_off = 0;
    off64_t dest_off = 0;
    while (true)
    {
        size_t to_read = calc_to_read(state, content_length,
                                      buf_off, dest_off);

        n = SSL_read(ssl, buf + buf_off, to_read);
        switch (SSL_get_error(ssl, n))
        {
        case SSL_ERROR_NONE:
            //fprintf(stderr, "NONE.\n");
            buf_off += n;
            break;
        case SSL_ERROR_WANT_READ:
            //fprintf(stderr, "WANT_READ.\n");
            continue;
        case SSL_ERROR_ZERO_RETURN:
            //fprintf(stderr, "ZERO_RETURN.\n");
            n = 0;
            break;
        case SSL_ERROR_SYSCALL:
        default:
            print_ssl_errors("SSL_read");
            snprintf(err_buf, LITTLE_BUFSIZE,
                     "<value><array><data>"
                     "<value>PULLER_SSL_READ_FAILED</value>"
                     "</data></array></value>");
            err = EIO;
            goto done;
        }

        if (n == 0 || n == to_read)
        {
            err = handle_read(buf, dest_path, n == 0,
                              &state, &content_length,
                              &buf_off, &dest_off);
            if (err != 0)
            {
                fprintf(stderr, "handle_read failed\n");
                goto done;
            }
            if (n == 0)
            {
                fprintf(stderr, "Complete\n");
                goto done;
            }
        }
    }
    
done:
    if (1 != SSL_shutdown(ssl))
    {
        print_ssl_errors("SSL_shutdown");
        snprintf(err_buf, LITTLE_BUFSIZE,
                 "<value><array><data>"
                 "<value>PULLER_SSL_SHUTDOWN_FAILED</value>"
                 "</data></array></value>");
        err = EIO;
    }
    
    free(buf);
    return err;
}


static void usage()
{
    fprintf(stderr, "Usage: puller <src protocol> <src username> <src password> <src host> <src port> <src path> <src keyfile> <dest path>\n");
}


int main(int argc, char **argv)
{
    assert(sizeof(off64_t) == 8);

    if (argc != 9)
    {
        usage();
        printf("<value><array><data>"
               "<value>PULLER_USAGE</value>"
               "<value>%d</value>", argc);
//  Need to XML-escape these if it's going to work properly.
        for (int i = 0; i < argc; i++)
            printf("<value>%s</value>", argv[i]);
        printf("</data></array></value>");
        exit(1);
    }

    char *src_proto = argv[1];
    char *src_user = argv[2];
    char *src_pass = argv[3];
    char *src_host = argv[4];
    int src_port = atoi(argv[5]);
    char *src_path = argv[6];
    char *src_keyfile = argv[7];
    char *dest_path = argv[8];
    int err;

    signal(SIGPIPE, SIG_IGN);

    err_buf[0] = '\0';

    err = create_bits_session(dest_path);
    if (err != 0)
        goto done;

    int src_sock = tcp_connect(src_host, src_port);
    if (src_sock == -1)
    {
        err = EIO;
        goto done;
    }

    if (0 == strcmp(src_proto, "https"))
    {
        SSL_CTX *ctx = make_ctx();

        if (!SSL_CTX_load_verify_locations(ctx, src_keyfile, NULL))
        {
            print_ssl_errors("Can't read certificate file");
            usage();
            err = EINVAL;
            snprintf(err_buf, LITTLE_BUFSIZE,
                     "<value><array><data>"
                     "<value>PULLER_CANNOT_READ_CERTIFICATE</value>"
                     "<value>%s</value>"
                     "</data></array></value>", src_keyfile);
            goto done;
        }

        SSL *ssl = SSL_new(ctx);
        BIO *sbio = BIO_new_socket(src_sock, BIO_NOCLOSE);
        SSL_set_bio(ssl, sbio, sbio);

        if (SSL_connect(ssl) <= 0)
        {
            print_ssl_errors("SSL_connect");
            err = EIO;
            snprintf(err_buf, LITTLE_BUFSIZE,
                     "<value><array><data>"
                     "<value>PULLER_SSL_CONNECT_FAILED</value>"
                     "<value>%s</value>"
                     "</data></array></value>", src_host);
            goto done;
        }

        err = check_cert(ssl, src_host);
        if (err != 0)
            goto done;

        err = stream_file_ssl(ssl, src_path, src_user, src_pass, dest_path);

        SSL_free(ssl);
        SSL_CTX_free(ctx);
    }
    else
    {
        err = stream_file_no_ssl(src_sock, src_path, src_user, src_pass,
                                 dest_path);
    }

done:
    close_bits_session(dest_path);

    if (src_sock != -1)
        close(src_sock);

    fprintf(stderr, "Transfer complete.\n");

    if (err == 0)
        printf("OK");
    else
        printf("%s", err_buf);

    exit(err == 0 ? 0 : 1);
}
