#!/usr/bin/env python3
"""
Standalone Runner Script for Daily Account Rotation.
Usage:
  python scripts/daily_rotation.py --dry-run
  python scripts/daily_rotation.py --day 2 --dry-run
  python scripts/daily_rotation.py --concurrency 2
"""

import sys
from pathlib import Path

# Add project root to sys.path
BASE_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE_DIR))

import typer
from src.core.logger import setup_logging
from src.db.database import init_db
from src.automation.daily_rotation import execute_daily_rotation

setup_logging()
init_db()

app = typer.Typer(help="Daily Account Rotation Automation Script")


@app.command()
def main(
    day: str = typer.Option(None, "--day", "-d", help="Target weekday (2, 3, 4, 5, 6, 7, cn). Default: today"),
    group_id: int = typer.Option(0, "--group-id", "-g", help="Account group_id in database (default: 0)"),
    status: str = typer.Option("live", "--status", "-s", help="Filter account status (live, idle, all. default: live)"),
    concurrency: int = typer.Option(1, "--concurrency", "-m", help="Concurrent workers (default: 1)"),
    group_count: int = typer.Option(3, "--group-count", "-c", help="Groups count for single_listing (default: 3)"),
    swipes: int = typer.Option(20, "--swipes", "-w", help="Max swipes for scroll_feed (default: 20)"),
    dry_run: bool = typer.Option(False, "--dry-run", help="Preview 7-group partition without executing"),
    only: str = typer.Option(None, "--only", help="Run only 'listing' or 'feed' accounts"),
):
    """Executes or previews daily rotation plan."""
    execute_daily_rotation(
        group_id=group_id,
        target_day=day,
        status_filter=status,
        concurrency=concurrency,
        single_listing_group_count=group_count,
        scroll_feed_swipes=swipes,
        dry_run=dry_run,
        only_action=only,
    )


if __name__ == "__main__":
    app()
