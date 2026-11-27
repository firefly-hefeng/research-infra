"""Serve the team progress MCP behind the platform's HTTPS reverse proxy."""
import argparse
import http.client
import json
import re
import time
from urllib.parse import urlsplit

from anyio import to_thread
from mcp.server.auth.routes import create_protected_resource_routes
from mcp.server.transport_security import TransportSecuritySettings
from pydantic import AnyHttpUrl
from starlette.middleware.trustedhost import TrustedHostMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse, Response

try:
    from .progress_mcp import create_server
    from .progress_mcp_source import ORIGIN, ProgressSource, loopback
except ImportError:
    from progress_mcp import create_server
    from progress_mcp_source import ORIGIN, ProgressSource, loopback


RESOURCE = ORIGIN + "/mcp"
ISSUER = RESOURCE + "/oauth"
METADATA = ORIGIN + "/.well-known/oauth-protected-resource/mcp"
SCOPE = "progress.read"
SESSION_COOKIE = "__Host-rmp_session"


class GatewayUnavailable(Exception):
    pass


class SessionReverification(Exception):
    """The member can resume the original grant by revalidating the bound Feishu session."""


class FeishuSessions:
    """Validate existing sessions with the local gateway. No cookie jar or redirect handling."""

    def __init__(self, origin, binding_type):
        self.gateway = urlsplit(loopback(origin))
        self.binding_type = binding_type

    def _request(self, method, path, headers, body=None):
        connection = http.client.HTTPConnection(self.gateway.hostname, self.gateway.port, timeout=5)
        try:
            connection.request(method, path, body=body, headers={"Host": urlsplit(ORIGIN).netloc, **headers})
            response = connection.getresponse()
            if response.status == 401 and response.getheader("X-RMP-Session-State") == "reverify":
                raise SessionReverification()
            if response.status in (401, 403):
                return None
            if response.status != 204:
                raise GatewayUnavailable()
            return response.headers
        except (OSError, http.client.HTTPException) as exc:
            raise GatewayUnavailable() from exc
        finally:
            connection.close()

    async def browser_member(self, request):
        cookie = request.cookies.get(SESSION_COOKIE, "")
        if not re.fullmatch(r"[A-Za-z0-9._~+/=-]{1,4096}", cookie):
            return None
        try:
            headers = await to_thread.run_sync(
                self._request, "GET", "/internal/mcp/member", {"Cookie": SESSION_COOKIE + "=" + cookie},
            )
        except SessionReverification:
            if request.url.path == "/mcp/oauth/consent":
                # The consent handler carries its pending request through the Feishu login.
                return None
            raise
        if headers is None:
            return None
        subject, session = headers.get("X-RMP-Subject", ""), headers.get("X-RMP-Session-Ref", "")
        if not all(re.fullmatch(r"[0-9a-f]{64}", item) for item in (subject, session)):
            raise GatewayUnavailable()
        return self.binding_type(subject, session)

    async def session_active(self, subject, session_ref):
        if not all(isinstance(item, str) and re.fullmatch(r"[0-9a-f]{64}", item) for item in (subject, session_ref)):
            return False
        headers = await to_thread.run_sync(
            self._request, "POST", "/internal/mcp/session", {"Content-Type": "application/json"},
            json.dumps({"subject": subject, "session_ref": session_ref}).encode(),
        )
        return headers is not None


class MemberAccess:
    """Authenticate every MCP request, including after a previous successful initialize."""

    def __init__(self, app, provider, browser_member):
        self.app = app
        self.provider = provider
        self.browser_member = browser_member

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http" or scope["path"] != "/mcp":
            return await self.app(scope, receive, send)
        request = Request(scope)
        origins = request.headers.getlist("origin")
        if origins and origins != [ORIGIN]:
            return await Response(status_code=403)(scope, receive, send)
        authorization = request.headers.getlist("authorization")
        if authorization:
            token = None
            if len(authorization) == 1:
                scheme, _, value = authorization[0].partition(" ")
                if scheme.lower() == "bearer" and 0 < len(value) <= 2048:
                    token = await self.provider.load_access_token(value)
            if token and token.resource == RESOURCE and token.expires_at and token.expires_at > time.time():
                if SCOPE not in token.scopes:
                    return await self.challenge(scope, receive, send, 403, "insufficient_scope")
                return await self.app(scope, receive, send)
        elif request.cookies.get(SESSION_COOKIE):
            if request.method not in ("GET", "HEAD") and origins != [ORIGIN]:
                return await Response(status_code=403)(scope, receive, send)
            if await self.browser_member(request):
                return await self.app(scope, receive, send)
        return await self.challenge(scope, receive, send, 401, "invalid_token")

    @staticmethod
    async def challenge(scope, receive, send, status, error):
        response = JSONResponse({"error": error}, status_code=status, headers={
            "Cache-Control": "no-store",
            "WWW-Authenticate": f'Bearer resource_metadata="{METADATA}", scope="{SCOPE}", error="{error}"',
        })
        await response(scope, receive, send)


def build_app(source, provider, browser_member, authorization_routes):
    host = urlsplit(ORIGIN).hostname
    server = create_server(
        source, stateless_http=True, json_response=True, streamable_http_path="/mcp",
        max_request_body_size=65536,
        transport_security=TransportSecuritySettings(
            enable_dns_rebinding_protection=True,
            allowed_hosts=[host, host + ":443"],
            allowed_origins=[ORIGIN],
        ),
    )
    app = server.streamable_http_app()
    app.router.redirect_slashes = False
    app.routes.extend(create_protected_resource_routes(
        AnyHttpUrl(RESOURCE), [AnyHttpUrl(ISSUER)], [SCOPE],
        resource_name="Research progress", resource_documentation=AnyHttpUrl(ORIGIN + "/docs/progress-mcp.md"),
    ))
    app.routes.extend(authorization_routes)
    app.add_middleware(MemberAccess, provider=provider, browser_member=browser_member)
    app.add_middleware(GatewayErrors)
    app.add_middleware(TrustedHostMiddleware, allowed_hosts=[host], www_redirect=False)
    return app


class GatewayErrors:
    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        try:
            await self.app(scope, receive, send)
        except SessionReverification:
            response = JSONResponse({
                "error": "temporarily_unavailable",
                "reason": "feishu_session_reverification_required",
                "error_description": "请在原登录设备打开平台账户，用同一飞书成员身份完成续验，再重试原请求。",
                "verification_uri": ORIGIN + "/auth/account",
            }, status_code=503, headers={"Cache-Control": "no-store", "Retry-After": "30"})
            await response(scope, receive, send)
        except GatewayUnavailable:
            response = JSONResponse({"error": "member_service_unavailable"}, status_code=503,
                                    headers={"Cache-Control": "no-store", "Retry-After": "5"})
            await response(scope, receive, send)


def main():
    import uvicorn
    try:
        from .progress_mcp_oauth import Binding, ProgressOAuthProvider, oauth_routes
    except ImportError:
        from progress_mcp_oauth import Binding, ProgressOAuthProvider, oauth_routes

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", type=int, default=8772)
    parser.add_argument("--local-progress-origin", required=True)
    parser.add_argument("--gateway-origin", default="http://127.0.0.1:18769")
    parser.add_argument("--oauth-db", required=True)
    args = parser.parse_args()
    source = ProgressSource(local=args.local_progress_origin)
    source.mode = "feishu_member_service"
    membership = FeishuSessions(args.gateway_origin, Binding)
    provider = ProgressOAuthProvider(args.oauth_db, session_active=membership.session_active)
    app = build_app(source, provider, membership.browser_member, oauth_routes(provider, membership.browser_member))
    uvicorn.run(app, host="127.0.0.1", port=args.port, access_log=False, proxy_headers=False)


if __name__ == "__main__":
    main()
