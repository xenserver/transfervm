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

#define _GNU_SOURCE
#include <sys/types.h>
#include <sys/stat.h>

#include <stdlib.h>
#include <string.h>
#include <errno.h>
#include <unistd.h>
#include <stdio.h>
#include <fcntl.h>
#include <assert.h>

#ifdef HAVE_CONFIG_H
#include "config.h"
#endif

#include "blockio.h"
#include "plugin.h"
#include "buffer.h"
#include "base.h"
#include "log.h"


int blockio_write_range_chunkqueue(server *srv, buffer *filename, chunkqueue *cq, buffer *content_range, off_t content_length) {
	off_t range_start, range_end, range_total;
	int range_error;

	if (NULL == filename || NULL == cq || NULL == content_range || content_length < 0) {
		return 500;
	}
	if (chunkqueue_length(cq) != content_length) {
		LOG("s", "Chunkqueue length does not match content_length");
		return 400;
	}

	if (0 != (range_error = blockio_parse_range(srv, content_range, &range_start, &range_end, &range_total))) {
		LOG("sbs", "->", content_range, "<- is not a valid HTTP Content-Range header.");
		return range_error;
	}
	if (0 != (range_error = blockio_check_range(srv, filename, range_start, range_end, range_total, content_length))) {
		LOG("sosososb", "Content-Range", range_start, "-", range_end, "/", range_total, "is not valid for", filename);
		return range_error;
	}

	// TODO: It is possible that the file is resized or relinked here, and the size check is no longer valid.

	return blockio_write(srv, filename, cq, range_start);
}

int blockio_write_range_chunkqueue_with_offset(
    server *srv, buffer *filename, chunkqueue *cq,
    off_t range_start, off_t range_end, off_t range_total, off_t *range_off,
    off_t content_length)
{
	int range_error =
		blockio_check_range(srv, filename, range_start, range_end,
				    range_total, content_length);

	if (range_error != 0)
	{
		LOG("sosososb", "Content-Range", range_start, "-", range_end,
		    "/", range_total, "is not valid for", filename);
		return range_error;
	}

	off_t chunkqueue_len = chunkqueue_length(cq);
	if (chunkqueue_len > 1 + range_end - range_start - *range_off)
	{
		LOG("sosososo", "Chunkqueue is longer than remaining range",
		    range_start, "-", range_end, "/", range_total, "offset",
		    *range_off);
		return 400;
	}

	// TODO: It is possible that the file is resized or relinked here, and
	// the size check is no longer valid.

	int write_error = blockio_write(srv, filename, cq,
					range_start + *range_off);
	if (write_error == 0)
		*range_off += chunkqueue_len;
	return write_error;
}

int blockio_write_wholefile_chunkqueue(server *srv, buffer *filename, chunkqueue *cq, off_t content_length) {
	off_t file_size;

	if (NULL == filename || NULL == cq || content_length < 0) return 500;
	if (chunkqueue_length(cq) != content_length) return 400;
	if ((file_size = blockio_size(srv, filename)) < 0) return 403;
	if (file_size != content_length) {
            LOG("soso", "Cannot write whole file, because its length is", file_size, " but Content-Length is", content_length);
            return 416;
        }
	return blockio_write(srv, filename, cq, 0);
}


off_t blockio_size(server *srv, buffer *filename) {
	(void)srv;
	off_t size;

	if (filename->used == 0)
		return -2;

	FILE *file = fopen(filename->ptr, "rb");
	if (NULL == file)
		return -3;

	if (0 != fseeko(file, 0, SEEK_END)) {
		fclose(file);
		return -4;
	}
	size = ftello(file); // Returns -1 on error
	fclose(file);
	return size;
}

ssize_t write_mem_chunk_to_fd(int fd, chunk *c, int *write_error) {
	ssize_t bytes = write(fd, c->mem->ptr + c->offset, c->mem->used - c->offset - 1);
	if (bytes >= 0) {
		c->offset += bytes;
	} else {
		*write_error = 500;
	}
	return bytes;
}

int blockio_write(server *srv, buffer *filename, chunkqueue *cq, off_t start) {
	int fd;
	DEBUGLOG("sbso", "Checks ok, writing chunkqueue to", filename, "at offset", start);

	if (-1 == (fd = open(filename->ptr, O_WRONLY | O_BINARY))) {
		LOG("sb", "Cannot open file", filename);
		if (ENOENT == errno) return 404;
		if (EACCES == errno) return 403;
		else return 500;
	}

	if (-1 == lseek(fd, start, SEEK_SET)) {
		LOG("so", "Cannot seek to offset", start);
		close(fd);
		return 500;
	}

	// Write out all chunks
	int write_error = 0;
	chunk *c = cq->first;
	while (NULL != c && 0 == write_error) {
		ssize_t bytes_written = 0;

		if (MEM_CHUNK == c->type) {
#if 0
			DEBUGLOG("so", "Writing out MEM_CHUNK of size", (off_t)(c->mem->used - c->offset - 1));
#endif
			bytes_written = write_mem_chunk_to_fd(fd, c, &write_error);
		} else if (FILE_CHUNK == c->type) {
			LOG("s", "Found a FILE_CHUNK to write, but the server should be configured to reject any request data so large that it is written into temporary files.");
			write_error = 500;
		}

#if 0
		DEBUGLOG("sosd", "Wrote", (off_t)bytes_written, "bytes, with error code", write_error);
#endif
		if (bytes_written > 0) {
			cq->bytes_out += bytes_written;
			chunkqueue_remove_finished_chunks(cq);
			c = cq->first;
		} else {
			break;
		}
	}

	close(fd);
	return write_error;
}

void skip_whitespace(char ** ptr) {
	while (**ptr == ' ' || **ptr == '\t')
		(*ptr)++;
}

int skip_match(char ** ptr, const char * str) {
	int len = strlen(str);
	if (0 != strncmp(*ptr, str, len)) {
		return -1;
	} else {
		(*ptr) += len;
		return 0;
	}
}

off_t read_nonnegative_integer(char ** ptr) {
	char * endptr = NULL;
	off_t num = strtoll(*ptr, &endptr, 10);

	if (endptr == *ptr) {
		// No decimal characters were found
		return -1;
	} else {
		// Move ptr past the last decimal character
		*ptr = endptr;
		// If num is negative, it can be an error code too
		return num;
	}
}

int blockio_parse_range(server *srv, buffer *http_content_range, off_t *out_start, off_t *out_end, off_t *out_total) {
	(void)srv;

	off_t start, end, total;
	char *ptr;

	if (NULL == http_content_range || NULL == out_start || NULL == out_end || NULL == out_total) return 500;

	// See http://www.w3.org/Protocols/rfc2616/rfc2616-sec14.html#sec14.16
	// But we don't accept "*" in the byte ranges or instance-length, client must specify the header as
	// "bytes 89-499/1234"

	ptr = http_content_range->ptr;

	if (0 != skip_match(&ptr, "bytes ")) return 400;
	skip_whitespace(&ptr);
	if ('*' == *ptr) return 501;
	if ((start = read_nonnegative_integer(&ptr)) < 0) return 400;
	if (0 != skip_match(&ptr, "-")) return 400;
	if ('*' == *ptr) return 501;
	if ((end = read_nonnegative_integer(&ptr)) < 0) return 400;
	if (0 != skip_match(&ptr, "/")) return 400;
	if ('*' == *ptr) return 501;
	if ((total = read_nonnegative_integer(&ptr)) < 0) return 400;
	skip_whitespace(&ptr);
	// Check for extra noise at the end
	if ('\0' != *ptr) return 400;

	// Check that 0 <= start <= end < total
	if (start < 0 || end < 0 || total < 0) return 400;
	if (start > end || end >= total) return 400;

	// Content-Range matches the RFC without any "*" ranges.
	*out_start = start;
	*out_end = end;
	*out_total = total;
	return 0;
}

int blockio_parse_http_range(server *srv, buffer *http_content_range, off_t *out_start, off_t *out_end) {
        (void)srv;

        off_t start, end, total;
        char *ptr;
        DEBUGLOG("s", "Parsing http_range");
        if (NULL == http_content_range || NULL == out_start || NULL == out_end) return 500;

        ptr = http_content_range->ptr;

        if (0 != skip_match(&ptr, "bytes=")) return 400;
        if ('*' == *ptr) return 501;
        if ((start = read_nonnegative_integer(&ptr)) < 0) return 400;
        if (0 != skip_match(&ptr, "-")) return 400;
        if ('*' == *ptr) return 501;
        if ((end = read_nonnegative_integer(&ptr)) < 0) return 400;
        skip_whitespace(&ptr);
        // Check for extra noise at the end
        if ('\0' != *ptr) return 400;

        // Check that 0 <= start <= end < total
        if (start < 0 || end < 0) return 400;
        if (start > end) return 400;

        // Content-Range matches the RFC without any "*" ranges.
        *out_start = start;
        *out_end = end;
        return 0;
}



int blockio_check_range(server *srv, buffer *filename, off_t range_start, off_t range_end, off_t range_total, off_t content_length) {
	off_t file_size;

	if (NULL == filename) return 500;
	if (range_end - range_start + 1 != content_length) return 400;
	if ((file_size = blockio_size(srv, filename)) < 0) return 403;
	if (range_total > file_size) return 416;
	// If total <= file_size, and 0 <= start <= end < total, then start and end must be valid.
	return 0;
}
