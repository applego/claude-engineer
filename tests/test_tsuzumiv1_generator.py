import unittest
from unittest.mock import Mock, patch
from goldenverba.components.generation.TsuzumiV1Generator import TsuzumiV1Generator


class TestTsuzumiV1Generator(unittest.TestCase):
    def setUp(self):
        self.generator = TsuzumiV1Generator()

    @patch("goldenverba.components.generation.TsuzumiV1Generator.requests")
    def test_generate(self, mock_requests):
        # ���b�N�̐ݒ�
        mock_response = Mock()
        mock_response.json.return_value = {"choices": [{"text": "Generated text from TsuzumiV1"}]}
        mock_requests.post.return_value = mock_response

        # �e�X�g�̎��s
        result = self.generator.generate("Test prompt")

        # �A�T�[�V����
        self.assertEqual(result, "Generated text from TsuzumiV1")
        mock_requests.post.assert_called_once()

    def test_init_with_custom_params(self):
        custom_generator = TsuzumiV1Generator(model="custom_model", max_tokens=100, temperature=0.8)
        self.assertEqual(custom_generator.model, "custom_model")
        self.assertEqual(custom_generator.max_tokens, 100)
        self.assertEqual(custom_generator.temperature, 0.8)

    @patch("goldenverba.components.generation.TsuzumiV1Generator.requests")
    def test_generate_with_context(self, mock_requests):
        # ���b�N�̐ݒ�
        mock_response = Mock()
        mock_response.json.return_value = {"choices": [{"text": "Generated text with context"}]}
        mock_requests.post.return_value = mock_response

        # �e�X�g�̎��s
        context = ["Context 1", "Context 2"]
        result = self.generator.generate("Test prompt", context=context)

        # �A�T�[�V����
        self.assertEqual(result, "Generated text with context")
        mock_requests.post.assert_called_once()
        # �R���e�L�X�g���K�؂Ɏg�p���ꂽ���Ƃ��m�F���邽�߂̂��ڍׂȃA�T�[�V�������K�v��������܂���


if __name__ == "__main__":
    unittest.main()
