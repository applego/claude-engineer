import unittest
from unittest.mock import Mock, patch
from goldenverba.components.retriever.FiltRetriever import FiltRetriever

class TestFiltRetriever(unittest.TestCase):
    def setUp(self):
        self.retriever = FiltRetriever()

    @patch('goldenverba.components.retriever.FiltRetriever.es')
    @patch('goldenverba.components.retriever.FiltRetriever.filter_results')
    def test_retrieve(self, mock_filter, mock_es):
        # モックの設定
        mock_es_response = Mock()
        mock_es_response.body = {
            'hits': {
                'hits': [
                    {'_source': {'content': 'Test content 1', 'metadata': {'type': 'A'}}},
                    {'_source': {'content': 'Test content 2', 'metadata': {'type': 'B'}}},
                    {'_source': {'content': 'Test content 3', 'metadata': {'type': 'A'}}}
                ]
            }
        }
        mock_es.search.return_value = mock_es_response

        mock_filter.return_value = [
            {'content': 'Test content 1', 'metadata': {'type': 'A'}},
            {'content': 'Test content 3', 'metadata': {'type': 'A'}}
        ]

        # テストの実行
        result = self.retriever.retrieve("Test query")

        # アサーション
        self.assertEqual(len(result), 2)
        self.assertEqual(result[0]['content'], 'Test content 1')
        self.assertEqual(result[1]['content'], 'Test content 3')
        mock_es.search.assert_called_once()
        mock_filter.assert_called_once()

    def test_init_with_custom_params(self):
        custom_retriever = FiltRetriever(index_name="custom_index", size=5, filter_criteria={'type': 'A'})
        self.assertEqual(custom_retriever.index_name, "custom_index")
        self.assertEqual(custom_retriever.size, 5)
        self.assertEqual(custom_retriever.filter_criteria, {'type': 'A'})

    def test_filter_results(self):
        results = [
            {'content': 'Test content 1', 'metadata': {'type': 'A'}},
            {'content': 'Test content 2', 'metadata': {'type': 'B'}},
            {'content': 'Test content 3', 'metadata': {'type': 'A'}}
        ]
        filtered = self.retriever.filter_results(results, {'type': 'A'})
        self.assertEqual(len(filtered), 2)
        self.assertEqual(filtered[0]['content'], 'Test content 1')
        self.assertEqual(filtered[1]['content'], 'Test content 3')

if __name__ == '__main__':
    unittest.main()