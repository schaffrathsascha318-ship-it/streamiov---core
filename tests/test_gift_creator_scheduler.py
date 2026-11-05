import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

from ai.runtime.gift_creator_scheduler import GiftCreatorScheduler, GiftCreatorScheduleError
from ai.runtime.task_queue import SpecialistTaskQueue


ROOT = Path(__file__).resolve().parents[1]


class GiftCreatorSchedulerTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        root = Path(self.temp.name)
        self.queue = SpecialistTaskQueue(root / "queue.sqlite3")
        self.scheduler = GiftCreatorScheduler(
            self.queue,
            root / "scheduler.sqlite3",
            config_path=ROOT / "ai/config/gift_creator_agent.json",
        )

    def tearDown(self):
        self.temp.cleanup()

    def test_weekly_batch_is_enqueued_once_and_uses_gifts_specialist(self):
        now = datetime(2026, 11, 6, 12, tzinfo=timezone.utc)
        first = self.scheduler.schedule_due(now)
        second = self.scheduler.schedule_due(now)
        self.assertEqual(len(first["scheduled"]), 1)
        self.assertEqual(second["scheduled"], [])
        tasks = self.queue.list_tasks()
        weekly = [task for task in tasks if task.task_id.startswith("gift-week-")]
        self.assertEqual(len(weekly), 3)
        self.assertTrue(all(task.specialist == "gifts" for task in weekly))
        self.assertTrue(all("Rose ist unveränderlich" in task.prompt for task in weekly))

    def test_christmas_collection_is_scheduled_sixty_days_before_event(self):
        now = datetime(2026, 10, 26, 8, tzinfo=timezone.utc)
        result = self.scheduler.schedule_due(now)
        self.assertIn(
            {"collection": "winter_christmas", "days_until": 60},
            result["seasonal_windows"],
        )
        self.assertTrue(any(task.task_id.startswith("gift-season-") for task in self.queue.list_tasks()))

    def test_seasonal_job_is_not_duplicated_on_repeated_scheduler_runs(self):
        now = datetime(2026, 11, 6, 12, tzinfo=timezone.utc)
        first = self.scheduler.schedule_due(now)
        count_after_first = len(self.queue.list_tasks())
        second = self.scheduler.schedule_due(now)
        self.assertGreaterEqual(len(first["scheduled"]), 1)
        self.assertEqual(second["scheduled"], [])
        self.assertEqual(len(self.queue.list_tasks()), count_after_first)

    def test_naive_datetime_is_rejected(self):
        with self.assertRaises(GiftCreatorScheduleError):
            self.scheduler.schedule_due(datetime(2026, 11, 6, 12))

    def test_auto_publish_configuration_is_rejected(self):
        config = Path(self.temp.name) / "unsafe.json"
        config.write_text(
            '{"agent_id":"streamiov-gift-creator","cadence":{"never_auto_publish":false,"concept_batch_size":3}}',
            encoding="utf-8",
        )
        with self.assertRaises(GiftCreatorScheduleError):
            GiftCreatorScheduler(self.queue, Path(self.temp.name) / "unsafe.sqlite3", config_path=config)


if __name__ == "__main__":
    unittest.main()
