"""Read only the platform's published progress endpoints, preserving the current identity."""
import json
import threading
import uuid
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit
from urllib.request import HTTPRedirectHandler, ProxyHandler, Request, build_opener


ORIGIN = "https://rmp.wuwangwo.top"
PATHS = {"digest": "/progress/api/progress-digest", "review": "/progress/api/lab-review?format=json",
         "directions": "/progress/api/directions", "methods": "/progress/api/direction-methods"}
LIMIT = 16 * 1024 * 1024


class Unavailable(ValueError):
    pass


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def loopback(origin):
    u = urlsplit(origin)
    if u.scheme != "http" or u.hostname not in {"localhost", "127.0.0.1", "::1"} or not u.port or u.username is not None or u.password is not None or u.path not in {"", "/"} or u.query or u.fragment:
        raise ValueError("请使用已授权本机服务的 HTTP 回环地址和端口。")
    return origin.rstrip("/")


def limited_read(stream, limit):
    raw = stream.read(limit + 1)
    if len(raw) > limit:
        raise Unavailable("来源响应超过读取上限。")
    return raw


def failure(status):
    if status in (0, 301, 302, 303, 307, 308, 401, 403):
        return Unavailable("当前会话需要飞书登录或缺少团队读取权限。")
    if status == 404:
        return Unavailable("当前平台版本没有发布此接口，或尚未发布这份资料（HTTP 404）。")
    return Unavailable(f"进度服务暂未返回资料（HTTP {status}）。")


class ProgressSource:
    def __init__(self, *, snapshot=None, local=None, bridge_port=10086):
        self.snapshot = Path(snapshot) if snapshot else None
        self.local = loopback(local) if local else None
        if not 1 <= bridge_port <= 65535:
            raise ValueError("浏览器连接端口无效。")
        self.bridge = f"http://127.0.0.1:{bridge_port}/command"
        self.mode = "member_snapshot" if snapshot else "authorized_local_service" if local else "feishu_browser"
        self.session = "research-progress-" + uuid.uuid4().hex
        self._lock = threading.Lock()
        self.opener = build_opener(ProxyHandler({}), NoRedirect())

    def _command(self, action, args):
        body = json.dumps({"action": action, "args": args, "session": self.session}).encode()
        request = Request(self.bridge, data=body, headers={"Content-Type": "application/json"})
        try:
            with self.opener.open(request, timeout=30) as response:
                # The bridge returns a JSON envelope containing the page's serialized result.
                result = json.loads(limited_read(response, LIMIT * 3))
        except (OSError, ValueError) as exc:
            raise Unavailable("浏览器连接未响应。请确认成员浏览器和本机浏览器扩展已连接。") from exc
        if not result.get("ok") or not isinstance(result.get("data"), dict):
            raise Unavailable("浏览器扩展未完成读取。请核对现有平台标签页及扩展的连接状态。")
        return result["data"]

    def _browser_read(self, path):
        # Only this application chooses the origin, the endpoint and the JavaScript.
        with self._lock:
            tabs = self._command("list_browser_tabs", {}).get("tabs", [])
            choices = [t for t in tabs if isinstance(t.get("url"), str) and t["url"].startswith(ORIGIN + "/")]
            if not choices:
                raise Unavailable("请在已连接的浏览器打开科研平台并使用飞书登录。")
            tab = next((t for t in choices if t.get("active")), None)
            if tab is None:
                tab = next((t for t in choices if urlsplit(t["url"]).path == "/progress/"), choices[0])
            self._command("attach_tab", {"tabId": tab["tabId"]})
            code = """(async () => {
                if (location.origin !== ORIGIN) return JSON.stringify({status: 403});
                const r = await fetch(PATH, {method:'GET', credentials:'same-origin', redirect:'manual', cache:'no-store', signal:AbortSignal.timeout(15000)});
                if (r.status !== 200) return JSON.stringify({status: r.status});
                if (!(r.headers.get('content-type') || '').includes('application/json')) return JSON.stringify({status: 401});
                const reader = r.body.getReader(), decoder = new TextDecoder(); let bytes = 0, body = '';
                for (;;) {
                    const part = await reader.read();
                    if (part.done) break;
                    bytes += part.value.length;
                    if (bytes > MAXIMUM) { await reader.cancel(); return JSON.stringify({status: 413}); }
                    body += decoder.decode(part.value, {stream:true});
                }
                return JSON.stringify({status:200, body:body + decoder.decode()});
            })()""".replace("ORIGIN", json.dumps(ORIGIN)).replace("PATH", json.dumps(path)).replace("MAXIMUM", str(LIMIT))
            result = self._command("evaluate", {"code": code})
        try:
            page = json.loads(result["value"])
            if page.get("status") != 200:
                raise failure(page.get("status"))
            return json.loads(page["body"])
        except (KeyError, TypeError, json.JSONDecodeError) as exc:
            raise Unavailable("浏览器没有返回完整 JSON。可从已登录平台导出上下文后重试。") from exc

    def get(self, key):
        path = PATHS[key]
        if self.snapshot:
            with self.snapshot.open("rb") as stream:
                snapshot = json.loads(limited_read(stream, LIMIT))
            if not isinstance(snapshot, dict) or snapshot.get("mode") != "offline_snapshot" or snapshot.get("schema_version") != "1.0" or not isinstance(snapshot.get("sources"), dict):
                raise Unavailable("本地文件不是支持的成员上下文导出。")
            row = next((r for r in snapshot["sources"].values() if isinstance(r, dict) and r.get("url") == path), None)
            if row is None:
                raise Unavailable("这份成员导出未包含该来源；可在浏览器中查询当前版本。")
            if row.get("status") != "ok":
                raise Unavailable("导出时该来源读取失败。")
            data = row.get("data")
            observation = {"snapshot_generated_at": snapshot.get("generated_at"), "fetched_at": row.get("fetched_at")}
        elif self.local:
            try:
                req = Request(self.local + path.removeprefix("/progress"), headers={"Accept": "application/json"})
                with self.opener.open(req, timeout=20) as response:
                    if response.headers.get_content_type() != "application/json":
                        raise Unavailable("来源返回登录页或其他非 JSON 内容。")
                    data = json.loads(limited_read(response, LIMIT))
            except HTTPError as exc:
                raise failure(exc.code) from exc
            except (URLError, TimeoutError) as exc:
                raise Unavailable("已配置的本机进度服务未响应。") from exc
            observation = {}
        else:
            data, observation = self._browser_read(path), {}
        if not isinstance(data, dict):
            raise Unavailable("来源格式异常，无法判断进展。")
        return data, {"path": path, "mode": self.mode, **observation}
