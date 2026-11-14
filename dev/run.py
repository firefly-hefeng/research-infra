"""Loopback-only development stack, with isolated data and source files served live."""
import argparse
import http.client
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
from pathlib import Path
import runpy
import socket
import subprocess
import sys
import time
from urllib.parse import urlsplit

ROOT = Path(__file__).resolve().parents[1]
STATE = ROOT / '.local-dev'
PORTAL = ROOT / 'research-data-center-next'
PROGRESS = ROOT / 'research-progress-next'
PAPERS = ROOT / 'paper-library-next'
ORIGIN = 'http://127.0.0.1:18081'
PORTS = (18081, 8765, 8766, 4186)


def bootstrap(module):
    if os.name == 'nt':
        import windows_locks
        sys.modules['fcntl'] = windows_locks
    if module == 'portal':
        sys.path.insert(0, str(PORTAL))
        import catalog
        db = STATE / 'catalog.sqlite3'
        if not db.exists():
            sys.argv = ['catalog', 'import', '--input', str(PORTAL / 'data/catalog.json'), '--db', str(db)]
            catalog.main()
        sys.argv = ['server', '--db', str(db), '--root', str(PORTAL), '--state-dir', str(STATE / 'ingestion'), '--port', '8765']
        runpy.run_path(str(PORTAL / 'server.py'), run_name='__main__')
    elif module == 'progress':
        sys.path.insert(0, str(PROGRESS))
        from research_weekly.core import load_config, init_dirs
        from research_weekly.app import create_app
        from waitress import serve
        config = STATE / 'progress.json'
        if not config.exists():
            config.write_text(json.dumps({
                'team_name':'本地开发演示团队', 'demo':True, 'timezone':'Asia/Shanghai', 'portal_url':'/',
                'members':[{'id':'demo','name':'本地测试成员'}],
                'paths':{key:str(STATE / 'progress' / key) for key in ('members','team','knowledge','state')},
                'security':{'allowed_origins':['http://127.0.0.1:8766'], 'https':False},
                'summary':{'mode':'extractive','max_report_bytes':65536,'max_total_bytes':1000000,'timeout_seconds':15}
            }, ensure_ascii=False, indent=2), encoding='utf-8')
        cfg = load_config(config)
        init_dirs(cfg, provision_members=True)
        welcome = cfg['roots']['knowledge'] / '01-local-development.md'
        if not welcome.exists():
            welcome.write_text('# 本地开发环境\n\n这里的成员和报告仅保存在当前电脑，不会写入生产服务器。\n', encoding='utf-8')
        serve(create_app(config), host='127.0.0.1', port=8766, threads=8)
    else:
        sys.path.insert(0, str(PAPERS))
        os.environ['PAPER_ROOT'] = str(STATE / 'papers')
        os.environ['PAPER_SCHEDULE_ENABLED'] = '0'
        os.environ['PAPER_PASSWORD'] = ''
        os.environ['PAPER_PUBLIC_ORIGIN'] = 'http://127.0.0.1:4186'
        sys.argv = ['manage', '--root', str(STATE / 'papers'), 'serve', '--host', '127.0.0.1', '--port', '4186']
        runpy.run_path(str(PAPERS / 'manage.py'), run_name='__main__')


class Gateway(BaseHTTPRequestHandler):
    def dispatch(self):
        if self.headers.get('Host') not in ('127.0.0.1:18081', 'localhost:18081'):
            return self.send_error(403)
        if self.headers.get('Origin') not in (None, ORIGIN, 'http://localhost:18081'):
            return self.send_error(403)
        path = self.path
        if urlsplit(path).path in ('/papers','/progress'):
            self.send_response(302); self.send_header('Location',path+'/'); self.end_headers(); return
        port = 8765
        if path.startswith('/papers/'):
            port, path = 4186, path[len('/papers'):]
        elif path.startswith('/progress/'):
            port, path = 8766, path[len('/progress'):]
        if self.headers.get('Transfer-Encoding'):
            return self.send_error(400)
        try:
            size = int(self.headers.get('Content-Length','0'))
        except ValueError:
            return self.send_error(400)
        if not 0 <= size <= 2_000_000:
            return self.send_error(413)
        body = self.rfile.read(size) if size else None
        excluded = {'host','origin','connection','content-length','accept-encoding','transfer-encoding'}
        headers = {k:v for k,v in self.headers.items() if k.lower() not in excluded}
        headers.update(Host=f'127.0.0.1:{port}', Origin=f'http://127.0.0.1:{port}')
        conn = http.client.HTTPConnection('127.0.0.1', port, timeout=30)
        try:
            conn.request(self.command, path, body=body, headers=headers)
            response = conn.getresponse()
            self.send_response(response.status)
            for key,value in response.getheaders():
                if key.lower() not in ('connection','transfer-encoding','server','date','cache-control'):
                    self.send_header(key,value)
            self.send_header('Cache-Control','no-store')
            self.send_header('X-Research-Environment','local-development')
            self.end_headers()
            if self.command != 'HEAD':
                while chunk := response.read(65536):
                    self.wfile.write(chunk)
        except (OSError, http.client.HTTPException):
            self.send_error(502, 'Local module unavailable; check .local-dev logs')
        finally:
            conn.close()

    do_GET = do_HEAD = do_POST = do_PATCH = do_DELETE = dispatch


def start():
    STATE.mkdir(exist_ok=True)
    for port in PORTS:
        with socket.socket() as probe:
            try:
                probe.bind(('127.0.0.1',port))
            except OSError:
                raise SystemExit(f'Port {port} is occupied; no existing process has been stopped.')
    children, logs = [], []
    try:
        for module in ('portal','progress','papers'):
            log = (STATE / f'{module}.log').open('ab')
            logs.append(log)
            env = dict(os.environ, PYTHONUTF8='1', PYTHONDONTWRITEBYTECODE='1')
            child = subprocess.Popen([sys.executable,'-u',str(Path(__file__).resolve()),'--module',module], cwd=ROOT,
                                     env=env, stdin=subprocess.DEVNULL, stdout=log, stderr=log)
            children.append(child)
        (STATE / 'processes.json').write_text(json.dumps({'gateway':os.getpid(),'modules':[p.pid for p in children]}))
        for port, child in zip((8765,8766,4186),children):
            for _ in range(100):
                if child.poll() is not None:
                    raise RuntimeError(f'Module on {port} failed; see .local-dev logs')
                try:
                    with socket.create_connection(('127.0.0.1',port),timeout=.2):
                        break
                except OSError:
                    time.sleep(.1)
            else:
                raise RuntimeError(f'Module startup timed out: {port}')
        print(f'Local development ready: {ORIGIN}', flush=True)
        ThreadingHTTPServer(('127.0.0.1',18081),Gateway).serve_forever()
    finally:
        for child in children:
            if child.poll() is None:
                child.terminate(); child.wait(timeout=10)
        for log in logs:
            log.close()


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--module', choices=['portal','progress','papers'])
    args = parser.parse_args()
    bootstrap(args.module) if args.module else start()
