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

#include <errno.h>
#include <sys/mman.h>
#include <sys/types.h>
#include <sys/stat.h>
#include <fcntl.h>

#include "vhd_common.h"
#include "log.h"
#include "blockio.h"

/*
 * helpers
 */ 
static int write_block_sparse(server *srv, chunkqueue *cq, vhd_state_t *state,
		off_t off_in_blk, off_t file_off, off_t *curr_off)
{
	int range_bit, next_bit;
	size_t bytes, avail, curr_range, range_inc;
	off_t off;
	unsigned int curr_sec;

	avail = chunkqueue_avail(cq);
	if (avail > state->vhd.header.block_size - off_in_blk)
		avail = state->vhd.header.block_size - off_in_blk;
	next_bit = 0;
	//DEBUGLOG("sdo", "Writing sparse start:", avail, off_in_blk);

	curr_sec = off_in_blk >> VHD_SECTOR_SHIFT;
	range_bit = test_bit(state->curr_bitmap, curr_sec);

	/* the first sector could be partial */
	curr_range = ((off_t)(curr_sec + 1) << VHD_SECTOR_SHIFT) - off_in_blk;
	if (curr_range > avail)
		curr_range = avail;
	avail -= curr_range;

	do {
		while (avail) {
			next_bit = test_bit(state->curr_bitmap, curr_sec + 1);
			if (next_bit != range_bit)
				break;
			range_inc = VHD_SECTOR_SIZE;
			if (range_inc > avail)
				range_inc = avail;
			curr_range += range_inc;
			avail -= range_inc;
			curr_sec++;
		}

		/*DEBUGLOG("sdddod", "Writing sparse:", range_bit, curr_range,
				curr_sec, file_off, avail);*/
		file_off += curr_range;
		if (range_bit) {
			bytes = write_bytes(srv, state->fd, cq, curr_range);
			if (bytes != curr_range) {
				LOG("sdsd", "ERROR: wrote", bytes,
						"!=", curr_range);
				return -EIO;
			}
		} else {
			bytes = discard_bytes(srv, cq, curr_range);
			DEBUGLOG("sd", "Discarding bytes:", bytes);
			if (bytes != curr_range) {
				LOG("sdsd", "ERROR: discarded", bytes,
						"!=", curr_range);
				return -EIO;
			}
			off = lseek(state->fd, file_off, SEEK_SET);
			if (off != file_off) {
				LOG("sdd", "ERROR: seeking to", file_off, errno);
				return INTERNAL_ERROR;
			}
		}

		*curr_off += curr_range;
		range_bit = next_bit;
		curr_range = 0;
	} while (avail);

	return 0;
}

static int write_block(server *srv, chunkqueue *cq, vhd_state_t *state,
		off_t *curr_off)
{
	off_t off, blk_off_vhd, blk_off_real, off_in_blk;
	size_t bytes;
	vhd_context_t *vhd = &state->vhd;

	blk_off_vhd = (off_t)vhd->bat.bat[state->curr_virt_blk] << VHD_SECTOR_SHIFT;
	blk_off_real = (off_t)state->curr_virt_blk * (off_t)vhd->header.block_size;
	off_in_blk = (*curr_off - blk_off_vhd -
			((off_t)vhd->bm_secs << VHD_SECTOR_SHIFT));

	off = lseek(state->fd, blk_off_real + off_in_blk, SEEK_SET);
	if (off != blk_off_real + off_in_blk) {
		LOG("sdd", "ERROR: seeking to", blk_off_real + off_in_blk,
				errno);
		return INTERNAL_ERROR;
	}

	DEBUGLOG("sooo", "blk_off_vhd, blk_off_real, off_in_blk", blk_off_vhd, blk_off_real, off_in_blk);

	if (state->backend_sparse) {
	  DEBUGLOG("s", "Write block sparse");
		return write_block_sparse(srv, cq, state, off_in_blk,
				blk_off_real + off_in_blk, curr_off);
	}

	// non-sparse case: the bitmap does not matter
	bytes = write_bytes(srv, state->fd, cq, 
			vhd->header.block_size - off_in_blk);
	*curr_off += bytes;
	return 0;
}

/* for debugging */
void print_cq(server *srv, chunkqueue *cq)
{
	chunk *c;

	DEBUGLOG("sd", "Chunkqueue size:", chunkqueue_avail(cq));
	for (c = cq->first; c != NULL; c = c->next) {
		if (c->type == MEM_CHUNK)
			DEBUGLOG("sdo", " M", c->mem->used, c->offset);
		else if (c->type == FILE_CHUNK)
			DEBUGLOG("sd", " F", c->file.length);
		else
			DEBUGLOG("s", " ?");
	}
}

/*
 * public interface
 */
void reset_state(vhd_state_t *state)
{
	memset(state, 0, sizeof(*state));
	state->curr_virt_blk = -1;
	state->fd = -1;
	state->abs_off = 0;
}

size_t chunkqueue_avail(chunkqueue *cq)
{
	chunk *c;
	size_t avail = 0;

	for (c = cq->first; c != NULL; c = c->next) {
		if (c->type == MEM_CHUNK)
			avail += c->mem->used - c->offset - 1;
	}

	return avail;
}

#define OP_DISCARD 0
#define OP_COPY 1
#define OP_WRITE 2
int consume_bytes(server *srv, int op, int fd, void *dst, chunkqueue *cq,
		size_t num_bytes)
{
	chunk *c;
	size_t written, bytes_this_chunk, bytes_consumed = 0;
	int gc = 0;

	if (!num_bytes)
		return 0;

	for (c = cq->first; c != NULL; c = c->next) {
		if (c->type != MEM_CHUNK) {
			LOG("sd", "ERROR: chunk not MEM_CHUNK:", c->type);
			break;
		}
		if (c->mem->used - c->offset <= 1) {
			LOG("s", "WARNING: empty chunk");
			gc = 1;
			continue;
		}

		bytes_this_chunk = c->mem->used - c->offset - 1;
		if (bytes_this_chunk > num_bytes)
			bytes_this_chunk = num_bytes;

		if (op == OP_COPY) {
			memcpy((char *)dst + bytes_consumed,
					c->mem->ptr + c->offset,
					bytes_this_chunk);
		} else if (op == OP_WRITE) {
			errno = 0;
			written = write(fd, c->mem->ptr + c->offset,
					bytes_this_chunk);
			//cq->bytes_out += written;
			if (written != bytes_this_chunk) {
				LOG("sdsdsd", "ERROR:", errno, "wrote", written,
						"instead of", bytes_this_chunk);
				break;
			}
		}

		c->offset += bytes_this_chunk;
		if (c->mem->used - c->offset <= 1) {
			gc = 1;
		}

		bytes_consumed += bytes_this_chunk;
		num_bytes -= bytes_this_chunk;
		if (num_bytes == 0)
			break;
	}

	/*if (num_bytes)
		DEBUGLOG("sdsd", "Still need", num_bytes, "cq_len:",
				chunkqueue_avail(cq)); */

	if (gc)
		chunkqueue_remove_finished_chunks(cq);

	//TODO: Rename bytes_out to bytes_consumed
	cq->bytes_out += bytes_consumed;

	return bytes_consumed;
}

int discard_bytes(server *srv, chunkqueue *cq, size_t num_bytes)
{
	return consume_bytes(srv, OP_DISCARD, -1, NULL, cq, num_bytes);
}

int copy_bytes(server *srv, void *dst, chunkqueue *cq, size_t num_bytes)
{
	return consume_bytes(srv, OP_COPY, -1, dst, cq, num_bytes);
}

int write_bytes(server *srv, int fd, chunkqueue *cq, size_t num_bytes)
{
	return consume_bytes(srv, OP_WRITE, fd, NULL, cq, num_bytes);
}

/* Fill the buffer with available data, skipping anything before start_off.  
 * Call repeatedly until curr_off is past the end of the structure being 
 * filled, or a non-zero value is returned, indicating an error */
int fill(server *srv, chunkqueue *cq, void *buf, size_t size,
		off_t start_off, off_t *curr_off)
{
	size_t bytes, buf_off;

	if (*curr_off < start_off) {
		bytes = discard_bytes(srv, cq, start_off - *curr_off);
		DEBUGLOG("sd", "Discarding bytes:", bytes);
		*curr_off += bytes;
		return 0;
	}

	buf_off = *curr_off - start_off;
	bytes = copy_bytes(srv, ((char *)buf) + buf_off, cq, size - buf_off);
	*curr_off += bytes;

	if (*curr_off < start_off + size) {
		DEBUGLOG("s", "Filling incomplete");
	}

	return 0;
}

int get_footer(server *srv, chunkqueue *cq, vhd_state_t *state, off_t *curr_off)
{
	int err;
	vhd_context_t *vhd = &state->vhd;

	err = fill(srv, cq, &vhd->footer, sizeof(vhd_footer_t), 0, curr_off);
	if (err)
		return err;

	if (*curr_off < 0 + sizeof(vhd_footer_t))
		return 0;

	DEBUGLOG("s", "Footer all in");
	vhd_footer_in(&vhd->footer);
	err = vhd_validate_footer(&vhd->footer);
	if (err)
		LOG("sd", "ERROR: VHD footer invalid:", err);

	if (!vhd_type_dynamic(vhd)) {
		LOG("s", "ERROR: static VHDs are not supported");
		err = -EINVAL;
	}

	return err;
}

int get_header(server *srv, chunkqueue *cq, vhd_state_t *state, off_t *curr_off)
{
	int err;
	vhd_context_t *vhd;
	off_t off;
	uint32_t vhd_blks;

	vhd = &state->vhd;
	off = vhd->footer.data_offset; 
	err = fill(srv, cq, &vhd->header, sizeof(vhd_header_t), off, curr_off);
	if (err)
		return err;

	if (*curr_off < off + sizeof(vhd_header_t))
		return 0;
	
	DEBUGLOG("s", "Header all in");
	vhd_header_in(&vhd->header);
	err = vhd_validate_header(&vhd->header);
	if (err) {
		LOG("sd", "ERROR: VHD header invalid:", err);
		return err;
	}

	vhd->spb = vhd->header.block_size >> VHD_SECTOR_SHIFT;
	vhd->bm_secs = secs_round_up_no_zero(vhd->spb >> 3);
	vhd_blks = vhd->footer.curr_size >> VHD_BLOCK_SHIFT;
	vhd->bat.spb = vhd->header.block_size >> VHD_SECTOR_SHIFT;
	vhd->bat.entries = vhd_blks;
	LOG("sOsDsd", "VHD virt size:", vhd->footer.curr_size, "; blocks:",
			vhd_blks, "; max BAT size:", vhd->header.max_bat_size);
	if (vhd->header.max_bat_size < vhd_blks) {
		LOG("s", "ERROR: BAT smaller than VHD size!");
		return -EINVAL;
	}

	state->bat_buf_size = vhd_bytes_padded(vhd_blks * sizeof(uint32_t));
	err = posix_memalign((void **)&vhd->bat.bat, VHD_SECTOR_SIZE,
			state->bat_buf_size);
	if (err) {
		LOG("sd", "ERROR: failed to allocate BAT buffer:", err);
		return err;
	}

	state->curr_bitmap = malloc(vhd->bm_secs << VHD_SECTOR_SHIFT);
	if (!state->curr_bitmap) {
		LOG("sd", "ERROR: failed to allocate bitmap buffer!");
		return -ENOMEM;
	}

	return 0;
}

int get_bat(server *srv, chunkqueue *cq, vhd_state_t *state, off_t *curr_off)
{
	int err;
	vhd_context_t *vhd = &state->vhd;

	err = fill(srv, cq, vhd->bat.bat, state->bat_buf_size,
				vhd->header.table_offset, curr_off);

	if (((off_t)(*curr_off)) < vhd->header.table_offset + state->bat_buf_size)
		return 0;

	DEBUGLOG("s", "BAT all in");
	vhd_bat_in(&vhd->bat);
	state->vhd_ready = 1;

	return 0;
}

int get_bitmap(server *srv, chunkqueue *cq, vhd_state_t *state, off_t *curr_off)
{
	int err;
	vhd_context_t *vhd = &state->vhd;

	err = fill(srv, cq, state->curr_bitmap,
			vhd->bm_secs << VHD_SECTOR_SHIFT,
			(off_t)vhd->bat.bat[state->curr_virt_blk] << VHD_SECTOR_SHIFT,
			curr_off);
	return err;
}

int process_block(server *srv, chunkqueue *cq, vhd_state_t *state,
		off_t *curr_off)
{
	int err;
	vhd_context_t *vhd;
	off_t blk_off;
	unsigned int bitmap_size;
	size_t bytes;

	vhd = &state->vhd;
	blk_off = (off_t)vhd->bat.bat[state->curr_virt_blk] << VHD_SECTOR_SHIFT;

	DEBUGLOG("sod", "Current Offset:", *curr_off, state->curr_virt_blk);

	if (*curr_off < blk_off) {
		bytes = discard_bytes(srv, cq, blk_off - *curr_off);
		DEBUGLOG("s", "curr_off < blk_off");
		DEBUGLOG("sd", "Discarding bytes:", bytes);
		*curr_off += bytes;
		return 0;
	}

	bitmap_size = vhd->bm_secs << VHD_SECTOR_SHIFT;
	if (*curr_off < blk_off + bitmap_size) {
		return get_bitmap(srv, cq, state, curr_off);
	}

	if (*curr_off < blk_off + bitmap_size + vhd->header.block_size) {
	        DEBUGLOG("so", "Abs_Off", state->abs_off);
		err = write_block(srv, cq, state, curr_off);
		return err;
	}

	/* this block is done */
	state->blocks_written++;
	DEBUGLOG("sd", "Blocks written:", state->blocks_written);
	if (state->blocks_written < state->blocks_allocated) {
		state->curr_virt_blk = find_next_virt_blk(srv, vhd, *curr_off,
				state->curr_virt_blk + 1);
		DEBUGLOG("sd", "Next VHD block:", state->curr_virt_blk);
	} else {
		state->curr_virt_blk = -1;
		DEBUGLOG("s", "No more blocks");
	}

	return 0;
}

int open_file(server *srv, buffer *filename, vhd_state_t *state)
{
	off_t file_size;
	int fd;

	if (filename == NULL) {
		LOG("s", "ERROR: Filename is NULL");
		return INTERNAL_ERROR;
	}

	file_size = blockio_size(srv, filename);
	if (file_size < 0) {
		LOG("s", "ERROR: Failed to determine device size");
		return -EPERM;
	}

	if (state->vhd.footer.curr_size != (off_t)file_size) {
		LOG("soo", "ERROR: size mismatch: expected size:", file_size,
				state->vhd.footer.curr_size);
		return -EINVAL;
	}

	fd = open(filename->ptr, O_WRONLY | O_BINARY);
	if (fd == -1) {
		LOG("sbd", "ERROR: Failed to open file", filename, errno);
		return INTERNAL_ERROR;
	}

	state->fd = fd;
	return 0;
}


/* Find the virtual block number of the VHD block sitting next in the 
 * chunkqueue after curr_off. We trade memory consumption for speed here by not  
 * building a reverse BAT (which can take up to 4MB) for O(1) lookups and 
 * instead search the entire BAT for every block (in the worst case where VHD 
 * blocks are all allocated in reverse order). However, this is still O(1) for 
 * the case where the VHD is allocated sequentially.
 */
int find_next_virt_blk(server *srv, vhd_context_t *vhd, off_t curr_off,
		int blk_hint)
{
	int blk, next_blk;
	off_t off, next_off, off1;
	uint32_t i;

	(void)srv;

	next_blk = -1;
	next_off = 0;
	for (i = 0; i < vhd->bat.entries; i++) {
		blk = (blk_hint + i) % vhd->bat.entries;
		if (vhd->bat.bat[blk] == DD_BLK_UNUSED)
			continue;
		off = (off_t)vhd->bat.bat[blk] << VHD_SECTOR_SHIFT;
		//DEBUGLOG("so", "off", off);
		//LOG("so", "next_off", next_off);
		//LOG("sd", "next_blk", next_blk);
		if (off >= curr_off && (off < next_off || next_blk == -1)) {
			next_blk = blk;
			next_off = off;
			if (next_off - curr_off < vhd->header.block_size)
				return next_blk;
		}
	}
	DEBUGLOG("so", "Current Offset", curr_off);
	/* this could still be a valid block number if for some reason the VHD 
	 * blocks here have huge gaps between them (which is not explicitly 
	 * forbidden by the specs) */
	return next_blk;
}

int get_num_allocated_blocks(vhd_context_t *vhd)
{
	uint32_t i;
	int blks = 0;
	for (i = 0; i < vhd->bat.entries; i++)
		if (vhd->bat.bat[i] != DD_BLK_UNUSED)
			blks++;
	return blks;
}

#define ZERO_BUF_SIZE 512
int zero_unallocated(server *srv, vhd_state_t *state)
{
	uint32_t i, j;
	int err;
	off_t off;
	char *zeros;
	ssize_t written;
	vhd_context_t *vhd = &state->vhd;

	zeros = mmap(0, ZERO_BUF_SIZE, PROT_READ, MAP_SHARED | MAP_ANONYMOUS,
			-1, 0);
	if (zeros == MAP_FAILED) {
		LOG("s", "ERROR: allocating zero buf");
		return -errno;
	}

	err = 0;
	for (i = 0; i < vhd->bat.entries; i++) {
		if (vhd->bat.bat[i] != DD_BLK_UNUSED)
			continue;
		DEBUGLOG("sd", "Zeroing out VHD block", i);
		errno = 0;
		off = lseek(state->fd, i * vhd->header.block_size, SEEK_SET);
		if (off != i * vhd->header.block_size) {
			LOG("sdd", "ERROR: seeking to",
					i * vhd->header.block_size, errno);
			err = errno ? -errno : -EIO;
			goto done;
		}

		for (j = 0; j < vhd->header.block_size / ZERO_BUF_SIZE; j++) {
			written = write(state->fd, zeros, ZERO_BUF_SIZE);
			if (written != ZERO_BUF_SIZE) {
				LOG("sdd", "ERROR: zeroing", written, errno);
				err = errno ? -errno : -EIO;
				goto done;
			}
		}
	}
done:
	munmap(zeros, ZERO_BUF_SIZE);
	return err;
}
