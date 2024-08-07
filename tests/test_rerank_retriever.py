import unittest
from unittest.mock import Mock, patch
from goldenverba.components.retriever.RerankRetriever import RerankRetriever

class TestRerankRetriever(unittest.TestCase):
    def setUp(self):
        self.retriever = RerankRetriever()

    @patch('goldenverba.components.retriever.RerankRetriever.es')
    @patch('goldenverba.components.retriever.RerankRetriever.rerank')
    def test_retrieve(self, mock_rerank, mock_es):
        # モックの設定
        mock_es_response = Mock()
        mock_es_response.body = {
            'hits': {
                'hits': [
                    {'_source': {'content': 'Test content 1'}},
                    {'_source': {'content': 'Test content 2'}}
                ]
            }
        }
        mock_es.search.return_value = mock_es_response

        mock_rerank.return_value = [
            {'content': 'Test content 2', 'score': 0.9},
            {'content': 'Test content 1', 'score': 0.7}
        ]

        # テストの実行
        result = self.retriever.retrieve("Test query")

        # アサーション
        self.assertEqual(len(result), 2)
        self.assertEqual(result[0], 'Test content 2')
        self.assertEqual(result[1], 'Test content 1')
        mock_es.search.assert_called_once()
        mock_rerank.assert_called_once()

    def test_init_with_custom_params(self):
        custom_retriever = RerankRetriever(index_name="custom_index", size=5, rerank_size=3)
        self.assertEqual(custom_retriever.index_name, "custom_index")
        self.assertEqual(custom_retriever.size, 5)
        self.assertEqual(custom_retriever.rerank_size, 3)

if __name__ == '__main__':
    unittest.main()