"""Documented access must match optional catalog auth; snapshots never imply live access."""
import contextlib
import importlib.util
import io
import json
from pathlib import Path
import re
import tempfile
import unittest

from server import agent_manifest, openapi_document
from tools.progress_mcp_source import PATHS

ROOT=Path(__file__).resolve().parents[1]
spec=importlib.util.spec_from_file_location('agent_reader',ROOT/'tools/agent_client.py')
client=importlib.util.module_from_spec(spec);spec.loader.exec_module(client)

class AgentAccessTests(unittest.TestCase):
    def test_manifest_distinguishes_gateway_from_optional_backend_auth(self):
        contract=json.loads((ROOT/'docs/agent-contract.json').read_text(encoding='utf-8'))
        for enabled in (False,True):
            manifest=agent_manifest(enabled)
            self.assertEqual(manifest['authentication']['catalog_token_enabled'],enabled)
            self.assertFalse(manifest['authentication']['self_service_agent_tokens'])
            self.assertIn('Feishu',manifest['authentication']['public_platform'])
            self.assertIn('not an MCP credential',manifest['authentication']['backend_bearer'])
            self.assertIn('OAuth access token',manifest['authentication']['mcp_oauth_bearer'])
            self.assertEqual(manifest['documentation']['start'],'/docs/agent-guide.md')
            self.assertEqual(manifest['documentation']['progress_mcp'],'/docs/progress-mcp.md')
            self.assertEqual(manifest['modules']['papers'],'/papers/api/export')
            self.assertEqual(manifest['mcp'],contract['mcp'])
            self.assertEqual(bool(openapi_document(enabled)['security']),enabled)
        mcp=contract['mcp']
        self.assertEqual(mcp['remote_url'],mcp['resource'])
        self.assertEqual(mcp['issuer'],mcp['resource']+'/oauth')
        self.assertEqual(mcp['discovery'],{
            'resource':'https://rmp.wuwangwo.top/.well-known/oauth-protected-resource/mcp',
            'authorization_server':'https://rmp.wuwangwo.top/.well-known/oauth-authorization-server/mcp/oauth'})
        self.assertEqual(mcp['transports'],['streamable_http','stdio'])
        self.assertEqual(mcp['oauth'],{'scope':'progress.read','pkce':'S256','callback':'desktop_loopback_http'})
        self.assertEqual(set(mcp['tools']),{'team_progress','member_progress','direction_progress','direction_methods'})
        self.assertTrue(mcp['read_only'])
        self.assertTrue(mcp['team_shared_not_per_member_rbac'])
        self.assertEqual(openapi_document()['externalDocs']['url'],'/docs/agent-guide.md')

    def test_offline_snapshot_keeps_failed_sources_and_never_connects(self):
        with tempfile.TemporaryDirectory() as temp:
            path=Path(temp)/'context.json'
            value={'schema_version':'1.0','mode':'offline_snapshot','generated_at':'2026-11-15T00:00:00Z',
                   'sources':{'one':{'url':'/api/platform/library','status':'ok','data':{'items':[{'id':'stable-id'}]}},
                              'two':{'url':'/progress/api/progress-digest','status':'failed','error_code':'503'}}}
            path.write_text(json.dumps(value),encoding='utf-8')
            output,error=io.StringIO(),io.StringIO()
            with contextlib.redirect_stdout(output),contextlib.redirect_stderr(error):
                self.assertEqual(client.main(['--snapshot',str(path),'library']),0)
            self.assertEqual(json.loads(output.getvalue())['items'][0]['id'],'stable-id')
            with contextlib.redirect_stdout(io.StringIO()),contextlib.redirect_stderr(error):
                self.assertEqual(client.main(['--snapshot',str(path),'progress']),1)
            self.assertIn('not an empty result',error.getvalue())
            with contextlib.redirect_stdout(io.StringIO()),contextlib.redirect_stderr(io.StringIO()):
                self.assertEqual(client.main(['--snapshot',str(path),'context']),0)

    def test_client_rejects_credentials_in_url_and_reports_login_without_following(self):
        with contextlib.redirect_stderr(io.StringIO()) as error:
            self.assertEqual(client.main(['--base-url','https://name:secret@example.invalid','library']),1)
        self.assertNotIn('secret',error.getvalue())
        self.assertIsNone(client.NoRedirect().redirect_request(None,None,302,'login',{},'https://example.invalid'))

    def test_fixed_snapshot_sources_match_contract_and_mcp_paths(self):
        contract=json.loads((ROOT/'docs/agent-contract.json').read_text(encoding='utf-8'))
        self.assertFalse(contract['access']['personal_agent_token_self_service'])
        self.assertTrue(all(x['method']=='GET' for x in contract['reads']))
        self.assertEqual(len({x['url'] for x in contract['reads']}),11)
        expected={x['snapshot_key']:x['url'] for x in contract['reads']}
        expected.update(guide='/docs/agent-guide.md',contract='/docs/agent-contract.json')
        script=(ROOT/'static/agent-context.js').read_text(encoding='utf-8')
        exported=dict(re.findall(r'\{ name: "([^"]+)", label: "[^"]+", url: "([^"]+)"(?:, text: true)? \}',script))
        self.assertEqual(exported,expected)
        self.assertEqual({key:expected[name] for key,name in {
            'digest':'progress_digest','review':'lab_review','directions':'directions','methods':'direction_methods'}.items()},PATHS)
        self.assertIn('paper_shared_notes',contract['snapshot']['contains'])
        for name in ('agent-guide.md','agent-status.md','agent-maintenance.md','progress-mcp.md'):
            self.assertTrue((ROOT/'docs'/name).is_file())
