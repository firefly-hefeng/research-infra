import unittest
from paperlib.graph import literature_graph


class GraphTests(unittest.TestCase):
    def test_catalog_fields_produce_traceable_deduplicated_relations(self):
        a, b = 'a' * 64, 'b' * 64
        papers = [{'id': a, 'notes': 'PRIVATE-NOTE', 'card': {
            'title': 'First', 'category': '声音', 'tags': ['Ａudio', 'Audio']},
            'insight': {'keywords': ['audio'], 'author_keywords': {'terms': ['AUDIO']}}},
            {'id': b, 'bibliography': {'title': 'Second', 'category': '声音',
             'tags': ['Audio'], 'fulltext_policy': 'restricted', 'path': 'PRIVATE-PATH'}},
            {'id': 'c' * 64, 'filename': 'PRIVATE-PENDING.pdf'}]
        graph = literature_graph(papers)
        nodes = {n['id']: n for n in graph['nodes']}
        self.assertEqual({k: sum(n['kind'] == k for n in nodes.values())
                          for k in ('paper', 'topic', 'direction')},
                         {'paper': 2, 'topic': 1, 'direction': 1})
        topic = next(n for n in nodes.values() if n['kind'] == 'topic')
        matches = {e['target']: e['fields'] for e in graph['edges'] if e['source'] == topic['id']}
        self.assertEqual(matches, {a: ['card.tags', 'insight.keywords', 'insight.author_keywords.terms'],
                                   b: ['bibliography.tags']})
        self.assertEqual(graph, literature_graph(reversed(papers)))
        self.assertNotIn('PRIVATE', str(graph))
        self.assertFalse(any(nodes[e['source']]['kind'] == 'paper' for e in graph['edges']))

    def test_empty_and_unclassified_papers(self):
        self.assertEqual(literature_graph([])['nodes'], [])
        graph = literature_graph([{'id': 'a' * 64, 'bibliography': {'title': 'Unclassified', 'tags': []}}])
        self.assertEqual([n['kind'] for n in graph['nodes']], ['paper'])
        self.assertEqual(graph['edges'], [])

    def test_revised_card_category_supersedes_old_archive_label(self):
        graph = literature_graph([{'id':'b' * 64, 'card':{'title':'One','category':'新方向'},
                                   'bibliography':{'title':'One','category':'原分类'}}])
        self.assertEqual([n['label'] for n in graph['nodes'] if n['kind']=='direction'], ['新方向'])
        self.assertEqual(graph['edges'][0]['fields'], ['card.category'])

    def test_inherited_category_is_not_counted_again_as_topic_and_byline_stays_verbatim(self):
        papers = [{'id':'a' * 64,'bibliography':{'title':'First','category':'评估','tags':['评估'],
                  'authors':['Smith, Ann', 'et al.']}},
                  {'id':'b' * 64,'card':{'title':'Second','category':'健康','authors':['Smith, Ann','Ann Smith']}}]
        graph = literature_graph(papers)
        self.assertFalse(any(n['kind'] == 'topic' for n in graph['nodes']))
        names = {n['label']:n['id'] for n in graph['nodes'] if n['kind'] == 'byline'}
        self.assertEqual(set(names), {'Smith, Ann','Ann Smith'})
        self.assertEqual(sum(e['source'] == names['Smith, Ann'] for e in graph['edges']), 2)
