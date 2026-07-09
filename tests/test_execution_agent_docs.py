import pathlib
import unittest


class ReadmeExecutionAgentDocsTests(unittest.TestCase):
    def test_readme_mentions_execution_agent_compose_command(self) -> None:
        text = pathlib.Path("README.md").read_text(encoding="utf-8")
        self.assertIn("docker compose up -d execution-agent", text)
        self.assertIn("TRACKING_JSON_URL", text)
