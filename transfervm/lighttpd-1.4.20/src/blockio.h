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

#ifndef BLOCKIO_H
#define BLOCKIO_H

#include <ctype.h>
#include <stdlib.h>

#ifdef HAVE_CONFIG_H
#include "config.h"
#endif
#ifdef HAVE_PCRE_H
# include <pcre.h>
#endif

#include "base.h"
#include "buffer.h"
#include "chunk.h"


#define LOG(format, ...) log_error_write(srv, __FILE__, __LINE__, format, __VA_ARGS__)
// do {} while(0) wrapping is necessary for cases where "else" immediately follows DEBUGLOG.
#define DEBUGLOG(format, ...) do { if (srv->srvconf.log_blockio) log_error_write(srv, __FILE__, __LINE__, format, __VA_ARGS__); } while (0)


/*
 * Code for writing HTTP requests with Content-Range into files and block devices.
 * */

// Public interface

// Writes data in the chunkqueue into the (block) file at the range specified in the Content-Range header value
// Returns 0 on success, or a suitable HTTP error code on error.
int blockio_write_range_chunkqueue(server *srv, buffer *filename, chunkqueue *cq, buffer *content_range, off_t content_length);

// Writes data in the chunkqueue into the (block) file at the range specified,
// including the consideration of the given offset into the range (range_off).
// Returns 0 and updates *range_off on success, or returns a suitable HTTP
// error code on error.
int blockio_write_range_chunkqueue_with_offset(
    server *srv, buffer *filename, chunkqueue *cq,
    off_t range_start, off_t range_end, off_t range_total, off_t *range_off,
    off_t content_length);

// Writes data in the chunkqueue into the (block) file. The file size must match Content-Length exactly.
// Returns 0 on success, or a suitable HTTP error code on error.
int blockio_write_wholefile_chunkqueue(server *srv, buffer *filename, chunkqueue *cq, off_t content_length);

ssize_t write_mem_chunk_to_fd(int fd, chunk *c, int *write_error);

// Private interface

// Returns the length of a (block) file in bytes.
// Returns 0 on success, or a suitable HTTP error code on error.
off_t blockio_size(server *srv, buffer *filename);

// Writes the data in the chunkqueue into the (block) file, starting at the given offset.
// Returns 0 on success, or a suitable HTTP error code on error.
int blockio_write(server *srv, buffer *filename, chunkqueue *cq, off_t start);

// Parses the value of the HTTP Content-Range header into its 3 parts.
// Returns 0 on success, or a suitable HTTP error code on error.
int blockio_parse_range(server *srv, buffer *http_content_range, off_t *out_start, off_t *out_end, off_t *out_total);

// Parse the value of the HTTP Range header into two parts.
// Returns 0 on success, or suitable HTTP error code on error.
int blockio_parse_http_range(server *srv, buffer *http_content_range, off_t *out_start, off_t *out_end);


// Checks that the HTTP Content-Range header values are valid for the given block device file,
// and data range matches the Content-Length header.
// Returns 0 on success, or a suitable HTTP error code on error.
int blockio_check_range(server *srv, buffer *filename, off_t range_start, off_t range_end, off_t range_total, off_t conent_length);


#endif
