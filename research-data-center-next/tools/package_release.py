"""Create a small deployable source bundle, excluding runtime secrets and debug files."""
import hashlib
import io
import json
from pathlib import Path
import posixpath
import sys
import tarfile

root = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(root))
from tools.path_migration import approved_path, evidence_file
def public_path(value):
    return approved_path(value) is not None

document = json.loads((root/'data/catalog.json').read_text(encoding='utf-8'))
assert document['assets'], 'Refuse to publish an empty catalog'
assert all(a['kind'] in ('dataset','model') and public_path(a['path']) for a in document['assets'])
for name in ('data/catalog.json','data/build-report.json','data/collection-config.json','data/resource-mapping.json','data/resource-mapping.csv',
             'data/sources/public-assets-20261018.csv','data/sources/live-public-metadata.json'):
    assert '/data/users/' not in (root/name).read_text(encoding='utf-8'), 'Private source path in '+name
files = [root/p for p in ['catalog.py','server.py','progress_proxy.py','ingestion.py','platform_data.py','research_portfolio.py','README.md','.gitignore',
    'tools/build_catalog.py','tools/build_inventory.py','tools/research_annotations.py','tools/build_research_guide.py','tools/collect_metadata.py','tools/path_migration.py','tools/agent_client.py','tools/package_release.py','tools/install_release.py','tools/check_docs.py','tools/verify_deployment.py',
    'data/catalog.json','data/build-report.json','data/collection-config.json',
    'data/resource-registry.json','data/resource-mapping.json','data/resource-mapping.csv','data/research-guide.json','data/research-portfolio.json',
    'data/sources/public-assets-20261018.csv','data/sources/live-public-metadata.json']]
for name in ('incoming_client.py','ingest_worker.py','ingest_cycle.py','cold_archive.py','activate_shared_management.py',
             'collect_server_resources.py','server_resource_probe.py','install_monitor_access.py','setup_server_monitor.py'):
    if (root/'tools'/name).is_file():
        files.append(root/'tools'/name)
if (root/'data/server-resources.json').is_file():
    files.append(root/'data/server-resources.json')
for folder in ['static','docs','tests','deploy']:
    files.extend(p for p in (root/folder).rglob('*') if p.is_file() and '__pycache__' not in p.parts)
files.extend(sorted((root/'data/annotations').glob('*.json')))
for name in ('data/sources/catalog-pre-migration.json','data/path-migration.json','data/physical-inventory.json','tools/build_physical_inventory.py'):
    if (root/name).is_file():
        files.append(root/name)
for name in ('cpfs_link_audit.py','cpfs_transfer.py','cpfs_revalidate.py','cpfs_usage.py','cpfs_cutover.py',
             'cpfs_observe_destination.py','cpfs_publish_evidence.py','cpfs_finalize.py'):
    path=root/'tools'/name
    if path.is_file():
        files.append(path)
# Deliberately curated, compact public receipts only. Raw per-file/process logs stay in var.
for name in ('copy.json','verification.json','cutover.json','cleanup.json','preflight.json'):
    path=root/'data/migration-evidence'/name
    if path.is_file():
        files.append(path)
# Include only immutable objects explicitly referenced by the current public
# migration manifest, with the same digest validation as catalog activation.
migration_path=root/'data/path-migration.json'
if migration_path.exists():
    migration=json.loads(migration_path.read_text(encoding='utf-8'))
    for value in migration.get('receipts',{}).values():
        reference=value.get('evidence') if isinstance(value,dict) else None
        if not reference or not reference.get('sha256'):
            continue
        relative=reference.get('ref','')
        if relative.startswith('data/migration-evidence/objects/'):
            assert relative=='data/migration-evidence/objects/'+reference['sha256']+'.json'
            evidence_file(root,reference)
            files.append(root/relative)
files=list(dict.fromkeys(files))
# Hash and archive the same captured bytes, including periodically refreshed snapshots.
captured = {p: p.read_bytes() for p in files}
manifest = {str(p.relative_to(root)).replace('\\','/'): hashlib.sha256(captured[p]).hexdigest() for p in sorted(files)}
(root/'release-manifest.json').write_text(json.dumps(manifest,ensure_ascii=False,indent=2),encoding='utf-8')
with tarfile.open(root/'release.tar.gz','w:gz') as archive:
    for p in files:
        info = archive.gettarinfo(str(p), arcname=p.relative_to(root).as_posix())
        info.size = len(captured[p])
        archive.addfile(info, io.BytesIO(captured[p]))
    archive.add(root/'release-manifest.json',arcname='release-manifest.json',recursive=False)
print(json.dumps({'files':len(files),'bytes':(root/'release.tar.gz').stat().st_size,'sha256':hashlib.sha256((root/'release.tar.gz').read_bytes()).hexdigest()}))
