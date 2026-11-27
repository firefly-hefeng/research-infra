"""Feishu member consent and durable OAuth grants for the read-only progress MCP."""
from contextlib import closing, contextmanager
from dataclasses import dataclass
from hashlib import sha256
from html import escape
from pathlib import Path
from urllib.parse import urlencode, urlsplit
import os
import re
import secrets
import sqlite3
import time

from mcp.server.auth.handlers.token import TokenHandler
from mcp.server.auth.middleware.client_auth import AuthenticationError, ClientAuthenticator
from mcp.server.auth.provider import (
    AccessToken, AuthorizationCode, AuthorizationParams, AuthorizeError, RefreshToken,
    RegistrationError, TokenError, construct_redirect_uri,
)
from mcp.server.auth.routes import build_metadata, cors_middleware, create_auth_routes
from mcp.server.auth.settings import ClientRegistrationOptions, RevocationOptions
from mcp.server.transport_security import RequestBodyLimitMiddleware
from mcp.shared.auth import OAuthClientInformationFull, OAuthToken
from pydantic import AnyHttpUrl
from starlette.responses import HTMLResponse, JSONResponse, RedirectResponse
from starlette.routing import Route, request_response

ORIGIN = "https://rmp.wuwangwo.top"
RESOURCE = ORIGIN + "/mcp"
PREFIX = "/mcp/oauth"
ISSUER = ORIGIN + PREFIX
SCOPE = "progress.read"
ACCESS_SECONDS = 3600
GRANT_SECONDS = 30 * 86400
HEADERS = {"Cache-Control": "no-store", "Referrer-Policy": "no-referrer",
           "X-Content-Type-Options": "nosniff", "X-Frame-Options": "DENY",
           "Content-Security-Policy": "default-src 'none'; style-src 'unsafe-inline'; form-action 'self'; frame-ancestors 'none'; base-uri 'none'"}


@dataclass(frozen=True)
class Binding:
    subject: str
    session_ref: str  # A non-replayable reference checked by the Feishu gateway.


def fingerprint(secret):
    return sha256(secret.encode()).hexdigest()


class DesktopClient(OAuthClientInformationFull):
    def validate_redirect_uri(self, redirect_uri):
        if redirect_uri is not None:
            requested = urlsplit(str(redirect_uri))
            for registered in self.redirect_uris or []:
                saved = urlsplit(str(registered))
                # RFC 8252 allows desktop clients to choose a fresh loopback port.
                if (requested.hostname == saved.hostname and requested.port and requested.username is None
                        and requested.password is None and requested._replace(netloc=saved.netloc) == saved):
                    return redirect_uri
        return super().validate_redirect_uri(redirect_uri)


class ProgressOAuthProvider:
    def __init__(self, db_path, session_active):
        self.path = Path(db_path)
        self.session_active = session_active
        self.path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        fd = os.open(str(self.path), os.O_CREAT | os.O_RDWR | getattr(os, "O_NOFOLLOW", 0), 0o600)
        os.close(fd)
        os.chmod(self.path, 0o600)
        with self.database() as db:
            db.executescript("""
                CREATE TABLE IF NOT EXISTS clients (id TEXT PRIMARY KEY, metadata TEXT NOT NULL, created INTEGER NOT NULL, approved INTEGER NOT NULL DEFAULT 0);
                CREATE TABLE IF NOT EXISTS requests (id TEXT PRIMARY KEY, client TEXT NOT NULL, params TEXT NOT NULL, expires INTEGER NOT NULL,
                    csrf TEXT, subject TEXT, session_ref TEXT);
                CREATE TABLE IF NOT EXISTS codes (id TEXT PRIMARY KEY, client TEXT NOT NULL, params TEXT NOT NULL,
                    expires INTEGER NOT NULL, subject TEXT NOT NULL, session_ref TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS grants (id TEXT PRIMARY KEY, client TEXT NOT NULL, subject TEXT NOT NULL, session_ref TEXT NOT NULL,
                    access TEXT UNIQUE NOT NULL, refresh TEXT UNIQUE NOT NULL, access_expiry INTEGER NOT NULL, expiry INTEGER NOT NULL);
                CREATE TABLE IF NOT EXISTS used_refresh (hash TEXT PRIMARY KEY, grant_id TEXT NOT NULL REFERENCES grants(id) ON DELETE CASCADE);
            """)

    @contextmanager
    def database(self, *, write=False):
        with closing(sqlite3.connect(str(self.path), timeout=5)) as db:
            db.row_factory = sqlite3.Row
            db.execute("PRAGMA foreign_keys=ON")
            with db:
                if write:
                    db.execute("BEGIN IMMEDIATE")
                yield db

    @staticmethod
    def expire(db, now):
        db.execute("DELETE FROM requests WHERE expires<=?", (now,))
        db.execute("DELETE FROM codes WHERE expires<=?", (now,))
        db.execute("DELETE FROM grants WHERE expiry<=?", (now,))
        db.execute("DELETE FROM clients WHERE approved=0 AND created<?", (now - 7 * 86400,))

    async def register_client(self, client_info):
        urls = client_info.redirect_uris or []
        if not 1 <= len(urls) <= 10:
            raise RegistrationError("invalid_redirect_uri", "Register a desktop loopback callback.")
        for uri in urls:
            callback = urlsplit(str(uri))
            if (callback.scheme != "http" or callback.hostname not in {"127.0.0.1", "localhost", "::1"}
                    or callback.username is not None or callback.password is not None
                    or callback.fragment or callback.query):
                raise RegistrationError("invalid_redirect_uri", "A desktop loopback callback is required.")
        now = int(time.time())
        with self.database(write=True) as db:
            self.expire(db, now)
            db.execute("INSERT INTO clients(id,metadata,created) VALUES(?,?,?)",
                       (client_info.client_id, client_info.model_dump_json(), now))

    async def get_client(self, client_id):
        with self.database() as db:
            row = db.execute("SELECT metadata FROM clients WHERE id=?", (client_id,)).fetchone()
        return DesktopClient.model_validate_json(row["metadata"]) if row else None

    async def authorize(self, client, params):
        if params.resource not in (None, RESOURCE) or (params.scopes is not None and params.scopes != [SCOPE]):
            raise AuthorizeError("invalid_request", "This service can only authorize read access to the progress MCP.")
        if not re.fullmatch(r"[A-Za-z0-9_-]{43}", params.code_challenge):
            raise AuthorizeError("invalid_request", "An S256 PKCE challenge is required.")
        request_id = secrets.token_urlsafe(32)
        now = int(time.time())
        with self.database(write=True) as db:
            self.expire(db, now)
            db.execute("INSERT INTO requests(id,client,params,expires) VALUES(?,?,?,?)",
                       (fingerprint(request_id), client.client_id, params.model_dump_json(), now + 600))
        return ISSUER + "/consent?" + urlencode({"request": request_id})

    def consent(self, request_id, member, *, submitted=None):
        now = int(time.time())
        with self.database(write=True) as db:
            row = db.execute("""SELECT r.*,c.metadata FROM requests r JOIN clients c ON c.id=r.client
                                WHERE r.id=? AND r.expires>?""", (fingerprint(request_id), now)).fetchone()
            if not row:
                return HTMLResponse("授权申请已失效，请从客户端重新发起连接。", 400, headers=HEADERS)
            params = AuthorizationParams.model_validate_json(row["params"])
            if submitted is None:
                csrf = secrets.token_urlsafe(32)
                db.execute("UPDATE requests SET csrf=?,subject=?,session_ref=? WHERE id=?",
                           (fingerprint(csrf), member.subject, member.session_ref, row["id"]))
                client = OAuthClientInformationFull.model_validate_json(row["metadata"])
                return consent_form(client, params, request_id, csrf)
            if (row["subject"] != member.subject or row["session_ref"] != member.session_ref
                    or not secrets.compare_digest(fingerprint(submitted.get("csrf", "")), row["csrf"] or "")):
                return HTMLResponse("授权表单已失效，请刷新后重试。", 403, headers=HEADERS)
            decision = submitted.get("decision")
            if decision not in ("allow", "deny"):
                return HTMLResponse("请选择允许或取消。", 400, headers=HEADERS)
            db.execute("DELETE FROM requests WHERE id=?", (row["id"],))
            if decision == "deny":
                target = construct_redirect_uri(str(params.redirect_uri), error="access_denied", state=params.state)
            else:
                code = secrets.token_urlsafe(32)
                db.execute("INSERT INTO codes VALUES(?,?,?,?,?,?)",
                           (fingerprint(code), row["client"], row["params"], now + 90, member.subject, member.session_ref))
                db.execute("UPDATE clients SET approved=1 WHERE id=?", (row["client"],))
                target = construct_redirect_uri(str(params.redirect_uri), code=code, state=params.state)
        return RedirectResponse(target, status_code=303, headers=HEADERS)

    async def load_authorization_code(self, client, authorization_code):
        with self.database() as db:
            row = db.execute("SELECT * FROM codes WHERE id=? AND client=? AND expires>?",
                             (fingerprint(authorization_code), client.client_id, int(time.time()))).fetchone()
        if not row or not await self.session_active(row["subject"], row["session_ref"]):
            return None
        params = AuthorizationParams.model_validate_json(row["params"])
        return AuthorizationCode(code=authorization_code, client_id=client.client_id, expires_at=row["expires"],
                                 scopes=[SCOPE], subject=row["subject"], resource=RESOURCE,
                                 code_challenge=params.code_challenge, redirect_uri=params.redirect_uri,
                                 redirect_uri_provided_explicitly=params.redirect_uri_provided_explicitly)

    @staticmethod
    def token_pair(expires):
        return OAuthToken(access_token=secrets.token_urlsafe(32), refresh_token=secrets.token_urlsafe(40),
                          expires_in=expires, scope=SCOPE)

    async def exchange_authorization_code(self, client, authorization_code):
        now = int(time.time())
        code_id = fingerprint(authorization_code.code)
        with self.database(write=True) as db:
            row = db.execute("SELECT * FROM codes WHERE id=? AND client=? AND expires>?",
                             (code_id, client.client_id, now)).fetchone()
            if row:
                db.execute("DELETE FROM codes WHERE id=?", (code_id,))
                pair = self.token_pair(ACCESS_SECONDS)
                db.execute("INSERT INTO grants VALUES(?,?,?,?,?,?,?,?)",
                           (secrets.token_urlsafe(24), row["client"], row["subject"], row["session_ref"],
                            fingerprint(pair.access_token), fingerprint(pair.refresh_token), now + ACCESS_SECONDS, now + GRANT_SECONDS))
        if not row:
            raise TokenError("invalid_grant", "The code has expired or was already exchanged.")
        return pair

    async def load_access_token(self, token):
        if not token or len(token) > 512:
            return None
        with self.database() as db:
            row = db.execute("SELECT * FROM grants WHERE access=? AND access_expiry>?",
                             (fingerprint(token), int(time.time()))).fetchone()
        if not row or not await self.session_active(row["subject"], row["session_ref"]):
            return None
        return AccessToken(token=token, client_id=row["client"], subject=row["subject"],
                           scopes=[SCOPE], resource=RESOURCE, expires_at=row["access_expiry"])

    async def load_refresh_token(self, client, refresh_token):
        value = fingerprint(refresh_token)
        with self.database(write=True) as db:
            row = db.execute("SELECT * FROM grants WHERE refresh=? AND client=? AND expiry>?",
                             (value, client.client_id, int(time.time()))).fetchone()
            if not row:
                # Reuse of a previously rotated refresh token ends its authorization family.
                db.execute("DELETE FROM grants WHERE client=? AND id=(SELECT grant_id FROM used_refresh WHERE hash=?)",
                           (client.client_id, value))
                return None
        if not await self.session_active(row["subject"], row["session_ref"]):
            return None
        return RefreshToken(token=refresh_token, client_id=client.client_id, subject=row["subject"],
                            scopes=[SCOPE], resource=RESOURCE, expires_at=row["expiry"])

    async def exchange_refresh_token(self, client, refresh_token, scopes):
        if scopes != [SCOPE]:
            raise TokenError("invalid_scope", "The only scope is progress.read.")
        value = fingerprint(refresh_token.token)
        now = int(time.time())
        with self.database(write=True) as db:
            row = db.execute("SELECT id,expiry FROM grants WHERE refresh=? AND client=? AND expiry>?",
                             (value, client.client_id, now)).fetchone()
            if row:
                duration = min(ACCESS_SECONDS, row["expiry"] - now)
                pair = self.token_pair(duration)
                db.execute("INSERT INTO used_refresh VALUES(?,?)", (value, row["id"]))
                db.execute("UPDATE grants SET access=?,refresh=?,access_expiry=? WHERE id=?",
                           (fingerprint(pair.access_token), fingerprint(pair.refresh_token), now + duration, row["id"]))
            else:
                db.execute("DELETE FROM grants WHERE client=? AND id=(SELECT grant_id FROM used_refresh WHERE hash=?)",
                           (client.client_id, value))
        if not row:
            raise TokenError("invalid_grant", "The refresh token is no longer active.")
        return pair

    async def revoke_token(self, token):
        value = fingerprint(token.token)
        with self.database(write=True) as db:
            db.execute("DELETE FROM grants WHERE client=? AND (access=? OR refresh=?)", (token.client_id, value, value))


def consent_form(client, params, request_id, csrf):
    name = escape((client.client_name or "桌面 Agent")[:160])
    callback = escape(str(params.redirect_uri))
    return HTMLResponse(f"""<!doctype html><html lang="zh-CN"><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1"><title>授权读取团队科研进度</title>
<style>body{{margin:0;background:#f3f6f8;color:#142838;font:1rem/1.65 system-ui,sans-serif}}
main{{max-width:32rem;margin:8vh auto;background:white;padding:clamp(1rem,5vw,2.5rem);border:1px solid #d4dfe4}}
h1{{font-size:1.5rem}}code{{overflow-wrap:anywhere}}button{{font:inherit;padding:.45rem .85rem;margin:.4rem .4rem 0 0}}
button:first-child{{background:#104b61;color:white;border:1px solid #104b61}}</style>
<main><h1>授权读取团队科研进度</h1><p>客户端 <strong>{name}</strong> 请求使用你的飞书成员身份读取团队、成员、研究方向和方法记录。</p>
<p>授权结果将发送到这台设备的回调地址<br><code>{callback}</code></p>
<form method="post" action="{PREFIX}/consent"><input type="hidden" name="request" value="{escape(request_id)}">
<input type="hidden" name="csrf" value="{csrf}"><button name="decision" value="allow">允许只读访问</button>
<button name="decision" value="deny">取消</button></form></main></html>""", headers=HEADERS)


def oauth_routes(provider, browser_member):
    options = ClientRegistrationOptions(enabled=True, valid_scopes=[SCOPE], default_scopes=[SCOPE])
    revocation = RevocationOptions(enabled=True)
    issuer = AnyHttpUrl(ISSUER)
    docs = AnyHttpUrl(ORIGIN + "/docs/progress-mcp.md")
    metadata = build_metadata(issuer, docs, options, revocation)
    metadata.token_endpoint_auth_methods_supported = ["none", "client_secret_post", "client_secret_basic"]
    metadata.revocation_endpoint_auth_methods_supported = metadata.token_endpoint_auth_methods_supported

    async def discovery(request):
        return JSONResponse(metadata.model_dump(mode="json", exclude_none=True))

    async def consent(request):
        if request.method == "POST" and request.headers.get("origin") != ORIGIN:
            return HTMLResponse("授权表单来源无效。", 403, headers=HEADERS)
        form = await request.form() if request.method == "POST" else None
        key = (request.query_params if form is None else form).get("request", "")
        if not isinstance(key, str) or not re.fullmatch(r"[\w-]{43}", key, re.ASCII):
            return HTMLResponse("请从客户端发起授权。", 400, headers=HEADERS)
        member = await browser_member(request)
        if not member:
            address = PREFIX + "/consent?" + urlencode({"request": key})
            return RedirectResponse(ORIGIN + "/auth/login?" + urlencode({"return_to": address}),
                                    status_code=303, headers=HEADERS)
        return provider.consent(key, member, submitted=form)

    authenticator = ClientAuthenticator(provider)
    token_handler = TokenHandler(provider, authenticator)

    async def token(request):
        form = await request.form()
        if form.getlist("resource") not in ([], [RESOURCE]):
            return JSONResponse({"error": "invalid_target"}, status_code=400, headers={"Cache-Control": "no-store"})
        return await token_handler.handle(request)

    async def revoke(request):
        # The 1.x SDK's revocation model requires a client_secret form field even for public clients.
        try:
            client = await authenticator.authenticate_request(request)
        except AuthenticationError:
            return JSONResponse({"error": "invalid_client"}, status_code=401, headers=HEADERS)
        form = await request.form()
        value = form.get("token")
        if not isinstance(value, str) or not value:
            return JSONResponse({"error": "invalid_request"}, status_code=400, headers=HEADERS)
        await provider.revoke_token(AccessToken(token=value, client_id=client.client_id, scopes=[SCOPE]))
        return HTMLResponse("", headers=HEADERS)

    routes = [Route("/.well-known/oauth-authorization-server" + PREFIX,
                    endpoint=cors_middleware(discovery, ["GET", "OPTIONS"]), methods=["GET", "OPTIONS"]),
              Route(PREFIX + "/consent", endpoint=RequestBodyLimitMiddleware(request_response(consent), 8192),
                    methods=["GET", "POST"])]
    for sdk_route in create_auth_routes(provider, issuer, docs, options, revocation):
        if sdk_route.path.startswith("/.well-known"):
            continue
        custom = {"/token": token, "/revoke": revoke}.get(sdk_route.path)
        handler = cors_middleware(custom, ["POST", "OPTIONS"]) if custom else sdk_route.endpoint
        routes.append(Route(PREFIX + sdk_route.path, endpoint=RequestBodyLimitMiddleware(handler, 16384),
                            methods=sdk_route.methods))
    return routes

