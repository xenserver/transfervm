#!/bin/sh

set -eu

thisdir=$(dirname "$0")

if ! pidof /opt/xensource/bin/xapi >/dev/null
then
  echo "xapi is not running -- template will be still installed."
  exit 0
fi

get_list_length() {
count=0
for x in $1; do
   count=$((count+1))
done
}

uninstall_template() {
xe template-uninstall template-uuid=$1 force=true >/dev/null
}

IFS=","
. /etc/xensource-inventory

template_uuids=$(xe template-list --minimal other-config:transfervm=true)

for template in $template_uuids; do
   vbd=$(xe vbd-list --minimal vm-uuid=$template)
   echo "VBD = $vbd"
   vdi=$(xe vbd-param-get uuid=$vbd param-name=vdi-uuid)
   echo "VDI = $vdi"
   sr=$(xe vdi-param-get uuid=$vdi param-name=sr-uuid)
   pbds=$(xe sr-param-get uuid=$sr param-name=PBDs)
   get_list_length pbds
   if [ $count == 1 ]; then
      echo "Local SR"
      host=$(xe pbd-param-get uuid=$pbds param-name=host-uuid)
      if [ "$host" == "$INSTALLATION_UUID" ]; then
         echo "On my Local SR, so remove"
         uninstall_template $template
      fi
   else
      #On a shared SR so remove template
      echo "On Shared SR, so remove"
      uninstall_template $template
   fi
done

