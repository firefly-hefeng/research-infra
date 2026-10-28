import contextlib
import fcntl
import hashlib
import ipaddress
import json
import os
from pathlib import Path
import re
import shutil
import sqlite3
import subprocess
import time
import unicodedata
from datetime import datetime, timezone
from urllib.parse import urlsplit

CATEGORIES = ['数据选择', '表征学习', '泛化理论', '核方法', '生成模型', '语言模型', '其他']
ID = re.compile(r'^[a-f0-9]{64}$')
READING_TEXT_FIELDS = ('takeaway', 'background', 'problem', 'method', 'experiments',
                       'results', 'discussion', 'reproduction')
READING_FIELDS = READING_TEXT_FIELDS + ('result_table', 'resources')


def reading_details(value):
    """Normalize optional source-grounded reading sections without inventing missing ones."""
    if not isinstance(value, dict) or set(value) - set(READING_FIELDS):
        raise ValueError('reading 必须是仅包含已定义解读字段的对象')
    clean = {}
    for key in READING_TEXT_FIELDS:
        item = value.get(key, '')
        maximum = 400 if key == 'takeaway' else 8000
        if not isinstance(item, str) or len(item) > maximum:
            raise ValueError(f'reading.{key} 必须是最多 {maximum} 字符的文本')
        if item.strip():
            clean[key] = item.strip()
    if 'result_table' in value and value['result_table'] is not None:
        table = value['result_table']
        if not isinstance(table, dict) or set(table) - {'caption', 'columns', 'rows'}:
            raise ValueError('reading.result_table 必须包含 caption、columns、rows')
        caption, columns, rows = table.get('caption', ''), table.get('columns'), table.get('rows')
        if not isinstance(caption, str) or len(caption) > 1000:
            raise ValueError('reading.result_table.caption 必须是最多 1000 字符的文本')
        if not isinstance(columns, list) or not 2 <= len(columns) <= 8 or any(
                not isinstance(c, str) or not c.strip() or len(c) > 160 for c in columns):
            raise ValueError('reading.result_table.columns 必须有 2–8 个非空列名，每项最多 160 字符')
        if not isinstance(rows, list) or len(rows) > 30 or any(
                not isinstance(row, list) or len(row) != len(columns) or any(
                    not isinstance(cell, str) or len(cell) > 1500 for cell in row) for row in rows):
            raise ValueError('reading.result_table.rows 最多 30 行，单元格须为最多 1500 字符的文本，且与列数一致')
        clean['result_table'] = {'caption': caption.strip(), 'columns': [c.strip() for c in columns],
                                 'rows': [[cell.strip() for cell in row] for row in rows]}
    resources = value.get('resources', [])
    if not isinstance(resources, list) or len(resources) > 12:
        raise ValueError('reading.resources 必须是最多 12 项的列表')
    links = []
    for resource in resources:
        if not isinstance(resource, dict) or set(resource) - {'label', 'url', 'kind'}:
            raise ValueError('reading.resources 每项必须包含 label、url、kind')
        label, url, kind = resource.get('label'), resource.get('url'), resource.get('kind')
        if not isinstance(label, str) or not label.strip() or len(label) > 160:
            raise ValueError('reading.resources.label 必须是最多 160 字符的非空文本')
        if kind not in ('code', 'data', 'project', 'other'):
            raise ValueError('reading.resources.kind 必须为 code、data、project 或 other')
        if not isinstance(url, str) or not url or len(url) > 2048 or any(
                c.isspace() or ord(c) < 32 or ord(c) == 127 for c in url) or '\\' in url or re.search(r'%(?![0-9a-fA-F]{2})', url):
            raise ValueError('reading.resources.url 不是有效的 HTTP(S) 链接')
        try:
            parsed = urlsplit(url)
            host = parsed.hostname
            if parsed.scheme not in ('http', 'https') or not host or parsed.username is not None or parsed.password is not None:
                raise ValueError('scheme, host or credentials')
            if parsed.netloc.endswith(':') or (parsed.port is not None and not 1 <= parsed.port <= 65535):
                raise ValueError('port')
            try:
                ipaddress.ip_address(host)
            except ValueError:
                ascii_host = host.encode('idna').decode('ascii').rstrip('.')
                if len(ascii_host) > 253 or re.fullmatch(r'[0-9.]+', ascii_host) or any(
                        not re.fullmatch(r'[a-zA-Z0-9](?:[a-zA-Z0-9-]{0,61}[a-zA-Z0-9])?', part)
                        for part in ascii_host.split('.')):
                    raise ValueError('hostname')
        except (ValueError, UnicodeError):
            raise ValueError('reading.resources.url 不是有效的无凭证 HTTP(S) 链接') from None
        links.append({'label': label.strip(), 'url': url, 'kind': kind})
    if links:
        clean['resources'] = links
    return clean


def now():
    return datetime.now(timezone.utc).isoformat()


def normalize(value):
    return re.sub(r'\s+', '', unicodedata.normalize('NFKC', value)).casefold()


def digest(path):
    h = hashlib.sha256()
    with path.open('rb') as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b''):
            h.update(chunk)
    return h.hexdigest()


def atomic_json(path, data):
    tmp = path.with_name(path.name + '.tmp')
    with tmp.open('w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp, path)


def title_folder(title, number=0):
    """Readable, portable single path component; keep room for collision suffixes."""
    title = unicodedata.normalize('NFC', title)
    title = ''.join(' ' if unicodedata.category(c).startswith('C') else c for c in title)
    title = re.sub(r'[<>:"/\\|?*]', ' - ', title)
    title = re.sub(r'\s+', ' ', title).strip(' .') or '未命名论文'
    if re.fullmatch(r'(?i)(CON|PRN|AUX|NUL|COM[1-9]|LPT[1-9])(?:\..*)?', title):
        title = '_' + title
    title = title.encode('utf-8')[:200].decode('utf-8', errors='ignore').rstrip(' .')
    return title + (f'（{number}）' if number else '')


class Library:
    def __init__(self, root):
        self.root = Path(root).absolute()
        if self.root.is_symlink():
            raise ValueError('论文库根目录不能是符号链接')
        self.root.mkdir(parents=True, exist_ok=True)
        self.root = self.root.resolve()
        for name in ('inbox', 'library', 'duplicates', '.paperlib', '.paperlib/text'):
            self.safe(name).mkdir(exist_ok=True)
        self.db_path = self.safe('.paperlib/catalog.sqlite3')
        self.safe('.paperlib/write.lock').touch(exist_ok=True)
        with self.db() as db:
            db.executescript('''
            PRAGMA journal_mode=WAL;
            CREATE TABLE IF NOT EXISTS papers(
                id TEXT PRIMARY KEY, filename TEXT NOT NULL, source TEXT NOT NULL,
                pdf TEXT, status TEXT NOT NULL, card TEXT, error TEXT,
                created TEXT NOT NULL, updated TEXT NOT NULL,
                notes TEXT NOT NULL DEFAULT '', favorite INTEGER NOT NULL DEFAULT 0);
            CREATE TABLE IF NOT EXISTS jobs(
                id INTEGER PRIMARY KEY AUTOINCREMENT, started TEXT NOT NULL,
                finished TEXT, status TEXT NOT NULL, result TEXT NOT NULL DEFAULT '{}');
            CREATE TABLE IF NOT EXISTS settings(key TEXT PRIMARY KEY, value TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS bibliographic_imports(
                paper_id TEXT PRIMARY KEY, collection_id TEXT NOT NULL,
                metadata TEXT NOT NULL, manifest_sha256 TEXT NOT NULL, imported_at TEXT NOT NULL);
            ''')

    def safe(self, relative):
        p = Path(relative)
        if p.is_absolute() or '..' in p.parts:
            raise ValueError('路径必须位于固定论文库内')
        current = self.root
        for part in p.parts:
            current = current / part
            if current.is_symlink():
                raise ValueError('不允许符号链接: ' + str(p))
        if not current.resolve().is_relative_to(self.root):
            raise ValueError('路径越界')
        return current

    @contextlib.contextmanager
    def db(self):
        db = sqlite3.connect(self.db_path, timeout=30)
        db.row_factory = sqlite3.Row
        try:
            with db:
                yield db
        finally:
            db.close()

    @contextlib.contextmanager
    def lock(self, name='write', blocking=True):
        path = self.safe('.paperlib/' + name + '.lock')
        with path.open('a') as f:
            fcntl.flock(f, fcntl.LOCK_EX | (0 if blocking else fcntl.LOCK_NB))
            try:
                yield
            finally:
                fcntl.flock(f, fcntl.LOCK_UN)

    def record(self, paper_id):
        if not isinstance(paper_id, str) or not ID.fullmatch(paper_id):
            raise ValueError('无效论文 ID')
        with self.db() as db:
            row = db.execute('SELECT * FROM papers WHERE id=?', (paper_id,)).fetchone()
            bibliography = db.execute('SELECT metadata,collection_id,manifest_sha256,imported_at FROM bibliographic_imports WHERE paper_id=?', (paper_id,)).fetchone()
        if not row:
            raise KeyError('论文不存在')
        result = dict(row)
        result['card'] = json.loads(result['card']) if result['card'] else None
        result['favorite'] = bool(result['favorite'])
        result['bibliography'] = None
        if bibliography:
            result['bibliography'] = json.loads(bibliography['metadata'])
            result['bibliography'].update(collection_id=bibliography['collection_id'],
                manifest_sha256=bibliography['manifest_sha256'], imported_at=bibliography['imported_at'])
        return result

    def papers(self):
        with self.db() as db:
            ids = [r[0] for r in db.execute('SELECT id FROM papers ORDER BY created DESC, filename')]
        return [self.record(i) for i in ids]

    def bootstrap(self):
        """Copy initial root PDFs once; keep originals untouched."""
        copied = []
        with self.lock():
            for source in sorted(self.root.iterdir()):
                if source.suffix.lower() != '.pdf' or source.is_symlink() or not source.is_file():
                    continue
                ident = digest(source)
                with self.db() as db:
                    if db.execute('SELECT 1 FROM papers WHERE id=?', (ident,)).fetchone():
                        continue
                target = self.safe('inbox/' + source.name)
                if target.exists():
                    if digest(target) == ident:
                        continue
                    raise ValueError('待整理区存在同名不同内容文件: ' + source.name)
                shutil.copy2(source, target)
                copied.append(source.name)
        return copied

    def scan(self, settle_seconds=3):
        result = {'added': 0, 'duplicates': 0, 'skipped': []}
        with self.lock():
            inbox = self.safe('inbox')
            for folder, dirs, files in os.walk(inbox, followlinks=False):
                dirs[:] = [d for d in dirs if not (Path(folder) / d).is_symlink() and not d.startswith('.')]
                for name in sorted(files):
                    path = Path(folder) / name
                    if path.suffix.lower() != '.pdf' or path.is_symlink():
                        continue
                    path = self.safe(str(path.relative_to(self.root)))
                    stat = path.stat()
                    if time.time() - stat.st_mtime < settle_seconds:
                        result['skipped'].append(name + ': 正在写入，稍后重试')
                        continue
                    if stat.st_size > 256 * 1024 * 1024:
                        result['skipped'].append(name + ': 超过 256 MiB')
                        continue
                    ident = digest(path)
                    after = path.stat()
                    if (stat.st_size, stat.st_mtime_ns) != (after.st_size, after.st_mtime_ns):
                        result['skipped'].append(name + ': 文件正在变化')
                        continue
                    rel = str(path.relative_to(self.root))
                    with self.db() as db:
                        existing = db.execute('SELECT source, pdf FROM papers WHERE id=?', (ident,)).fetchone()
                        if existing:
                            if existing['source'] == rel and not existing['pdf']:
                                continue
                            # Preserve duplicate files instead of deleting them.
                            dest = self.safe('duplicates/' + ident)
                            dest.mkdir(exist_ok=True)
                            target = dest / name
                            if target.exists():
                                target = dest / (str(time.time_ns()) + '-' + name)
                            os.rename(path, target)
                            result['duplicates'] += 1
                            continue
                        db.execute('INSERT INTO papers(id,filename,source,status,created,updated) VALUES(?,?,?,?,?,?)',
                                   (ident, name, rel, 'pending', now(), now()))
                        result['added'] += 1
        return result

    def pdf_path(self, paper_id):
        item = self.record(paper_id)
        path = self.safe(item['pdf'] or item['source'])
        if not path.is_file():
            raise FileNotFoundError('论文原件缺失，请检查服务器目录')
        return path

    def extract(self, paper_id):
        with self.lock():
            path = self.pdf_path(paper_id)
            if digest(path) != paper_id:
                raise ValueError('PDF 内容已变化，请重新扫描')
            with path.open('rb') as f:
                if f.read(5) != b'%PDF-':
                    raise ValueError('文件不是有效的 PDF')
            executable = shutil.which('pdftotext')
            if not executable:
                raise RuntimeError('缺少 pdftotext，请安装 Poppler')
            out = self.safe('.paperlib/text/' + paper_id + '.txt')
            tmp = self.safe(str(out.with_suffix('.tmp').relative_to(self.root)))
            try:
                subprocess.run([executable, '-layout', str(path), str(tmp)], check=True,
                               timeout=90, capture_output=True)
                if tmp.stat().st_size > 8 * 1024 * 1024:
                    raise ValueError('正文过大，需人工分段处理')
                text = tmp.read_text(encoding='utf-8')
                if len(normalize(text)) < 80:
                    raise ValueError('正文不足，可能是扫描件；请先进行 OCR')
                if digest(path) != paper_id:
                    raise ValueError('提取期间文件变化，请重试')
                os.replace(tmp, out)
                return text
            finally:
                tmp.unlink(missing_ok=True)

    def text(self, paper_id):
        self.record(paper_id)
        path = self.safe('.paperlib/text/' + paper_id + '.txt')
        return path.read_text(encoding='utf-8') if path.exists() else self.extract(paper_id)

    def validate_card(self, paper_id, card):
        if not isinstance(card, dict):
            raise ValueError('卡片必须是 JSON 对象')
        def string(key, maximum, required=False):
            val = card.get(key, '')
            if not isinstance(val, str) or len(val) > maximum or (required and not val.strip()):
                raise ValueError('字段不符合要求: ' + key)
            return val.strip()
        clean = {k: string(k, n, req) for k, n, req in [
            ('title', 600, True), ('summary', 5000, True), ('venue', 200, False),
            ('doi', 200, False), ('year_note', 500, False)]}
        year = card.get('year')
        if year is not None and (type(year) is not int or not 1800 <= year <= datetime.now().year + 2):
            raise ValueError('year 必须是合理年份或 null')
        clean['year'] = year
        category = card.get('category')
        if category not in CATEGORIES:
            raise ValueError('category 必须使用既有分类')
        clean['category'] = category
        for key, limit, maxlen in [('authors', 100, 180), ('tags', 12, 60), ('contributions', 8, 1500), ('limitations', 8, 1500)]:
            val = card.get(key, [])
            if not isinstance(val, list) or len(val) > limit or any(not isinstance(x, str) or not x.strip() or len(x) > maxlen for x in val):
                raise ValueError('无效列表: ' + key)
            clean[key] = list(dict.fromkeys(x.strip() for x in val))
        if not clean['tags'] or not clean['contributions']:
            raise ValueError('至少需要一个标签和一项贡献')
        clean['reading'] = reading_details(card.get('reading', {}))
        pages = self.text(paper_id).split('\f')
        evidence = card.get('evidence', [])
        if not isinstance(evidence, list) or len(evidence) > 100:
            raise ValueError('evidence 必须是最多 100 项的列表')
        evidence_fields = ('title', 'authors', 'year', 'venue', 'summary', 'contributions', 'limitations', 'doi')
        evidence_fields += tuple('reading.' + key for key in READING_FIELDS)
        valid = []
        for index, e in enumerate(evidence):
            if not isinstance(e, dict):
                raise ValueError('无效证据')
            page, quote, field = e.get('page'), e.get('quote'), e.get('field')
            if type(page) is not int or not 1 <= page <= len(pages):
                raise ValueError(f'evidence[{index}] 证据页码超出 PDF 页数')
            if not isinstance(field, str) or field not in evidence_fields:
                raise ValueError('证据字段无效')
            if not isinstance(quote, str) or not 8 <= len(quote) <= 1200 or normalize(quote) not in normalize(pages[page - 1]):
                raise ValueError(f'evidence[{index}] 证据引文无法在指定原文页找到: {field}，PDF 第 {page} 页；请改用已提供的 source_id 或逐字连续引文')
            valid.append({'field': field, 'page': page, 'quote': quote})
        needed = {'title', 'summary', 'contributions'}
        needed.update(k for k in ('authors', 'year', 'venue', 'doi', 'limitations') if clean.get(k))
        needed.update('reading.' + key for key, value in clean['reading'].items() if value)
        if needed - {e['field'] for e in valid}:
            raise ValueError('缺少字段证据: ' + ', '.join(sorted(needed - {e['field'] for e in valid})))
        clean['evidence'] = valid
        if type(card.get('needs_review', False)) is not bool:
            raise ValueError('needs_review 必须为布尔值')
        clean['needs_review'] = card.get('needs_review', False) or not clean['authors'] or year is None
        clean['review_reason'] = string('review_reason', 1500)
        if clean['needs_review'] and not clean['review_reason']:
            raise ValueError('待核对卡片需要 review_reason')
        clean['schema_version'] = 1
        return clean

    def title_directory(self, parent, title, reserved=()):
        """Allocate under the writer lock, counting files, symlinks and DB paths too."""
        parent = self.safe(str(parent.relative_to(self.root)))
        parent.mkdir(parents=True, exist_ok=True)
        key = lambda name: unicodedata.normalize('NFC', name).casefold()
        occupied = {key(p.name) for p in parent.iterdir()}
        occupied.update(key(name) for name in reserved)
        with self.db() as db:
            for row in db.execute('SELECT pdf FROM papers WHERE pdf IS NOT NULL'):
                directory = Path(row['pdf']).parent
                if directory.parent == parent.relative_to(self.root):
                    occupied.add(key(directory.name))
        number = 0
        while key(title_folder(title, number)) in occupied:
            number += 1
        return self.safe(str((parent / title_folder(title, number)).relative_to(self.root)))

    def migrate_title_directories(self):
        """Offline migration of legacy hash folders; back up DB and roll back on errors."""
        with self.lock('server', blocking=False), self.lock('agent', blocking=False), self.lock():
            plan, reserved = [], {}
            for item in self.papers():
                if not item['pdf'] or not item['card']:
                    continue
                old = self.safe(str(Path(item['pdf']).parent))
                if old.name != item['id']:
                    continue
                source = self.pdf_path(item['id'])
                if digest(source) != item['id']:
                    raise ValueError('迁移前 PDF 哈希校验失败: ' + item['filename'])
                new = self.title_directory(old.parent, item['card']['title'], reserved.get(old.parent, []))
                reserved.setdefault(old.parent, []).append(new.name)
                plan.append({'id': item['id'], 'title': item['card']['title'],
                             'old': str(old.relative_to(self.root)), 'new': str(new.relative_to(self.root))})
            if not plan:
                return {'moved': 0, 'items': []}
            directory = self.safe('.paperlib/migrations')
            directory.mkdir(exist_ok=True)
            stamp = str(time.time_ns())
            backup = self.safe('.paperlib/migrations/' + stamp + '-catalog.sqlite3')
            with self.db() as source_db, sqlite3.connect(backup) as backup_db:
                source_db.backup(backup_db)
            report = self.safe('.paperlib/migrations/' + stamp + '-title-directories.json')
            journal = {'started': now(), 'status': 'prepared', 'database_backup': str(backup.relative_to(self.root)), 'items': plan}
            atomic_json(report, journal)
            moved = []
            try:
                with self.db() as db:
                    for entry in plan:
                        old, new = self.safe(entry['old']), self.safe(entry['new'])
                        if new.exists():
                            raise ValueError('迁移目标已被占用，禁止覆盖: ' + entry['new'])
                        os.rename(old, new)
                        moved.append(entry)
                        db.execute('UPDATE papers SET pdf=? WHERE id=?',
                                   (str(Path(entry['new']) / 'paper.pdf'), entry['id']))
            except Exception:
                for entry in reversed(moved):
                    old, new = self.safe(entry['old']), self.safe(entry['new'])
                    if old.exists():
                        raise RuntimeError('迁移回滚目标被占用，请按迁移记录恢复: ' + str(report))
                    os.rename(new, old)
                journal.update(status='rolled_back', finished=now())
                atomic_json(report, journal)
                raise
            journal.update(status='completed', finished=now())
            atomic_json(report, journal)
            return {'moved': len(plan), 'items': plan, 'report': str(report), 'database_backup': str(backup)}

    def commit(self, paper_id, card):
        # Extract before acquiring the writer lock (extract uses it too).
        clean = self.validate_card(paper_id, card)
        with self.lock():
            record = self.record(paper_id)
            source = self.pdf_path(paper_id)
            if digest(source) != paper_id:
                raise ValueError('源文件哈希已变化，禁止入库')
            # Preserve the first archive location on subsequent revisions.
            directory = self.safe(str(Path(record['pdf']).parent)) if record['pdf'] else self.title_directory(
                self.safe('library/' + clean['category'] + '/' + str(clean['year'] or 'unknown')), clean['title'])
            directory.mkdir(parents=True, exist_ok=True)
            dest = self.safe(str((directory / 'paper.pdf').relative_to(self.root)))
            if dest != source:
                if dest.exists() and digest(dest) != paper_id:
                    raise ValueError('归档位置有冲突，禁止覆盖')
                if not dest.exists():
                    tmp = self.safe(str(dest.with_suffix('.tmp').relative_to(self.root)))
                    shutil.copy2(source, tmp)
                    if digest(tmp) != paper_id:
                        tmp.unlink()
                        raise ValueError('复制校验失败')
                    os.replace(tmp, dest)
            clean['updated_at'] = now()
            atomic_json(self.safe(str((directory / 'card.json').relative_to(self.root))), clean)
            with self.db() as db:
                db.execute('UPDATE papers SET pdf=?,card=?,status=?,error=NULL,updated=? WHERE id=?',
                           (str(dest.relative_to(self.root)), json.dumps(clean, ensure_ascii=False),
                            'review' if clean['needs_review'] else 'ready', now(), paper_id))
            if source != dest and source.is_file() and digest(source) == paper_id:
                source.unlink()
        return self.record(paper_id)

    def edit(self, paper_id, payload):
        with self.lock(), self.db() as db:
            record = self.record(paper_id)
            if set(payload) - {'notes', 'favorite'}:
                raise ValueError('仅允许修改笔记与收藏')
            notes, favorite = payload.get('notes', record['notes']), payload.get('favorite', record['favorite'])
            if not isinstance(notes, str) or len(notes) > 20000 or type(favorite) is not bool:
                raise ValueError('笔记或收藏格式错误')
            db.execute('UPDATE papers SET notes=?,favorite=?,updated=? WHERE id=?', (notes, favorite, now(), paper_id))
        return self.record(paper_id)

    def error(self, paper_id, message):
        with self.lock(), self.db() as db:
            db.execute("UPDATE papers SET status='error',error=?,updated=? WHERE id=? AND pdf IS NULL", (message[:1000], now(), paper_id))

    def settings(self, key, value=None):
        with self.db() as db:
            if value is not None:
                db.execute('INSERT OR REPLACE INTO settings VALUES(?,?)', (key, value))
            row = db.execute('SELECT value FROM settings WHERE key=?', (key,)).fetchone()
            return row[0] if row else None

    def jobs(self):
        with self.db() as db:
            rows = [dict(r) for r in db.execute('SELECT * FROM jobs ORDER BY id DESC LIMIT 40')]
        for row in rows:
            row['result'] = json.loads(row['result'])
        return rows
