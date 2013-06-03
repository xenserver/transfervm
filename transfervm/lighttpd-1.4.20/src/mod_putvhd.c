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

#include <ctype.h>
#include <stdlib.h>
#include <stdio.h>
#include <string.h>
#include <iconv.h>

#include "base.h"
#include "log.h"
#include "buffer.h"

#include "plugin.h"

#ifdef HAVE_CONFIG_H
#include "config.h"
#endif

#include "blockio.h"
#include "vhd_common.h"

/**
 * This is a plugin for uploading VHD files with support for block device 
 * files.
 */


/* plugin config for all request/connections */
typedef struct {
	unsigned short activate;
	int sparse;
} plugin_config;

typedef struct {
	PLUGIN_DATA;
        plugin_config **config_storage;
	plugin_config conf;
} plugin_data;

/* init the plugin data */
INIT_FUNC(mod_putvhd_init) {
	plugin_data *p;
	p = calloc(1, sizeof(*p));
	return p;
}

/* destroy the plugin data */
FREE_FUNC(mod_putvhd_free) {
	plugin_data *p = p_d;

	UNUSED(srv);

	if (!p) return HANDLER_GO_ON;

	if (p->config_storage) {
		size_t i;

		for (i = 0; i < srv->config_context->used; i++) {
			plugin_config *s = p->config_storage[i];
			if (!s)
				continue;
			free(s);
		}
		free(p->config_storage);
	}

	free(p);

	return HANDLER_GO_ON;
}

/* handle plugin config and check values */

SETDEFAULTS_FUNC(mod_putvhd_set_defaults) {
	plugin_data *p = p_d;
	size_t i = 0;

	config_values_t cv[] = {
		{ "putvhd.activate", NULL,
			T_CONFIG_BOOLEAN, T_CONFIG_SCOPE_CONNECTION },  /* 0 */
		{ "putvhd.sparse", NULL,
			T_CONFIG_BOOLEAN, T_CONFIG_SCOPE_CONNECTION },
		{ NULL,              NULL,
			T_CONFIG_UNSET, T_CONFIG_SCOPE_UNSET }
	};

	if (!p) return HANDLER_ERROR;

	p->config_storage = calloc(1,
			srv->config_context->used * sizeof(specific_config *));

	for (i = 0; i < srv->config_context->used; i++) {
		plugin_config *s;

		s = calloc(1, sizeof(plugin_config));

		cv[0].destination = &(s->activate);
		cv[1].destination = &(s->sparse);

		p->config_storage[i] = s;

		if (0 != config_insert_values_global(srv,
					((data_config *)
					 srv->config_context->data[i])->value,
					cv)) {
			return HANDLER_ERROR;
		}
	}

	return HANDLER_GO_ON;
}

#define PATCH(x) \
	p->conf.x = s->x;
static int mod_putvhd_patch_connection(server *srv, connection *con,
		plugin_data *p) {
	size_t i, j;
	plugin_config *s = p->config_storage[0];

	PATCH(activate);
	PATCH(sparse);

	/* skip the first, the global context */
	for (i = 1; i < srv->config_context->used; i++) {
		data_config *dc = (data_config *)srv->config_context->data[i];
		s = p->config_storage[i];

		/* condition didn't match */
		if (!config_check_cond(srv, con, dc)) continue;

		/* merge config */
		for (j = 0; j < dc->value->used; j++) {
			data_unset *du = dc->value->data[j];

			if (buffer_is_equal_string(du->key,
					CONST_STR_LEN("putvhd.activate"))) {
				PATCH(activate);
			} else if (buffer_is_equal_string(du->key,
					CONST_STR_LEN("putvhd.sparse"))) {
				PATCH(sparse);
			}
		}
	}

	return 0;
}
#undef PATCH

int parse_vhd(server *srv, chunkqueue *cq, vhd_state_t *state, 
		off_t *curr_off)
{
	int err;
	size_t request_size, size, bytes;
	off_t off;
	uint32_t vhd_blks;
	char *buf;
	vhd_context_t *vhd = &state->vhd;

	request_size = chunkqueue_avail(cq);
	DEBUGLOG("sd", "Parsing VHD", request_size);
	if (request_size < sizeof(vhd_footer_t) + sizeof(vhd_header_t)) {
		LOG("s", "ERROR: Request too small to be a VHD");
		return -EINVAL;
	}

	memset(vhd, 0, sizeof(*vhd));
	bytes = copy_bytes(srv, &vhd->footer, cq, sizeof(vhd_footer_t));
	if (bytes != sizeof(vhd_footer_t)) {
		LOG("sd", "ERROR: got incomplete footer:", bytes);
		return INTERNAL_ERROR;
	}
	*curr_off += bytes;
	vhd_footer_in(&vhd->footer);
	err = vhd_validate_footer(&vhd->footer);
	if (err) {
		LOG("sd", "ERROR: VHD footer invalid:", err);
		return err;
	}
	if (!vhd_type_dynamic(vhd)) {
		LOG("s", "ERROR: static VHD not supported");
		return -ENOSYS;
	}

	off = vhd->footer.data_offset; 
	if (off > *curr_off) {
		bytes = discard_bytes(srv, cq, off - *curr_off);
		if (bytes < off - *curr_off) {
			LOG("s", "ERROR: header offset past end of request");
			return -EINVAL;
		}
		*curr_off += bytes;
	}
	bytes = copy_bytes(srv, &vhd->header, cq, sizeof(vhd_header_t));
	if (bytes < sizeof(vhd_header_t)) {
		LOG("s", "ERROR: request does not contain entire VHD header");
		return -EINVAL;
	}
	*curr_off += bytes;
	vhd_header_in(&vhd->header);
	err = vhd_validate_header(&vhd->header);
	if (err) {
		LOG("sd", "ERROR: VHD header invalid:", err);
		return err;
	}

	vhd->spb = vhd->header.block_size >> VHD_SECTOR_SHIFT;
	vhd->bm_secs = secs_round_up_no_zero(vhd->spb >> 3);

	off = vhd->header.table_offset;
	vhd_blks = vhd->footer.curr_size >> VHD_BLOCK_SHIFT;
	LOG("sOsDsd", "VHD virt size:", vhd->footer.curr_size, "; blocks:",
			vhd_blks, "; max BAT size:", vhd->header.max_bat_size);
	if (vhd->header.max_bat_size < vhd_blks) {
		LOG("s", "ERROR: BAT smaller than VHD size!");
		return -EINVAL;
	}

	size = vhd_bytes_padded(vhd_blks * sizeof(uint32_t));
	err = posix_memalign((void **)&buf, VHD_SECTOR_SIZE, size);
	if (err) {
		LOG("sd", "ERROR: failed to allocate BAT buf:", err);
		return err;
	}

	if (off > *curr_off) {
		bytes = discard_bytes(srv, cq, off - *curr_off);
		if (bytes < off - *curr_off) {
			LOG("s", "ERROR: BAT offset past end of request");
			err = -EINVAL;
			goto cleanup;
		}
		*curr_off += bytes;
	}
	bytes = copy_bytes(srv, buf, cq, size);
	if (bytes < size) {
		LOG("s", "ERROR: request does not contain entire VHD BAT");
		err = -EINVAL;
		goto cleanup;
	}
	*curr_off += bytes;
	
	vhd->bat.spb = vhd->header.block_size >> VHD_SECTOR_SHIFT;
	vhd->bat.entries = vhd_blks;
	vhd->bat.bat = (uint32_t *)buf;
	vhd_bat_in(&vhd->bat);

	return 0;

cleanup:
	free(buf);
	return err;
}

int write_vhd(server *srv, chunkqueue *cq, vhd_state_t *state,
		buffer *filename, off_t curr_off, int zero_unalloc)
{
	off_t off;
	size_t bytes;
	int i, err;
	int blk, blks_total;
	vhd_context_t *vhd = &state->vhd;

	err = open_file(srv, filename, state);

	blks_total = get_num_allocated_blocks(vhd);
	DEBUGLOG("sdsb", "Writing", blks_total, "VHD data blocks to", filename);

	err = 0;
	blk = -1;
	for (i = 0; i < blks_total; i++) {
		blk = find_next_virt_blk(srv, vhd, curr_off, blk + 1);
		if (blk == -1) {
			LOG("sd", "ERROR: didn't find next block at", i);
			err = INTERNAL_ERROR;
			goto cleanup;
		}
		DEBUGLOG("sd", "Writing VHD block:", blk);
		off = ((off_t)vhd->bat.bat[blk] + (off_t)vhd->bm_secs) << VHD_SECTOR_SHIFT;
		bytes = discard_bytes(srv, cq, off - curr_off);
		if (bytes < off - curr_off) {
			LOG("sod", "ERROR: eof before block", blk, off);
			err = -EINVAL;
			goto cleanup;
		}
		curr_off += bytes;
		errno = 0;
		off = lseek(state->fd, blk * vhd->header.block_size, SEEK_SET);
		if (off != blk * vhd->header.block_size) {
			LOG("sdd", "ERROR: seeking to",
					blk * vhd->header.block_size, errno);
			err = INTERNAL_ERROR;
			goto cleanup;
		}

		bytes = write_bytes(srv, state->fd, cq, vhd->header.block_size);
		if (bytes < vhd->header.block_size) {
			LOG("sddo", "ERROR: incomplete block", blk, bytes,
					curr_off);
			err = -EINVAL;
			goto cleanup;
		}
		curr_off += bytes;
	}

	if (zero_unalloc)
		err = zero_unallocated(srv, state);

cleanup:
	close(state->fd);
	return err;
}

PHYSICALPATH_FUNC(mod_putvhd_physicalpath_handler) {
	plugin_data *p = p_d;
	data_string *range_header;
	int err, zero_unalloc;
	vhd_state_t state;
	off_t curr_off;

	// Ignore if somebody else handled this already
        if (con->http_status != 0)
		return HANDLER_GO_ON;
	if (con->mode != DIRECT)
		return HANDLER_GO_ON;

        // Ignore if the physical path has not been computed yet
	if (con->physical.path->used == 0)
		return HANDLER_GO_ON;

	// Ignore all HTTP methods but PUT
	if (con->request.http_method != HTTP_METHOD_PUT)
		return HANDLER_GO_ON;

	// Patch plugin_data.conf with the current connection config settings
	mod_putvhd_patch_connection(srv, con, p);

	// Ignore if mod_putvhd is not activated for the current connection
        if (p->conf.activate == 0)
		return HANDLER_GO_ON;

	zero_unalloc = 0;
	if (p->conf.sparse)
		DEBUGLOG("s", "Backend target is sparse");
	else
		zero_unalloc = 1;

	DEBUGLOG("so", "Content-Length is", (off_t)con->request.content_length);
	DEBUGLOG("sd", "Request data length is",
			chunkqueue_avail(con->request_content_queue));

	range_header =
            (data_string *)array_get_element(con->request.headers,
                                             "Content-Range");
	if (range_header != NULL) {
		// The Content-Range header exists
		LOG("s", "Content-Range not supported for VHD");
		con->http_status = 501;
		return HANDLER_FINISHED;
	}

	curr_off = 0;
	err = parse_vhd(srv, con->request_content_queue, &state, &curr_off);
	if (err)
		goto out;

	err = write_vhd(srv, con->request_content_queue, &state,
			con->physical.path, curr_off, zero_unalloc);

	free(state.vhd.bat.bat);

out:
	if (!err)
		con->http_status = 200;
	else if (err == -EINVAL)
		con->http_status = 400;
	else if (err == -EPERM)
		con->http_status = 403;
	else if (err == -EACCES)
		con->http_status = 403;
	else if (err == -ENOENT)
		con->http_status = 404;
	else if (err == -ENOMEM)
		con->http_status = 500;
	else if (err == -ENOSYS)
		con->http_status = 501;
	else if (err >= 400 && err <= 505)
		con->http_status = err;
	else if (err == INTERNAL_ERROR)
		con->http_status = 500;
	else
		con->http_status = 500;

	return HANDLER_FINISHED;
}

/* this function is called at dlopen() time and inits the callbacks */

int mod_putvhd_plugin_init(plugin *p) {
	p->version     = LIGHTTPD_VERSION_ID;
	p->name        = buffer_init_string("putvhd");

	p->init        = mod_putvhd_init;
	p->handle_physical = mod_putvhd_physicalpath_handler;
	p->set_defaults  = mod_putvhd_set_defaults;
	p->cleanup     = mod_putvhd_free;

	p->data        = NULL;

	return 0;
}
