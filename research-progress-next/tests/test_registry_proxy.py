import io
import importlib.util
from email.message import Message
from pathlib import Path
import pytest

spec=importlib.util.spec_from_file_location('progress_proxy',Path(__file__).parents[1]/'deploy/registry/progress_proxy.py')
proxy=importlib.util.module_from_spec(spec);spec.loader.exec_module(proxy)

class Handler:
    command='GET';path='/progress/api/public';valid=True;origin=True;authenticated=True
    def __init__(self):self.headers=Message();self.rfile=io.BytesIO(b'{}');self.connection=self;self.result=None
    def _valid_host(self):return self.valid
    def _same_origin(self):return self.origin
    def _authenticated(self):return self.authenticated
    def _json(self,data,status):self.result=(status,data)
    def _send(self,status,data,content_type,**kwargs):self.result=(status,data)
    def settimeout(self,value):pass

@pytest.mark.parametrize('field,status',[('valid',403),('origin',403),('authenticated',401)])
def test_proxy_respects_registry_boundary(field,status,monkeypatch):
    def forbidden(*a,**kw):raise AssertionError('must not reach backend')
    monkeypatch.setattr(proxy,'HTTPConnection',forbidden)
    h=Handler();setattr(h,field,False);proxy.proxy_progress(h);assert h.result[0]==status

@pytest.mark.parametrize('endpoint',['/api/uploads','/api/daily/uploads','/api/members'])
def test_proxy_routes_upload_without_forwarding_credentials(monkeypatch,endpoint):
    seen={}
    class Conn:
        def __init__(self,host,port,timeout):assert (host,port)==('127.0.0.1',8766)
        def request(self,method,path,body,headers):seen.update(method=method,path=path,body=body,headers=headers)
        def getresponse(self):return self
        status=201
        def read(self,n):return b'{"ok":true}'
        def getheader(self,*args):return 'application/json'
        def close(self):pass
    monkeypatch.setattr(proxy,'HTTPConnection',Conn)
    h=Handler();h.command='POST';h.path='/progress'+endpoint
    for key,value in {'Content-Length':'2','Content-Type':'application/json','X-Requested-With':'ResearchWeekly','Authorization':'Bearer TEST_ONLY','Cookie':'test=private'}.items():h.headers[key]=value
    proxy.proxy_progress(h)
    assert h.result[0]==201 and seen['path']==endpoint and seen['body']==b'{}'
    assert 'Authorization' not in seen['headers'] and 'Cookie' not in seen['headers']
    assert seen['headers']['X-Requested-With']=='ResearchWeekly'

def test_proxy_rejects_unknown_write_and_large_payload():
    h=Handler();h.command='POST';h.path='/progress/api/team';proxy.proxy_progress(h);assert h.result[0]==405
    h.path='/progress/api/uploads';h.headers['Content-Length']='100001';proxy.proxy_progress(h);assert h.result[0]==413
