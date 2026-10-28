"""Development-only bridge client. JSON requests use temporary UTF-8 file bodies."""
import json
from pathlib import Path
import subprocess
import sys
import tempfile

sys.stdout.reconfigure(encoding='utf-8')
action = sys.argv[1]
args = json.loads(sys.argv[2]) if len(sys.argv) > 2 else {}
body = {'session': 'research-data-center-v2', 'action': action, 'args': args}
with tempfile.NamedTemporaryFile(mode='w', encoding='utf-8', suffix='.json', prefix='rdc-webbridge-', delete=False) as handle:
    json.dump(body, handle, ensure_ascii=False)
    filename = Path(handle.name)
try:
    result = subprocess.run(['curl.exe', '-sS', '--max-time', '40', '-X', 'POST',
                             'http://127.0.0.1:10086/command', '-H', 'Content-Type: application/json',
                             '--data-binary', '@' + str(filename)], capture_output=True)
    raw = result.stdout.decode('utf-8', 'replace')
    if action == 'snapshot' and result.returncode == 0:
        payload = json.loads(raw)
        output = Path(__file__).resolve().parents[1] / 'var' / 'browser-snapshot.json'
        output.parent.mkdir(exist_ok=True)
        output.write_text(raw, encoding='utf-8')
        elements = []
        def visit(node):
            if isinstance(node, dict):
                if node.get('ref') or node.get('role') == 'heading':
                    elements.append({key: node[key] for key in ('role', 'name', 'ref') if key in node})
                for child in node.get('children', []):
                    visit(child)
            elif isinstance(node, list):
                for child in node:
                    visit(child)
        visit(payload.get('data', {}).get('tree', []))
        print(json.dumps({'ok': payload.get('ok'), 'url': payload.get('data', {}).get('url'),
                          'elements': elements, 'saved_snapshot': str(output)}, ensure_ascii=False))
    else:
        print(raw)
    if result.returncode:
        print(result.stderr.decode('utf-8', 'replace'), file=sys.stderr)
        raise SystemExit(result.returncode)
finally:
    filename.unlink(missing_ok=True)
