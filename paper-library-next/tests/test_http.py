import json
import http.client
import os
from pathlib import Path
import socket
import subprocess
import sys
import tempfile
import time
import unittest
from urllib.request import Request, urlopen
from urllib.error import HTTPError, URLError
from paperlib.library import Library, digest
from paperlib.server import catalog_paper
from test_library import pdf_bytes


class HTTPTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        cls.root = Path(cls.tmp.name) / 'papers'
        cls.library = Library(cls.root)
        file = cls.root/'inbox'/'paper.pdf'; file.write_bytes(pdf_bytes()); cls.id=digest(file)
        cls.library.scan(settle_seconds=0)
        with socket.socket() as sock:
            sock.bind(('127.0.0.1',0)); cls.port=sock.getsockname()[1]
        cls.url = 'http://127.0.0.1:' + str(cls.port)
        cls.log = tempfile.TemporaryFile()
        env={**os.environ,'PAPER_PASSWORD':'test-password-for-http-测试','PAPER_AGENT_COMMAND':'','PAPER_SCHEDULE_ENABLED':'0'}
        cls.process=subprocess.Popen([sys.executable,'manage.py','--root',str(cls.root),'serve','--port',str(cls.port)],env=env,stdout=cls.log,stderr=cls.log)
        for _ in range(60):
            try:
                with urlopen(cls.url) as r:
                    if r.status==200: break
            except URLError: time.sleep(.05)
        else:
            cls.process.terminate(); cls.process.wait(); cls.log.seek(0)
            raise RuntimeError(cls.log.read().decode())
        req=Request(cls.url+'/api/login',data=json.dumps({'password':'test-password-for-http-测试'}).encode(),headers={'Content-Type':'application/json','X-Paper-Library':'1'})
        with urlopen(req) as r: cls.cookie=r.headers['Set-Cookie'].split(';')[0]

    @classmethod
    def tearDownClass(cls):
        cls.process.terminate(); cls.process.wait(timeout=10); cls.log.close(); cls.tmp.cleanup()

    def request(self,path,method='GET',body=None,headers=None,auth=True):
        h={'Content-Type':'application/json','X-Paper-Library':'1'}
        if auth: h['Cookie']=self.cookie
        h.update(headers or {})
        connection = http.client.HTTPConnection('127.0.0.1', self.port, timeout=5)
        try:
            connection.request(method, path, body=json.dumps(body).encode() if body is not None else None, headers=h)
            response = connection.getresponse()
            return response.status, response.read(), response.headers
        finally:
            connection.close()

    def test_state_and_static(self):
        code,body,h=self.request('/api/state'); self.assertEqual(code,200)
        self.assertEqual(json.loads(body)['papers'][0]['id'],self.id)
        self.assertFalse(json.loads(body)['agent']['configured'])
        self.assertEqual(self.request('/app.js')[0],200)
        self.assertIn("default-src 'self'",h['Content-Security-Policy'])

    def test_catalog_and_pdf_require_login(self):
        self.assertEqual(self.request('/api/state',auth=False)[0],401)
        self.assertEqual(self.request('/api/catalog', auth=False)[0], 401)
        self.assertEqual(self.request('/api/papers/' + self.id + '/pdf', auth=False)[0], 401)
        code, body, _ = self.request('/api/catalog')
        self.assertEqual(code, 200)
        data = json.loads(body)
        self.assertEqual(data['papers'][0]['id'], self.id)
        self.assertTrue(data['papers'][0]['fulltext_available'])
        self.assertFalse(data['access']['can_manage'])
        self.assertTrue(json.loads(self.request('/api/state')[1])['access']['can_manage'])
        code, body, _ = self.request('/api/papers/'+self.id+'/pdf')
        self.assertEqual(code, 200)
        self.assertEqual(body, pdf_bytes())
        code, body, _ = self.request('/api/papers/'+self.id+'/pdf',
                                     headers={'Range': 'bytes=0-4'})
        self.assertEqual((code, body), (206, b'%PDF-'))
        self.assertEqual(self.request('/manage', auth=False)[0], 200)

    def test_public_catalog_does_not_expose_workspace_data(self):
        before = self.library.record(self.id)
        self.library.edit(self.id, {'notes': 'private note marker', 'favorite': True})
        try:
            code, body, _ = self.request('/api/catalog')
            self.assertEqual(code, 200)
            data = json.loads(body)
            paper = data['papers'][0]
            for key in ('root', 'inbox', 'scheduler_error'):
                self.assertNotIn(key, data)
            for key in ('source', 'pdf', 'error'):
                self.assertNotIn(key, paper)
            self.assertEqual(data['jobs'], [])
            self.assertEqual(data['agent'], {'configured': False, 'enabled': False})
            self.assertEqual(paper['notes'], '')
            self.assertFalse(paper['favorite'])
            self.assertNotIn(b'private note marker', body)
            self.assertNotIn(str(self.root).encode(), body)
        finally:
            self.library.edit(self.id, {'notes': before['notes'], 'favorite': before['favorite']})

    def test_graph_uses_catalog_access_and_serves_assets(self):
        self.assertEqual(self.request('/api/graph', auth=False)[0], 401)
        status, body, _ = self.request('/api/graph')
        self.assertEqual(status, 200)
        self.assertEqual(set(json.loads(body)), {'schema_version', 'nodes', 'edges'})
        self.assertNotIn(str(self.root).encode(), body)
        for name, mime in [('graph.js', 'text/javascript'), ('graph.css', 'text/css')]:
            status, _, headers = self.request('/' + name)
            self.assertEqual(status, 200)
            self.assertIn(mime, headers['Content-Type'])

    def test_public_read_does_not_authorize_management(self):
        for path, method, body in (
                ('/api/state', 'GET', None), ('/api/settings', 'GET', None),
                ('/api/export', 'GET', None), ('/api/skill', 'GET', None),
                ('/api/scan', 'POST', {}), ('/api/run', 'POST', {}),
                ('/api/papers/' + self.id + '/reading', 'POST', {}),
                ('/api/papers/' + self.id, 'PATCH', {'notes': 'not permitted'}),
                ('/api/catalog', 'PATCH', {}),
                ('/api/papers/' + self.id + '/pdf', 'POST', {})):
            with self.subTest(path=path, method=method):
                self.assertEqual(self.request(path, method, body, auth=False)[0], 401)

    def test_missing_and_unsafe_pdf_return_not_found(self):
        self.assertEqual(self.request('/api/papers/' + '0' * 64 + '/pdf')[0], 404)
        file = self.library.pdf_path(self.id)
        original = file.read_bytes()
        file.unlink()
        try:
            code, body, _ = self.request('/api/papers/' + self.id + '/pdf')
            self.assertEqual(code, 404)
            self.assertNotIn(str(self.root).encode(), body)
            catalog = json.loads(self.request('/api/catalog')[1])
            self.assertFalse(catalog['papers'][0]['fulltext_available'])
            file.symlink_to('/etc/passwd')
            self.assertEqual(self.request('/api/papers/' + self.id + '/pdf')[0], 404)
        finally:
            if file.is_symlink():
                file.unlink()
            file.write_bytes(original)

    def test_public_metadata_uses_nested_whitelists(self):
        value = {'id': self.id, 'source': '/private/source.pdf', 'pdf': '/private/archive.pdf',
                 'error': '/private/failed', 'notes': 'private note', 'favorite': True,
                 'card': {'title': 'A paper', 'private_path': '/private/card',
                          'reading': {'method': 'A method', 'source_path': '/private/text',
                                      'resources': [{'label': 'Code', 'url': 'https://example.org',
                                                     'kind': 'code', 'secret': 'private resource'}],
                                      'result_table': {'columns': ['A', 'B'], 'rows': [['1', '2']],
                                                       'path': '/private/table'}},
                          'evidence': [{'field': 'summary', 'page': 1, 'quote': 'Quoted text',
                                        'file': '/private/evidence'}]},
                 'bibliography': {'title': 'Imported paper', 'source_path': '/private/index',
                                  'provenance': [{'label': 'Index', 'record_id': 'A01',
                                                  'sha256': 'a' * 64, 'path': '/private/provenance'}]}}
        public = catalog_paper(value)
        self.assertNotIn('private', json.dumps(public))
        self.assertEqual(public['card']['reading']['method'], 'A method')
        self.assertEqual(public['card']['evidence'][0]['page'], 1)
        self.assertEqual(public['bibliography']['provenance'][0]['record_id'], 'A01')

    def test_public_catalog_includes_saved_insight(self):
        from paperlib.insights import source_text
        source = source_text(self.library, self.id).strip()
        value = {'schema_version': 1, 'abstract': {'status': 'available', 'text': source,
                  'language': 'en', 'pages': [1]}, 'keywords': ['数据选择', '模型质量', '实验'],
                 'summary': {'overview': '这项研究通过数据选择改善模型质量并开展实验。'},
                 'evidence': [{'field': 'summary.overview', 'page': 1, 'quote': source}],
                 'coverage': 'abstract', 'generated_by': 'codex'}
        try:
            self.library.commit_insight(self.id, value)
            code, body, _ = self.request('/api/catalog')
            self.assertEqual(code, 200)
            insight = json.loads(body)['papers'][0]['insight']
            self.assertEqual(insight['abstract']['text'], source)
            self.assertEqual(insight['summary']['overview'], value['summary']['overview'])
            self.assertEqual(insight['source_digest'], self.id)
        finally:
            with self.library.db() as db:
                db.execute('DELETE FROM paper_insights WHERE paper_id=?', (self.id,))

    def test_csrf_and_host_checks(self):
        self.assertEqual(self.request('/api/scan','POST',{}, {'Origin':'https://untrusted.example'})[0],403)
        self.assertEqual(self.request('/api/scan','POST',{}, {'X-Paper-Library':''})[0],403)
        self.assertEqual(self.request('/api/state',headers={'Host':'untrusted.example'})[0],403)

    def test_pdf_bytes_and_ranges(self):
        path='/api/papers/'+self.id+'/pdf'
        code,body,h=self.request(path); self.assertEqual(body,pdf_bytes())
        code,body,h=self.request(path,headers={'Range':'bytes=0-4'}); self.assertEqual(code,206); self.assertEqual(body,b'%PDF-')
        code,body,h=self.request(path,headers={'Range':'bytes=-5'}); self.assertEqual(code,206); self.assertEqual(body,pdf_bytes()[-5:])
        self.assertEqual(self.request(path,headers={'Range':'bytes=999999-'})[0],416)
        self.assertEqual(self.request(path,headers={'Range':'bytes=-0'})[0],416)

    def test_notes_round_trip(self):
        path='/api/papers/'+self.id
        code,body,h=self.request(path,'PATCH',{'notes':'持久化笔记','favorite':True})
        self.assertEqual(code,200); self.assertEqual(json.loads(body)['notes'],'持久化笔记')
        self.assertTrue(Library(self.root).record(self.id)['favorite'])
        self.assertEqual(self.request(path,'PATCH',{'source':'/etc/passwd'})[0],400)

    def test_unconfigured_agent_and_export(self):
        self.assertEqual(self.request('/api/run','POST',{})[0],400)
        self.assertEqual(self.request('/api/export')[0],200)
        self.assertEqual(self.request('/api/skill')[0],200)

    def test_path_escape_and_directory_not_exposed(self):
        for path in ('/../manage.py','/.paperlib/catalog.sqlite3','/api/papers/../../etc/passwd/pdf'):
            self.assertEqual(self.request(path)[0],404)

    def test_provider_settings_auth_persistence_and_redaction(self):
        self.assertEqual(self.request('/api/settings', auth=False)[0], 401)
        self.assertEqual(self.request('/api/settings', 'PATCH', {}, auth=False)[0], 401)
        self.assertEqual(self.request('/api/settings', 'PATCH', {}, {'Origin': 'https://untrusted.example'})[0], 403)
        self.assertEqual(self.request('/api/settings', 'PATCH', {'command': ['arbitrary-command']})[0], 400)
        try:
            code, body, _ = self.request('/api/settings', 'PATCH', {
                'mode': 'api', 'api_base_url': 'https://api.example.com/v1',
                'api_model': 'example-model', 'api_key': 'private-http-test-key'})
            self.assertEqual(code, 200)
            self.assertTrue(json.loads(body)['api_key_set'])
            self.assertNotIn(b'private-http-test-key', body)
            self.assertTrue(json.loads(self.request('/api/state')[1])['agent']['configured'])
            self.assertNotIn(b'private-http-test-key', self.request('/api/state')[1])
            self.assertEqual(json.loads(self.request('/api/settings')[1])['api_model'], 'example-model')
            self.assertEqual(self.request('/.paperlib/providers.json')[0], 404)
        finally:
            self.request('/api/settings', 'PATCH', {'mode': 'auto', 'api_base_url': '',
                                                   'api_model': '', 'clear_api_key': True})

if __name__ == '__main__': unittest.main()
