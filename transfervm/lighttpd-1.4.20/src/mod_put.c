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

#include "base.h"
#include "log.h"
#include "buffer.h"

#include "plugin.h"

#ifdef HAVE_CONFIG_H
#include "config.h"
#endif

#include "blockio.h"

/**
 * This is a simple HTTP PUT plugin with support for block device files.
 */


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

        // Nothing at the moment.
} plugin_data;



/* init the plugin data */
INIT_FUNC(mod_put_init) {
	plugin_data *p;

	p = calloc(1, sizeof(*p));

	return p;
}

/* destroy the plugin data */
FREE_FUNC(mod_put_free) {
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


	free(p);

	return HANDLER_GO_ON;
}

/* handle plugin config and check values */

SETDEFAULTS_FUNC(mod_put_set_defaults) {
	plugin_data *p = p_d;
	size_t i = 0;

	config_values_t cv[] = {
		{ "put.activate",               NULL, T_CONFIG_BOOLEAN, T_CONFIG_SCOPE_CONNECTION },  /* 0 */
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
static int mod_put_patch_connection(server *srv, connection *con, plugin_data *p) {
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

			if (buffer_is_equal_string(du->key, CONST_STR_LEN("put.activate"))) {
				PATCH(activate);
			}
		}
	}

	return 0;
}
#undef PATCH

PHYSICALPATH_FUNC(mod_put_physicalpath_handler) {
	plugin_data *p = p_d;
	data_string *range_header;

        // Ignore if somebody else handled this already
        if (con->http_status != 0) return HANDLER_GO_ON;
	if (con->mode != DIRECT) return HANDLER_GO_ON;

        // Ignore if the physical path has not been computed yet
	if (con->physical.path->used == 0) return HANDLER_GO_ON;

	// Ignore all HTTP methods but PUT
	if (con->request.http_method != HTTP_METHOD_PUT) return HANDLER_GO_ON;

        // Patch the plugin_data.conf with the current connection config settings
	mod_put_patch_connection(srv, con, p);

        // Ignore if mod_put has not been activated for the current connection
        if (p->conf.activate == 0) return HANDLER_GO_ON;

	DEBUGLOG("so", "Content-Length is", (off_t)con->request.content_length);
	DEBUGLOG("so", "Request data length is", (off_t)chunkqueue_length(con->request_content_queue));

	if (NULL != (range_header = (data_string *)array_get_element(con->request.headers, "Content-Range"))) {
		// The Content-Range header exists
		DEBUGLOG("sbs", "Content-Range header is ->", range_header->value, "<-");

		con->http_status = blockio_write_range_chunkqueue(srv,
			con->physical.path,
			con->request_content_queue,
			range_header->value,
			con->request.content_length);
	} else {
		// There is no Content-Range header, operating on the whole file
		DEBUGLOG("s", "No Content-Range header.");

		con->http_status = blockio_write_wholefile_chunkqueue(srv,
			con->physical.path,
			con->request_content_queue,
			con->request.content_length);
	}

	if (0 == con->http_status) {
		con->http_status = 200;
                con->file_finished = 1;
        }
        return HANDLER_FINISHED;
}

/* this function is called at dlopen() time and inits the callbacks */

int mod_put_plugin_init(plugin *p) {
	p->version     = LIGHTTPD_VERSION_ID;
	p->name        = buffer_init_string("put");

	p->init        = mod_put_init;
	p->handle_physical = mod_put_physicalpath_handler;
	p->set_defaults  = mod_put_set_defaults;
	p->cleanup     = mod_put_free;

	p->data        = NULL;

	return 0;
}
