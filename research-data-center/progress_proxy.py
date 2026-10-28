"""Bounded /progress/ reverse proxy for the existing loopback-only registry."""
from http.client import HTTPConnection, HTTPException
from urllib.parse import urlsplit


def proxy_progress(handler):
    if not handler._valid_host() or not handler._same_origin():
        return handler._json({'error':'请求来源不允许'},403)
    if not handler._authenticated():
        return handler._json({'error':'资源中心访问验证未通过'},401)
    parsed=urlsplit(handler.path)
    if parsed.path == '/progress':
        return handler._send(308,b'', 'text/plain', extra_headers={'Location':'/progress/'})
    path=parsed.path[len('/progress'):]
    if not path.startswith('/') or path.startswith('//') or '\\' in path:
        return handler._json({'error':'无效路径'},400)
    if handler.command not in ('GET','HEAD','POST') or (handler.command=='POST' and path!='/api/uploads'):
        return handler._json({'error':'该模块只接受周报上传，其余内容只读'},405)
    body=None
    headers={}
    if handler.command=='POST':
        if handler.headers.get('Transfer-Encoding') or len(handler.headers.get_all('Content-Length',[]))!=1:
            return handler._json({'error':'必须提供单个 Content-Length'},411)
        try: length=int(handler.headers['Content-Length'])
        except ValueError: return handler._json({'error':'无效长度'},400)
        if not 0 <= length <= 100_000:
            return handler._json({'error':'上传超过大小限制'},413)
        handler.connection.settimeout(15)
        try: body=handler.rfile.read(length)
        except OSError: return handler._json({'error':'上传超时'},408)
        if len(body)!=length:
            return handler._json({'error':'上传数据不完整'},400)
        headers={'Content-Type':handler.headers.get('Content-Type',''),
                 'X-Requested-With':handler.headers.get('X-Requested-With',''),
                 'Origin':'http://127.0.0.1:8766'}
    conn=HTTPConnection('127.0.0.1',8766,timeout=20)
    try:
        conn.request(handler.command, path+('?' + parsed.query if parsed.query else ''), body=body, headers=headers)
        response=conn.getresponse(); data=response.read(2_000_001)
        if len(data)>2_000_000:
            return handler._json({'error':'模块响应超过限制'},502)
        handler._send(response.status,data,response.getheader('Content-Type','application/json'))
    except (OSError,HTTPException):
        handler._json({'error':'科研进度模块暂时不可用，请联系维护人员'},503)
    finally:
        conn.close()
