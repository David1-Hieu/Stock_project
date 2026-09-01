"""Local EOD scheduler: Monday-Friday at 15:30 Asia/Ho_Chi_Minh.

The data layer upserts by actual ``trade_date`` returned by vnstock, therefore
weekends/holidays do not create duplicate trading sessions even if the scheduler
process runs.
"""
from __future__ import annotations

import logging

from monitoring.run_eod import run_once


def main() -> None:
    try:
        from apscheduler.schedulers.blocking import BlockingScheduler
        from apscheduler.triggers.cron import CronTrigger
    except ImportError as exc:
        raise SystemExit("Thiếu APScheduler. Chạy: pip install APScheduler>=3.10,<4") from exc

    logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(levelname)s | %(name)s | %(message)s")
    scheduler = BlockingScheduler(timezone="Asia/Ho_Chi_Minh")
    scheduler.add_job(
        run_once,
        CronTrigger(day_of_week="mon-fri", hour=15, minute=30, timezone="Asia/Ho_Chi_Minh"),
        id="stock_analyze_eod",
        max_instances=1,
        coalesce=True,
        replace_existing=True,
    )
    print("EOD scheduler đang chạy: Thứ 2-Thứ 6 lúc 15:30 (Asia/Ho_Chi_Minh). Ctrl+C để dừng.")
    scheduler.start()


if __name__ == "__main__":
    main()
