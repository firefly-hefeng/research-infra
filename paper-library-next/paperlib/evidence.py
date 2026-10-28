"""Source-addressed excerpts: model selects evidence; code supplies literal quotes."""
import copy
import re

SECTION = re.compile(r'^\s*(?:\d+(?:\.\d+)*[.\s]+)?(?:conclusions?|discussion|limitations?|results|experiments?|结论|局限|讨论)\b', re.I | re.M)


def source_context(content, limit=160000):
    pages = content.split('\f')
    if pages and not pages[-1].strip():
        pages.pop()
    blocks = {}
    for page, text in enumerate(pages, 1):
        snippets = []
        while text:
            end = min(800, len(text))
            if end < len(text):
                boundary = text.rfind(' ', 400, end)
                if boundary > 0:
                    end = boundary
            quote, text = text[:end].strip(), text[end:]
            if quote:
                snippets.append(quote)
        blocks[page] = [
            (f'p{page}-b{i}', {'page': page, 'quote': quote})
            for i, quote in enumerate(snippets, 1)
        ]
    # Retain the start plus substantive section pages before filling remaining space.
    section_pages = []
    for page, text in enumerate(pages, 1):
        if SECTION.search(text):
            section_pages.extend([page, page + 1])
    selected, used = {}, 0
    phases = [(range(1, min(12, len(pages)) + 1), int(limit * .60)),
              (dict.fromkeys(section_pages), int(limit * .90)),
              (range(1, len(pages) + 1), limit)]
    for page_order, budget in phases:
        for page in page_order:
            for source_id, source in blocks.get(page, []):
                if source_id in selected:
                    continue
                rendered = f'\n--- PDF PAGE {page} | SOURCE {source_id} ---\n{source["quote"]}\n'
                if used + len(rendered) <= budget:
                    selected[source_id] = (source, rendered)
                    used += len(rendered)
    # Display excerpts in PDF order, keeping original physical page numbers.
    ordered = [(ident, selected[ident]) for page in blocks.values() for ident, _ in page if ident in selected]
    sources = {ident: value[0] for ident, value in ordered}
    included = sorted({source['page'] for source in sources.values()})
    partial = [page for page, entries in blocks.items()
               if any(ident in sources for ident, _ in entries) and any(ident not in sources for ident, _ in entries)]
    truncated = len(sources) < sum(len(entries) for entries in blocks.values())
    coverage = {'total_pages': len(pages), 'included_pages': included, 'partial_pages': partial,
                'omitted_pages': [p for p in blocks if p not in included], 'text_truncated': truncated}
    return ''.join(value[1] for _, value in ordered), sources, coverage


def resolve_evidence(card, sources):
    """Only known, actually supplied source IDs can replace page/quote fields."""
    result = copy.deepcopy(card)
    if not isinstance(result, dict):
        raise ValueError('卡片必须是 JSON 对象')
    evidence = result.get('evidence', [])
    if not isinstance(evidence, list):
        raise ValueError('evidence 必须是列表')
    for index, entry in enumerate(evidence):
        if not isinstance(entry, dict):
            raise ValueError(f'evidence[{index}] 必须是对象')
        if 'source_id' in entry:
            ident = entry['source_id']
            if not isinstance(ident, str) or ident not in sources:
                raise ValueError(f'evidence[{index}] 的 source_id 不在已提供的原文片段中')
            entry.update(sources[ident])
            entry.pop('source_id')
    return result
