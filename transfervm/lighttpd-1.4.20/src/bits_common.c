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

#include "connections.h"
#include "log.h"
#include "response.h"

#include "bits_common.h"

#define LOG(format, ...) log_error_write(srv, __FILE__, __LINE__, format, __VA_ARGS__)


void convert_to_lowercase(char * ptr) {
	while (*ptr) {
		*ptr = tolower(*ptr);
		++ptr;
	}
}

void set_error(server *srv, connection *con, int http_status_code, const char *bits_error_code) {
	con->http_status = http_status_code;
	if (NULL != bits_error_code) {
		response_header_insert(srv, con, CONST_STR_LEN("BITS-Error-Code"), bits_error_code, strlen(bits_error_code));
		response_header_insert(srv, con, CONST_STR_LEN("BITS-Error-Context"), CONST_STR_LEN(BITS_CONTEXT_SERVER));
	}
	//log_error_write(srv, __FILE__, __LINE__, "sd", "http_status set error", con->http_status);
	// Terminate HTTP connection
	con->file_finished = 1;
}

static keyvalue bits_packet_types[] = {
	{ BITS_CREATE_SESSION, "create-session" },
	{ BITS_PING, "ping" },
	{ BITS_FRAGMENT, "fragment" },
	{ BITS_CLOSE_SESSION, "close-session" },
	{ BITS_CANCEL_SESSION, "cancel-session" },
	// Must be last for keyvalue_get_* to work
	{ BITS_INVALID, NULL }
};

bits_packet_t get_bits_packet_type(server *srv, connection *con) {
	UNUSED(srv);
	data_string *header = (data_string*)array_get_element(con->request.headers, "BITS-Packet-Type");
	if (NULL == header || NULL == header->value || 0 == header->value->used) {
		return BITS_INVALID;
	} else {
            for (int i = 0; bits_packet_types[i].value; i++) {
		convert_to_lowercase(header->value->ptr);
                if (0 == strcmp(bits_packet_types[i].value, header->value->ptr)) {
                    return bits_packet_types[i].key;
                }
            }
            return BITS_INVALID;
	}
}

#define MAX_SESSIONS 100
static char *open_sessions[MAX_SESSIONS];

static int con_has_valid_session(server *srv, connection *con);

void bits_sessions_init()
{
	if (connection_session_validator != NULL) {
		/* Already registered */
		return;
	}
	for (int i = 0; i < MAX_SESSIONS; i++) {
		open_sessions[i] = NULL;
	}
        connection_session_validator = con_has_valid_session;
}

/*
 * This passes ownership of uuid to open_sessions.  It will be freed when the session is closed.
 */
static void add_session(server *srv, char *uuid)
{
	for (int i = 0; i < MAX_SESSIONS; i++) {
		if (open_sessions[i] == NULL) {
			open_sessions[i] = uuid;
			return;
		}
	}
	/* Evicting the first one every time isn't going to work so well, but hopefully this never happens. */
	LOG("s", "BITS session leak detected!  Evicting the first one we have.");
	open_sessions[0] = uuid;
}

static void remove_session(server *srv, char *uuid)
{
	for (int i = 0; i < MAX_SESSIONS; i++) {
		if (open_sessions[i] != NULL && strcmp(open_sessions[i], uuid) == 0) {
			free(open_sessions[i]);
			open_sessions[i] = NULL;
			return;
		}
	}
	LOG("ss", "Tried to remove a BITS session that didn't exist!", uuid);
}


void bits_remove_session(server *srv, connection *con)
{
	buffer *buf = get_bits_session_id(srv, con);
	if (buf == NULL)
		LOG("s", "BITS close/cancel-session without BITS-Session-Id!");
	else
		remove_session(srv, buf->ptr);
}

static int is_session_valid(server *srv, char *uuid)
{
	UNUSED(srv);
	for (int i = 0; i < MAX_SESSIONS; i++) {
		if (open_sessions[i] != NULL && strcmp(open_sessions[i], uuid) == 0) {
			return 1;
		}
	}
	return 0;
}

static int con_has_valid_session(server *srv, connection *con)
{
	buffer *buf = get_bits_session_id(srv, con);
	return buf == NULL ? 0 : is_session_valid(srv, buf->ptr);
}

/* mallocs and returns a stringified version of the given UUID, with braces
   around. */
static char *print_uuid_with_braces(uuid_t uuid)
{
	char *result = malloc(UUID_IN_BRACES_STR_LEN);
	result[0] = '{';
	uuid_unparse(uuid, result + 1);
	result[UUID_STR_LEN] = '}';
	result[UUID_IN_BRACES_STR_LEN - 1] = '\0';
	return result;
}

void bits_create_session(server *srv, connection *con, uuid_t uuid)
{
	if (set_error_if_bits_protocol_does_not_match(srv, con))
		return;
	if (set_error_if_request_has_content(srv, con))
		return;

	char *uuid_str = print_uuid_with_braces(uuid);

	response_header_insert(srv, con, CONST_STR_LEN("BITS-Protocol"), CONST_STR_LEN(BITS_PROTOCOL_RETURN));
	response_header_insert(srv, con, CONST_STR_LEN("BITS-Session-Id"), uuid_str, UUID_IN_BRACES_STR_LEN - 1);

	add_session(srv, uuid_str);
}

buffer *get_bits_session_id(server *srv, connection *con) {
	UNUSED(srv);
	data_string *header = (data_string*)array_get_element(con->request.headers, "BITS-Session-Id");
	if (NULL == header || NULL == header->value || 0 == header->value->used) {
		return NULL;
	} else {
		return header->value;
	}
}

void set_bits_session_id(server *srv, connection *con, buffer *sessionid) {
	if (NULL != sessionid) {
		response_header_overwrite(srv, con, CONST_STR_LEN("BITS-Session-Id"), CONST_BUF_LEN(sessionid));
	}
}

// Copies the BITS-Session-Id header from request to response. Returns 0 if successful, some other value if not.
int copy_bits_session_id_or_set_error(server *srv, connection *con) {
	buffer *buf = get_bits_session_id(srv, con);
	if (buf == NULL) {
		set_error(srv, con, 400, BITS_E_INVALIDARG);
		return -1;
	} else {
		set_bits_session_id(srv, con, buf);
		return 0;
	}
}

int set_error_if_request_has_content(server *srv, connection *con) {
	if (0 != con->request.content_length) {
		set_error(srv, con, 400, BITS_E_INVALIDARG);
		return -1;
	}
	return 0;
}

void skip_to_next_alphanumeric(char ** ptr) {
	while (0 != **ptr && isalnum(**ptr))
		++(*ptr);
	while (0 != **ptr && !isalnum(**ptr))
		++(*ptr);
}


int set_error_if_bits_protocol_does_not_match(server *srv, connection *con) {
	data_string *header = (data_string*)array_get_element(con->request.headers, "BITS-Supported-Protocols");
	if (NULL == header || NULL == header->value || 0 == header->value->used) {
		// Header missing or has no value
		set_error(srv, con, 400, BITS_E_INVALIDARG);
		return -1;
	} else {
		convert_to_lowercase(header->value->ptr);
		char * ptr = header->value->ptr;

		while (0 != *ptr) {
			if (0 == strncmp(ptr, BITS_PROTOCOL_MATCH, strlen(BITS_PROTOCOL_MATCH))) {
				// Match found
				return 0;
			}
			skip_to_next_alphanumeric(&ptr);
		}

		// No known protocol value found in the string or comma-separated list
		set_error(srv, con, 400, BITS_E_INVALIDARG);
		return -1;
	}
}

void handle_ping(server *srv, connection *con, void *plugindata) {
	UNUSED(plugindata);
	if (set_error_if_request_has_content(srv, con)) return;
	// Done. This is all there is to PING.
}
