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

#ifndef _BITS_COMMON_H_
#define _BITS_COMMON_H_

#include <uuid/uuid.h>

#include "base.h"

#define BITS_CONTEXT_SERVER "0x7"
#define BITS_E_INVALIDARG "0x80070057"
#define BITS_BG_E_TOO_LARGE "0x80200020"
#define BITS_PROTOCOL_MATCH "7df0354d-249b-430f-820d-3d2a9bef4931"
#define BITS_PROTOCOL_RETURN "{7df0354d-249b-430f-820d-3d2a9bef4931}"
// This BITS-Session-Id is returned for EVERY CREATE-SESSION request.
#define CREATE_SESSION_BITS_SESSION_ID "{10000001-1001-1001-1001-100000000001}"

#define UUID_STR_LEN 37
#define UUID_IN_BRACES_STR_LEN (UUID_STR_LEN + 2)

typedef enum {
	BITS_INVALID = -1, // must be -1 to match keyvalue_get_* error code
	BITS_CREATE_SESSION,
	BITS_PING,
	BITS_FRAGMENT,
	BITS_CLOSE_SESSION,
	BITS_CANCEL_SESSION
} bits_packet_t;

// Helpers for BITS message handlers
void convert_to_lowercase(char * ptr);
void set_error(server *srv, connection *con, int http_status_code,
		const char *bits_error_code);
bits_packet_t get_bits_packet_type(server *srv, connection *con);
buffer *get_bits_session_id(server *srv, connection *con);
void set_bits_session_id(server *srv, connection *con, buffer *sessionid);
int copy_bits_session_id_or_set_error(server *srv, connection *con);
int set_error_if_request_has_content(server *srv, connection *con);
void skip_to_next_alphanumeric(char ** ptr);
int set_error_if_bits_protocol_does_not_match(server *srv, connection *con);

void bits_sessions_init();
void bits_create_session(server *srv, connection *con, uuid_t uuid);
void bits_remove_session(server *srv, connection *con);

// Some BITS message handlers
void handle_ping(server *srv, connection *con, void *plugindata);

#endif // _BITS_COMMON_H_
