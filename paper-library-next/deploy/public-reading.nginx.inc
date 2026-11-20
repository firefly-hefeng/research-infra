# Include inside the existing authenticated HTTPS server block.
# Keep the existing /papers/api/ proxy and /papers/ static location unchanged.
# Public reading is limited to these explicit routes; management inherits auth_request.
location = /papers/ {
    auth_request off;
    try_files /papers/index.html =404;
}
location = /papers/app.js {
    auth_request off;
    try_files $uri =404;
}
location = /papers/style.css {
    auth_request off;
    try_files $uri =404;
}
location = /papers/api/catalog {
    auth_request off;
    if ($request_method != GET) { return 405; }
    proxy_pass http://127.0.0.1:4186/api/catalog;
    proxy_set_header Host 127.0.0.1:4186;
    proxy_set_header Origin http://127.0.0.1:4186;
    proxy_read_timeout 30s;
}
location ~ "^/papers/api/papers/(?<paper_pdf_id>[a-f0-9]{64})/pdf$" {
    auth_request off;
    if ($request_method != GET) { return 405; }
    proxy_pass http://127.0.0.1:4186/api/papers/$paper_pdf_id/pdf$is_args$args;
    proxy_set_header Host 127.0.0.1:4186;
    proxy_set_header Origin http://127.0.0.1:4186;
    proxy_read_timeout 120s;
}
location = /papers/manage {
    try_files /papers/index.html =404;
}
location = /papers/manage/ {
    return 302 /papers/manage;
}
