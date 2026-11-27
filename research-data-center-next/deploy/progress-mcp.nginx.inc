# Include inside the public HTTPS server. The application validates the MCP
# bearer or maps a same-origin browser session through the local Feishu gateway.
location ^~ /internal/mcp/ { return 404; }

location = /mcp {
    auth_request off;
    proxy_pass http://127.0.0.1:8772;
    proxy_http_version 1.1;
    proxy_set_header Connection "";
    proxy_set_header Host $host;
    proxy_set_header X-RMP-Subject "";
    proxy_set_header X-RMP-Session-Ref "";
    proxy_buffering off;
    proxy_read_timeout 90s;
    client_max_body_size 1m;
}

location = /mcp/oauth/consent {
    auth_request off;
    proxy_pass http://127.0.0.1:8772;
    proxy_set_header Host $host;
    proxy_set_header X-RMP-Subject "";
    proxy_set_header X-RMP-Session-Ref "";
    client_max_body_size 8k;
}

# Only the consent page needs a member's browser cookie.
location = /mcp/oauth/register {
    auth_request off;
    limit_req zone=rmp_auth_rate burst=10 nodelay;
    limit_req_status 429;
    proxy_pass http://127.0.0.1:8772;
    proxy_set_header Host $host;
    proxy_set_header Cookie "";
    proxy_set_header X-RMP-Subject "";
    proxy_set_header X-RMP-Session-Ref "";
    client_max_body_size 16k;
}
location ~ ^/(?:mcp/oauth/(?:authorize|token|revoke)|\.well-known/(?:oauth-authorization-server/mcp/oauth|oauth-protected-resource/mcp))$ {
    auth_request off;
    proxy_pass http://127.0.0.1:8772;
    proxy_set_header Host $host;
    proxy_set_header Cookie "";
    proxy_set_header X-RMP-Subject "";
    proxy_set_header X-RMP-Session-Ref "";
    client_max_body_size 16k;
}
