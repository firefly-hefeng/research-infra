"""Read existing platform APIs or a downloaded context snapshot; never submit or run jobs."""
import argparse
import json
from pathlib import Path
import sys
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone

try:
    from tools.direction_context import dossier, markdown
except ModuleNotFoundError:
    from direction_context import dossier, markdown

ENDPOINTS = {
    'summary':'/api/summary', 'manifest':'/api/agent/manifest',
    'mapping':'/api/resource-mapping', 'library':'/api/platform/library',
    'guide':'/api/research-guide', 'research':'/api/platform/research',
    'documents':'/api/workspace-docs', 'servers':'/api/platform/servers',
    'progress':'/progress/api/progress-digest', 'directions':'/progress/api/directions',
    'papers':'/papers/api/export',
}
class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def fetch_json(base, path, headers):
    request = urllib.request.Request(base.rstrip('/') + path, headers=headers)
    with urllib.request.build_opener(NoRedirect).open(request, timeout=20) as response:
        if 'application/json' not in response.headers.get('Content-Type', ''):
            raise ValueError('Expected JSON, received an identity/HTML page. Use the signed-in browser or an offline snapshot.')
        raw = response.read(16 * 1024 * 1024 + 1)
        if len(raw) > 16 * 1024 * 1024:
            raise ValueError('Response exceeds 16 MiB; use a narrower source')
        return json.loads(raw)


def direction_pack(args, snapshot=None, headers=None):
    sources, observations = {}, {}
    for name in ('directions', 'research', 'progress', 'library', 'papers'):
        path = '/papers/api/catalog' if name == 'papers' else ENDPOINTS[name]
        if snapshot is not None:
            source = next((r for r in snapshot['sources'].values() if r.get('url') == path), {})
            if name == 'papers' and not source:
                path = ENDPOINTS['papers']
                source = next((r for r in snapshot['sources'].values() if r.get('url') == path), {})
            meta = {key: source[key] for key in ('status', 'fetched_at', 'error_code') if key in source}
            observation = {'url': path, 'status': 'not_exported', **meta}
            data = source.get('data')
        else:
            observation = {'url': path, 'fetched_at': datetime.now(timezone.utc).isoformat(), 'status': 'ok'}
            try:
                data = fetch_json(args.base_url, path, headers)
            except (OSError, ValueError) as exc:
                observation.update(status='failed', error_code=getattr(exc, 'code', type(exc).__name__))
                data = None
        if observation['status'] == 'ok':
            if isinstance(data, dict):
                sources[name] = data
            else:
                observation['status'] = 'invalid_source'
        observations[name] = observation
    pack = dossier(args.direction, sources, observations, mode='offline_snapshot' if snapshot is not None else 'live',
                   generated_at=datetime.now(timezone.utc).isoformat(), search_terms=args.keyword, limit=args.limit)
    if snapshot is not None:
        pack['snapshot_generated_at'] = snapshot.get('generated_at')
    return pack

def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--base-url',default='http://127.0.0.1:8765')
    parser.add_argument('--token-file',type=Path,help='Optional catalog administrator token, not a Feishu credential')
    parser.add_argument('--snapshot',type=Path,help='Offline context exported by a signed-in member')
    sub=parser.add_subparsers(dest='action',required=True)
    for name in [*ENDPOINTS,'context']:
        sub.add_parser(name)
    direction = sub.add_parser('direction', help='按稳定方向 ID 或名称整理成果、进展、原报告和检索线索')
    direction.add_argument('direction')
    direction.add_argument('--format', choices=('markdown', 'json'), default='markdown')
    direction.add_argument('--keyword', action='append', default=[], help='候选资料关键词，可重复')
    direction.add_argument('--limit', type=int, default=5, help='每类候选最多显示几条（1–25）')
    entry=sub.add_parser('entry');entry.add_argument('registry_id')
    detail=sub.add_parser('show');detail.add_argument('id')
    search=sub.add_parser('search')
    for name in ('query','kind','server','status'):search.add_argument('--'+name,default='')
    search.add_argument('--page',type=int,default=1);search.add_argument('--page-size',type=int,default=30)
    args=parser.parse_args(argv)
    try:
        path=ENDPOINTS.get(args.action)
        if args.action=='search':
            path='/api/assets?'+urllib.parse.urlencode({'q':args.query,'kind':args.kind,'server':args.server,'status':args.status,'page':args.page,'page_size':args.page_size})
        elif args.action=='entry':path='/api/resource-mapping/'+urllib.parse.quote(args.registry_id,safe='')
        elif args.action=='show':path='/api/assets/'+urllib.parse.quote(args.id,safe='')
        if args.snapshot:
            if args.snapshot.stat().st_size>16*1024*1024:raise ValueError('Snapshot exceeds 16 MiB')
            document=json.loads(args.snapshot.read_text(encoding='utf-8'))
            if not isinstance(document,dict) or document.get('schema_version')!='1.0' or document.get('mode')!='offline_snapshot' or not isinstance(document.get('sources'),dict):
                raise ValueError('Not a supported research context snapshot')
            if any(not isinstance(row,dict) or row.get('status') not in ('ok','failed') for row in document['sources'].values()):
                raise ValueError('Snapshot source records must have explicit ok/failed states')
            if args.action=='context':
                value={'mode':'offline_snapshot','generated_at':document.get('generated_at'),'warning':'Export time is not the original source observation time.',
                       'sources':{name:{k:row.get(k) for k in ('url','status','fetched_at','error_code')} for name,row in document['sources'].items()}}
            elif args.action=='direction':
                value = direction_pack(args, snapshot=document)
            elif args.action=='manifest':
                value={'mode':'offline_snapshot','generated_at':document.get('generated_at'),'contract':document.get('contract')}
            else:
                row=next((row for row in document['sources'].values() if row.get('url')==path),None)
                if not row:raise ValueError('This source was not exported; use context to inspect available sources. Search/show/entry require the live API.')
                if row.get('status')!='ok':raise ValueError('The exported source failed; this is not an empty result. Re-export or inspect context.')
                value=row['data']
        else:
            if args.action=='context':raise ValueError('context requires --snapshot; download research context from the signed-in platform /#agent')
            base=urllib.parse.urlsplit(args.base_url)
            if base.scheme not in ('http','https') or not base.hostname or base.username or base.password or base.query or base.fragment or base.path not in ('','/'):
                raise ValueError('Use an HTTP(S) origin without credentials, path, query or fragment')
            headers={'Accept':'application/json'}
            if args.token_file:
                if base.scheme!='https' and base.hostname not in ('127.0.0.1','localhost','::1'):
                    raise ValueError('Catalog tokens require HTTPS or loopback')
                token=args.token_file.read_text(encoding='utf-8').strip()
                if not 32<=len(token)<=512 or any(c.isspace() for c in token):raise ValueError('Invalid catalog token file format')
                headers['Authorization']='Bearer '+token
            value = direction_pack(args, headers=headers) if args.action=='direction' else fetch_json(args.base_url, path, headers)
        if hasattr(sys.stdout,'reconfigure'):sys.stdout.reconfigure(encoding='utf-8')
        if args.action == 'direction' and args.format == 'markdown':
            print(markdown(value))
        else:
            print(json.dumps(value,ensure_ascii=False,indent=2))
        return 0
    except urllib.error.HTTPError as exc:
        if exc.code in (301,302,303,307,308,401,403):
            print('Access requires a valid deployment session. Public Feishu access cannot be obtained with a catalog token. Use /#agent export or authorized server access.',file=sys.stderr)
        else:print('Platform request failed (HTTP '+str(exc.code)+').',file=sys.stderr)
        return 1
    except (OSError,ValueError,KeyError,TypeError) as exc:
        print('Cannot read platform context: '+str(exc),file=sys.stderr)
        return 1

if __name__=='__main__':
    raise SystemExit(main())

