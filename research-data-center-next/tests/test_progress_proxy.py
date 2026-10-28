"""Daily/weekly/name intake forwarding keeps the existing portal boundary."""
from email.message import Message
import io
import unittest
from unittest import mock
import progress_proxy


class Handler:
    command='POST'
    valid=True
    origin=True
    authenticated=True

    def __init__(self, path):
        self.path='/progress'+path
        self.headers=Message()
        for key,value in {'Content-Length':'2','Content-Type':'application/json',
                          'X-Requested-With':'ResearchWeekly','Authorization':'Bearer fixture',
                          'Cookie':'fixture=private'}.items():
            self.headers[key]=value
        self.rfile=io.BytesIO(b'{}');self.connection=self;self.result=None
    def _valid_host(self):return self.valid
    def _same_origin(self):return self.origin
    def _authenticated(self):return self.authenticated
    def _json(self,data,status):self.result=(status,data)
    def _send(self,status,data,content_type,**kwargs):self.result=(status,data)
    def settimeout(self,value):pass


class ProgressProxyTests(unittest.TestCase):
    def test_only_explicit_intake_endpoints_forward(self):
        for endpoint in ['/api/uploads','/api/daily/uploads','/api/members']:
            with self.subTest(endpoint=endpoint):
                conn=mock.Mock();response=conn.getresponse.return_value
                response.status=201;response.read.return_value=b'{"ok":true}'
                response.getheader.return_value='application/json'
                handler=Handler(endpoint)
                with mock.patch.object(progress_proxy,'HTTPConnection',return_value=conn):
                    progress_proxy.proxy_progress(handler)
                self.assertEqual(handler.result[0],201)
                args,kwargs=conn.request.call_args
                self.assertEqual(args,('POST',endpoint))
                self.assertEqual(kwargs['body'],b'{}')
                self.assertNotIn('Authorization',kwargs['headers'])
                self.assertNotIn('Cookie',kwargs['headers'])
                self.assertEqual(kwargs['headers']['X-Requested-With'],'ResearchWeekly')
                conn.close.assert_called_once()

    def test_denied_origins_auth_and_extra_writes_never_connect(self):
        with mock.patch.object(progress_proxy,'HTTPConnection') as conn:
            for field in ['valid','origin','authenticated']:
                handler=Handler('/api/members');setattr(handler,field,False)
                progress_proxy.proxy_progress(handler)
                self.assertIn(handler.result[0],(401,403))
            for endpoint in ['/api/daily','/api/members/alice','/api/daily/uploads/','/api/summarize']:
                handler=Handler(endpoint);progress_proxy.proxy_progress(handler)
                self.assertEqual(handler.result[0],405)
            handler=Handler('/api/daily/uploads');handler.headers.replace_header('Content-Length','100001')
            progress_proxy.proxy_progress(handler);self.assertEqual(handler.result[0],413)
            conn.assert_not_called()


if __name__=='__main__':
    unittest.main()
