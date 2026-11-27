"""Verify a gateway source file offline against a synthetic Feishu provider."""
import concurrent.futures
from dataclasses import replace
import http.client
import importlib.util
import json
import os
import sys
import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import patch
from urllib.parse import parse_qs, urlsplit

SOURCE = Path(os.environ.get('RMP_TEST_GATEWAY', 'auth_service.py')).resolve()
spec = importlib.util.spec_from_file_location('test_subject_gateway', SOURCE)
auth = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = auth
spec.loader.exec_module(auth)


class Provider:
    def __init__(self):
        self.tokens = {"access_token": "example-access0", "expires_in": 600,
                       "refresh_token": "example-refresh0", "refresh_token_expires_in": 86400}
        self.rotations = 0
        self.user_calls = 0
        self.organization = 'example-tenant'
        self.identity = 'example-user'
        self.outage = False
        self.revoked = False
        self.invalid_first = False

    def exchange(self, code, verifier):
        return self.tokens.copy()

    def user(self, token):
        self.user_calls += 1
        if self.outage:
            raise auth.AuthError(503, 'mock temporary outage')
        if self.invalid_first and token.endswith('0'):
            raise auth.AuthError(401, 'mock access invalid')
        return {'open_id':self.identity, 'tenant_key':self.organization, 'name':'示例成员'}

    def refresh(self, token):
        if self.revoked or token != 'example-refresh'+str(self.rotations):
            raise auth.AuthError(401, 'mock grant revoked')
        self.rotations += 1
        return {**self.tokens, "access_token":"example-access"+str(self.rotations),
                "refresh_token":"example-refresh"+str(self.rotations)}


class GatewayTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.cfg = auth.Config("example-app", "demo", "example-tenant",
                               str(Path(self.tmp.name)/'gateway.sqlite'), origin='https://example.org',offline_access=True)
        self.provider = Provider()
        self.now = 1_800_000_000
        clock = patch.object(auth.time, 'time', side_effect=lambda:self.now)
        clock.start()
        self.addCleanup(clock.stop)
        self.engine = auth.Engine(self.cfg, self.provider)

    def login(self, persistent=True):
        url, browser = self.engine.begin('/progress/#team', persistent)
        query = parse_qs(urlsplit(url).query)
        self.assertEqual(query.get('scope'), ['offline_access'] if persistent and self.cfg.offline_access else None)
        return self.engine.finish(query['state'][0], browser, 'example-code')

    def status(self, expected, f, *args):
        with self.assertRaises(auth.AuthError) as result:
            f(*args)
        self.assertEqual(result.exception.status, expected)

    def test_short_token_outlived_with_rotation_and_restart(self):
        sid, age, _ = self.login()
        self.assertEqual(age, 30*86400)
        self.now += 601
        self.engine = auth.Engine(self.cfg, self.provider)
        with concurrent.futures.ThreadPoolExecutor(max_workers=6) as pool:
            members = list(pool.map(self.engine.session, [sid]*6))
        self.assertEqual(self.provider.rotations, 1)
        self.assertEqual(self.provider.user_calls, 2)
        self.assertEqual(members[0], {'name':'示例成员','subject':auth.digest('example-user'),'session_ref':auth.digest(sid)})
        self.now += 601
        self.assertEqual(self.engine.session(sid), members[0])
        self.assertEqual(self.provider.rotations, 2)
        self.now += 31*86400
        self.status(401,self.engine.session,sid)

    def test_short_login_no_unintended_renewal_and_old_rows(self):
        sid,age,_=self.login(False)
        self.assertEqual(age,600)
        with self.engine.db() as db:
            self.assertEqual(db.execute('SELECT COUNT(*) FROM session_renewals').fetchone()[0],0)
            db.execute('INSERT INTO sessions VALUES (?,?,?,?,?,?)',
                       (auth.digest('old'), 'old-access','old-user','示例旧成员',self.now+88,self.now))
        self.assertEqual(self.engine.session('old')['name'],'示例旧成员')
        self.now+=601
        self.status(401,self.engine.session,sid)
        self.status(401,self.engine.session,'old')
        del self.provider.tokens['refresh_token']
        sid, age, _ = self.login()
        self.assertEqual(age, 30*86400)
        self.now+=601
        with self.assertRaises(auth.Reverify):
            self.engine.session(sid)

    def test_rotation_persisted_before_interrupted_user_check(self):
        sid,_,_=self.login()
        self.now+=601
        self.provider.outage=True
        self.status(503,self.engine.session,sid)
        with self.engine.db() as db:
            self.assertEqual(db.execute('SELECT refresh_token FROM session_renewals').fetchone()[0],'example-refresh1')
            self.assertEqual(db.execute('SELECT verified FROM sessions').fetchone()[0],0)
        self.engine=auth.Engine(self.cfg,self.provider)
        self.provider.outage=False
        self.assertEqual(self.engine.session(sid)['name'],'示例成员')
        self.assertEqual(self.provider.rotations,1)
        self.provider.organization='other-org'
        self.now+=301
        self.status(403,self.engine.session,sid)
        self.status(401,self.engine.session,sid)
        self.assertEqual(auth.provider_error(400,99991400).status,503)
        self.assertEqual(auth.provider_error(429,None).status,503)
        self.assertEqual(auth.provider_error(400,987654).status,503)

    def test_revoked_early_access_expiry_cap_and_logout(self):
        sid,_,_=self.login()
        self.provider.invalid_first=True
        self.now+=301
        self.engine.session(sid)
        self.assertEqual(self.provider.rotations,1)
        self.provider.revoked=True
        self.now+=601
        self.status(401,self.engine.session,sid)
        self.assertTrue(self.engine.held(sid))
        self.engine.logout(sid)
        self.provider.invalid_first=False
        sid,_,_=self.login()
        self.engine.logout(sid)
        self.status(401,self.engine.session,sid)
        with self.engine.db() as db:
            self.assertEqual(db.execute('SELECT COUNT(*) FROM session_renewals').fetchone()[0],0)

    def test_internal_http_grants_bind_before_and_after_logout(self):
        sid,_,_=self.login()
        server=auth.ThreadingHTTPServer(('127.0.0.1',0),auth.Handler)
        server.engine=self.engine
        thread=threading.Thread(target=server.serve_forever)
        thread.start()
        self.addCleanup(server.server_close)
        self.addCleanup(thread.join)
        self.addCleanup(server.shutdown)
        def request(method,path,extra=None,body=None):
            connection=http.client.HTTPConnection('127.0.0.1',server.server_port,timeout=5)
            try:
                connection.request(method,path,body=body,headers={'Host':'example.org',**(extra or {})})
                resp=connection.getresponse()
                return resp.status, dict(resp.getheaders()), resp.read()
            finally:
                connection.close()
        cookie={'Cookie':auth.SESSION_COOKIE+'='+sid}
        fetch=lambda:request('GET','/internal/mcp/member',cookie)
        self.assertEqual(request('GET','/internal/mcp/member')[0],401)
        code,headers,_=fetch()
        self.assertEqual(code,204)
        binding={'subject':headers['X-RMP-Subject'], 'session_ref':headers['X-RMP-Session-Ref']}
        verify=lambda data: request('POST','/internal/mcp/session',{'Content-Type':'application/json'},json.dumps(data))[0]
        self.assertEqual(verify(binding),204)
        self.assertEqual(verify({**binding,'subject':'c'*64}),401)
        self.assertEqual(verify({**binding,'session_ref':'not-a-reference'}),400)
        self.now+=301
        self.provider.outage=True
        self.assertEqual(verify(binding),503)
        self.provider.outage=False
        self.assertEqual(request('POST','/auth/logout',cookie)[0],403)
        self.assertEqual(verify(binding),204)
        code,headers,_=request('POST','/auth/logout',{**cookie,'Origin':self.cfg.origin})
        self.assertEqual(code,302)
        self.assertIn('Max-Age=0',headers['Set-Cookie'])
        self.assertEqual(verify(binding),401)
        self.assertEqual(fetch()[0],401)

    def test_normal_scope_fixed_deadline_and_same_member_sso(self):
        self.cfg = replace(self.cfg,offline_access=False)
        self.engine = auth.Engine(self.cfg,self.provider)
        self.provider.tokens.pop('refresh_token')
        sid, age, _=self.login()
        self.assertEqual(age,30*86400)
        ref, sub = auth.digest(sid), auth.digest(self.provider.identity)
        self.now+=604
        with self.assertRaises(auth.Reverify):
            self.engine.member_session(ref,sub)
        self.assertTrue(self.engine.held(sid))
        self.engine=auth.Engine(self.cfg,self.provider)
        url,browser=self.engine.begin('/progress/?target=report',prior_sid=sid)
        query=parse_qs(urlsplit(url).query)
        self.assertNotIn('scope',query)
        self.status(400,self.engine.finish,query['state'][0],browser,'example','wrong-cookie')
        same, remaining, path=self.engine.finish(query['state'][0],browser,'example',sid)
        self.assertEqual((same, remaining, path),(sid,age-604,'/progress/?target=report'))
        self.assertEqual(self.engine.member_session(ref,sub)['subject'],sub)
        self.now+=610
        with self.assertRaises(auth.Reverify):
            self.engine.session(sid)
        url,browser=self.engine.begin('/',prior_sid=sid)
        self.provider.identity='other-user'
        new,age,_=self.engine.finish(parse_qs(urlsplit(url).query)['state'][0],browser,'example',sid)
        self.assertNotEqual(new,sid)
        self.status(401,self.engine.member_session,ref,sub)
        self.assertFalse(self.engine.held(sid))
        url,browser=self.engine.begin('/',prior_sid=new)
        self.engine.logout(new)
        self.status(401,self.engine.finish,parse_qs(urlsplit(url).query)['state'][0],browser,'example',new)

    def test_legacy_cookie_migration_and_reverify_http_contract(self):
        self.cfg = replace(self.cfg,offline_access=False)
        self.engine=auth.Engine(self.cfg,self.provider)
        sid,sub='legacy-cookie',auth.digest(self.provider.identity)
        with self.engine.db() as db:
            db.execute("INSERT INTO sessions VALUES (?,?,?,?,?,?)", (auth.digest(sid),'legacy',self.provider.identity,'old',self.now+200,self.now))
        server=auth.ThreadingHTTPServer(('127.0.0.1',0),auth.Handler)
        server.engine=self.engine
        thread=threading.Thread(target=server.serve_forever)
        thread.start()
        self.addCleanup(server.server_close)
        self.addCleanup(thread.join)
        self.addCleanup(server.shutdown)
        def call(method,path,headers=None,body=None):
            connection=http.client.HTTPConnection('127.0.0.1',server.server_port,timeout=5)
            try:
                connection.request(method,path,body=body,headers={'Host':'example.org','Cookie':auth.SESSION_COOKIE+'='+sid,**(headers or {})})
                response=connection.getresponse()
                return response.status,dict(response.getheaders()),response.read()
            finally:
                connection.close()
        code,headers,_=call('GET','/auth/check')
        self.assertEqual(code,204)
        self.assertIn('Max-Age=2592000',headers['Set-Cookie'])
        self.assertNotIn('Set-Cookie',call('GET','/auth/check')[1])
        self.now+=601
        code,headers,_=call('GET','/auth/check')
        self.assertEqual((code,headers.get('X-RMP-Session-State')),(401,'reverify'))
        code,headers,_=call('GET','/auth/required',{'X-Original-URI':'/progress/team?day=1'})
        self.assertEqual(code,302)
        self.assertEqual(parse_qs(urlsplit(headers['Location']).query)['return_to'],['/progress/team?day=1'])
        self.assertTrue(urlsplit(headers['Location']).path.endswith('/auth/start'))
        code,_,body=call('GET','/auth/required',{'X-Original-URI':'/progress/api/public'})
        self.assertEqual((code,json.loads(body)['session_state']),(401,'reverify'))
        code,headers,_=call('POST','/internal/mcp/session',{'Content-Type':'application/json'},
            json.dumps({'subject':sub,'session_ref':auth.digest(sid)}))
        self.assertEqual((code,headers.get('X-RMP-Session-State')),(401,'reverify'))
        self.engine.logout(sid)
        self.assertFalse(self.engine.held(sid))
        self.assertNotIn('X-RMP-Session-State',call('GET','/auth/check')[1])

if __name__=='__main__':
    unittest.main()

