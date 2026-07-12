import pathlib
import unittest


class ReadmeExecutionAgentDocsTests(unittest.TestCase):
    def test_readme_mentions_one_shot_compose_command(self) -> None:
        text = pathlib.Path("README.md").read_text(encoding="utf-8")
        self.assertIn("docker compose run --rm execution-agent", text)
        self.assertIn("TRACKING_JSON_URL", text)
        self.assertNotIn("docker compose up -d execution-agent", text)

    def test_readme_mentions_gcp_region_and_telegram_setup(self) -> None:
        text = pathlib.Path("README.md").read_text(encoding="utf-8")
        self.assertIn("asia-east1", text)
        self.assertIn("TELEGRAM_BOT_TOKEN", text)
        self.assertIn("TELEGRAM_CHAT_ID", text)
        self.assertIn("data/*.csv", text)
        self.assertIn("next-trading-date", text)

    def test_env_example_includes_telegram_secrets(self) -> None:
        text = pathlib.Path("execution_agent/.env.example").read_text(encoding="utf-8")
        self.assertIn("TRACKING_JSON_URL=", text)
        self.assertIn("TELEGRAM_BOT_TOKEN=", text)
        self.assertIn("TELEGRAM_CHAT_ID=", text)

    def test_env_example_documents_sandbox_broker_safety(self) -> None:
        text = pathlib.Path("execution_agent/.env.example").read_text(encoding="utf-8")
        self.assertIn("BROKER_MODE=noop", text)
        self.assertIn("SANDBOX_ONLY=1", text)
        self.assertIn("SHIOAJI_API_KEY=", text)
        self.assertIn("SHIOAJI_SECRET_KEY=", text)

    def test_compose_mounts_data_directory_for_trading_date_lookup(self) -> None:
        text = pathlib.Path("execution_agent/docker-compose.yml").read_text(encoding="utf-8")
        self.assertIn("../data:/app/data:ro", text)
        self.assertNotIn("restart: unless-stopped", text)

    def test_docker_installs_execution_agent_shioaji_dependency(self) -> None:
        dockerfile = pathlib.Path("execution_agent/Dockerfile").read_text(encoding="utf-8")
        requirements = pathlib.Path("execution_agent/requirements.txt").read_text(encoding="utf-8")

        self.assertIn("execution_agent/requirements.txt", dockerfile)
        self.assertIn("shioaji==1.5.4", requirements)

    def test_github_scans_full_history_for_secrets(self) -> None:
        workflow = pathlib.Path(".github/workflows/secret-scan.yml").read_text(encoding="utf-8")

        self.assertIn("fetch-depth: 0", workflow)
        self.assertIn(
            "gitleaks/gitleaks-action@dcedce43c6f43de0b836d1fe38946645c9c638dc",
            workflow,
        )
