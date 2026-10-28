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

    def test_auth_required_for_pdfs_and_metadata(self):
        self.assertEqual(self.request('/api/state',auth=False)[0],401)
        self.assertEqual(self.request('/api/papers/'+self.id+'/pdf',auth=False)[0],401)

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
