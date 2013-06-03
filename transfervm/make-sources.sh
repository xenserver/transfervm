#!/bin/sh

set -eu

dest="$1"
buildroot="$2"
buildroot_dl="$3"
buildroot_src="$4"

thisdir=$(dirname "$0")

tempdir=$(mktemp -d)

function cleanup()
{
  rm -rf "$tempdir"
}

trap cleanup ERR

cd "$tempdir"
cp -R "$thisdir/lighttpd-1.4.20" "$tempdir"
cp -R "$thisdir/overlay" "$tempdir"
cp "$thisdir/Makefile" "$tempdir"
cp "$thisdir/buildroot.config" "$tempdir"
cp "$thisdir/lighttpd.mk" "$tempdir"
cp "$thisdir/menu.lst" "$tempdir"
cp "$thisdir/mkxva" "$tempdir"
cp "$thisdir/ova.xml.in" "$tempdir"
cp "$thisdir"/*.patch "$tempdir"

for dir in "$buildroot/build_i686/"* \
           "$buildroot/project_build_i686/transfervm/busybox"* \
           "$buildroot/toolchain_build_i686/"*
do
  d=$(basename "$dir" -host)
  if [ "$d" = "bin" ]
  then
    continue
  fi
  if [ ! -f $buildroot_dl/$d* ]
  then
    d=${d/-/_}
  fi
  if [ -f $buildroot_dl/$d* ]
  then
    cp $buildroot_dl/$d* "$tempdir"
  fi
done

cp "$buildroot_src" "$tempdir" 

mkdir -p $(dirname "$dest")
tar -C "$tempdir" -cjf "$dest" .
cleanup
