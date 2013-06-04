ifdef B_BASE
USE_BRANDING := yes
IMPORT_BRANDING := yes
include $(B_BASE)/common.mk
include $(B_BASE)/rpmbuild.mk
include $(PROJECT_OUTPUTDIR)/uclibc-toolchain/toolchain.mk
include $(PROJECT_OUTPUTDIR)/kernel-iscsitarget/kernel.inc
endif

VENDOR_CODE := xs
VENDOR_NAME := "Citrix Systems, Inc."
LABEL := xenserver-transfer-vm
TEXT := XenServer Transfer VM
VERSION := $(PRODUCT_VERSION)
BUILD := $(BUILD_NUMBER)

REPONAME := transfervm
ifdef B_BASE
REPO := $(call git_loc,$(REPONAME))
else
REPO := .
endif

RPM_RPMSDIR := $(MY_OBJ_DIR)/RPMS

PYLINT := sh $(REPO)/pylint.sh

TRANSFER_VM := $(PROJECT_OUTPUTDIR)/transfervm/transfer-vm.xva
TRANSFER_VM_SRC := $(PROJECT_OUTPUTDIR)/transfervm/SOURCES/transfer-vm-sources.tar.bz2

SUPP_PACK_SCRIPTS := $(PROJECT_OUTPUTDIR)/ddk/supplemental-pack.tar.bz2

TRANSFER_VM_DEST := /opt/xensource/packages/files/transfer-vm
PLUGIN_DEST := /etc/xapi.d/plugins

INSTALL_TRANSFER_VM := $(REPO)/supp-pack/install-transfer-vm.sh
UNINSTALL_TRANSFER_VM := $(REPO)/supp-pack/uninstall-transfer-vm.sh
FIRSTBOOT_TRANSFER_VM := $(REPO)/supp-pack/65-install-transfer-vm
TRANSFER_VM_ISCSI_PATCH := $(REPO)/supp-pack/ISCSISR.py.md5 \
			   $(REPO)/supp-pack/ISCSISR.py.patch

ALL_PLUGINS := $(addprefix $(REPO)/transferplugin/, \
		 copy forest.py pluginlib.py transfer \
		 vhd.py vhd_bitmaps.py vm_metadata.py)
ALL_WRAPPERS := $(addprefix $(REPO)/transferplugin/, do-copy do-transfer)

TRANSFER_SPEC := $(MY_OBJ_DIR)/xenserver-transfer-vm.spec
TRANSFER_RPM_TMP_DIR := $(MY_OBJ_DIR)/RPM_BUILD_DIRECTORY/tmp/xenserver-transfer-vm
TRANSFER_RPM := $(MY_OBJ_DIR)/RPMS/noarch/xenserver-transfer-vm-$(PRODUCT_VERSION)-$(BUILD_NUMBER).noarch.rpm

SUPP_PACK_ISO := $(MY_OUTPUT_DIR)/xenserver-transfer-vm.iso
SUPP_PACK_DIR := $(MY_OUTPUT_DIR)/PACKAGES.transfer-vm
TESTS_TARBALL := $(MY_OUTPUT_DIR)/transfer-tests.tar.bz2

TRANSFER_RPM_LINK := $(MY_OUTPUT_DIR)/xenserver-transfer-vm.noarch.rpm

OUTPUT := $(SUPP_PACK_ISO) $(TRANSFER_RPM_LINK) $(TESTS_TARBALL)

.PHONY: build
build: $(OUTPUT)
	@:

$(TRANSFER_RPM_LINK):
	ln -sf PACKAGES.transfer-vm/$(notdir $(TRANSFER_RPM)) $@

$(SUPP_PACK_ISO): $(TRANSFER_RPM)
	$(call mkdir_clean,$(SUPP_PACK_DIR))
	python setup.py --out $(SUPP_PACK_DIR) --pdn $(PRODUCT_BRAND) --pdv $(PRODUCT_VERSION) --bld $(BUILD) $<
	mv -f $(SUPP_PACK_DIR)/$(notdir $@) $@
	mkisofs -A "Citrix" -V "Transfer VM Source ISO" -J -joliet-long -r -o $(MY_OUTPUT_DIR)/xenserver-transfer-vm-source.iso $(TRANSFER_VM_SRC)

$(TRANSFER_RPM): $(TRANSFER_SPEC) $(TRANSFER_VM) pylint
	mkdir -p $(dir $@)
	mkdir -p $(TRANSFER_RPM_TMP_DIR)/$(TRANSFER_VM_DEST)
	mkdir -p $(TRANSFER_RPM_TMP_DIR)/$(PLUGIN_DEST)
	cp $(TRANSFER_VM) $(INSTALL_TRANSFER_VM) $(UNINSTALL_TRANSFER_VM) \
	     $(TRANSFER_VM_ISCSI_PATCH) \
	     $(TRANSFER_RPM_TMP_DIR)/$(TRANSFER_VM_DEST)
	cp $(ALL_PLUGINS) $(TRANSFER_RPM_TMP_DIR)/$(PLUGIN_DEST)
	cp $(ALL_WRAPPERS) $(TRANSFER_RPM_TMP_DIR)/$(TRANSFER_VM_DEST)
	chmod a+x $(TRANSFER_RPM_TMP_DIR)/$(TRANSFER_VM_DEST)/*.sh \
	          $(TRANSFER_RPM_TMP_DIR)/$(PLUGIN_DEST)/*
	$(RPMBUILD) -bb $<

$(TESTS_TARBALL): $(wildcard transfertests/*.py)
	tar cjf $(TESTS_TARBALL) transfertests/*.py

$(MY_OBJ_DIR)/%.spec: supp-pack/%.spec.in
	mkdir -p $(dir $@)
	$(call brand,$^) >$@

pylint:
	$(PYLINT) $(ALL_PLUGINS)


clean:
	rm -rf $(MY_OBJ_DIR)/*
	rm -f $(OUTPUT)
