"""Refresh the portal's classified ledger display using the Feishu Open API."""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import re
from tempfile import NamedTemporaryFile
from urllib.parse import urlencode
from urllib.request import Request, urlopen

API = "https://open.feishu.cn/open-apis"
TABLE_ID = "tbl9Ggk0cGF0Zlxz"
VIEW_ID = "vew5x8yw5H"
COLUMNS = ("数据名称", "一级标签", "研究大类", "细分类", "当前进度")
ROW_ID = re.compile(r"rec[a-zA-Z0-9]+\Z")


def post(path, body, token=None):
    headers = {"Content-Type": "application/json; charset=utf-8"}
    if token:
        headers["Authorization"] = "Bearer " + token
    request = Request(API + path, json.dumps(body, ensure_ascii=False).encode(), headers)
    with urlopen(request, timeout=15) as response:
        raw = response.read(2_000_001)
    if len(raw) > 2_000_000:
        raise ValueError("Feishu response too large")
    reply = json.loads(raw)
    if reply.get("code") != 0:
        raise ValueError(f"Feishu returned code {reply.get('code')}")
    return reply


def plain(value):
    if isinstance(value, list):
        value = "".join(item.get("text", "") for item in value if isinstance(item, dict))
    if not isinstance(value, str):
        return ""
    return " ".join(value.split())[:180]


def load_view(app_id, app_secret, base_token):
    if not re.fullmatch(r"[a-zA-Z0-9]+", base_token):
        raise ValueError("Set the base app token to use this integration")
    reply = post("/auth/v3/tenant_access_token/internal", {"app_id": app_id, "app_secret": app_secret})
    token = reply["tenant_access_token"]
    rows = []
    records_seen, pages_seen = set(), set()
    page = None
    for _ in range(20):
        args = {"page_size": 100}
        if page:
            args["page_token"] = page
        reply = post(
            f"/bitable/v1/apps/{base_token}/tables/{TABLE_ID}/records/search?{urlencode(args)}",
            {"view_id": VIEW_ID, "field_names": list(COLUMNS), "automatic_fields": False}, token,
        )["data"]
        for record in reply.get("items", []):
            record_id = record["record_id"]
            if not ROW_ID.fullmatch(record_id) or record_id in records_seen:
                raise ValueError("Invalid or repeated Feishu record ID")
            records_seen.add(record_id)
            fields = record["fields"]
            row = {name: plain(fields.get(name)) for name in COLUMNS}
            if row[COLUMNS[0]]:
                rows.append({"id": record_id, **row})
        if not reply.get("has_more"):
            return {"observed_at": datetime.now(timezone.utc).isoformat(), "rows": rows}
        page = reply.get("page_token")
        if not page or page in pages_seen:
            raise ValueError("Incomplete Feishu pagination")
        pages_seen.add(page)
    raise ValueError("Feishu view exceeds the sync page limit")


def write_snapshot(path, payload):
    path.parent.mkdir(parents=True, exist_ok=True)
    with NamedTemporaryFile(mode="w", encoding="utf-8", dir=path.parent, delete=False) as temp:
        temp_path = Path(temp.name)
        json.dump(payload, temp, ensure_ascii=False)
        temp.write("\n")
    try:
        os.chmod(temp_path, 0o600)
        temp_path.replace(path)
    finally:
        temp_path.unlink(missing_ok=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--state-dir", required=True, type=Path)
    args = parser.parse_args()
    names = ("RMP_FEISHU_APP_ID", "RMP_FEISHU_APP_SECRET", "RMP_FEISHU_BASE_TOKEN")
    values = [os.environ.get(name, "") for name in names]
    if not all(values):
        parser.exit(2, "Set RMP_FEISHU_APP_ID, RMP_FEISHU_APP_SECRET, and RMP_FEISHU_BASE_TOKEN.\n")
    try:
        payload = load_view(*values)
        write_snapshot(args.state_dir / "feishu-library-sync.json", payload)
    except (OSError, ValueError, KeyError, TypeError) as exc:
        parser.exit(1, f"Feishu refresh failed ({type(exc).__name__}). Previous view retained.\n")
    print(f"Refreshed {len(payload['rows'])} records at {payload['observed_at']}")


if __name__ == "__main__":
    main()
