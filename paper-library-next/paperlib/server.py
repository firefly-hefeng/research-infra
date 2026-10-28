import hmac
import json
import mimetypes
import os
from pathlib import Path
import re
import secrets
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlsplit
from .worker import Scheduler, configuration
from .providers import public_settings, save_settings

WEB = Path(__file__).resolve().parent.parent / 'web'


def serve(library, host='127.0.0.1', port=4186):
    password = os.environ.get('PAPER_PASSWORD', '')
    if host not in ('127.0.0.1', 'localhost', '::1') and len(password) < 12:
        raise ValueError('非本机监听需要至少 12 位的 PAPER_PASSWORD')
    public_origin = os.environ.get('PAPER_PUBLIC_ORIGIN', '').rstrip('/')
    allowed_hosts = {f'127.0.0.1:{port}', f'localhost:{port}', f'[::1]:{port}'}
    if public_origin:
        parsed = urlsplit(public_origin)
        if parsed.scheme not in ('http', 'https') or not parsed.netloc:
            raise ValueError('PAPER_PUBLIC_ORIGIN 必须为完整 http(s) 地址')
        allowed_hosts.add(parsed.netloc)
    sessions, attempts = {}, {}
    session_lock = threading.Lock()
    scheduler = Scheduler(library)
    scheduler_thread = threading.Thread(target=scheduler.loop, daemon=True)

    class Handler(BaseHTTPRequestHandler):
        server_version = 'PaperLibrary/1.0'

        def log_message(self, fmt, *args):
            print('%s %s' % (self.log_date_time_string(), fmt % args), flush=True)

        def send_headers(self, status, content_type, length=None, extra=None):
            self.send_response(status)
            self.send_header('Content-Type', content_type)
            self.send_header('X-Content-Type-Options', 'nosniff')
            self.send_header('Referrer-Policy', 'same-origin')
            self.send_header('Cache-Control', 'no-store')
            self.send_header('Content-Security-Policy', "default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data:; frame-src 'self'; object-src 'none'; frame-ancestors 'self'")
            if length is not None:
                self.send_header('Content-Length', str(length))
            for key, value in (extra or {}).items():
                self.send_header(key, value)
            self.end_headers()

        def json(self, data, status=200, extra=None):
            data = json.dumps(data, ensure_ascii=False).encode()
            self.send_headers(status, 'application/json; charset=utf-8', len(data), extra)
            self.wfile.write(data)

        def body(self):
            length = int(self.headers.get('Content-Length', '0'))
            if length > 128000 or length < 0:
                raise ValueError('请求过大')
            if self.headers.get('Content-Type', '').split(';')[0] != 'application/json':
                raise ValueError('仅接受 JSON 请求')
            value = json.loads(self.rfile.read(length) or b'{}')
            if not isinstance(value, dict):
                raise ValueError('请求必须是对象')
            return value

        def authenticated(self):
            if not password:
                return True
            cookie = dict(x.strip().split('=', 1) for x in self.headers.get('Cookie', '').split(';') if '=' in x)
            with session_lock:
                return sessions.get(cookie.get('paper_session'), 0) > time.time()

        def boundary(self, write=False):
            host_header = self.headers.get('Host', '')
            if host_header not in allowed_hosts:
                self.json({'error': 'Host 未获允许；远程部署需配置 PAPER_PUBLIC_ORIGIN'}, 403)
                return False
            origin = self.headers.get('Origin')
            if origin and origin not in {f'http://{host_header}', f'https://{host_header}', public_origin}:
                self.json({'error': '跨站请求被拒绝'}, 403)
                return False
            if write and self.headers.get('X-Paper-Library') != '1':
                self.json({'error': '缺少请求校验头'}, 403)
                return False
            return True

        def dispatch(self, method):
            if not self.boundary(method != 'GET'):
                return
            path = urlsplit(self.path).path
            if path == '/api/login' and method == 'POST':
                body = self.body()
                with session_lock:
                    ip = self.client_address[0]
                    recent = [t for t in attempts.get(ip, []) if time.time() - t < 60]
                    attempts[ip] = recent
                    if len(recent) >= 8:
                        self.json({'error': '尝试过于频繁，请一分钟后重试'}, 429)
                        return
                    if not isinstance(body.get('password'), str) or not hmac.compare_digest(body['password'].encode('utf-8'), password.encode('utf-8')):
                        recent.append(time.time())
                        self.json({'error': '密码不正确'}, 401)
                        return
                    token = secrets.token_urlsafe(32)
                    sessions[token] = time.time() + 86400
                    for key in list(sessions):
                        if sessions[key] < time.time():
                            sessions.pop(key)
                secure = '; Secure' if public_origin.startswith('https:') else ''
                self.json({'ok': True}, extra={'Set-Cookie': f'paper_session={token}; Path=/; HttpOnly; SameSite=Strict; Max-Age=86400{secure}'})
                return
            if path.startswith('/api/') and not self.authenticated():
                self.json({'error': '请输入论文库访问密码', 'login_required': True}, 401)
                return
            if path == '/api/state' and method == 'GET':
                c = configuration(library)
                papers = library.papers()
                for item in papers:
                    try:
                        library.pdf_path(item['id'])
                        item['available'] = True
                    except (ValueError, FileNotFoundError):
                        item['available'] = False
                    item['fulltext_available'] = item['available'] and not (
                        item.get('bibliography', {}).get('fulltext_policy') == 'restricted'
                        if item.get('bibliography') else False)
                self.json({'root': str(library.root), 'inbox': str(library.root / 'inbox'),
                           'papers': papers, 'jobs': library.jobs(),
                           'agent': public_settings(c),
                           'running': scheduler.active.locked(), 'scheduler_error': scheduler.last_error})
            elif path == '/api/settings' and method == 'GET':
                self.json(public_settings(configuration(library)))
            elif path == '/api/settings' and method == 'PATCH':
                save_settings(library, self.body())
                self.json(public_settings(configuration(library)))
            elif path == '/api/scan' and method == 'POST':
                self.body()
                self.json(library.scan())
            elif path == '/api/run' and method == 'POST':
                self.body()
                scheduler.trigger()
                self.json({'started': True}, 202)
            elif re.fullmatch(r'/api/papers/[a-f0-9]{64}/reading', path) and method == 'POST':
                self.body()
                paper_id = path.split('/')[-2]
                scheduler.trigger(paper_ids=[paper_id])
                self.json({'started': True, 'task': 'reading', 'paper_id': paper_id}, 202)
            elif re.fullmatch(r'/api/papers/[a-f0-9]{64}', path) and method == 'PATCH':
                self.json(library.edit(path.split('/')[-1], self.body()))
            elif re.fullmatch(r'/api/papers/[a-f0-9]{64}/pdf', path) and method == 'GET':
                paper = library.record(path.split('/')[-2])
                if (paper.get('bibliography') or {}).get('fulltext_policy') == 'restricted':
                    self.json({'error': '此批导入仅开放题录；原文需按团队授权访问。'}, 403)
                    return
                self.send_file(library.pdf_path(path.split('/')[-2]), 'application/pdf', ranges=True)
            elif path == '/api/export' and method == 'GET':
                self.json({'schema_version': 1, 'papers': library.papers()}, extra={'Content-Disposition': 'attachment; filename="paper-library.json"'})
            elif path == '/api/skill' and method == 'GET':
                self.send_file(WEB.parent / 'skills/paper-curator/SKILL.md', 'text/plain; charset=utf-8')
            elif method == 'GET' and path in ('/', '/app.js', '/style.css'):
                file = WEB / ('index.html' if path == '/' else path[1:])
                self.send_file(file, mimetypes.guess_type(str(file))[0] or 'text/plain')
            else:
                self.json({'error': '接口不存在'}, 404)

        def send_file(self, file, mime, ranges=False):
            size = file.stat().st_size
            start, end, status = 0, size - 1, 200
            extra = {'Accept-Ranges': 'bytes'} if ranges else {}
            requested = self.headers.get('Range') if ranges else None
            if requested:
                match = re.fullmatch(r'bytes=(\d*)-(\d*)', requested)
                if not match or not any(match.groups()):
                    self.send_headers(416, mime, 0, {'Content-Range': f'bytes */{size}'})
                    return
                a, b = match.groups()
                if a:
                    start, end = int(a), min(int(b), size - 1) if b else size - 1
                else:
                    start = max(0, size - int(b))
                if start >= size or end < start or (not a and int(b) == 0):
                    self.send_headers(416, mime, 0, {'Content-Range': f'bytes */{size}'})
                    return
                status = 206
                extra['Content-Range'] = f'bytes {start}-{end}/{size}'
            self.send_headers(status, mime, end - start + 1, extra)
            with file.open('rb') as f:
                f.seek(start)
                remaining = end - start + 1
                while remaining > 0:
                    chunk = f.read(min(65536, remaining))
                    if not chunk:
                        break
                    self.wfile.write(chunk)
                    remaining -= len(chunk)

        def handle_request(self, method):
            self.connection.settimeout(30)
            try:
                self.dispatch(method)
            except (BrokenPipeError, ConnectionResetError, TimeoutError):
                pass
            except (ValueError, KeyError, FileNotFoundError) as exc:
                self.json({'error': str(exc)}, 400)
            except BlockingIOError:
                self.json({'error': '已有整理进程正在运行'}, 409)
            except Exception as exc:
                print('Request failed:', type(exc).__name__, str(exc), flush=True)
                self.json({'error': '服务端处理失败，请检查日志'}, 500)

        def do_GET(self):
            self.handle_request('GET')

        def do_POST(self):
            self.handle_request('POST')

        def do_PATCH(self):
            self.handle_request('PATCH')

    # One server per library; CLI scans and commits use a separate writer lock.
    with library.lock('server', blocking=False):
        httpd = ThreadingHTTPServer((host, port), Handler)
        scheduler_thread.start()
        print(f'Paper Library: http://{host}:{port} | {library.root}', flush=True)
        try:
            httpd.serve_forever()
        except KeyboardInterrupt:
            pass
        finally:
            scheduler.stop.set()
            httpd.server_close()
