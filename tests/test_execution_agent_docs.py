import pathlib
import unittest


class ReadmeExecutionAgentDocsTests(unittest.TestCase):
    def test_readme_mentions_execution_agent_compose_command(self) -> None:
        text = pathlib.Path("README.md").read_text(encoding="utf-8")
        self.assertIn("docker compose up -d execution-agent", text)
        self.assertIn("TRACKING_JSON_URL", text)

    def test_readme_mentions_gcp_region_and_telegram_setup(self) -> None:
        text = pathlib.Path("README.md").read_text(encoding="utf-8")
        self.assertIn("asia-east1", text)
        self.assertIn("TELEGRAM_BOT_TOKEN", text)
        self.assertIn("TELEGRAM_CHAT_ID", text)

    def test_env_example_includes_telegram_secrets(self) -> None:
        text = pathlib.Path("execution_agent/.env.example").read_text(encoding="utf-8")
        self.assertIn("TRACKING_JSON_URL=", text)
        self.assertIn("TELEGRAM_BOT_TOKEN=", text)
        self.assertIn("TELEGRAM_CHAT_ID=", text)
