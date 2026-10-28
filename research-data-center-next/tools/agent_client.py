"""Small stdlib client for agents; JSON goes to stdout, errors to stderr."""
import argparse
import json
import pathlib
import sys
import urllib.error
import urllib.parse
import urllib.request

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('--base-url', default='http://127.0.0.1:8765')
parser.add_argument('--token-file', type=pathlib.Path)
sub = parser.add_subparsers(dest='action', required=True)
sub.add_parser('summary')
sub.add_parser('manifest')
sub.add_parser('mapping', help='In-place registry, explanations, evidence and gaps')
entry = sub.add_parser('entry', help='Look up a persistent registry entry, not an immutable release')
entry.add_argument('registry_id')
search = sub.add_parser('search')
search.add_argument('--query', default='')
search.add_argument('--kind', default='')
search.add_argument('--server', default='')
search.add_argument('--status', default='')
search.add_argument('--page', type=int, default=1)
search.add_argument('--page-size', type=int, default=30)
detail = sub.add_parser('show')
detail.add_argument('id')
args = parser.parse_args()
if args.action == 'search':
    path = '/api/assets?' + urllib.parse.urlencode({'q':args.query,'kind':args.kind,'server':args.server,'status':args.status,'page':args.page,'page_size':args.page_size})
elif args.action == 'show':
    path = '/api/assets/' + urllib.parse.quote(args.id, safe='')
elif args.action == 'manifest': path = '/api/agent/manifest'
elif args.action == 'mapping': path = '/api/resource-mapping'
elif args.action == 'entry': path = '/api/resource-mapping/' + urllib.parse.quote(args.registry_id, safe='')
else: path = '/api/summary'
headers = {}
if args.token_file:
    headers['Authorization'] = 'Bearer ' + args.token_file.read_text().strip()
try:
    request = urllib.request.Request(args.base_url.rstrip('/') + path, headers=headers)
    with urllib.request.urlopen(request, timeout=15) as response:
        value = json.load(response)
    if hasattr(sys.stdout, 'reconfigure'): sys.stdout.reconfigure(encoding='utf-8')
    print(json.dumps(value,ensure_ascii=False,indent=2))
except (OSError, ValueError) as exc:
    print('Catalog request failed: '+str(exc), file=sys.stderr)
    raise SystemExit(1)

