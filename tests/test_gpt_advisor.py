import io
import json
import unittest

from scripts.gpt_advisor import response_text, validate_report


class GptAdvisorTest(unittest.TestCase):
    def test_report_is_strict_and_streamed(self) -> None:
        report = {
            "schema_version": 1,
            "status": "warning",
            "summary": "Проверка",
            "anomalies": ["Низкий win rate"],
            "recommended_test": "Walk-forward",
        }
        event = {"type": "response.output_text.delta", "delta": json.dumps(report)}
        stream = io.BytesIO(("data: " + json.dumps(event) + "\n\ndata: [DONE]\n").encode())

        self.assertEqual(validate_report(json.loads(response_text(stream))), report)
        with self.assertRaises(ValueError):
            validate_report({**report, "allow_entry": True})


if __name__ == "__main__":
    unittest.main()
