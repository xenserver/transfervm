#
# All the ?= variable assignments here are to support building outside of
# build.hg.  They aren't used in the main product build.
#

PRODUCT_BRAND ?= XenServer
PRODUCT_MAJOR_VERSION ?= 5
PRODUCT_MINOR_VERSION ?= 5
PRODUCT_MICRO_VERSION ?= 900
PRODUCT_VERSION ?= $(PRODUCT_MAJOR_VERSION).$(PRODUCT_MINOR_VERSION).$(PRODUCT_MICRO_VERSION)
BUILD_NUMBER ?= 0
B_BASE ?= .

USE_BRANDING := yes
IMPORT_BRANDING := yes
include $(B_BASE)/common.mk
FAKEROOT ?= 

PROJECT_OUTPUTDIR ?= .

include $(PROJECT_OUTPUTDIR)/uclibc-toolchain/toolchain.mk
include $(PROJECT_OUTPUTDIR)/kernel-iscsitarget/kernel.inc

CARBON_DISTFILES ?= /usr/groups/linux/distfiles
MY_OBJ_DIR ?= /tmp/transfervm-obj
MY_OUTPUT_DIR ?= /tmp/transfervm-output
UCLIBC_TOOLCHAIN_PATH ?= /tmp/transfervm-obj/buildroot-2009.02/build_i686/staging_dir/usr/bin
UCLIBC_TOOL_PREFIX ?= i686-linux-uclibc-

REPONAME := transfervm
REPO := $(call git_loc,$(REPONAME))

BLKTAP_REPONAME := blktap
BLKTAP_HG := $(call git_loc,$(BLKTAP_REPONAME))

DD_DISTFILES := $(CARBON_DISTFILES)/driverdomain
BR_DISTFILES := $(CARBON_DISTFILES)/buildroot
CROSS_COMPILE := $(UCLIBC_TOOLCHAIN_PATH)/$(UCLIBC_TOOL_PREFIX)


BUILDROOT_VERSION := 2009.02
BUILDROOT_SOURCE := $(BR_DISTFILES)/buildroot-$(BUILDROOT_VERSION).tar.gz
BUILDROOT_DIR := $(MY_OBJ_DIR)/buildroot-$(BUILDROOT_VERSION)
BUILDROOT_MAKE := LOCAL_DISTFILES=$(CARBON_DISTFILES)/buildroot $(MAKE) -C $(BUILDROOT_DIR)
BUILDROOT_OUTPUT_IMAGE := $(BUILDROOT_DIR)/binaries/transfervm/rootfs.i686.tar
OPENSSL_VERSION_IN_BUILDROOT := 1.0.2d
OPENSSL_OUTPUT_DIR := $(BUILDROOT_DIR)/build_i686/openssl-$(OPENSSL_VERSION_IN_BUILDROOT)
LIGHTTPD_VERSION_IN_BUILDROOT := 1.4.20
LIGHTTPD_BUILD_DIR := $(BUILDROOT_DIR)/build_i686/lighttpd-$(LIGHTTPD_VERSION_IN_BUILDROOT)

LIGHTTPD_SOURCE := lighttpd-1.4.20
LIGHTTPD_FILES := mod_bits.c mod_put.c blockio.h blockio.c mod_getvhd.c mod_putvhd.c mod_bitsvhd.c connections.c base64.h base64.c bits_common.h bits_common.c vhd_common.h vhd_common.c
LIGHTTPD_PATCHES := $(wildcard lighttpd.*.patch)
LIGHTTPD_FILE_PATHS := $(foreach F,$(LIGHTTPD_FILES),$(LIGHTTPD_SOURCE)/src/$(F))
LIGHTTPD_MAKEFILEAM := $(LIGHTTPD_SOURCE)/src/Makefile.am

ISCSITARGET_VERSION := 20071227
ISCSITARGET_TAR := $(DD_DISTFILES)/iscsi-target-$(ISCSITARGET_VERSION).tar.bz2
ISCSITARGET_SOURCE := $(MY_OBJ_DIR)/tgt-$(ISCSITARGET_VERSION)/usr
ISCSITARGET_BASE := $(MY_OBJ_DIR)/tgt-$(ISCSITARGET_VERSION)


# Intermediate targets
BUILDROOT_STAMP := $(MY_OBJ_DIR)/.buildroot.stamp
BUILDROOT_SOURCE_STAMP := $(MY_OBJ_DIR)/.buildroot.source.stamp
BUILDROOT_BUILD_STAMP := $(MY_OBJ_DIR)/.buildroot.build.stamp

LIGHTTPD_BUILD_STAMP := $(MY_OBJ_DIR)/.lighttpd.module.stamp
LIGHTTPD_RECONFIGURE_STAMP := $(MY_OBJ_DIR)/.lighttpd.reconfigure.stamp
LIGHTTPD_PACKAGEPATCH_STAMP := $(MY_OBJ_DIR)/.lighttpd.packagepatch.stamp

INITRD_STAGING_STAMP := $(MY_OBJ_DIR)/.initrd.staging.stamp
INITRD_STAGING_DIR := $(MY_OBJ_DIR)/initrd

ISCSITARGET_STAMP := $(MY_OBJ_DIR)/.iscsitarget.stamp
ISCSITARGET_SOURCE_STAMP := $(MY_OBJ_DIR)/.iscsitarget.source.stamp
ISCSITARGET_BUILD_STAMP := $(MY_OBJ_DIR)/.iscsitarget.build.stamp

PULLER_SOURCE_STAMP := $(MY_OBJ_DIR)/.puller.source.stamp
XENSTORE_SOURCE_STAMP := $(MY_OBJ_DIR)/.xenstore.source.stamp

MODULES_STAMP := $(MY_OBJ_DIR)/.modules.stamp

OVERLAY_STAMP := $(MY_OBJ_DIR)/.overlay.stamp

LIBVHD_STAMP := $(MY_OBJ_DIR)/.libvhd.stamp

VHD_TMP := $(MY_OBJ_DIR)/vhd


MAKE_SOURCES := $(REPO)/transfervm/make-sources.sh

OVERLAY := $(REPO)/transfervm/overlay

PULLER_DIR := $(REPO)/transfervm/puller
XENSTORE_DIR := $(REPO)/transfervm/xenstore

# Output targets
KERNEL := $(MY_OUTPUT_DIR)/vmlinuz
INITRD := $(MY_OUTPUT_DIR)/initrd.img
VM_TEMPLATE := $(MY_OUTPUT_DIR)/transfer-vm.xva
SOURCES := $(MY_SOURCES)/transfer-vm-sources.tar.bz2
MANIFEST := $(MY_SOURCES)/MANIFEST

# Rules

.PHONY: build
build: $(VM_TEMPLATE) $(SOURCES) $(MANIFEST)
	@:


$(VM_TEMPLATE): $(MY_OBJ_DIR)/ova.xml $(KERNEL) $(INITRD) menu.lst
	# Create a .xva
	rm -Rf $(MY_OBJ_DIR)/image-staging
	mkdir -p $(MY_OBJ_DIR)/image-staging/boot/grub
	cp $(KERNEL) $(INITRD) $(MY_OBJ_DIR)/image-staging/boot/
	cp menu.lst $(MY_OBJ_DIR)/image-staging/boot/grub/
	$(FAKEROOT) chown -R root:root $(MY_OBJ_DIR)/image-staging
	test -r /etc/mtab || ln -sf /proc/mounts /etc/mtab
	sh ./mkxva $(MY_OBJ_DIR)/image-staging $(MY_OBJ_DIR)/ova.xml $(MY_OBJ_DIR) $@

$(MY_OBJ_DIR)/ova.xml: ova.xml.in
	# Create a .xva metadata file
	$(call brand,ova.xml.in) > $@

$(KERNEL): $(PROJECT_OUTPUTDIR)/kernel-iscsitarget/$(KERNEL_FILENAME) $(MY_OUTPUT_DIR)/.dirstamp
	cp $(PROJECT_OUTPUTDIR)/kernel-iscsitarget/$(KERNEL_FILENAME) $@

$(INITRD): $(INITRD_STAGING_STAMP)
	# Create initrd.img from a filesystem
	$(FAKEROOT) chown -R root:root $(INITRD_STAGING_DIR)
	cd $(INITRD_STAGING_DIR) && set -o pipefail && find . \
	| $(FAKEROOT) cpio --quiet -o -Hnewc \
	| gzip -v9 >$@.tmp && mv $@.tmp $@

$(INITRD_STAGING_STAMP): $(BUILDROOT_STAMP) $(ISCSITARGET_STAMP) $(MODULES_STAMP) $(OVERLAY_STAMP)
	# Create the filesystem tree (each dependency installs itself)
	touch $@

$(BUILDROOT_STAMP): $(BUILDROOT_BUILD_STAMP) $(LIGHTTPD_BUILD_STAMP)
	# Extract the buildroot output into a filesystem tree
	mkdir -p $(INITRD_STAGING_DIR)
	$(FAKEROOT) tar -C $(INITRD_STAGING_DIR) -xf $(BUILDROOT_OUTPUT_IMAGE)
	# Clean up the .subversion directory that buildroot build generates for some reason.
	rm -rf .subversion
	touch $@

$(BUILDROOT_BUILD_STAMP): $(BUILDROOT_SOURCE_STAMP) $(PULLER_SOURCE_STAMP) $(XENSTORE_SOURCE_STAMP)
	# Buildroot compilation.
	$(BUILDROOT_MAKE)
	touch $@

$(BUILDROOT_SOURCE_STAMP): $(BUILDROOT_SOURCE) buildroot.config
	# Buildroot unpacking and patching
	tar -C $(MY_OBJ_DIR) -xvzf $(BUILDROOT_SOURCE)
	cp $(REPO)/transfervm/buildroot.config $(BUILDROOT_DIR)/.config
	patch -d $(BUILDROOT_DIR) -p0 <$(PULLER_DIR)/buildroot.patch
	patch -d $(BUILDROOT_DIR) -p0 <$(XENSTORE_DIR)/buildroot.patch
	rsync -av $(PULLER_DIR)/package/ $(BUILDROOT_DIR)/package/
	rsync -av $(XENSTORE_DIR)/package/ $(BUILDROOT_DIR)/package/
	if [ "$(MY_OUTPUT_DIR)" = "/tmp/transfervm-output" ]; \
	then \
		patch $(BUILDROOT_DIR)/.config <buildroot.config.patch; \
	fi
	patch -d $(BUILDROOT_DIR) -p0 <hvc.patch

	# Rev stunnel to 4.56
	patch -d $(BUILDROOT_DIR) -p0 <stunnel.patch
	patch -d $(BUILDROOT_DIR) -p0 <stunnel-4.56.patch
	rm $(BUILDROOT_DIR)/package/stunnel/stunnel-have-pty.patch
	cp pollhup.patch $(BUILDROOT_DIR)/package/stunnel/pollhup.patch

	# Rev openssl to 1.0.2d
	patch -d $(BUILDROOT_DIR) -p0 <openssl-1.0.2d.patch
	patch -d $(BUILDROOT_DIR) -p0 <openssl-1.0.2d-patches.patch
	$(BUILDROOT_MAKE) oldconfig
	touch $@

$(LIGHTTPD_BUILD_STAMP): $(LIGHTTPD_RECONFIGURE_STAMP) $(LIGHTTPD_FILE_PATHS) $(LIGHTTPD_PATCHES) $(LIBVHD_STAMP)
	# Copy modified lighttpd files over the build directory
	set -e ; for f in $(LIGHTTPD_FILE_PATHS); do \
	cp $$f $(LIGHTTPD_BUILD_DIR)/src; \
	done
	set -e ; for f in $(LIGHTTPD_PATCHES); do \
	patch -d $(LIGHTTPD_BUILD_DIR) -p0 <$$f; \
	done
	# Rebuild buildroot to recompile and reinstall lighttpd with the module.
	rm -f $(LIGHTTPD_BUILD_DIR)/.stamp_built
	rm -f $(LIGHTTPD_BUILD_DIR)/.stamp_staging_installed
	rm -f $(BUILDROOT_DIR)/project_build_i686/transfervm/autotools-stamps/lighttpd_target_installed
	$(BUILDROOT_MAKE) EXTRA_CPPFLAGS="-I$(VHD_TMP)/include -I$(BUILDROOT_DIR)/build_i686/e2fsprogs-1.41.3/lib" EXTRA_LDFLAGS="-L$(BUILDROOT_DIR)/build_i686/e2fsprogs-1.41.3/lib"
	set -e ; for f in `ls -r $(LIGHTTPD_PATCHES)`; do \
	patch -R -d $(LIGHTTPD_BUILD_DIR) -p0 <$$f; \
	done
	touch $@

$(LIGHTTPD_RECONFIGURE_STAMP): $(LIGHTTPD_PACKAGEPATCH_STAMP) $(LIGHTTPD_MAKEFILEAM)
	# Copy modified Makefile.am to the project and run autoreconf to re-generate Makefiles from Makefile.am
	cp $(LIGHTTPD_MAKEFILEAM) $(LIGHTTPD_BUILD_DIR)/src
	rm -f $(LIGHTTPD_BUILD_DIR)/.stamp_autoconfigured
	rm -f $(LIGHTTPD_BUILD_DIR)/.stamp_configured
	$(BUILDROOT_MAKE) lighttpd-configure
	touch $@

$(LIGHTTPD_PACKAGEPATCH_STAMP): $(BUILDROOT_BUILD_STAMP) lighttpd.mk
	$(BUILDROOT_MAKE) lighttpd-clean
	# Patch buildroot lighttpd package so that it would run autoreconf
	# before a build to re-generate Makefiles from Makefile.am
	cp lighttpd.mk $(BUILDROOT_DIR)/package/lighttpd
	$(BUILDROOT_MAKE) lighttpd-patch
	touch $@

$(ISCSITARGET_STAMP): $(ISCSITARGET_BUILD_STAMP)
	mkdir -p $(INITRD_STAGING_DIR)/usr/sbin/
	cp $(ISCSITARGET_SOURCE)/tgtadm $(INITRD_STAGING_DIR)/usr/sbin/.
	cp $(ISCSITARGET_SOURCE)/tgtd $(INITRD_STAGING_DIR)/usr/sbin/.
	strip --strip-unneeded $(INITRD_STAGING_DIR)/usr/sbin/tgtadm
	strip --strip-unneeded $(INITRD_STAGING_DIR)/usr/sbin/tgtd
	touch $@

$(ISCSITARGET_BUILD_STAMP): $(ISCSITARGET_SOURCE_STAMP) $(OPENSSL_BUILD_STAMP)
	# Include OpenSSL from Buildroot
	$(MAKE) -C $(ISCSITARGET_SOURCE) all ISCSI=1 \
	CC="$(CROSS_COMPILE)gcc" LDFLAGS="-L$(OPENSSL_OUTPUT_DIR)" \
	CFLAGS="-D_GNU_SOURCE -I$(OPENSSL_OUTPUT_DIR)/include -I$(ISCSITARGET_SOURCE)"
	touch $@

$(LIBVHD_STAMP): $(BUILDROOT_BUILD_STAMP)
	$(call mkdir_clean,$(VHD_TMP))
	cp -R $(BLKTAP_HG)/* $(VHD_TMP)
	cd $(VHD_TMP) && sed -i -e 's/AC_CHECK_HEADERS.*//' -e 's/AC_MSG_ERROR/AC_MSG_WARN/' configure.ac && ./autogen.sh && CC="$(CROSS_COMPILE)gcc" CFLAGS="-I$(BUILDROOT_DIR)/build_i686/e2fsprogs-1.41.3/lib -I$(BUILDROOT_DIR)/build_i686/staging_dir/usr/include -L$(BUILDROOT_DIR)/build_i686/e2fsprogs-1.41.3/lib" ./configure --host=i686-linux-uclibc
	$(MAKE) -C $(VHD_TMP)/vhd/lib libvhd.la
	$(MAKE) -C $(VHD_TMP)/vhd/lib DESTDIR=$(BUILDROOT_DIR)/build_i686/staging_dir libdir=/usr/lib install-libLTLIBRARIES
	$(MAKE) -C $(VHD_TMP)/vhd/lib DESTDIR=$(BUILDROOT_DIR)/project_build_i686/transfervm/root libdir=/usr/lib install-libLTLIBRARIES
	touch $@

$(ISCSITARGET_SOURCE_STAMP):
	rm -rf $(ISCSITARGET_BASE)
	tar -C $(MY_OBJ_DIR) -xvjf $(ISCSITARGET_TAR)
	patch -d $(ISCSITARGET_BASE) -p1 < iscsitarget.patch
	patch -d $(ISCSITARGET_BASE) -p1 < iscsitarget-account-lookup.patch
	patch -d $(ISCSITARGET_BASE) -p1 < multihomed.patch
	patch -d $(ISCSITARGET_BASE) -p1 < securebinding.patch
	patch -d $(ISCSITARGET_BASE) -p1 < securearg.patch
	patch -d $(ISCSITARGET_BASE) -p1 < lun_assoc.patch
	touch $@

$(PULLER_SOURCE_STAMP): $(BUILDROOT_SOURCE_STAMP) $(PULLER_DIR)/Makefile \
			$(wildcard $(PULLER_DIR)/*.[ch])
	mkdir -p $(MY_OBJ_DIR)/puller
	cp $^ $(MY_OBJ_DIR)/puller
	rm -rf $(BUILDROOT_DIR)/build_i686/puller
	touch $@

$(XENSTORE_SOURCE_STAMP): $(BUILDROOT_SOURCE_STAMP) $(XENSTORE_DIR)/Makefile \
			$(wildcard $(XENSTORE_DIR)/*.[ch])
	mkdir -p $(MY_OBJ_DIR)/xenstore
	cp $^ $(MY_OBJ_DIR)/xenstore
	rm -rf $(BUILDROOT_DIR)/build_i686/xenstore
	touch $@

$(MODULES_STAMP): $(PROJECT_OUTPUTDIR)/kernel-iscsitarget/$(MODULES_FILENAME)
	tar -C $(INITRD_STAGING_DIR) -xjf $(PROJECT_OUTPUTDIR)/kernel-iscsitarget/$(MODULES_FILENAME)
	/sbin/depmod -b $(INITRD_STAGING_DIR) $(KERNEL_VERSION)
	touch $@

# Overlay should be the last thing to be added to the INITRD_STAGING_DIR
$(OVERLAY_STAMP): $(BUILDROOT_STAMP) $(ISCSITARGET_STAMP) $(MODULES_STAMP) $(shell find $(OVERLAY) -type f)
	cp -R $(OVERLAY)/* $(INITRD_STAGING_DIR)
	$(call brand, $(OVERLAY)/etc/init.d/S60xenapiversion) >$(INITRD_STAGING_DIR)/etc/init.d/S60xenapiversion
	touch $@

$(SOURCES): $(INITRD_STAGING_STAMP)
	sh -x $(MAKE_SOURCES) $@ $(BUILDROOT_DIR) $(BR_DISTFILES) $(BUILDROOT_SOURCE)

$(MANIFEST):
	mkdir -p $(dir $@)
	echo "transfervm gpl local $(notdir $(SOURCES))" >$@

clean:
	rm -f $(VM_TEMPLATE)
	rm -f $(KERNEL)
	rm -f $(INITRD)
	rm -rf $(SOURCES) $(MANIFEST)
	rm -rf $(MY_OBJ_DIR)/*
	rm -rf $(MY_OBJ_DIR)/.*.stamp

