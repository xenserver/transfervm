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

#include <fcntl.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <unistd.h>

#include "xs_wire.h"

#define XEN_PATH "/proc/xen"
#define XENBUS_PATH XEN_PATH"/xenbus"

#ifndef min
#define min(a, b) (((a) < (b)) ? (a) : (b))
#endif

enum mode {
  M_INVALID,
  M_READ,
  M_WRITE,
  M_EXISTS,
  M_RM
};

static uint32_t req_id = 0;

/*
 * stripped down xenstore read
 */
char *xenstore_read(int fd, const char *key)
{
  struct xsd_sockmsg msg = { XS_READ };
  char buffer[XENSTORE_PAYLOAD_MAX];
  ssize_t len;

  msg.req_id = req_id++;
  /* payload is key, NUL */
  msg.len = strlen(key) + 1;
  if (write(fd, &msg, sizeof(msg)) != sizeof(msg))
    return NULL;
  write(fd, key, strlen(key) + 1);

  /* read response */
  if (read(fd, &msg, sizeof(msg)) != sizeof(msg))
    return NULL;
  if (msg.len) {
    len = read(fd, buffer, min(msg.len, XENSTORE_PAYLOAD_MAX));
    if (len == -1)
      return NULL;
  }
  if (msg.type != XS_READ)
    return NULL;

  return strdup(buffer);
}

/*
 * stripped down xenstore write
 */
int xenstore_write(int fd, const char *key, const char *value)
{
  struct xsd_sockmsg msg = { XS_WRITE };
  char buffer[8];
  int ret = 0;

  msg.req_id = req_id++;
  /* payload is key, NUL, value */
  msg.len = strlen(key) + strlen(value) + 1;
  if (write(fd, &msg, sizeof(msg)) != sizeof(msg))
    return 1;
  write(fd, key, strlen(key) + 1);
  write(fd, value, strlen(value));

  /* read and discard response */
  if (read(fd, &msg, sizeof(msg)) != sizeof(msg))
    return 1;
  while (msg.len) {
    ssize_t len = read(fd, buffer, min(msg.len, sizeof(buffer)));

    if (len < 1)
      break;
    msg.len -= len;
  }
  if (msg.type != XS_WRITE)
    ret = 1;

  return ret;
}

/*
 * stripped down xenstore rm
 */
int xenstore_rm(int fd, const char *key)
{
  struct xsd_sockmsg msg = { XS_RM };
  char buffer[8];
  int ret = 0;

  msg.req_id = req_id++;
  /* payload is key, NUL */
  msg.len = strlen(key) + 1;
  if (write(fd, &msg, sizeof(msg)) != sizeof(msg))
    return 1;
  write(fd, key, strlen(key) + 1);

  /* read and discard response */
  if (read(fd, &msg, sizeof(msg)) != sizeof(msg))
    return 1;
  while (msg.len) {
    ssize_t len = read(fd, buffer, min(msg.len, sizeof(buffer)));

    if (len < 1)
      break;
    msg.len -= len;
  }
  if (msg.type != XS_RM)
    ret = 1;

  return ret;
}

void usage(void)
{
  fprintf(stderr, "Usage: xenstore [read|write|exists|rm] ...\n");
  exit(1);
}

enum mode get_mode(const char *str)
{
  if (strcmp(str, "read") == 0)
    return M_READ;
  if (strcmp(str, "write") == 0)
    return M_WRITE;
  if (strcmp(str, "exists") == 0)
    return M_EXISTS;
  if (strcmp(str, "rm") == 0)
    return M_RM;
  return M_INVALID;
}

int read_cmd(int fd, const char *key)
{
  char *value;
  char *p;

  value = xenstore_read(fd, key);
  if (value == NULL)
    return 1;

  /* escape control characters for shell */
  for (p = value; *p; p++)
    if (*p >= ' ' && *p <= '~' && *p != '\\')
      putchar(*p);
    else {
      putchar('\\');
      switch (*p) {
      case '\t': putchar('t'); break;
      case '\n': putchar('n'); break;
      case '\r': putchar('r'); break;
      case '\\': putchar('\\'); break;
      default:
	if (*p < 010)
	  printf("%03o", *p);
	else
	  printf("x%02x", *p);
      }
    }
  putchar('\n');
  free(value);
  
  return 0;
}

int main(int argc, char **argv)
{
  char *mode_p;
  char *p;
  unsigned arg_ind = 1;
  int ret = 0;
  int fd;

  /* determine mode and argument position */
  p = strrchr(argv[0], '/');
  if (p)
    p++;
  else
    p = argv[0];
  if (strncmp(p, "xenstore-", 9) == 0) {
    mode_p = p + 9;
  }
  else {
    if (argc < 2)
      usage();
    mode_p = argv[1];
    arg_ind = 2;
  }

  /* all modes need at least one argument */
  if (arg_ind + 1 > argc)
    usage();

  fd = open(XENBUS_PATH, O_RDWR);

  switch (get_mode(mode_p)) {
  case M_READ:
    ret = read_cmd(fd, argv[arg_ind]);
    break;
  case M_WRITE:
    /* write needs two arguments */
    if (arg_ind + 2 > argc)
      usage();
    ret = xenstore_write(fd, argv[arg_ind], argv[arg_ind+1]);
    break;
  case M_EXISTS:
    p = xenstore_read(fd, argv[arg_ind]);
    if (p)
      free(p);
    else
      ret = 1;
    break;
  case M_RM:
    ret = xenstore_rm(fd, argv[arg_ind]);
    break;
  default:
    usage();
  }

  close(fd);

  return ret;
}
