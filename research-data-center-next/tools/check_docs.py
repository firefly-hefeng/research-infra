"""Check authored/generated HTML links and template syntax without reading source data."""
from html.parser import HTMLParser
import json
from pathlib import Path
from urllib.parse import unquote, urlsplit
import zipfile

ROOT = Path(__file__).resolve().parents[1]


class Links(HTMLParser):
    def __init__(self):
        super().__init__()
        self.links, self.ids = [], set()

    def handle_starttag(self, tag, attributes):
        attrs = dict(attributes)
        if attrs.get('id'):
            self.ids.add(attrs['id'])
        if tag in ('a', 'link', 'script'):
            value = attrs.get('href') or attrs.get('src')
            if value:
                self.links.append(value)


def main():
    documents = list((ROOT / 'docs').rglob('*.html')) + [ROOT / 'static' / 'index.html']
    parsed, errors, checked = {}, [], 0
    for source in documents:
        parser = Links()
        parser.feed(source.read_text(encoding='utf-8'))
        parsed[source.resolve()] = parser
    for source, parser in parsed.items():
        for href in parser.links:
            value = urlsplit(href)
            # Independent loopback applications are mounted by the unified gateway.
            if value.scheme or value.netloc or value.path.startswith('/api/') or value.path in ('/progress/', '/papers/'):
                continue
            if value.path == '/':
                target = ROOT / 'static' / 'index.html'
            elif value.path.startswith('/docs/'):
                target = ROOT / value.path.lstrip('/')
            elif value.path.startswith('/'):
                target = ROOT / 'static' / value.path.lstrip('/')
            else:
                target = source.parent / unquote(value.path) if value.path else source
            target = target.resolve()
            checked += 1
            if not target.is_file():
                errors.append(f'{source.relative_to(ROOT)} -> {href}: missing file')
            elif value.fragment and target in parsed and unquote(value.fragment) not in parsed[target].ids:
                errors.append(f'{source.relative_to(ROOT)} -> {href}: missing fragment')
    templates = ROOT / 'docs' / 'templates'
    for target in templates.glob('*.json'):
        json.loads(target.read_text(encoding='utf-8'))
    for target in templates.glob('*.jsonl'):
        for line in target.read_text(encoding='utf-8').splitlines():
            if line.strip():
                json.loads(line)
    for target in templates.glob('*.zip'):
        with zipfile.ZipFile(target) as archive:
            if archive.testzip():
                errors.append('Invalid template archive')
    print(json.dumps({'html_documents': len(documents), 'internal_links_checked': checked,
                      'template_syntax': 'ok', 'errors': errors}, ensure_ascii=False))
    return bool(errors)


if __name__ == '__main__':
    raise SystemExit(main())
