# Lab member login and interactive shells create readable files by default.
# Shared storage cannot inherit POSIX ACLs. Explicit application modes are
# handled separately by research-share-permissions on the coordinator.
case "$(id -u)" in
    ''|*[!0-9]*) ;;
    *) if [ "$(id -u)" -ge 1000 ] && [ "$(id -u)" -lt 60000 ]; then
           umask 022
       fi ;;
esac
