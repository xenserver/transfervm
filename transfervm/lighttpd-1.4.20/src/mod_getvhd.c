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
#include <limits.h>
#include <stdio.h>
#include <string.h>
#include <errno.h>
#include <zlib.h>

#include "base.h"
#include "log.h"
#include "buffer.h"

#include "plugin.h"

#include "stat_cache.h"
#include "etag.h"
#include "http_chunk.h"
#include "response.h"

#include "blockio.h"
#include "vhd_common.h"

#define off64_t off_t
#include "libvhd.h"
//#include "relative-path.h"
#undef off64_t

#include <base64.h>
#define b64decode b64_pton

/**
 * This is a plugin for downloading VHD files with support for block device 
 * files.
 */

#define VHD_CREATOR_APP "tvm"

#define INTERNAL_ERROR 1000

typedef struct {
	buffer *dev;
	unsigned char *blocks;
} block_mapping_t;

/* plugin config for all request/connections */
typedef struct {
	unsigned short activate;
	buffer *blocks;
	buffer *uuid_str;
	buffer *puuid_str;
	buffer *ppath;
	unsigned short non_leaf;
	buffer *vdi_size_str;
	buffer *block_map_str;
} plugin_config;

typedef struct {
	PLUGIN_DATA;
	plugin_config **config_storage;
	plugin_config conf;
	vhd_state_t state;
	off_t vdi_size;
	block_mapping_t *block_mapping;
        int partial_request;
        buffer *shadowed_block;
} plugin_data;

/* init the plugin data */
INIT_FUNC(mod_getvhd_init) {
	plugin_data *p;
	p = calloc(1, sizeof(*p));
	reset_state(&p->state);
	p->shadowed_block = buffer_init_string("/dev/shadow");
	return p;
}

static void free_vhd_state(vhd_state_t *state)
{
	free(state->vhd.bat.bat);
	free(state->ploc_buf);
	reset_state(state);
}

static void free_block_mapping(block_mapping_t *block_mapping)
{
	if (block_mapping == NULL)
		return;
	block_mapping_t *bm = block_mapping;
	while (bm->dev != NULL) {
		buffer_free(bm->dev);
		free(bm->blocks);
		bm++;
	}
	free(block_mapping);
}

/* destroy the plugin data */
FREE_FUNC(mod_getvhd_free) {
	plugin_data *p = p_d;

	UNUSED(srv);

	if (!p) return HANDLER_GO_ON;

	if (p->config_storage) {
		size_t i;

		for (i = 0; i < srv->config_context->used; i++) {
			plugin_config *s = p->config_storage[i];
			if (!s)
				continue;
			buffer_free(s->blocks);
			buffer_free(s->uuid_str);
			buffer_free(s->puuid_str);
			buffer_free(s->ppath);
			buffer_free(s->vdi_size_str);
			buffer_free(s->block_map_str);
			free(s);
		}
		free(p->config_storage);
	}

	free_vhd_state(&p->state);
	free_block_mapping(p->block_mapping);
	buffer_free(p->shadowed_block);
	free(p);

	return HANDLER_GO_ON;
}

/* handle plugin config and check values */

int count_chars(char *s, char c)
{
	int result = 0;
	while (*s != '\0') {
		if (*s == c)
			result++;
		s++;
	}
	return result;
}

SETDEFAULTS_FUNC(mod_getvhd_set_defaults) {
	plugin_data *p = p_d;
	size_t i = 0;

	config_values_t cv[] = {
		{ "getvhd.activate",  NULL,
		  T_CONFIG_BOOLEAN, T_CONFIG_SCOPE_CONNECTION }, /* 0 */
		{ "getvhd.blocks",    NULL,
		  T_CONFIG_STRING,  T_CONFIG_SCOPE_CONNECTION }, /* 1 */
		{ "getvhd.uuid",      NULL,
		  T_CONFIG_STRING,  T_CONFIG_SCOPE_CONNECTION }, /* 2 */
		{ "getvhd.puuid",     NULL,
		  T_CONFIG_STRING,  T_CONFIG_SCOPE_CONNECTION }, /* 3 */
		{ "getvhd.ppath",     NULL,
		  T_CONFIG_STRING,  T_CONFIG_SCOPE_CONNECTION }, /* 4 */
		{ "getvhd.non_leaf",  NULL,
		  T_CONFIG_BOOLEAN, T_CONFIG_SCOPE_CONNECTION }, /* 5 */
		{ "getvhd.vdi_size",  NULL,
		  T_CONFIG_STRING,  T_CONFIG_SCOPE_CONNECTION }, /* 6 */
		{ "getvhd.block_map", NULL,
		  T_CONFIG_STRING,  T_CONFIG_SCOPE_CONNECTION }, /* 7 */
		{ NULL,               NULL,
		  T_CONFIG_UNSET, T_CONFIG_SCOPE_UNSET }
	};

	if (!p) return HANDLER_ERROR;

	p->config_storage = calloc(1,
			srv->config_context->used * sizeof(specific_config *));

	for (i = 0; i < srv->config_context->used; i++) {
		plugin_config *s;

		s = calloc(1, sizeof(plugin_config));
		s->activate = 0;
		s->blocks = buffer_init();
		s->uuid_str = buffer_init();
		s->puuid_str = buffer_init();
		s->ppath = buffer_init();
		s->non_leaf = 0;
		s->vdi_size_str = buffer_init();
		s->block_map_str = buffer_init();

		cv[0].destination = &(s->activate);
		cv[1].destination = s->blocks;
		cv[2].destination = s->uuid_str;
		cv[3].destination = s->puuid_str;
		cv[4].destination = s->ppath;
		cv[5].destination = &(s->non_leaf);
		cv[6].destination = s->vdi_size_str;
		cv[7].destination = s->block_map_str;

		p->config_storage[i] = s;

		if (config_insert_values_global(srv,
					((data_config *)
					 srv->config_context->data[i])->value,
					cv) != 0) {
			return HANDLER_ERROR;
		}
	}

	return HANDLER_GO_ON;
}

#define PATCH(x) \
	p->conf.x = s->x;
static int mod_getvhd_patch_connection(server *srv, connection *con,
		plugin_data *p) {
	size_t i, j;
	plugin_config *s = p->config_storage[0];

	PATCH(activate);
	PATCH(blocks);
	PATCH(uuid_str);
	PATCH(puuid_str);
	PATCH(ppath);
	PATCH(non_leaf);
	PATCH(vdi_size_str);
	PATCH(block_map_str);

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
					CONST_STR_LEN("getvhd.activate"))) {
				PATCH(activate);
			} else if (buffer_is_equal_string(du->key,
					CONST_STR_LEN("getvhd.blocks"))) {
				PATCH(blocks);
			} else if (buffer_is_equal_string(du->key,
					CONST_STR_LEN("getvhd.uuid"))) {
				PATCH(uuid_str);
			} else if (buffer_is_equal_string(du->key,
					CONST_STR_LEN("getvhd.puuid"))) {
				PATCH(puuid_str);
			} else if (buffer_is_equal_string(du->key,
					CONST_STR_LEN("getvhd.ppath"))) {
				PATCH(ppath);
			} else if (buffer_is_equal_string(du->key,
					CONST_STR_LEN("getvhd.non_leaf"))) {
				PATCH(non_leaf);
			} else if (buffer_is_equal_string(du->key,
					CONST_STR_LEN("getvhd.vdi_size"))) {
				PATCH(vdi_size_str);
			} else if (buffer_is_equal_string(du->key,
					CONST_STR_LEN("getvhd.block_map"))) {
				PATCH(block_map_str);
			}
		}
	}

	return 0;
}
#undef PATCH


#define MAX_ZLIB_EXPANSION 1.03
/* base64-decode & uncompress the bitmap stored in param_str. The caller must 
 * free it unless we return error. */
int init_blocks(server *srv, off_t size, char *param_str,
		unsigned char **bitmap)
{
	int err, size_compressed;
	unsigned int num_blocks, buf_size, size_bitmap;
	unsigned char *buf_compressed;
	z_stream strm;

	num_blocks = size >> VHD_BLOCK_SHIFT;
	size_bitmap = num_blocks >> 3;
	if (size_bitmap << 3 < num_blocks)
		size_bitmap++;
	DEBUGLOG("sd", "Bitmap size", size_bitmap);

	buf_size = MAX((size_bitmap * MAX_ZLIB_EXPANSION), 128);

	*bitmap = malloc(size_bitmap);
	if (!*bitmap)
		return -ENOMEM;

	memset(*bitmap, 0, size_bitmap);

	if (strlen(param_str) == 0) {
		LOG("s", "No blocks specified, will return everything");
		memset(*bitmap, 0xff, size_bitmap);
		return 0;
	}

	/* b64decode & decompress the bitmap string param */
	buf_compressed = malloc(buf_size);
	if (!buf_compressed) {
		LOG("sd", "ERROR: malloc buf_compressed", buf_size);
		err = -ENOMEM;
		goto out;
	}

	DEBUGLOG("s", "Decoding param string");
	size_compressed = b64decode(param_str, buf_compressed, buf_size);
	if (size_compressed <= 0) {
		LOG("sd", "ERROR: b64decode returned", size_compressed);
		err = -EINVAL;
		goto out;
	}

	DEBUGLOG("sd", "Decompressing param string", size_compressed);
	strm.zalloc = Z_NULL;
	strm.zfree = Z_NULL;
	strm.opaque = Z_NULL;
	err = inflateInit(&strm);
	if (err != Z_OK) {
		LOG("sd", "ERROR: zlib:inflateInit", err);
		err = INTERNAL_ERROR;
		goto out;
	}
	strm.next_in = buf_compressed;
	strm.avail_in = size_compressed;
	strm.next_out = *bitmap;
	strm.avail_out = size_bitmap;
	
	err = inflate(&strm, Z_FINISH);
	if (err != Z_STREAM_END) {
		if (err == Z_OK) {
			LOG("s", "ERROR: zlib:inflate: param bitmap too large");
			err = -EINVAL;
		} else {
			LOG("sd", "ERROR: zlib:inflate", err);
			err = INTERNAL_ERROR;
		}
		inflateEnd(&strm);
		goto out;
	}

	err = inflateEnd(&strm);
	if (err != Z_OK) {
		LOG("s", "ERROR: zlib:inflateEnd", err);
		err = INTERNAL_ERROR;
		goto out;
	}

	if (strm.total_out != size_bitmap) {
		LOG("s", "ERROR: wrong bitmap size", strm.total_out);
		err = -EINVAL;
		goto out;
	}

	err = 0;

out:
	free(buf_compressed);
	if (err) {
		free(*bitmap);
		*bitmap = NULL;
	}

	return err;
}

int init_block_mapping(server *srv, plugin_data *p, off_t size) {
	char *block_map_str = NULL;
	block_mapping_t *map = NULL;
	int err = 0;
	char *bm = p->conf.block_map_str->ptr;

	DEBUGLOG("s", "init_block_mapping");

	if (bm == NULL || *bm == '\0') {
		/* No mapping, nothing to do */
		DEBUGLOG("s", "No block_mapping");
		return 0;
	}

	block_map_str = strdup(bm);
	if (block_map_str == NULL) {
		LOG("s", "ERROR: ENOMEM: strdup(block_map_str)");
		err = -ENOMEM;
		goto out;
	}

	int mapping_count = count_chars(block_map_str, ';') + 1;

	DEBUGLOG("sd", "mapping_count is", mapping_count);

	/* The +1 allows for a sentinel */
	map = calloc(sizeof(block_mapping_t), mapping_count + 1);
	if (map == NULL) {
		LOG("sd", "ERROR: ENOMEM: calloc block_mapping",
		    mapping_count + 1);
		err = -ENOMEM;
		goto out;
	}

	char *str = block_map_str;
	for (int i = 0; i < mapping_count; i++) {
		char *semi = strchr(str, ';');
		if (semi != NULL)
			*semi = '\0';
		char *colon = strchr(str, ':');
		if (colon == NULL) {
			LOG("ss", "ERROR: Missing colon in block_map",
			    str);
			err = -EINVAL;
			goto out;
		}
		*colon = '\0';
		map[i].dev = buffer_init();
		buffer_append_string(map[i].dev, "/dev/");
		buffer_append_string(map[i].dev, str);
		DEBUGLOG("sss", "Parsed block_map", map[i].dev->ptr,
			 colon + 1);
		err = init_blocks(srv, size, colon + 1, &map[i].blocks);
		if (err) {
			goto out;
		}
		str = semi + 1;
	}

out:
	free(block_map_str);
	if (err) {
		DEBUGLOG("s", "init_block_mapping failed");
		free_block_mapping(map);
	}
	else {
		DEBUGLOG("s", "init_block_mapping done");
		p->block_mapping = map;
	}
	return err;
}

int init_parent_locators(server *srv, vhd_state_t *state, char *parent_path)
{
	int i, err;
	off64_t off;
	uint32_t code;
	int mac_len, win_len, len, mac_size, win_size, size, buf_size, buf_off;
	char *relative_path, *mac_enc, *win_enc, *encoded;

	relative_path = NULL;
	mac_enc       = NULL;
	win_enc       = NULL;
	mac_len       = 0;
	win_len       = 0;

	err = 0;
	//relative_path = relative_path_to(vhd->file, parent_path, &err); TODO
	relative_path = parent_path;
	if (!relative_path || err) {
		LOG("s", "ERROR: computing the relative path");
		err = (err ? err : -EINVAL);
		goto out;
	}

	err = vhd_macx_encode_location(relative_path, &mac_enc, &mac_len);
	if (err) {
		LOG("s", "ERROR: encoding to PLAT_CODE_MACX");
		goto out;
	}

	err = vhd_w2u_encode_location(relative_path, &win_enc, &win_len);
	if (err) {
		LOG("s", "ERROR: encoding to PLAT_CODE_W2RU");
		goto out;
	}

	mac_size = vhd_bytes_padded(mac_len);
	win_size = vhd_bytes_padded(win_len);
	buf_size = mac_size + win_size + win_size;

	void *buf;
	err = posix_memalign(&buf, VHD_SECTOR_SIZE, buf_size);
	if (err) {
		err = -err;
		goto out;
	}
	state->ploc_buf = buf;
	memset(state->ploc_buf, 0, buf_size);
	state->ploc_buf_size = buf_size;

	off = state->data_off;
	code = PLAT_CODE_NONE;
	encoded = NULL;
	len = 0;
	size = 0;
	buf_off = 0;
	for (i = 0; i < 3; i++) {
		switch (i) {
		case 0:
			code = PLAT_CODE_MACX;
			encoded = mac_enc;
			len = mac_len;
			size = mac_size;
			break;
		case 1:
			code = PLAT_CODE_W2KU;
			encoded = win_enc;
			len = win_len;
			size = win_size;
			break;
		case 2:
			code = PLAT_CODE_W2RU;
			encoded = win_enc;
			len = win_len;
			size = win_size;
			break;
		}

		memcpy(state->ploc_buf + buf_off, encoded, len);
		state->vhd.header.loc[i].code = code;
		state->vhd.header.loc[i].data_len = len;
		state->vhd.header.loc[i].data_space = size; 
		state->vhd.header.loc[i].data_offset = off;

		buf_off += size;
		off += size;
	}
	state->data_off = off;

out:
	//free(relative_path);
	free(mac_enc);
	free(win_enc);

	if (err)
		LOG("sd", "ERROR: code", err);
	return err;
}

#define BITMASK 0x80
int init_bat(server *srv, vhd_state_t *state, unsigned char *blocks)
{
	int err;
	size_t bytes;
	unsigned int i;
	off_t off;
	vhd_context_t *vhd = &state->vhd;

	bytes = vhd_bytes_padded(vhd->header.max_bat_size * sizeof(uint32_t));

	void *buf;
	err = posix_memalign(&buf, VHD_SECTOR_SIZE, bytes);
	if (err) {
		return err;
	}
	vhd->bat.bat = buf;

	state->bat_buf_size = bytes;
	vhd->bat.entries = vhd->header.max_bat_size;
	vhd->bat.spb     = vhd->spb;
	DEBUGLOG("sdd", "BAT size:", vhd->bat.entries, state->bat_buf_size);

	off = state->data_off >> VHD_SECTOR_SHIFT;
	memset(vhd->bat.bat, 0, bytes);
	for (i = 0; i < vhd->header.max_bat_size; i++) {
		if (test_bit((char *)blocks, i)) {
			DEBUGLOG("sdso", "Data block", i, "is at sec", off);
			vhd->bat.bat[i] = off;
			off += vhd->bat.spb + vhd->bm_secs;
			state->blocks_allocated++;
		} else {
			vhd->bat.bat[i] = DD_BLK_UNUSED;
		}
	}
	return 0;
}

int init_vhd(server *srv, vhd_state_t *state, off_t size, uuid_t uuid,
	     uuid_t parent_uuid, char *path, char *parent_path,
	     unsigned char *blocks)
{
	int err;
	uint32_t type;
	vhd_context_t *vhd = &state->vhd;
		
	type = HD_TYPE_DYNAMIC;
	if (!uuid_is_null(parent_uuid))
		type = HD_TYPE_DIFF;

	DEBUGLOG("sd", "Creating VHD of type", type);

	memcpy(vhd->footer.cookie, HD_COOKIE, sizeof(vhd->footer.cookie));
	vhd->footer.features     = HD_RESERVED;
	vhd->footer.ff_version   = HD_FF_VERSION;
	vhd->footer.timestamp    = vhd_time(time(NULL));
	vhd->footer.crtr_ver     = VHD_CURRENT_VERSION;
	vhd->footer.crtr_os      = 0x00000000;
	vhd->footer.orig_size    = size;
	vhd->footer.curr_size    = size;
	vhd->footer.geometry     = vhd_chs(size);
	vhd->footer.type         = type;
	vhd->footer.saved        = 0;
	vhd->footer.data_offset  = VHD_SECTOR_SIZE;
	strcpy(vhd->footer.crtr_app, VHD_CREATOR_APP);
	uuid_copy(vhd->footer.uuid, uuid);

	memcpy(vhd->header.cookie, DD_COOKIE, sizeof(vhd->header.cookie));
	vhd->header.data_offset  = (off_t)-1;
	vhd->header.table_offset = VHD_SECTOR_SIZE * 3; /* 1 ftr + 2 hdr */
	vhd->header.hdr_ver      = DD_VERSION;
	vhd->header.block_size   = VHD_BLOCK_SIZE;
	vhd->header.prt_ts       = 0;
	vhd->header.res1         = 0;
	vhd->header.max_bat_size = (vhd->footer.curr_size +
			VHD_BLOCK_SIZE - 1) >> VHD_BLOCK_SHIFT;

	vhd->file    = path;
	vhd->spb     = vhd->header.block_size >> VHD_SECTOR_SHIFT;
	vhd->bm_secs = secs_round_up_no_zero(vhd->spb >> 3);
	/* calculate offset for the next structure (parent locator data or data 
	 * blocks in this case, not batmap) */
	err = vhd_batmap_header_offset(vhd, &state->data_off);
	if (err)
		return err;

	if (vhd->footer.type == HD_TYPE_DIFF) {
		DEBUGLOG("s", "Initializing VHD parent");
		vhd->header.prt_ts = vhd_time(time(NULL));
		uuid_copy(vhd->header.prt_uuid, parent_uuid);

		err = vhd_initialize_header_parent_name(vhd, parent_path);
		if (err)
			return err;

		err = init_parent_locators(srv, state, parent_path);
		if (err)
			return err;
	}

	err = init_bat(srv, state, blocks);
	if (err)
		return err;

	vhd->footer.checksum = vhd_checksum_footer(&vhd->footer);
	err = vhd_validate_footer(&vhd->footer);
	if (err)
		return err;

	vhd->header.checksum = vhd_checksum_header(&vhd->header);
	err = vhd_validate_header(&vhd->header);
	if (err)
		return err;

	state->total_size_vhd = state->data_off +
		(off_t)state->blocks_allocated * (off_t)(vhd->header.block_size +
				((off_t)vhd->bm_secs << VHD_SECTOR_SHIFT)) +
		(off_t)sizeof(vhd_footer_t);
	DEBUGLOG("so", "Data offset", state->data_off);
	DEBUGLOG("sd", "Blocks Allocated", state->blocks_allocated);
	DEBUGLOG("sd", "Header block size", vhd->header.block_size);
	DEBUGLOG("sd", "Bitmap sectors", ((off_t)vhd->bm_secs << VHD_SECTOR_SHIFT));
	DEBUGLOG("sd", "Size of the VHD footer", sizeof(vhd_footer_t));
	DEBUGLOG("so", "Total VHD size:", state->total_size_vhd);

	return 0;
}

static int init_vhd_from_params(server *srv, plugin_data *p,
				vhd_state_t *state, off_t size, uuid_t uuid)
{
	int err = 0;
	unsigned char *blocks = NULL;
	uuid_t parent_uuid;
	char *path, *parent_path;

	err = init_blocks(srv, size, p->conf.blocks->ptr, &blocks);
	if (err)
		goto out;

	uuid_clear(parent_uuid);
	if (strlen(p->conf.puuid_str->ptr) > 0) {
		DEBUGLOG("ss", "VHD puuid:", p->conf.puuid_str->ptr);
		err = uuid_parse(p->conf.puuid_str->ptr, parent_uuid);
		if (err) {
			LOG("ss", "ERROR: invalid puuid",
			    p->conf.puuid_str->ptr);
			err = -EINVAL;
			goto out;
		}
	}

	path = NULL;
	parent_path = NULL;
	if (strlen(p->conf.ppath->ptr) > 0)
		parent_path = p->conf.ppath->ptr;
	if (!uuid_is_null(parent_uuid) && !parent_path) {
		LOG("s", "ERROR: parent path empty");
		err = -EINVAL;
		goto out;
	}

	err = init_vhd(srv, state, size, uuid, parent_uuid, path,
		       parent_path, blocks);
	if (err)
		goto out;

	err = init_block_mapping(srv, p, size);
	if (err)
		goto out;

out:
	free(blocks);
	return err;
}

/* If the VHD is not yet initialized, initialize it. Otherwise, if the param 
 * UUID doesn't match the VHD UUID, assume the client wants a new VHD, in which  
 * case we reinitialize the VHD with the new params. */
static int update_vhd(server *srv, plugin_data *p, vhd_state_t *state,
		      off_t size)
{
	int err;
	uuid_t uuid;
	int init = 0;

	DEBUGLOG("s", "Updating vhd");

	if (uuid_is_null(state->vhd.footer.uuid)) {
		DEBUGLOG("s", "Blank UUID: initializing VHD");
		init = 1;
	}

	uuid_clear(uuid);
	if (strlen(p->conf.uuid_str->ptr) > 0) {
		err = uuid_parse(p->conf.uuid_str->ptr, uuid);
		if (err) {
			LOG("ss", "ERROR: invalid UUID",
			    p->conf.uuid_str->ptr);
			return  -EINVAL;
		}
	}

	if (init && uuid_is_null(uuid)) {
		LOG("s", "No UUID supplied, generating one");
		uuid_generate(uuid);
	}

	if (!init && !uuid_is_null(uuid) && 
	    uuid_compare(uuid, state->vhd.footer.uuid)) {
		DEBUGLOG("s", "New UUID supplied, reinitializing VHD");
		free_vhd_state(state);
		free_block_mapping(p->block_mapping);
		p->block_mapping = NULL;
		init = 1;
	}

	if (init)
		return init_vhd_from_params(srv, p, state, size, uuid);
	else
		DEBUGLOG("s", "VHD metadata unchanged");

	return 0;
}

static int init_range(server *srv, connection *con, vhd_state_t *state, plugin_data *p)
{
	int err;
	data_string *range_header;
	off_t range_total;
	DEBUGLOG("s", "Initialising Range");

	range_header = (data_string *)array_get_element(con->request.headers, "Range");

	DEBUGLOG("ss", "Range Header", range_header);

	if (!range_header) {
		DEBUGLOG("s", "No range set, returning complete VHD");
		state->req_start_off = 0;
		state->req_end_off = state->total_size_vhd - 1; //First byte is at the zeroth offset
		return 0;
	}
	DEBUGLOG("s", "Partial request made");
	p->partial_request = 1; //Setting the request as being partial

	err = blockio_parse_http_range(srv, range_header->value,
			&state->req_start_off, &state->req_end_off);
	
	DEBUGLOG("sd", "Error with parsing:", err);

	range_total = state->req_end_off;
	if (err) {
		LOG("sb", "Not a valid Content-Range value:",
				range_header->value);
		return -EINVAL;
	}

	DEBUGLOG("soo", "Request start, request end", state->req_start_off, state->req_end_off);

	if (state->req_start_off >= state->req_end_off) {
		LOG("s", "Invalid Content-Range");
		return -EINVAL;
	}
	if (range_total > state->total_size_vhd) {
		LOG("soo", "Range total exceeds VHD size", range_total, state->total_size_vhd);
		return -EINVAL;
	}

	return 0;
}

static int init_from_params(server *srv, connection *con, plugin_data *p,
			    vhd_state_t *state, off_t size)
{
	int err;

	err = update_vhd(srv, p, state, size);
	if (err)
		return err;

	return init_range(srv, con, state, p);
}

/* return the subrange that falls within the content-range requested */
static void constrain_range(vhd_state_t *state, off_t off, off_t len,
		off_t *skip, off_t *new_len)
{
	*skip = 0;
	*new_len = 0;

	if (off > state->req_end_off)
		return;

	if (state->req_start_off > off)
		*skip = state->req_start_off - off;

	if (*skip >= len)
		return;

	*new_len = len;
	if (off + len > state->req_end_off)
		*new_len = state->req_end_off - off + 1;

	*new_len -= *skip;
}

static buffer *choose_file(plugin_data *p, unsigned block)
{
	block_mapping_t *m = p->block_mapping;
	while (m->blocks != NULL) {
		if (test_bit((char *)m->blocks, block)) {
			return m->dev;
		}
		m++;
	}
	return NULL;
}

static int append_file(server *srv, connection *con, plugin_data *p,
		       vhd_state_t *state, unsigned block,
		       off_t file_off, off_t off, off_t len)
{
	off_t skip, new_len;

	DEBUGLOG("sosd", "Offset", off, "Length", len);
	constrain_range(state, off, len, &skip, &new_len);
	DEBUGLOG("soso", "Skip", skip, "New Length", new_len);
	if (new_len == 0)
		return new_len;

	if (p->conf.non_leaf) {
		LOG("s", "Conf.non_leaf path");
		buffer *file = choose_file(p, block);
		if (file == NULL) {
		  //no file being found indicates a non-accessible block (shadowed)
		  DEBUGLOG("sdos", "Appending a shadow block", block, skip, p->shadowed_block->ptr);		 	       
		  chunkqueue_append_file(con->write_queue, p->shadowed_block,
					skip, new_len);
		}
		else
		{
			DEBUGLOG("sdos", "Found file for block",
				 block, off + skip, file->ptr);
		
			DEBUGLOG("so", "File Offset", file_off);
			chunkqueue_append_file(con->write_queue, file,
				       file_off + skip, new_len);
		}
	}
	else {
		chunkqueue_append_file(con->write_queue, con->physical.path,
				       file_off + skip, new_len);
		if (new_len != 0)
			DEBUGLOG("soo", "Appended Data", new_len, file_off + skip);
	}
	return new_len;
}

static int append_buf(server *srv, connection *con, vhd_state_t *state,
		char *buf, off_t off, off_t len)
{
	off_t skip, new_len;
	
	(void)srv;

	constrain_range(state, off, len, &skip, &new_len);
	if (new_len == 0)
		return new_len;

	chunkqueue_append_mem(con->write_queue, buf + skip,(size_t)new_len + 1);
	if (new_len != 0) {
		DEBUGLOG("sdd", "Appended Data", new_len, buf + skip);
	}
	return new_len;
}

int append_data(server *srv, connection *con, plugin_data *p,
		vhd_state_t *state)
{
	int err;
        off_t bytes;
	unsigned int i, searched, block;
	off_t off, sec, start;
	char *bm;
	off_t bm_size;
	vhd_context_t *vhd = &state->vhd;

	bm_size = vhd->bm_secs << VHD_SECTOR_SHIFT;
	bm = malloc(bm_size);
	if (!bm)
		return -ENOMEM;
	memset(bm, 0xff, bm_size);

	i = 0;
	block = 0;
	searched = 0;
	err = 0;

	off = state->data_off;
	sec = off >> VHD_SECTOR_SHIFT;
	DEBUGLOG("sd", "Blocks allocated", state->blocks_allocated);
	while (i < state->blocks_allocated) {
		if ((off_t)vhd->bat.bat[block] == sec) {
			bytes = append_buf(srv, con, state, bm, off, bm_size);
			DEBUGLOG("sdooo", "Appended bitmap", block, sec, off, bytes);
			start = (off_t) block * (off_t)state->vhd.header.block_size;
			bytes = append_file(srv, con, p, state, block,
					start,
					off + (off_t)bm_size,
					(off_t)state->vhd.header.block_size);
			DEBUGLOG("sdo", "Appended block", block, bytes);

			i++;
			searched = 0;
			sec += (off_t)vhd->bat.spb + (off_t)vhd->bm_secs;
			off = (off_t)sec << VHD_SECTOR_SHIFT;
			if (off > state->req_end_off){
				DEBUGLOG("soo", "Offset & Req End", (off + state->vhd.header.block_size), state->req_end_off);
				break;	
			}
		}
		block = (block + 1) % vhd->header.max_bat_size;
		DEBUGLOG("sd", "vhd->header.max_bat_size", vhd->header.max_bat_size);
		DEBUGLOG("sd", "Maximum Bat Size = ", vhd->header.max_bat_size);
		DEBUGLOG("sd", "Block values is now = ", block);
		searched++;
		if (searched > vhd->header.max_bat_size) {
			LOG("sod", "ERROR: can't find block for sec", sec, i);
			err = INTERNAL_ERROR;
			break;
		}
	}

	free(bm);
	return err;
}

int send_vhd(server *srv, connection *con, plugin_data *p, vhd_state_t *state)
{
	int err;
	off_t bytes;
	off_t off;
	vhd_context_t *vhd = &state->vhd;

	vhd_footer_out(&vhd->footer);
	vhd_header_out(&vhd->header);
	vhd_bat_out(&vhd->bat);

	DEBUGLOG("soo", "Range:", state->req_start_off, state->req_end_off);

	off = 0;
	bytes = append_buf(srv, con, state, (void *)&vhd->footer, off,
			(off_t)sizeof(vhd->footer));
	off += sizeof(vhd->footer);
	DEBUGLOG("so", "Appended backup footer:", bytes);

	bytes = append_buf(srv, con, state, (void *)&vhd->header, off,
			(off_t)sizeof(vhd->header));
	off += sizeof(vhd->header);
	DEBUGLOG("so", "Appended header:", bytes);

	bytes = append_buf(srv, con, state, (void *)vhd->bat.bat, off,
			(off_t)state->bat_buf_size);
	off += state->bat_buf_size;
	DEBUGLOG("so", "Appending BAT:", bytes);

	/* convert the VHD buffers back (now that they've been copied out) so 
	 * we can keep using the structures */
	vhd_footer_in(&vhd->footer);
	vhd_header_in(&vhd->header);
	vhd_bat_in(&vhd->bat);

	if (vhd->footer.type == HD_TYPE_DIFF) {
		bytes = append_buf(srv, con, state, (void *)state->ploc_buf,
				off, (off_t)state->ploc_buf_size);
		off += state->ploc_buf_size;
		DEBUGLOG("so", "Appended parent loc:", bytes);
	}

	DEBUGLOG("s", "Appending data blocks");
	err = append_data(srv, con, p, state);
	if (err)
		return err;

	vhd_footer_out(&vhd->footer);
	off = state->total_size_vhd - sizeof(vhd->footer);
	bytes = append_buf(srv, con, state, (void *)&vhd->footer, off,
			(off_t)sizeof(vhd->footer));
	DEBUGLOG("so", "Appended primary footer:", bytes);

	buffer *buf = buffer_init();
	buffer_append_string(buf, "bytes ");
	buffer_append_off_t(buf, state->req_start_off);
	buffer_append_string(buf, "-");
	buffer_append_off_t(buf, state->req_end_off);
	buffer_append_string(buf, "/");
	buffer_append_off_t(buf, state->total_size_vhd);

	response_header_insert(srv, con, CONST_STR_LEN("Content-Range"),
					CONST_BUF_LEN(buf));

	buffer_free(buf);

	/* balance out the byte conversion for the next time we come here */
	vhd_footer_in(&vhd->footer);

	return 0;
}

int send_head(server *srv, connection *con, vhd_state_t *state)
{
	buffer *buf = buffer_init();
	buffer_append_off_t(buf, state->total_size_vhd);
	response_header_insert(srv, con, CONST_STR_LEN("Content-Length"),
			       CONST_BUF_LEN(buf));
	buffer_free(buf);
	return 0;
}

static int probe_file(server *srv, connection *con, off_t size)
{
	stat_cache_entry *sce = NULL;

	if (stat_cache_get_entry(srv, con, con->physical.path, &sce) ==
			HANDLER_ERROR) {
		con->http_status = 403;
		LOG("sbsb", "not a regular file:", con->uri.path, "->",
				con->physical.path);
		return -EPERM;
	}

#ifdef HAVE_LSTAT
	if ((sce->is_symlink == 1) && !con->conf.follow_symlink) {
		con->http_status = 403;
		if (con->conf.log_request_handling) {
			LOG("s",  "-- access denied due symlink restriction");
			LOG("sb", "Path         :", con->physical.path);
		}
		buffer_reset(con->physical.path);
		return -EPERM;
	}
#endif
	if (!S_ISREG(sce->st.st_mode) && !S_ISBLK(sce->st.st_mode)) {
		con->http_status = 404;
		if (con->conf.log_file_not_found)
			LOG("sbsb", "not a regular file nor block device:",
					con->uri.path, "->", sce->name);
		return -ENOENT;
	}

	if (size != sce->st.st_size) {
		LOG("soo", "ERROR: file does not match configured size",
		    sce->st.st_size, size);
		return -EINVAL;
	}

	/* mod_compress might set some data directly, don't overwrite it */
	/* set response content-type, if not set already */
	if (!array_get_element(con->response.headers, "Content-Type")) {
		if (buffer_is_empty(sce->content_type)) {
			/* we are setting application/octet-stream, but also 
			 * announce that this header field might change in the 
			 * seconds few requests. This should fix the aggressive 
			 * caching of FF and the script download seen by the 
			 * first installations */
			response_header_overwrite(srv, con,
					CONST_STR_LEN("Content-Type"),
					CONST_STR_LEN("application/octet-stream"));
		} else {
			response_header_overwrite(srv, con,
					CONST_STR_LEN("Content-Type"),
					CONST_BUF_LEN(sce->content_type));
		}
	}

	return 0;
}

static int parse_size_config(server *srv, connection *con, plugin_data *p,
			     off_t *size)
{
	UNUSED(con);

	char *vs = p->conf.vdi_size_str->ptr;

	if (vs == NULL || *vs == '\0') {
		LOG("s", "ERROR: No vdi_size configured");
		return -EINVAL;
	}

	*size = (off_t)strtoll(vs, NULL, 0);
	if (*size <= 0) {
		LOG("ss", "ERROR: vdi_size invalid", vs);
		return -EINVAL;
	}

	return 0;
}

URIHANDLER_FUNC(mod_getvhd_subrequest) {
	plugin_data *p = p_d;
	int err, s_len;
	off_t size;

	/* someone else has made a decision for us */
	if (con->http_status != 0)
		return HANDLER_GO_ON;
	if (con->uri.path->used == 0)
		return HANDLER_GO_ON;
	if (con->physical.path->used == 0)
		return HANDLER_GO_ON;

	/* someone else has handled this request */
	if (con->mode != DIRECT)
		return HANDLER_GO_ON;

	if (con->request.http_method != HTTP_METHOD_GET &&
	    con->request.http_method != HTTP_METHOD_HEAD)
		return HANDLER_GO_ON;

	mod_getvhd_patch_connection(srv, con, p);

	// Ignore if mod_getvhd is not activated for the current connection
        if (p->conf.activate == 0)
		return HANDLER_GO_ON;

	s_len = con->uri.path->used - 1;

	if (con->conf.log_request_handling)
		LOG("s",  "-- handling file with GET VHD");

	if (0 != parse_size_config(srv, con, p, &size)) {
		LOG("s", "ERROR: file size misconfigured");
		con->http_status = 500;
		return HANDLER_FINISHED;
	}

	if (p->conf.non_leaf) {
		LOG("s", "-- non_leaf VDI");

		/* mod_compress might set some data directly, don't overwrite it */
		/* set response content-type, if not set already */
		if (!array_get_element(con->response.headers, "Content-Type")) {
			response_header_overwrite(srv, con,
						  CONST_STR_LEN("Content-Type"),
						  CONST_STR_LEN("application/octet-stream"));
		}
	}
	else {
		err = probe_file(srv, con, size);
		if (err)
			goto out;
	}

	err = init_from_params(srv, con, p, &p->state, size);
	if (err)
		goto out;

	if (con->request.http_method == HTTP_METHOD_HEAD) {
		err = send_head(srv, con, &p->state);
	}
	else {
		err = send_vhd(srv, con, p, &p->state);
	}
	if (err)
		goto out;

	con->file_finished = 1;

out:
	if(p->partial_request == 1)
		con->http_status=206;
	else if (!err)
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
int mod_getvhd_plugin_init(plugin *p) {
	p->version     = LIGHTTPD_VERSION_ID;
	p->name        = buffer_init_string("getvhd");

	p->init        = mod_getvhd_init;
	p->handle_subrequest_start = mod_getvhd_subrequest;
	p->set_defaults  = mod_getvhd_set_defaults;
	p->cleanup     = mod_getvhd_free;

	p->data        = NULL;

	return 0;
}
