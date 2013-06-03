#
# This is used when building outside of build.hg.
#

%/.dirstamp:
	@mkdir -p $*
	@touch $@

brand = \
  sed -e "s/@PRODUCT_BRAND@/$(PRODUCT_BRAND)/g" \
      -e "s/@PRODUCT_VERSION@/$(PRODUCT_VERSION)/g" \
      -e "s/@PRODUCT_MAJOR_VERSION@/$(PRODUCT_MAJOR_VERSION)/g" \
      -e "s/@PRODUCT_MINOR_VERSION@/$(PRODUCT_MINOR_VERSION)/g" \
      -e "s/@PRODUCT_MICRO_VERSION@/$(PRODUCT_MICRO_VERSION)/g" \
      -e "s/@BUILD_NUMBER@/$(BUILD_NUMBER)/g" $1

FAKEROOT := fakeroot
