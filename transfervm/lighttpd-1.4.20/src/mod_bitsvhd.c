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
#include <errno.h>

#include "base.h"
#include "log.h"
#include "buffer.h"
#include "response.h"
#include "bits_common.h"

#include "plugin.h"

#ifdef HAVE_CONFIG_H
#include "config.h"
#endif

#include "blockio.h"
#include "vhd_common.h"

/**
 * This is a HTTP BITS plugin with support for VHD files.
 */

#define LOG(format, ...) \
	log_error_write(srv, __FILE__, __LINE__, format, __VA_ARGS__)

/* plugin config for all request/connections */

typedef struct {
	unsigned short activate;
	int sparse;
} plugin_config;

typedef struct {
	PLUGIN_DATA;

	// Plugin config storage: filled by SETDEFAULTS_FUNC based on the 
	// lighttpd conf file
	plugin_config **config_storage;

        // Temporary plugin config for one handler call:
        // combines the values from all entries of config_storage whose
        // conditions match the current connection's properties.
	plugin_config conf;

	// All heap-allocated data used in the handlers should be held in 
	// plugin_data, allocated in INIT_FUNC, deallocated in FREE_FUNC, and 
	// reused for every handler call.

	buffer *tmpbuf;
	uuid_t session_id;
	vhd_state_t state;
} plugin_data;



/* init the plugin data */
INIT_FUNC(mod_bitsvhd_init) {
	plugin_data *p;

	p = calloc(1, sizeof(*p));
	p->tmpbuf = buffer_init();
	uuid_clear(p->session_id);
	reset_state(&p->state);
	return p;
}

/* destroy the plugin data */
FREE_FUNC(mod_bitsvhd_free) {
	plugin_data *p = p_d;

	UNUSED(srv);

	if (!p) return HANDLER_GO_ON;

	if (p->config_storage) {
		size_t i;

		for (i = 0; i < srv->config_context->used; i++) {
			plugin_config *s = p->config_storage[i];

			if (!s) continue;

			free(s);
		}
		free(p->config_storage);
	}

	buffer_free(p->tmpbuf);
	free(p->state.vhd.bat.bat);
	free(p->state.curr_bitmap);
	free(p);

	return HANDLER_GO_ON;
}

/* handle plugin config and check values */

SETDEFAULTS_FUNC(mod_bitsvhd_set_defaults)
{
	plugin_data *p = p_d;
	size_t i = 0;

	config_values_t cv[] = {
		{ "bitsvhd.activate", NULL,
			T_CONFIG_BOOLEAN, T_CONFIG_SCOPE_CONNECTION },  /* 0 */
		{ "bitsvhd.sparse", NULL,
			T_CONFIG_BOOLEAN, T_CONFIG_SCOPE_CONNECTION },
		{ NULL, NULL, T_CONFIG_UNSET, T_CONFIG_SCOPE_UNSET }
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

		if (config_insert_values_global(srv,
					((data_config *)srv->config_context->data[i])->value, cv) != 0) {
			return HANDLER_ERROR;
		}
	}

	return HANDLER_GO_ON;
}

#define PATCH(x) \
	p->conf.x = s->x;
static int mod_bitsvhd_patch_connection(server *srv, connection *con,
		plugin_data *p)
{
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
					CONST_STR_LEN("bitsvhd.activate"))) {
				PATCH(activate);
			} else if (buffer_is_equal_string(du->key,
					CONST_STR_LEN("bitsvhd.sparse"))) {
				PATCH(sparse);
			}
		}
	}

	return 0;
}
#undef PATCH


//
// BITS message handlers
//

static int prepare_for_write(server *srv, vhd_state_t *state, buffer *filename,
		off_t curr_off)
{
	int err;
	vhd_context_t *vhd = &state->vhd;

	err = open_file(srv, filename, state);
	if (err)
		return err;

	state->curr_virt_blk = find_next_virt_blk(srv, vhd, curr_off, 0);
	state->blocks_allocated = get_num_allocated_blocks(vhd);
	DEBUGLOG("sdsd", "VHD has", state->blocks_allocated,
			"allocated blocks; first block:", state->curr_virt_blk);
	return 0;
}

static int process_data(server *srv, connection *con, plugin_data *p,
			buffer *filename, chunkqueue *cq, off_t range_start)
{
	int err;
	size_t len;
	//off_t *abs_off;
	vhd_state_t *state;
	vhd_context_t *vhd;

	err = 0;
	state = &p->state;
	vhd = &state->vhd;
	//abs_off = range_start + con->range_offset;
	//abs_off = state->abs_off;
	DEBUGLOG("so", "Absolute Offset", state->abs_off);
	DEBUGLOG("sd", "Current Virtual Block = ", state->curr_virt_blk);
	if (state->curr_virt_blk != -1) {
		DEBUGLOG("s", "Process Block");
		err = process_block(srv, cq, state, &(state->abs_off));
		goto done;
	}

	if (state->abs_off < 0 + sizeof(vhd_footer_t)) {
		err = get_footer(srv, cq, state, &(state->abs_off));
		goto done;
	}

	if (((off_t)state->abs_off) < vhd->footer.data_offset + sizeof(vhd_header_t)) {
		err = get_header(srv, cq, state, &(state->abs_off));
		goto done;
	}

	if (((off_t)state->abs_off) < vhd->header.table_offset + state->bat_buf_size) {
		err = get_bat(srv, cq, state, &(state->abs_off));
		if (err)
			goto done;
		if (state->vhd_ready)
			err = prepare_for_write(srv, state, filename, state->abs_off);
		goto done;
	}

	if (state->blocks_written < state->blocks_allocated) {
		LOG("sdd", "BUG!", state->blocks_written,
				state->blocks_allocated);
		err = -EINVAL;
		goto done;
	}

	// TODO: we could actually validate the primary footer at the end
	len = chunkqueue_avail(cq);
	DEBUGLOG("sd", "Discarding the remainder", len);
	discard_bytes(srv, cq, len);
	state->abs_off += len;

	if (state->zero_unalloc) {
		err = zero_unallocated(srv, state);
		state->zero_unalloc = 0;
	}

done:
	con->range_offset = state->abs_off - range_start;
	return err;
}

static int get_range(server *srv, connection *con, off_t range_off,
		off_t *range_start, off_t *range_end)
{
	int err;
	data_string *range_header;
	off_t range_total;
	chunkqueue *cq = con->request_content_queue;

	range_header = (data_string*)array_get_element(con->request.headers,
			"Content-Range");
	if (!range_header || !range_header->value ||
			range_header->value->used == 0) {
		LOG("s", "ERROR: Missing range header");
		return -EINVAL;
	}

	err = blockio_parse_range(srv, range_header->value, range_start,
				range_end, &range_total);
	if (err) {
		LOG("s", "ERROR: Range value invalid");
		return -EINVAL;
	}

	if (*range_end - *range_start + 1 != con->request.content_length) {
		LOG("sososos", "Content-Range", *range_start, "-", *range_end,
		    "/", range_total, "is not valid");
		return -EINVAL;
	}

	size_t avail = chunkqueue_avail(cq);
	if (avail > *range_end - *range_start - range_off + 1) {
		LOG("sosososo(d)", "Chunkqueue is longer than remaining range",
		    *range_start, "-", *range_end, "/", range_total, "offset",
		    range_off, avail);
		return -EINVAL;
	}

	return 0;
}

static void handle_fragment(server *srv, connection *con, void *plugindata)
{
	int err;
	plugin_data *p = plugindata;
	off_t range_start, range_end;
	
	if (copy_bits_session_id_or_set_error(srv, con))
		return;

	err = get_range(srv, con, con->range_offset, &range_start, &range_end);

	if (range_start > p->state.abs_off || range_end < p->state.abs_off) {
		//BITS requests must be contiguious - a Transient error may have occured
		DEBUGLOG("sooo", "The fragment range is greater than abs_off", range_start, p->state.abs_off, range_end);
		con->http_status = 416;
		err = -EINVAL;
		goto done;
	}

	if (((con->range_offset + range_start) < p->state.abs_off) && (range_end > p->state.abs_off)){
		DEBUGLOG("sooo", "Fragment Overlaps Abs_off:", con->range_offset + range_start, p->state.abs_off, range_end);
		//Discard bytes we already have:
		//discard_bytes(srv, con->request_content_queue, p->state.abs_off - (con->range_offset + range_start)+1);

		//DEBUGLOG("sos", "Discarded", p->state.abs_off -(range_start + con->range_offset), "bytes");
		//con->range_offset = p->state.abs_off - range_start;
		//DEBUGLOG("so", "Setting range offset - ", con->range_offset);
		p->state.abs_off = con->range_offset + range_start;
		DEBUGLOG("so", "Re-adjust abs_off", p->state.abs_off);
	}
	
	/* *PREVIOUS IMPLEMENTATION OF 416 - Discards already written data*
	if ( range_end < p->state.abs_off ) {
		DEBUGLOG("soo", "The requests range has already been dealt with", range_start, range_end);
		//Set the range_offset to be the content_length, to return with a healthy 200 http_status
		con->range_offset = con->request.content_length;
		goto done;
		}*/

	DEBUGLOG("so", "Range Offset", con->range_offset);
	DEBUGLOG("soo","Handling Fragment (start/end)", range_start, range_end);
	if (err)
		goto done;

	while (1) {
		if (chunkqueue_avail(con->request_content_queue) >
		    range_end - range_start + 1 - con->range_offset) {
			LOG("sdo", "More data than we want!",
			    chunkqueue_avail(con->request_content_queue),
			    range_end - range_start + 1 - con->range_offset);
			err = -EINVAL;
			goto done;
		}

		err = process_data(srv, con, p, con->physical.path,
				   con->request_content_queue, range_start);
		if (err)
			goto done;

		if (con->range_offset >= range_end - range_start + 1 || 
		     chunkqueue_avail(con->request_content_queue) == 0){
			DEBUGLOG("sd", "Leaving for more data", chunkqueue_avail(con->request_content_queue));
			break;
		}
	}

done:
	/*
	if (con->range_offset == range_end - range_start + 1) {
		buffer_reset(p->tmpbuf);
		if (err)
			buffer_append_off_t(p->tmpbuf, range_start);
		else
			buffer_append_off_t(p->tmpbuf, range_end + 1);

		DEBUGLOG("sdb", "BITS-Received-Content-Range header length",
				p->tmpbuf->used, p->tmpbuf);
		response_header_insert(srv, con,
				CONST_STR_LEN("BITS-Received-Content-Range"),
				CONST_BUF_LEN(p->tmpbuf));
	} 

	*/
	DEBUGLOG("so", "Abs_off", p->state.abs_off);

	if (!err) {
		DEBUGLOG("s", "Resetting HTTP Status");
		con->http_status = 0;
		return;
	}

	if (con->http_status != 416 && con->http_status != 400)
		con->http_status = 400;

       
	if (con->http_status = 416) {
		buffer_reset(p->tmpbuf);
		buffer_append_off_t(p->tmpbuf, p->state.abs_off);
		response_header_insert(srv, con,
				       CONST_STR_LEN("BITS-Received-Content-Range"),
						     CONST_BUF_LEN(p->tmpbuf));
	
	 }

	set_error(srv, con, con->http_status, BITS_E_INVALIDARG);
}

static void reset_session(plugin_data *p)
{
	if (p->state.fd != -1) {
		close(p->state.fd);
		p->state.fd = -1;
	}
	free(p->state.vhd.bat.bat);
	p->state.vhd.bat.bat = NULL;
	free(p->state.curr_bitmap);
	p->state.curr_bitmap = NULL;
	reset_state(&p->state);
	uuid_clear(p->session_id);
}

static void handle_close_cancel_session(server *srv, connection *con,
		void *plugindata)
{
	plugin_data *p = (plugin_data *)plugindata;

	if (copy_bits_session_id_or_set_error(srv, con))
		return;
	if (set_error_if_request_has_content(srv, con))
		return;

	char uuid_str[UUID_STR_LEN];
	uuid_unparse(p->session_id, uuid_str);
	DEBUGLOG("ss", "Ending session", uuid_str);

	reset_session(p);
	bits_remove_session(srv, con);
}

static void handle_create_session(server *srv, connection *con,
		void *plugindata)
{
        plugin_data *data = (plugin_data *)plugindata;

	if (!uuid_is_null(data->session_id)) {
		DEBUGLOG("s", "Session changed");
		reset_session(data);
	}

	uuid_generate(data->session_id);
	bits_create_session(srv, con, data->session_id);

	if (data->conf.sparse) {
		DEBUGLOG("s", "Backend target is sparse");
		data->state.backend_sparse = 1;
	} else {
		data->state.zero_unalloc = 1;
	}
}

static int check_session(server *srv, connection *con, plugin_data *p,
		bits_packet_t packet_type)
{
	int err;
	buffer *req_session_id;
	uuid_t req_session_uuid;
	char uuid_str[UUID_STR_LEN];

	if (packet_type == BITS_PING ||
	    packet_type == BITS_CREATE_SESSION) {
		return 0;
	}

	if (uuid_is_null(p->session_id)) {
		LOG("s", "ERROR: No-one is logged in.");
		return -EINVAL;
	}

	uuid_clear(req_session_uuid);
	req_session_id = get_bits_session_id(srv, con);
	if (!req_session_id) {
		LOG("s", "ERROR: No session ID provided in request");
		return -EINVAL;
	}

	if (strlen(req_session_id->ptr) != UUID_IN_BRACES_STR_LEN -1) {
		LOG("ss", "ERROR: session ID invalid:",
		    req_session_id->ptr);
		return -EINVAL;
	}
	strncpy(uuid_str, req_session_id->ptr + 1, UUID_STR_LEN - 1);
	uuid_str[UUID_STR_LEN - 1] = '\0';
	err = uuid_parse(uuid_str, req_session_uuid);
	if (err) {
		LOG("ss", "ERROR: session ID not a valid UUID:",
		    uuid_str);
		return -EINVAL;
	}

	if (uuid_compare(p->session_id, req_session_uuid)) {
		char uuid_str2[UUID_STR_LEN];
		uuid_unparse(p->session_id, uuid_str2);
		LOG("ssss", "ERROR: Wrong session ID:",
		    req_session_id->ptr, "expect:", uuid_str2);
		return -EINVAL;
	}

	return 0;
}

PHYSICALPATH_FUNC(mod_bitsvhd_physicalpath_handler)
{
	int err;
	plugin_data *p = p_d;
	bits_packet_t packet_type;

        // Ignore if somebody else handled this already
        if (con->http_status != 0)
		return HANDLER_GO_ON;
	if (con->mode != DIRECT)
		return HANDLER_GO_ON;

        // Ignore if the physical path has not been computed yet
	if (con->physical.path->used == 0)
		return HANDLER_GO_ON;

	// Ignore all HTTP methods but BITS_POST
	if (con->request.http_method != HTTP_METHOD_BITS_POST)
		return HANDLER_GO_ON;

	// Patch the plugin_data.conf with the current connection config 
	// settings 
	mod_bitsvhd_patch_connection(srv, con, p);

        // Ignore if mod_bits has not been activated for the current connection
        if (p->conf.activate == 0)
		return HANDLER_GO_ON;

	packet_type = get_bits_packet_type(srv, con);

	err = check_session(srv, con, p, packet_type);
	if (err) {
		set_error(srv, con, 400, BITS_E_INVALIDARG);
		return HANDLER_FINISHED;
	}

	if (packet_type == BITS_FRAGMENT) {
		handle_fragment(srv, con, p);
		if (con->http_status != 0) {
			LOG("sd", "Error handling fragment:", con->http_status);
                        response_header_insert(srv, con, CONST_STR_LEN("BITS-Packet-Type"),
                                               CONST_STR_LEN("Ack"));
                        response_header_insert(srv, con, CONST_STR_LEN("Content-Length"),
                                               CONST_STR_LEN("0"));
			return HANDLER_FINISHED;
		}
		if (con->request.content_length > con->range_offset) {
			DEBUGLOG("sxdo", "con->request.content_length > con->range_offset", (int)con, con->request.content_length, con->range_offset);
			return HANDLER_WAIT_FOR_FD;
		}
		else {
			DEBUGLOG("s", "Resetting range_offset");
			con->range_offset = 0;
		}

		//Always respond with 'BITS-Received-Content-Range' for Fragment ACK
		buffer_reset(p->tmpbuf);
		buffer_append_off_t(p->tmpbuf, p->state.abs_off);
		response_header_insert(srv, con,
				       CONST_STR_LEN("BITS-Received-Content-Range"),
				       CONST_BUF_LEN(p->tmpbuf));
	}

	response_header_insert(srv, con, CONST_STR_LEN("BITS-Packet-Type"),
			CONST_STR_LEN("Ack"));
	response_header_insert(srv, con, CONST_STR_LEN("Content-Length"),
			CONST_STR_LEN("0"));
	con->parsed_response |= HTTP_CONTENT_LENGTH;

	switch (packet_type) {
		case BITS_CREATE_SESSION:
			handle_create_session(srv, con, p);
			break;
		case BITS_PING:
			handle_ping(srv, con, p);
			break;
		case BITS_FRAGMENT:
                        // Data was handled above.
			break;
		case BITS_CLOSE_SESSION:
		case BITS_CANCEL_SESSION:
			handle_close_cancel_session(srv, con, p);
			break;
		case BITS_INVALID:
			set_error(srv, con, 400, BITS_E_INVALIDARG);
			break;
		default:
			LOG("sd", "ERROR: unknown BITS Packet Type",
					packet_type);
			set_error(srv, con, 500, NULL);
	}

	if (con->http_status == 0)
		con->http_status = 200;
		con->file_finished = 1;

	DEBUGLOG("sd", "con->file_finished at mod_bitsvhd handler end:",
			con->file_finished);
	DEBUGLOG("sd", "HTTP Status at mod_bitsvhd handler end:",
			con->http_status);
        return HANDLER_FINISHED;
}

/* this function is called at dlopen() time and inits the callbacks */

int mod_bitsvhd_plugin_init(plugin *p)
{
	bits_sessions_init();

	p->version     = LIGHTTPD_VERSION_ID;
	p->name        = buffer_init_string("bitsvhd");

	p->init        = mod_bitsvhd_init;
	p->handle_physical = mod_bitsvhd_physicalpath_handler;
	p->set_defaults  = mod_bitsvhd_set_defaults;
	p->cleanup     = mod_bitsvhd_free;

	p->data        = NULL;

	return 0;
}

// Local Variables:
// indent-tabs-mode: t
// c-basic-offset: 8
// End:
