#!/bin/bash


TEST_SCRIPT="runtests.py"
HOST="sunburn"
array=( bits_test expose_failure_test expose_test getrecord_test http_test manualnetwork_test ssl_test timeout_test unexpose_test )

for MODULE in ${array[@]}; do
    ./$TEST_SCRIPT --xml -vvv --host $HOST $MODULE > $MODULE.results
done
