import tempfile
import unittest
import os
from pathlib import Path

from execution_agent.run_lock import ExecutionAgentAlreadyRunningError, execution_agent_lock


class ExecutionAgentRunLockTests(unittest.TestCase):
    def test_overlapping_live_run_is_rejected_and_lock_is_reusable(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = str(Path(tmpdir) / "state" / "agent.db")

            with execution_agent_lock(db_path):
                with self.assertRaises(ExecutionAgentAlreadyRunningError):
                    with execution_agent_lock(db_path):
                        self.fail("overlapping run must not acquire the lock")

            with execution_agent_lock(db_path):
                self.assertTrue(Path(f"{db_path}.lock").exists())

            self.assertTrue(Path(f"{db_path}.lock").exists())

    def test_active_lock_is_not_reclaimed_because_its_file_is_old(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = str(Path(tmpdir) / "agent.db")
            lock_path = Path(f"{db_path}.lock")

            with execution_agent_lock(db_path):
                os.utime(lock_path, (1, 1))
                with self.assertRaises(ExecutionAgentAlreadyRunningError):
                    with execution_agent_lock(db_path):
                        self.fail("an active OS lock must not be reclaimed by age")
