CFLAGS += -Wall -Werror
ROOTDIR := ../../project_build_i686/transfervm/root

xenstore-compat: xenstore-compat.o

.PHONY: install
install:
	cp -p xenstore-compat ${ROOTDIR}/usr/bin/xenstore
	ln -sf xenstore ${ROOTDIR}/usr/bin/xenstore-read
	ln -sf xenstore ${ROOTDIR}/usr/bin/xenstore-write
	ln -sf xenstore ${ROOTDIR}/usr/bin/xenstore-exists
	ln -sf xenstore ${ROOTDIR}/usr/bin/xenstore-rm
