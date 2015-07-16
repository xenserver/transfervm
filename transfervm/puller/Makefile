CFLAGS += -Wall -Werror -std=c99 -O0 -ggdb
CPPFLAGS += -I. -DFILE_OFFSET_BITS=64 -D_LARGEFILE_SOURCE -D_LARGEFILE64_SOURCE
LDFLAGS += -L../openssl-1.0.2a -lssl

puller: base64.o puller.o

.PHONY: install
install:
	cp puller ../../project_build_i686/transfervm/root/usr/bin/
