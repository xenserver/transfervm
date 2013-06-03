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

#ifndef _VHD_H_
#define _VHD_H_

#include "base.h"

#define off64_t off_t
#include "libvhd.h"
//#include "relative-path.h"
#undef off64_t

#define INTERNAL_ERROR 1000

struct vhd_state {
	vhd_context_t vhd;
	size_t bat_buf_size;
	unsigned int blocks_allocated;

	// put only
	int vhd_ready;
	unsigned int blocks_written;
	int curr_virt_blk;
	char *curr_bitmap;
	int fd;
	int backend_sparse;
	int zero_unalloc;
        off_t abs_off;

	// get only
	char *ploc_buf; /* area holding all parent locator encodings */
	size_t ploc_buf_size;
	off_t data_off;
	off_t req_start_off;
	off_t req_end_off; /* inclusive */
	off_t total_size_vhd;
};
typedef struct vhd_state vhd_state_t;

void reset_state(vhd_state_t *state);

size_t chunkqueue_avail(chunkqueue *cq);
int discard_bytes(server *srv, chunkqueue *cq, size_t num_bytes);
int copy_bytes(server *srv, void *dst, chunkqueue *cq, size_t num_bytes);
int write_bytes(server *srv, int fd, chunkqueue *cq, size_t num_bytes);

int fill(server *srv, chunkqueue *cq, void *buf, size_t size, off_t start_off,
		off_t *curr_off);
int get_footer(server *srv, chunkqueue *cq, vhd_state_t *state,
		off_t *curr_off);
int get_header(server *srv, chunkqueue *cq, vhd_state_t *state,
		off_t *curr_off);
int get_bat(server *srv, chunkqueue *cq, vhd_state_t *state, off_t *curr_off);
int process_block(server *srv, chunkqueue *cq, vhd_state_t *state,
		off_t *curr_off);
int open_file(server *srv, buffer *filename, vhd_state_t *state);

int find_next_virt_blk(server *srv, vhd_context_t *vhd, off_t curr_off,
		int blk_hint);
int get_num_allocated_blocks(vhd_context_t *vhd);
int zero_unallocated(server *srv, vhd_state_t *state);

void print_cq(server *srv, chunkqueue *cq);
#endif // _VHD_H_
