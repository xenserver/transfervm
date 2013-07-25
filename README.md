The Transfer VM is a BusyBox virtual appliance that can be used to expose
virtual disk images (VDIs) over a number of protocols. The disk can be exposed
over the network for both uploading and downloading disks.

The currently supported transport protocols are:
   * HTTP
   * HTTPS
   * BITS (Microsoft's Background Intelligent Transfer Service)
   * iSCSI
   * iSCSI over SSL

Usage
-----

A client makes a request to the XenServer host using a XAPI plguin 'transfer'
whcih is installed along with the Transfer VM VPX image. Once the plugin has
been called to expose a disk, a record can be returned by the client which
contains a URL over which the Trnsfer VM can be contacted to either
upload/download a disk image.
