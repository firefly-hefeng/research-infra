"""Member consent and read-only desktop OAuth lifecycle, using only synthetic sessions."""
import base64
import hashlib
import importlib.util
import re
import sys
import tempfile
import unittest
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))
if importlib.util.find_spec("mcp"):
    from progress_mcp_oauth import Binding, ORIGIN, PREFIX, RESOURCE, SCOPE, ProgressOAuthProvider, oauth_routes
    from starlette.applications import Starlette
    from starlette.testclient import TestClient


@unittest.skipUnless(importlib.util.find_spec("mcp"), "Install the progress MCP requirements.")
class MemberOAuthTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.binding = Binding("a" * 64, "b" * 64)
        self.active = True
        self.callback = "http://127.0.0.1:14783/callback"
        self.verifier = "z" * 70
        self.challenge = base64.urlsafe_b64encode(hashlib.sha256(self.verifier.encode()).digest()).decode().rstrip("=")
        self.mount()
        self.client_id = self.register(self.callback).json()["client_id"]

    def mount(self):
        async def session_active(subject, session_ref):
            return self.active and Binding(subject, session_ref) == self.binding

        async def browser_member(request):
            if self.active and request.headers.get("x-test-member") == "synthetic":
                return self.binding
            return None

        self.provider = ProgressOAuthProvider(Path(self.tmp.name) / "state.db", session_active)
        self.web = TestClient(Starlette(routes=oauth_routes(self.provider, browser_member)),
                              base_url=ORIGIN, follow_redirects=False)
        self.addCleanup(self.web.close)

    def register(self, uri):
        return self.web.post(PREFIX + "/register", json={"redirect_uris": [uri], "client_name": "Test desktop",
                                                        "token_endpoint_auth_method": "none"})

    def authorize(self, **changes):
        params = {"client_id": self.client_id, "response_type": "code", "scope": SCOPE,
                  "code_challenge_method": "S256", "code_challenge": self.challenge,
                  "redirect_uri": self.callback, "state": "client-opaque-state", "resource": RESOURCE}
        params.update(changes)
        return self.web.get(PREFIX + "/authorize", params=params)

    def approve(self, *, decision="allow", callback=None):
        start = self.authorize(redirect_uri=callback or self.callback)
        self.assertEqual(start.status_code, 302, start.text)
        consent = start.headers["location"]
        login = self.web.get(consent)
        self.assertEqual(login.status_code, 303)
        self.assertEqual(urlsplit(login.headers["location"]).path, "/auth/login")
        self.assertEqual(parse_qs(urlsplit(login.headers["location"]).query)["return_to"][0], consent.removeprefix(ORIGIN))
        page = self.web.get(consent, headers={"x-test-member": "synthetic"})
        self.assertEqual(page.status_code, 200)
        request_id, csrf = (re.search('name="' + field + '" value="([^"]+)"', page.text).group(1)
                            for field in ("request", "csrf"))
        submitted = {"request": request_id, "csrf": csrf, "decision": decision}
        self.assertEqual(self.web.post(PREFIX + "/consent", data=submitted,
                                       headers={"origin": "https://wrong.invalid", "x-test-member": "synthetic"}).status_code, 403)
        headers = {"origin": ORIGIN, "x-test-member": "synthetic"}
        result = self.web.post(PREFIX + "/consent", data=submitted, headers=headers)
        self.assertEqual(result.status_code, 303, result.text)
        self.assertEqual(self.web.post(PREFIX + "/consent", data=submitted, headers=headers).status_code, 400)
        query = parse_qs(urlsplit(result.headers["location"]).query)
        self.assertEqual(query.pop("state"), ["client-opaque-state"])
        return query

    def exchange(self, code, **extras):
        data = {"grant_type": "authorization_code", "client_id": self.client_id, "code": code,
                "code_verifier": self.verifier, "redirect_uri": self.callback, "resource": RESOURCE}
        return self.web.post(PREFIX + "/token", data={**data, **extras})

    def refresh(self, token):
        return self.web.post(PREFIX + "/token", data={"grant_type": "refresh_token", "client_id": self.client_id,
                                                      "refresh_token": token, "resource": RESOURCE})

    def access(self, token):
        import asyncio
        return asyncio.run(self.provider.load_access_token(token))

    def test_desktop_discovery_restrictions_and_member_can_decline(self):
        meta = self.web.get("/.well-known/oauth-authorization-server" + PREFIX).json()
        self.assertEqual(meta["issuer"], ORIGIN + PREFIX)
        self.assertEqual(meta["authorization_endpoint"], ORIGIN + PREFIX + "/authorize")
        self.assertIn("none", meta["token_endpoint_auth_methods_supported"])
        self.assertEqual(meta["code_challenge_methods_supported"], ["S256"])
        self.assertEqual(self.register("https://other.invalid/callback").status_code, 400)
        self.assertEqual(self.approve(decision="deny"), {"error": ["access_denied"]})
        self.client_id = self.register("http://127.0.0.1/callback").json()["client_id"]
        ephemeral = "http://127.0.0.1:27971/callback"
        code = self.approve(callback=ephemeral)["code"][0]
        self.assertEqual(self.exchange(code, redirect_uri=ephemeral).status_code, 200)
        self.assertIn("error=", self.authorize(resource=ORIGIN + "/other").headers["location"])

    def test_pkce_rotation_replay_restart_logout_and_revocation(self):
        code = self.approve()["code"][0]
        self.assertEqual(self.exchange(code, code_verifier="incorrect").status_code, 400)
        self.assertEqual(self.exchange(code, resource=ORIGIN + "/other").status_code, 400)
        pair = self.exchange(code).json()
        self.assertEqual(pair["scope"], SCOPE)
        self.assertEqual(self.exchange(code).status_code, 400)
        self.mount()
        access = self.access(pair["access_token"])
        self.assertEqual((access.subject, access.resource), (self.binding.subject, RESOURCE))
        new = self.refresh(pair["refresh_token"]).json()
        self.assertIsNone(self.access(pair["access_token"]))
        self.assertIsNotNone(self.access(new["access_token"]))
        self.assertEqual(self.refresh(pair["refresh_token"]).status_code, 400)
        self.assertIsNone(self.access(new["access_token"]))
        pair = self.exchange(self.approve()["code"][0]).json()
        revoked = self.web.post(PREFIX + "/revoke", data={"client_id": self.client_id, "token": pair["access_token"]})
        self.assertEqual(revoked.status_code, 200)
        self.assertEqual(self.refresh(pair["refresh_token"]).status_code, 400)
        pair = self.exchange(self.approve()["code"][0]).json()
        self.active = False
        self.assertIsNone(self.access(pair["access_token"]))
        self.assertEqual(self.refresh(pair["refresh_token"]).status_code, 400)

    def test_authorization_is_bound_to_the_member_who_saw_the_form(self):
        consent = self.authorize().headers["location"]
        headers = {"x-test-member": "synthetic", "origin": ORIGIN}
        page = self.web.get(consent, headers=headers)
        form = {key: re.search('name="' + key + '" value="([^"]+)"', page.text).group(1)
                for key in ("request", "csrf")}
        self.binding = Binding("c" * 64, "d" * 64)
        self.assertEqual(self.web.post(PREFIX + "/consent", headers=headers,
                                       data={**form, "decision": "allow"}).status_code, 403)

    def test_two_requests_loading_the_same_grant_before_either_commits(self):
        import asyncio
        from progress_mcp_oauth import TokenError
        code = self.approve()["code"][0]
        client = asyncio.run(self.provider.get_client(self.client_id))
        loaded = asyncio.run(self.provider.load_authorization_code(client, code))
        pair = asyncio.run(self.provider.exchange_authorization_code(client, loaded))
        with self.assertRaises(TokenError):
            asyncio.run(self.provider.exchange_authorization_code(client, loaded))
        token = asyncio.run(self.provider.load_refresh_token(client, pair.refresh_token))
        rolled = asyncio.run(self.provider.exchange_refresh_token(client, token, [SCOPE]))
        with self.assertRaises(TokenError):
            asyncio.run(self.provider.exchange_refresh_token(client, token, [SCOPE]))
        self.assertIsNone(self.access(rolled.access_token))


if __name__ == "__main__":
    unittest.main()

