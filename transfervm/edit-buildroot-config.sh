#!/bin/bash

# Run this script from myrepos/hyde.hg/transfervm to modify the buildroot.config using make menuconfig.

# Not part of the build process!

VERSION=buildroot-2009.02
TARBALL=/usr/groups/linux/distfiles/buildroot/${VERSION}.tar.gz
TMPDIR=$(mktemp -d)
BRDIR=${TMPDIR}/${VERSION}

tar -C ${TMPDIR} -xzf ${TARBALL}
cp buildroot.config ${BRDIR}/.config
make -C ${BRDIR} menuconfig

echo "CHANGES:"
diff buildroot.config ${BRDIR}/.config
cp ${BRDIR}/.config buildroot.config

rm -rf ${TMPDIR}
