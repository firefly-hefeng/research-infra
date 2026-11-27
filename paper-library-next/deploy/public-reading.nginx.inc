# Compatibility filename. All paper routes inherit the existing Feishu gateway.
# The service is bound to loopback. Preserve the existing /papers/api/ proxy.
location = /papers/manage {
    try_files /papers/index.html =404;
}
location = /papers/manage/ {
    return 302 /papers/manage;
}
