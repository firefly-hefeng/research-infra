"""Read-only HTTP checks plus a disposable SQLite backup/restore rehearsal."""
import json
from pathlib import Path
import sqlite3
import tempfile
import sys
import urllib.error
import urllib.request

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from tools.path_migration import approved_path
BASE = 'http://127.0.0.1:8765'
token = (ROOT/'var/access-token').read_text().strip()

def request(path, authenticated=True):
    headers = {'Authorization':'Bearer '+token} if authenticated else {}
    with urllib.request.urlopen(urllib.request.Request(BASE+path, headers=headers), timeout=15) as response:
        return response.read()

health = json.loads(request('/api/health', False))
assert health['status'] == 'ok'
auth_required = health['authentication_required']
if auth_required:
    try:
        request('/api/summary', False)
        raise AssertionError('Metadata must require authentication')
    except urllib.error.HTTPError as exc:
        assert exc.code == 401
else:
    assert json.loads(request('/api/summary', False))['total'] > 0
session = json.loads(request('/api/session', False))
assert session['auth_enabled'] == auth_required
assert session['authenticated'] == (not auth_required)

summary = json.loads(request('/api/summary'))
export = json.loads(request('/api/export.json'))
assets = export['assets']
assert len(assets) == summary['total'] > 0
for asset in assets:
    assert asset['kind'] in ('dataset', 'model')
    assert approved_path(asset['path']) is not None
assert '/data/users/' not in json.dumps(export, ensure_ascii=False)
for path in ('/api/openapi.json','/api/agent/manifest','/docs/plan.html','/api/export.csv',
             '/docs/standards.html','/docs/resource-inventory.html',
             '/docs/templates/dataset-README.md','/docs/templates/model-README.md','/api/resource-mapping.csv'):
    assert request(path)
mapping = json.loads(request('/api/resource-mapping'))
assert {item['asset_id'] for item in mapping['items']} == {item['id'] for item in assets}
assert len({item['registry_id'] for item in mapping['items']}) == len(assets)
guide = json.loads(request('/api/research-guide'))
assert guide['catalog_sha256'] == mapping['catalog_sha256']
members = [asset_id for category in guide['categories'] for asset_id in category['asset_ids']]
assert len(members) == len(set(members)) == len(assets)
assert set(members) == {item['id'] for item in assets}
assert guide['coverage']['records'] == len(assets)
by_id = {item['asset_id']: item for item in mapping['items']}
for category in guide['categories']:
    selected = [by_id[asset_id] for asset_id in category['asset_ids']]
    assert category['counts']['records'] == len(selected)
    assert category['counts']['unique_paths'] == len({item['current_path'] for item in selected})
for item in mapping['items']:
    research = item['documentation']['research']
    assert research['summary'] and research['background'] and research['research_uses'] and research['getting_started']
    assert research['provenance'] and research['reviewed_at'] and research['evidence_basis']
    historical = (item.get('storage') or {}).get('historical') or {}
    assert research['local_observed_at'] == (historical.get('observed_at') or item['checks']['observed_at'])
    assert request(item['card_url'])
assert json.loads(request('/api/resource-mapping/'+mapping['items'][0]['registry_id']))['asset_id'] == mapping['items'][0]['asset_id']
with sqlite3.connect('file:'+str(ROOT/'var/catalog.sqlite3')+'?mode=ro', uri=True) as source:
    with tempfile.TemporaryDirectory(dir=ROOT/'var', prefix='restore-check-') as scratch:
        with sqlite3.connect(str(Path(scratch)/'restored.sqlite3')) as restored:
            source.backup(restored)
            assert restored.execute('PRAGMA integrity_check').fetchone()[0] == 'ok'
            assert restored.execute('SELECT count(*) FROM assets').fetchone()[0] == len(assets)
print(json.dumps({'http':'ok','authentication':'enabled' if auth_required else 'disabled', 'public_scope':'ok',
                  'backup_restore':'ok','inventory_cards':len(mapping['items']),
                  'research_annotations':len(mapping['items']),'research_categories':len(guide['categories']),'total':summary['total'],
                  'by_kind':summary['by_kind'], 'by_status':summary['by_status']}, ensure_ascii=False))
