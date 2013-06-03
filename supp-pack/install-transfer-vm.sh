#!/bin/sh

set -eu

thisdir=$(dirname "$0")


if md5sum --status -c "$thisdir/ISCSISR.py.md5"
then
  echo -n "Hotfixing ISCSISR.py..."
  patch -p0 -s <"$thisdir/ISCSISR.py.patch"
  echo "done."
fi


if ! pidof /opt/xensource/bin/xapi >/dev/null
then
  echo "Saving import of XenServer Transfer VM until next boot."
  cp "$thisdir/65-install-transfer-vm" /etc/firstboot.d
  chmod a+x /etc/firstboot.d/65-install-transfer-vm
  exit 0
fi

. /etc/xensource-inventory

IFS=, sr_uuids=$(xe sr-list --minimal other-config:i18n-key=local-storage)
dest_sr=""
for sr_uuid in $sr_uuids
do
  pbd=$(xe pbd-list --minimal sr-uuid=$sr_uuid host-uuid=$INSTALLATION_UUID)
  if [ "$pbd" ]
  then
    dest_sr="$sr_uuid"
    break
  fi
done

if [ "$dest_sr" = "" ]
then
  dest_sr=$(xe sr-list --minimal \
                       uuid=$(xe pool-list --minimal params=default-SR))
  if [ "$dest_sr" = "" ]
  then
    echo "No local storage and no default storage; cannot import Transfer VM."
    exit 0
  fi
fi

IFS=","  
templates=$(xe template-list --minimal other-config:transfervm=true)
if [ "$templates" != "" ]
then
   for template in $templates; do
      vbd=$(xe vbd-list --minimal vm-uuid=$template)
      vdi=$(xe vbd-param-get uuid=$vbd param-name=vdi-uuid)
      sr=$(xe vdi-param-get uuid=$vdi param-name=sr-uuid)
      if [ "$sr" == "$dest_sr" ]; then
          echo "I can see a Transfer VM template already; refusing to import another one."
          exit 0
      fi
   done
fi

echo -n "Importing XenServer Transfer VM... "
vm_uuid=$(xe vm-import filename="$thisdir/transfer-vm.xva" sr-uuid="$dest_sr")
nl=$(xe vm-list --minimal params=name-label uuid=$vm_uuid)
xe vm-param-set \
   is-a-template=true \
   "name-label=${nl/ import/}" \
   other-config:transfervm=true \
   other-config:transfervm_installation_host=$INSTALLATION_UUID \
   other-config:HideFromXenCenter=true \
   uuid=$vm_uuid
vdi_uuid=$(xe vbd-list vm-uuid=$vm_uuid type=Disk params=vdi-uuid --minimal)
xe vdi-param-set \
   name-label='XenServer Transfer VM system disk' \
   other-config:transfervm=true \
   other-config:HideFromXenCenter=true \
   uuid=$vdi_uuid
cd_uuid=$(xe vbd-list --minimal type=CD vm-uuid=$vm_uuid)
xe vbd-destroy uuid=$cd_uuid
echo "done."
