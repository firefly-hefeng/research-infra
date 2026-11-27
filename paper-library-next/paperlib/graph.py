"""Read-only projection of catalog metadata and recorded bylines."""
import hashlib
import unicodedata


def normalized(value):
    return ' '.join(unicodedata.normalize('NFKC', value).split()).casefold()


def literature_graph(papers):
    nodes, edges = {}, {}
    for item in sorted(papers, key=lambda p: p['id']):
        card = item.get('card') or {}
        bibliography = item.get('bibliography') or {}
        insight = item.get('insight') or {}
        title = card.get('title') or bibliography.get('title')
        if not title:
            continue
        paper_id = item['id']
        nodes[paper_id] = {'id': paper_id, 'kind': 'paper', 'label': title,
                           'year': card.get('year') or bibliography.get('year')}
        fields = []
        category_key = normalized(card.get('category') or bibliography.get('category') or '')
        for name, record in [('card', card), ('bibliography', bibliography)]:
            category = record.get('category')
            current = card.get('category')
            if name == 'card' or not current or (category and normalized(category) == normalized(current)):
                fields.append(('direction', name + '.category', [category]))
            fields.append(('topic', name + '.tags', record.get('tags')))
            fields.append(('byline', name + '.authors', record.get('authors')))
        fields.append(('topic', 'insight.keywords', insight.get('keywords')))
        author_terms = insight.get('author_keywords') or {}
        fields.append(('topic', 'insight.author_keywords.terms', author_terms.get('terms')))
        for kind, source, terms in fields:
            if not isinstance(terms, list):
                continue
            for term in terms:
                if not isinstance(term, str) or not term.strip():
                    continue
                label = ' '.join(term.split())
                text = normalized(label)
                if source.endswith('.tags') and text == category_key:
                    continue
                if kind == 'byline' and text.strip(' .…') in {'et al', '等', 'unknown', 'n/a', '待核对', '佚名'}:
                    continue
                key = kind + ':' + hashlib.sha256(text.encode()).hexdigest()[:24]
                nodes.setdefault(key, {'id': key, 'kind': kind, 'label': label})
                relation = edges.setdefault((key, paper_id), {
                    'source': key, 'target': paper_id, 'fields': []})
                if source not in relation['fields']:
                    relation['fields'].append(source)
    return {'schema_version': 1, 'nodes': list(nodes.values()), 'edges': list(edges.values())}
