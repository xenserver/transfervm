#!/bin/bash
./runtests.py --text --host sunburn --plugin ../transferplugin/transfer --plugin-xenapi ../../api.hg/scripts/examples/python/XenAPIPlugin.py --vm-template ../../../output/hyde-transfervm/transfervm.xva -v -v $@
