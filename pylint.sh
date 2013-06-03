#!/bin/sh

set -eu

files="$@"
thisdir=$(dirname "$0")

for file in $files
do
  out=$(PYLINTHOME=/tmp PYLINTRC="$thisdir/pylint.rc" \
        pylint --persistent=n "$file")

  if [ "$out" ]
  then
    echo "$out" 1>&2
    exit 1
  fi
done
