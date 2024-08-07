import unittest
from unittest.mock import Mock, patch
from goldenverba.components.retriever.SimpleRetriever import SimpleRetriever

class TestSimpleRetriever(unittest.TestCase):
    def setUp(self):
        self.retriever = SimpleRetriever()

    @patch('goldenverba.components.retriever.SimpleRetriever.es')
    def test_retrieve(self, mock_es):
        # ���b�N�̐ݒ�
        mock_response = Mock()
        mock_response.body = {
            'hits': {
                'hits': [
                    {'_source': {'content': 'Test content 1'}},
                    {'_source': {'content': 'Test content 2'}}
                ]
            }
        }
        mock_es.search.return_value = mock_response

        # �e�X�g�̎��s
        result = self.retriever.retrieve("Test query")

        # �A�T�[�V����
        self.assertEqual(len(result), 2)
        self.assertEqual(result[0], 'Test content 1')
        self.assertEqual(result[1], 'Test content 2')
        mock_es.search.assert_called_once()

    def test_init_with_custom_params(self):
        custom_retriever = SimpleRetriever(index_name="custom_index", size=5)
        self.assertEqual(custom_retriever.index_name, "custom_index")
        self.assertEqual(custom_retriever.size, 5)

if __name__ == '__main__':
    unittest.main()