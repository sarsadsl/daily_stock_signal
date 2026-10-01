from __future__ import annotations

from dataclasses import dataclass
import os


@dataclass(frozen=True)
class ExecutionAgentConfig:
    tracking_json_url: str
    state_db_path: str
    signal_date: str
    dry_run: bool

    @classmethod
    def from_env(cls) -> "ExecutionAgentConfig":
        return cls(
            tracking_json_url=os.environ["TRACKING_JSON_URL"],
            state_db_path=os.environ.get("STATE_DB_PATH", "./state/agent.db"),
            signal_date=os.environ["SIGNAL_DATE"],
            dry_run=os.environ.get("DRY_RUN", "0") == "1",
        )
