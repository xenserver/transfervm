#############################################################
#
# xenstore
#
#############################################################
XENSTORE_VERSION:=1
XENSTORE_SOURCE:=xenstore.tar.gz
XENSTORE_SITE:=
XENSTORE_DIR:=$(BUILD_DIR)/xenstore
XENSTORE_BINARY:=xenstore
XENSTORE_TARGET_BINARY:=usr/bin/xenstore

$(eval $(call AUTOTARGETS,package,foo))

$(XENSTORE_DIR)/.source:
	rsync -av /obj/xenstore/ $(XENSTORE_DIR)
	touch $@

$(XENSTORE_DIR)/.configured: $(XENSTORE_DIR)/.source
	touch $@

$(XENSTORE_DIR)/$(XENSTORE_BINARY): $(XENSTORE_DIR)/.configured
	$(MAKE) $(TARGET_CONFIGURE_ARGS) $(TARGET_CONFIGURE_OPTS) -C $(XENSTORE_DIR)

$(TARGET_DIR)/$(XENSTORE_TARGET_BINARY): $(XENSTORE_DIR)/$(XENSTORE_BINARY)
	$(MAKE) -C $(XENSTORE_DIR) install

xenstore: $(TARGET_DIR)/$(XENSTORE_TARGET_BINARY)

xenstore-source:

xenstore-clean:
	$(MAKE) -C $(XENSTORE_DIR) uninstall
	-$(MAKE) -C $(XENSTORE_DIR) clean

xenstore-dirclean:
	rm -rf $(XENSTORE_DIR)

#############################################################
#
# Toplevel Makefile options
#
#############################################################
ifeq ($(BR2_PACKAGE_XENSTORE),y)
TARGETS+=xenstore
endif
