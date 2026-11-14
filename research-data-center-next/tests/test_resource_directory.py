import http.client
import json
from pathlib import Path
import sys
import tempfile
import threading
import unittest
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from catalog import import_catalog
from resource_directory import query_directory, load_directory
from server import create_server
ROOT = Path(__file__).resolve().parents[1]

class ResourceDirectoryTests(unittest.TestCase):
    def test_snapshot_distinguishes_resources_files_and_access(self):
        data = query_directory(ROOT, 'status=shared')
        self.assertEqual(data['total'], 7)
        self.assertEqual(sum(i['linked_file_count'] for i in data['items']), 113)
        coswara = next(i for i in data['items'] if i['name'] == 'Coswara')
        self.assertEqual(coswara['linked_file_count'], 43)
        self.assertEqual(query_directory(ROOT, 'kind=model')['total'], 1)
        self.assertEqual(query_directory(ROOT, 'kind=model&status=shared')['total'], 0)
        for item in load_directory(ROOT)['items']:
            if item['status'] != 'shared':
                self.assertFalse(item['files'])
                self.assertIsNone(item['shared_directory'])

    def test_unsupported_and_duplicate_filters(self):
        for q in ('path=/etc/passwd', 'status=shared&status=restricted'):
            with self.assertRaises(ValueError):query_directory(ROOT,q)

    def test_internal_http_authentication_and_readonly(self):
        with tempfile.TemporaryDirectory() as temp:
            db=Path(temp)/'catalog.sqlite3'
            import_catalog({'schema_version':'1.0','assets':[{'id':'a','name':'A','kind':'dataset','status':'documented'}]},db)
            token='resource-directory-test-token-1234567890'
            server=create_server(db,port=0,root=ROOT,token=token)
            thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
            def request(path,auth=True,method='GET'):
                conn=http.client.HTTPConnection('127.0.0.1',server.server_port,timeout=3)
                conn.request(method,path,headers={'Authorization':'Bearer '+token} if auth else {})
                response=conn.getresponse();result=response.status,response.read();conn.close();return result
            try:
                endpoint='/api/classified-resources'
                self.assertEqual(request(endpoint,False)[0],401)
                status,body=request(endpoint+'?status=shared')
                self.assertEqual(status,200)
                data=json.loads(body);self.assertEqual(data['total'],7)
                identity=data['items'][0]['id']
                path=endpoint+'/'+identity+'/README.md'
                self.assertEqual(request(path,False)[0],401)
                self.assertIn(b'Resource card',request(path)[1])
                self.assertEqual(request(endpoint+'/missing')[0],404)
                self.assertEqual(request(endpoint+'?path=/etc/passwd')[0],400)
                self.assertEqual(request(endpoint,method='POST')[0],405)
                self.assertEqual(request(endpoint,method='HEAD'),(200,b''))
                self.assertEqual(request('/var/catalog-monitor/changes.jsonl')[0],404)
                self.assertEqual(request('/api/catalog-monitor/changes')[0],404)
            finally:
                server.shutdown();server.server_close();thread.join(timeout=3)

if __name__=='__main__':unittest.main()
