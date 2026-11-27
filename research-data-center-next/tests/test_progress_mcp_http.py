import importlib.util
import time
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock


@unittest.skipUnless(importlib.util.find_spec("mcp"), "安装 tools/requirements-progress-mcp.txt 后运行")
class RemoteProgressTest(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        import httpx
        from tools.progress_mcp_http import ORIGIN, RESOURCE, SCOPE, build_app

        self.resource = RESOURCE
        self.token = SimpleNamespace(resource=RESOURCE, scopes=[SCOPE], expires_at=int(time.time()) + 300)
        self.provider = SimpleNamespace(load_access_token=AsyncMock(return_value=self.token))
        self.browser_member = AsyncMock(return_value=None)
        self.app = build_app(SyntheticSource(), self.provider, self.browser_member, [])
        self.client = httpx.AsyncClient(transport=httpx.ASGITransport(app=self.app), base_url=ORIGIN)
        self.addAsyncCleanup(self.client.aclose)
        self.headers = {"accept": "application/json, text/event-stream", "content-type": "application/json"}

    async def request(self, headers=None):
        return await self.client.post("/mcp", headers=self.headers | (headers or {}), json={
            "jsonrpc": "2.0", "id": 1, "method": "initialize",
            "params": {"protocolVersion": "2025-11-25", "capabilities": {}, "clientInfo": {"name": "test", "version": "1"}},
        })

    async def test_discovery_and_denials(self):
        async with self.app.router.lifespan_context(self.app):
            from tools.progress_mcp_http import ISSUER, METADATA
            response = await self.request()
            self.assertEqual(response.status_code, 401)
            self.assertIn(METADATA, response.headers["WWW-Authenticate"])
            self.assertEqual((await self.client.get(METADATA)).json()["authorization_servers"], [ISSUER])
            self.assertEqual((await self.client.get(METADATA)).json()["resource"], self.resource)
            self.assertEqual((await self.request({"Origin": "https://elsewhere.invalid"})).status_code, 403)
            self.assertEqual((await self.request({"Host": "elsewhere.invalid"})).status_code, 400)
            self.assertEqual((await self.request({"X-Authenticated-User": "test-member"})).status_code, 401)

    async def test_cookie_bearer_audience_and_revocation(self):
        async with self.app.router.lifespan_context(self.app):
            from tools.progress_mcp_http import ORIGIN
            cookie = {"Cookie": "__Host-rmp_session=synthetic", "Origin": ORIGIN}
            self.browser_member.return_value = object()
            self.assertEqual((await self.request({"Cookie": "__Host-rmp_session=synthetic"})).status_code, 403)
            self.assertEqual((await self.request(cookie)).status_code, 200)
            self.browser_member.return_value = None
            self.assertEqual((await self.request(cookie)).status_code, 401)
            self.token.resource = "https://elsewhere.invalid/"
            self.browser_member.return_value = object()
            bearer = {"Authorization": "Bearer synthetic", "Cookie": "__Host-rmp_session=synthetic"}
            self.assertEqual((await self.request(bearer)).status_code, 401)
            self.token.resource = self.resource
            self.token.scopes = []
            self.assertEqual((await self.request(bearer)).status_code, 403)
            self.token.scopes = ["progress.read"]
            self.token.expires_at = int(time.time()) - 1
            self.assertEqual((await self.request(bearer)).status_code, 401)

    async def test_official_http_client(self):
        async with self.app.router.lifespan_context(self.app):
            from mcp import ClientSession
            from mcp.client.streamable_http import streamable_http_client

            self.client.headers["Authorization"] = "Bearer synthetic"
            async with streamable_http_client(self.resource, http_client=self.client) as (rx, tx, _), ClientSession(rx, tx) as session:
                self.assertEqual((await session.initialize()).serverInfo.name, "research-progress")
                tools = (await session.list_tools()).tools
                self.assertEqual({t.name for t in tools}, {"team_progress", "member_progress", "direction_progress", "direction_methods"})
                result = await session.call_tool("direction_methods", {})
                self.assertEqual(result.structuredContent["data"]["methods"]["items"][0]["id"], "example")
            self.assertGreaterEqual(self.provider.load_access_token.await_count, 3)

    async def test_unavailable_gateway_is_temporary(self):
        from tools.progress_mcp_http import GatewayUnavailable, ORIGIN
        self.browser_member.side_effect = GatewayUnavailable()
        response = await self.request({"Cookie": "__Host-rmp_session=synthetic", "Origin": ORIGIN})
        self.assertEqual(response.status_code, 503)
        self.assertNotIn("WWW-Authenticate", response.headers)

    async def test_gateway_filters_cookies_and_binding(self):
        from unittest.mock import Mock
        from tools.progress_mcp_http import FeishuSessions, GatewayUnavailable, SESSION_COOKIE
        member = SimpleNamespace(cookies={SESSION_COOKIE: "fake", "elsewhere": "omit"})
        gateway = FeishuSessions("http://127.0.0.1:1234", lambda *args: args)
        gateway._request = Mock(return_value={"X-RMP-Subject": "a" * 64, "X-RMP-Session-Ref": "b" * 64})
        self.assertEqual(await gateway.browser_member(member), ("a" * 64, "b" * 64))
        gateway._request.assert_called_once_with("GET", "/internal/mcp/member", {"Cookie": SESSION_COOKIE + "=fake"})
        gateway._request.return_value = {}
        with self.assertRaises(GatewayUnavailable):
            await gateway.browser_member(member)
        self.assertTrue(await gateway.session_active("a" * 64, "b" * 64))
        self.assertEqual(gateway._request.call_args.args[2], {"Content-Type": "application/json"})
        gateway._request.return_value = None
        self.assertFalse(await gateway.session_active("a" * 64, "b" * 64))

    async def test_gateway_reverification_preserves_pending_consent(self):
        from unittest.mock import Mock, patch
        from tools.progress_mcp_http import FeishuSessions, SESSION_COOKIE, SessionReverification
        gateway = FeishuSessions("http://127.0.0.1:1234", tuple)
        req = SimpleNamespace(cookies={SESSION_COOKIE: "example"}, url=SimpleNamespace(path="/mcp"))
        with patch("tools.progress_mcp_http.http.client.HTTPConnection") as connection:
            upstream = connection.return_value.getresponse.return_value
            upstream.status = 401
            upstream.getheader.return_value = "reverify"
            with self.assertRaises(SessionReverification):
                await gateway.browser_member(req)
            req.url.path = "/mcp/oauth/consent"
            self.assertIsNone(await gateway.browser_member(req))
            upstream.getheader.return_value = None
            self.assertFalse(await gateway.session_active("a" * 64, "b" * 64))

    async def test_official_client_discovers_authorizes_and_reads(self):
        import re
        import tempfile
        from pathlib import Path
        from urllib.parse import parse_qs, urlsplit

        import httpx
        from mcp import ClientSession
        from mcp.client.auth import OAuthClientProvider
        from mcp.client.streamable_http import streamable_http_client
        from mcp.shared.auth import OAuthClientMetadata
        from tools.progress_mcp_http import ORIGIN, SCOPE, SessionReverification, build_app
        from tools.progress_mcp_oauth import Binding, PREFIX, ProgressOAuthProvider, oauth_routes

        callback = "http://127.0.0.1:12999/callback"
        member = Binding("a" * 64, "b" * 64)
        active = AsyncMock(return_value=True)
        browser_member = AsyncMock(return_value=member)
        storage = SimpleNamespace(get_tokens=AsyncMock(return_value=None), get_client_info=AsyncMock(return_value=None))

        async def save_tokens(tokens):
            storage.get_tokens.return_value = tokens

        async def save_client(client):
            storage.get_client_info.return_value = client

        storage.set_tokens, storage.set_client_info = save_tokens, save_client
        redirected = {}
        with tempfile.TemporaryDirectory() as work:
            provider = ProgressOAuthProvider(Path(work) / "oauth.db", active)
            app = build_app(SyntheticSource(), provider, browser_member, oauth_routes(provider, browser_member))
            transport = httpx.ASGITransport(app=app)
            async with app.router.lifespan_context(app), httpx.AsyncClient(transport=transport, base_url=ORIGIN) as browser:
                async def show_consent(url):
                    self.assertTrue(url.startswith(ORIGIN + PREFIX + "/authorize?"))
                    response = await browser.get(url)
                    page = await browser.get(response.headers["location"])
                    form = {key: re.search('name="' + key + '" value="([^"]+)"', page.text).group(1)
                            for key in ("request", "csrf")}
                    result = await browser.post(PREFIX + "/consent", data={**form, "decision": "allow"},
                                                headers={"Origin": ORIGIN})
                    self.assertTrue(result.headers["location"].startswith(callback + "?"))
                    redirected.update(parse_qs(urlsplit(result.headers["location"]).query))

                async def callback_result():
                    return redirected["code"][0], redirected["state"][0]

                auth = OAuthClientProvider(self.resource, OAuthClientMetadata(
                    client_name="SDK test", redirect_uris=[callback], token_endpoint_auth_method="none", scope=SCOPE,
                ), storage, show_consent, callback_result)
                async with httpx.AsyncClient(transport=transport, base_url=ORIGIN, auth=auth) as remote:
                    async with streamable_http_client(self.resource, http_client=remote) as (rx, tx, _), ClientSession(rx, tx) as client:
                        await client.initialize()
                        self.assertEqual(len((await client.list_tools()).tools), 4)
                        result = await client.call_tool("direction_methods", {})
                        self.assertEqual(result.structuredContent["data"]["methods"]["items"][0]["id"], "example")
                tokens = await storage.get_tokens()
                token = tokens.access_token
                active.side_effect = SessionReverification()
                bearer = {"Authorization": "Bearer " + token}
                temporarily_paused = await browser.post("/mcp", headers=bearer, json={})
                self.assertEqual(temporarily_paused.status_code, 503)
                self.assertEqual(temporarily_paused.json()["verification_uri"], ORIGIN + "/auth/account")
                self.assertNotIn("WWW-Authenticate", temporarily_paused.headers)
                refresh = {"grant_type": "refresh_token", "client_id": (await storage.get_client_info()).client_id,
                           "refresh_token": tokens.refresh_token, "resource": self.resource}
                paused_refresh = await browser.post(PREFIX + "/token", data=refresh)
                self.assertEqual(paused_refresh.status_code, 503)
                self.assertEqual(paused_refresh.json()["reason"], "feishu_session_reverification_required")
                active.side_effect = None
                resumed = await browser.post(PREFIX + "/token", data=refresh)
                self.assertEqual(resumed.status_code, 200)
                token = resumed.json()["access_token"]
                active.return_value = False
                denied = await browser.post("/mcp", headers={"Authorization": "Bearer " + token}, json={})
                self.assertEqual(denied.status_code, 401)


class SyntheticSource:
    mode = "feishu_member_service"

    def get(self, key):
        assert key == "methods"
        return {"directions": [{"id": "example", "methods": []}]}, {}
