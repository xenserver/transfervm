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
#include <uuid/uuid.h>

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

/**
 * This is a simple HTTP BITS plugin with support for block device files.
 * Session semantics are NOT completely implemented; all FRAGMENT data is
 * written to disk immediately.
 */

#define LOG(format, ...) log_error_write(srv, __FILE__, __LINE__, format, __VA_ARGS__)

/* plugin config for all request/connections */

typedef struct {
	unsigned short activate;
} plugin_config;

typedef struct {
	PLUGIN_DATA;

        // Plugin config storage: filled by SETDEFAULTS_FUNC based on the lighttpd conf file.
        plugin_config **config_storage;

        // Temporary plugin config for one handler call:
        // combines the values from all entries of config_storage whose
        // conditions match the current connection's properties.
	plugin_config conf;

        // All heap-allocated data used in the handlers should be held in plugin_data,
        // allocated in INIT_FUNC, deallocated in FREE_FUNC, and reused for every handler call.

        buffer *tmpbuf;
} plugin_data;



/* init the plugin data */
INIT_FUNC(mod_bits_init) {
	plugin_data *p;

	p = calloc(1, sizeof(*p));
	p->tmpbuf = buffer_init();

	return p;
}

/* destroy the plugin data */
FREE_FUNC(mod_bits_free) {
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
	free(p);


	return HANDLER_GO_ON;
}

/* handle plugin config and check values */

SETDEFAULTS_FUNC(mod_bits_set_defaults) {
	plugin_data *p = p_d;
	size_t i = 0;

	config_values_t cv[] = {
		{ "bits.activate",               NULL, T_CONFIG_BOOLEAN, T_CONFIG_SCOPE_CONNECTION },  /* 0 */
		{ NULL,                         NULL, T_CONFIG_UNSET, T_CONFIG_SCOPE_UNSET }
	};

	if (!p) return HANDLER_ERROR;

	p->config_storage = calloc(1, srv->config_context->used * sizeof(specific_config *));

	for (i = 0; i < srv->config_context->used; i++) {
		plugin_config *s;

		s = calloc(1, sizeof(plugin_config));

		cv[0].destination = &(s->activate);

		p->config_storage[i] = s;

		if (0 != config_insert_values_global(srv, ((data_config *)srv->config_context->data[i])->value, cv)) {
			return HANDLER_ERROR;
		}
	}

	return HANDLER_GO_ON;
}

#define PATCH(x) \
	p->conf.x = s->x;
static int mod_bits_patch_connection(server *srv, connection *con, plugin_data *p) {
	size_t i, j;
	plugin_config *s = p->config_storage[0];

	PATCH(activate);

	/* skip the first, the global context */
	for (i = 1; i < srv->config_context->used; i++) {
		data_config *dc = (data_config *)srv->config_context->data[i];
		s = p->config_storage[i];

		/* condition didn't match */
		if (!config_check_cond(srv, con, dc)) continue;

		/* merge config */
		for (j = 0; j < dc->value->used; j++) {
			data_unset *du = dc->value->data[j];

			if (buffer_is_equal_string(du->key, CONST_STR_LEN("bits.activate"))) {
				PATCH(activate);
			}
		}
	}

	return 0;
}
#undef PATCH


//
// BITS message handlers
//

static void handle_create_session(server *srv, connection *con,
				  void *plugindata)
{
	UNUSED(plugindata);

	uuid_t uuid;
	uuid_generate(uuid);
        bits_create_session(srv, con, uuid);
}

void handle_fragment(server *srv, connection *con, void *plugindata) {
	plugin_data *p = plugindata;
	int write_error;
	data_string *range_header;
	off_t range_start, range_end, range_total;

	if (copy_bits_session_id_or_set_error(srv, con))
		return;

	range_header = (data_string*)array_get_element(con->request.headers, "Content-Range");
	if (NULL == range_header || NULL == range_header->value || 0 == range_header->value->used) {
		set_error(srv, con, 400, BITS_E_INVALIDARG);
		return;
	}

	if (0 != blockio_parse_range(srv, range_header->value, &range_start, &range_end, &range_total)) {
		set_error(srv, con, 400, BITS_E_INVALIDARG);
		return;
	}

	write_error = blockio_write_range_chunkqueue_with_offset(
		srv, con->physical.path, con->request_content_queue,
		range_start, range_end, range_total, &con->range_offset,
		con->request.content_length);

	if (con->range_offset == 1 + range_end - range_start)
	{
		// Using the tmpbuf in plugin data to hold the temporary string representation of range_end
		buffer_reset(p->tmpbuf);
		switch (write_error) {
		case 0:
			// Return the next byte after this fragment
			buffer_append_off_t(p->tmpbuf, range_end + 1);
			break;
		case 416:
		case 501:
			// Translate more specific error codes to 400 Bad Request to match BITS spec.
			set_error(srv, con, 400, BITS_E_INVALIDARG);
			// Return the first byte of this fragment
			buffer_append_off_t(p->tmpbuf, range_start);
			break;
		default:
			set_error(srv, con, write_error, NULL);
			// Return the first byte of this fragment
			buffer_append_off_t(p->tmpbuf, range_start);
			break;
		}

		DEBUGLOG("sdsb", "BITS-Received-Content-Range header has length", p->tmpbuf->used, "and is", p->tmpbuf);
		response_header_insert(srv, con, CONST_STR_LEN("BITS-Received-Content-Range"), CONST_BUF_LEN(p->tmpbuf));
	}
	else
	{
		switch (write_error) {
		case 0:
			break;
		case 416:
		case 501:
			// Translate more specific error codes to 400 Bad Request to match BITS spec.
			set_error(srv, con, 400, BITS_E_INVALIDARG);
			// Return the first byte of this fragment
			buffer_append_off_t(p->tmpbuf, range_start);
			break;
		default:
			set_error(srv, con, write_error, NULL);
			// Return the first byte of this fragment
			buffer_append_off_t(p->tmpbuf, range_start);
			break;
		}
	}
}

void handle_close_cancel_session(server *srv, connection *con, void *plugindata) {
	UNUSED(plugindata);
	if (copy_bits_session_id_or_set_error(srv, con)) return;
	if (set_error_if_request_has_content(srv, con)) return;

	bits_remove_session(srv, con);
}


PHYSICALPATH_FUNC(mod_bits_physicalpath_handler) {
	plugin_data *p = p_d;
	bits_packet_t packet_type;

        // Ignore if somebody else handled this already
        if (con->http_status != 0) return HANDLER_GO_ON;
	if (con->mode != DIRECT) return HANDLER_GO_ON;

        // Ignore if the physical path has not been computed yet
	if (con->physical.path->used == 0) return HANDLER_GO_ON;

	// Ignore all HTTP methods but BITS_POST
	if (con->request.http_method != HTTP_METHOD_BITS_POST) return HANDLER_GO_ON;

        // Patch the plugin_data.conf with the current connection config settings
	mod_bits_patch_connection(srv, con, p);

        // Ignore if mod_bits has not been activated for the current connection
        if (p->conf.activate == 0) return HANDLER_GO_ON;

	packet_type = get_bits_packet_type(srv, con);
	switch (packet_type)
	{
	case BITS_FRAGMENT:
		handle_fragment(srv, con, p);
		if (con->http_status != 0)
		{
			LOG("sd", "Error handling fragment:", con->http_status);
                        response_header_insert(srv, con, CONST_STR_LEN("BITS-Packet-Type"), CONST_STR_LEN("Ack"));
                        response_header_insert(srv, con, CONST_STR_LEN("Content-Length"), CONST_STR_LEN("0"));
			return HANDLER_FINISHED;
		}
		if (con->request.content_length > con->range_offset)
		{
			return HANDLER_WAIT_FOR_FD;
		}
		else
		{
			con->range_offset = 0;
		}
		break;

	default:
		// Fall through to send a response.
		break;
	}

	response_header_insert(srv, con, CONST_STR_LEN("BITS-Packet-Type"), CONST_STR_LEN("Ack"));
	response_header_insert(srv, con, CONST_STR_LEN("Content-Length"), CONST_STR_LEN("0"));
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
			LOG("sds", "Should never happen: unknown BITS Packet Type", packet_type, "to switch on.");
			set_error(srv, con, 500, NULL);
	}

	if (0 == con->http_status) {
		con->http_status = 200;
		con->file_finished = 1;
	}

	DEBUGLOG("sd", "con->file_finished at mod_bits handler end:", con->file_finished);
	DEBUGLOG("sd", "HTTP Status at mod_bits handler end:", con->http_status);
        return HANDLER_FINISHED;
}

/* this function is called at dlopen() time and inits the callbacks */

int mod_bits_plugin_init(plugin *p) {
        bits_sessions_init();

	p->version     = LIGHTTPD_VERSION_ID;
	p->name        = buffer_init_string("bits");

	p->init        = mod_bits_init;
	p->handle_physical = mod_bits_physicalpath_handler;
	p->set_defaults  = mod_bits_set_defaults;
	p->cleanup     = mod_bits_free;

	p->data        = NULL;

	return 0;
}

// Local Variables:
// indent-tabs-mode: t
// c-basic-offset: 8
// End:
