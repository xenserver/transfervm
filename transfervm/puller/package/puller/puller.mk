#############################################################
#
# puller
#
#############################################################
PULLER_VERSION:=1
PULLER_SOURCE:=puller.tar.gz
PULLER_SITE:=
PULLER_DIR:=$(BUILD_DIR)/puller
PULLER_BINARY:=puller
PULLER_TARGET_BINARY:=usr/bin/puller

$(eval $(call AUTOTARGETS,package,foo))

$(PULLER_DIR)/.source:
	rsync -av /obj/puller/ $(PULLER_DIR)
	touch $@

$(PULLER_DIR)/.configured: $(PULLER_DIR)/.source
	touch $@

$(PULLER_DIR)/$(PULLER_BINARY): $(PULLER_DIR)/.configured
	$(MAKE) $(TARGET_CONFIGURE_ARGS) $(TARGET_CONFIGURE_OPTS) -C $(PULLER_DIR)

$(TARGET_DIR)/$(PULLER_TARGET_BINARY): $(PULLER_DIR)/$(PULLER_BINARY)
	$(MAKE) -C $(PULLER_DIR) install

puller: openssl $(TARGET_DIR)/$(PULLER_TARGET_BINARY)

puller-source:

puller-clean:
	$(MAKE) -C $(PULLER_DIR) uninstall
	-$(MAKE) -C $(PULLER_DIR) clean

puller-dirclean:
	rm -rf $(PULLER_DIR)

#############################################################
#
# Toplevel Makefile options
#
#############################################################
ifeq ($(BR2_PACKAGE_PULLER),y)
TARGETS+=puller
endif
