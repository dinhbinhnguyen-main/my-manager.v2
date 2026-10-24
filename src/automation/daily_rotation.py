"""Daily Account Rotation Automation (Kịch bản xoay vòng tài khoản theo thứ trong tuần).

Chia các tài khoản trong database (group_id = -1) thành 7 nhóm cố định tương ứng với 7 ngày trong tuần:
- Nhóm Thứ 2 (Monday, index 0)
- Nhóm Thứ 3 (Tuesday, index 1)
- Nhóm Thứ 4 (Wednesday, index 2)
- Nhóm Thứ 5 (Thursday, index 3)
- Nhóm Thứ 6 (Friday, index 4)
- Nhóm Thứ 7 (Saturday, index 5)
- Nhóm Chủ Nhật (Sunday, index 6)

Logic vận hành:
- Vào thứ X (hoặc chỉ định qua --day):
  - Nhóm tài khoản thuộc thứ X sẽ chạy action 'single_listing' (đăng bài marketplace/group đơn lẻ).
  - Tất cả các tài khoản thuộc 6 nhóm còn lại sẽ chạy action 'scroll_feed' (lướt news feed tương tác nuôi nick).
"""

import re
import json
import time
import logging
from datetime import datetime
from concurrent.futures import ThreadPoolExecutor
from typing import List, Dict, Any, Optional, Tuple
from rich.console import Console
from rich.table import Table
from rich.panel import Panel

from src.core.models import Account, AccountStatus, AutomationJob, JobStatus
from src.db.repository import AccountRepository, AutomationJobRepository

logger = logging.getLogger(__name__)
console = Console()

WEEKDAY_LABELS = {
    0: ("Thứ 2", "Monday"),
    1: ("Thứ 3", "Tuesday"),
    2: ("Thứ 4", "Wednesday"),
    3: ("Thứ 5", "Thursday"),
    4: ("Thứ 6", "Friday"),
    5: ("Thứ 7", "Saturday"),
    6: ("Chủ Nhật", "Sunday"),
}


def parse_target_weekday(target_input: Optional[Any] = None) -> int:
    """
    Parses user input into standard Python weekday integer (0 = Monday / Thứ 2 ... 6 = Sunday / CN).
    If target_input is None or empty, returns current local day of the week.
    """
    if target_input is None or str(target_input).strip() == "":
        return datetime.now().weekday()

    raw = str(target_input).strip().lower()
    raw_clean = re.sub(r'[\s_\-]', '', raw)

    mapping = {
        # Thứ 2 (Monday -> 0)
        "2": 0, "thu2": 0, "t2": 0, "mon": 0, "monday": 0,
        # Thứ 3 (Tuesday -> 1)
        "3": 1, "thu3": 1, "t3": 1, "tue": 1, "tuesday": 1,
        # Thứ 4 (Wednesday -> 2)
        "4": 2, "thu4": 2, "t4": 2, "wed": 2, "wednesday": 2,
        # Thứ 5 (Thursday -> 3)
        "5": 3, "thu5": 3, "t5": 3, "thu": 3, "thursday": 3,
        # Thứ 6 (Friday -> 4)
        "6": 4, "thu6": 4, "t6": 4, "fri": 4, "friday": 4,
        # Thứ 7 (Saturday -> 5)
        "7": 5, "thu7": 5, "t7": 5, "sat": 5, "saturday": 5,
        # Chủ Nhật (Sunday -> 6)
        "8": 6, "cn": 6, "chunhat": 6, "chu_nhat": 6, "sun": 6, "sunday": 6,
    }

    if raw_clean in mapping:
        return mapping[raw_clean]

    try:
        val = int(raw)
        if 0 <= val <= 6:
            return val
    except ValueError:
        pass

    logger.warning(f"Could not parse weekday '{target_input}'. Falling back to current local day.")
    return datetime.now().weekday()


def partition_accounts_by_weekday(
    group_id: int = 0,
    status_filter: Optional[str] = "live",
) -> Dict[int, List[Account]]:
    """
    Fetches accounts with the specified group_id and partitions them into 7 stable groups.
    The partition is deterministic: sorted by account DB ID (or UID), each account is placed
    into bucket (index % 7). This ensures each account stays permanently in its assigned day.
    """
    all_accs = AccountRepository.list_by_group(group_id=group_id, limit=10000)

    if status_filter and status_filter.lower() != "all":
        st = status_filter.lower()
        accs = [a for a in all_accs if (a.status.value if hasattr(a.status, "value") else str(a.status)).lower() == st]
    else:
        accs = all_accs

    # Sort deterministically by id (fallback to uid)
    accs.sort(key=lambda a: (a.id if a.id is not None else 0, a.uid))

    buckets: Dict[int, List[Account]] = {i: [] for i in range(7)}
    for idx, acc in enumerate(accs):
        weekday_idx = idx % 7
        buckets[weekday_idx].append(acc)

    return buckets


def get_daily_rotation_plan(
    group_id: int = 0,
    target_day: Optional[Any] = None,
    status_filter: Optional[str] = "live",
) -> Dict[str, Any]:
    """
    Calculates the execution plan for today (or the target day):
    - target_day_idx: weekday index (0..6)
    - listing_accounts: accounts scheduled for 'single_listing'
    - feed_accounts: accounts scheduled for 'scroll_feed'
    """
    day_idx = parse_target_weekday(target_day)
    buckets = partition_accounts_by_weekday(group_id=group_id, status_filter=status_filter)

    listing_accs = buckets.get(day_idx, [])
    feed_accs: List[Account] = []
    for d, accs in buckets.items():
        if d != day_idx:
            feed_accs.extend(accs)

    day_name_vi, day_name_en = WEEKDAY_LABELS.get(day_idx, ("Không xác định", "Unknown"))

    return {
        "group_id": group_id,
        "target_day_idx": day_idx,
        "target_day_name": f"{day_name_vi} ({day_name_en})",
        "day_vi": day_name_vi,
        "day_en": day_name_en,
        "total_accounts": sum(len(b) for b in buckets.values()),
        "listing_accounts": listing_accs,
        "feed_accounts": feed_accs,
        "buckets": buckets,
    }


def print_rotation_plan_table(plan: Dict[str, Any]):
    """Renders a beautiful Rich table summarizing the 7-day partition and today's execution plan."""
    day_idx = plan["target_day_idx"]
    day_name = plan["target_day_name"]
    buckets = plan["buckets"]
    total = plan["total_accounts"]
    group_id = plan.get("group_id", 0)

    table = Table(title=f"📅 Phân Bổ 7 Nhóm Tài Khoản Theo Thứ (Group: {group_id} | Hôm nay: {day_name})", show_lines=True)
    table.add_column("Thứ", justify="center", style="bold cyan")
    table.add_column("Tên Ngày", style="white")
    table.add_column("Số Lượng Nick", justify="right", style="green")
    table.add_column("Hành Động Hôm Nay", justify="center")
    table.add_column("Mẫu UIDs (Top 3)", style="dim")

    for i in range(7):
        vi, en = WEEKDAY_LABELS[i]
        count = len(buckets[i])
        sample_uids = ", ".join([a.uid for a in buckets[i][:3]])
        if len(buckets[i]) > 3:
            sample_uids += f" (+{len(buckets[i]) - 3})"

        if i == day_idx:
            day_cell = f"[bold green]▶ {vi}[/bold green]"
            action_cell = "[bold red]🔥 SINGLE_LISTING[/bold red]"
        else:
            day_cell = vi
            action_cell = "[cyan]🔄 SCROLL_FEED[/cyan]"

        table.add_row(day_cell, en, str(count), action_cell, sample_uids)

    console.print(table)

    summary_panel = Panel(
        f"[bold white]Tổng số tài khoản (group_id = {group_id}):[/bold white] [bold cyan]{total}[/bold cyan]\n"
        f"[bold red]✦ Chạy single_listing:[/bold red] [bold red]{len(plan['listing_accounts'])}[/bold red] nick ({day_name})\n"
        f"[bold cyan]✦ Chạy scroll_feed:[/bold cyan] [bold cyan]{len(plan['feed_accounts'])}[/bold cyan] nick (6 nhóm ngày còn lại)\n"
        f"[dim]Chiến lược xoay vòng: Mỗi nick đăng bài 1 ngày/tuần, 6 ngày còn lại lướt feed tương tác giữ trust & hạn chế checkpoint.[/dim]",
        title="🎯 Kế Hoạch Chạy Hôm Nay",
        style="bright_blue",
    )
    console.print(summary_panel)


def execute_daily_rotation(
    group_id: int = 0,
    target_day: Optional[Any] = None,
    status_filter: str = "live",
    concurrency: int = 1,
    single_listing_group_count: int = 3,
    scroll_feed_swipes: int = 20,
    dry_run: bool = False,
    only_action: Optional[str] = None,  # 'listing' or 'feed' or None (both)
):
    """
    Executes the daily rotation scenario directly:
    - Runs 'single_listing' for accounts assigned to target_day
    - Runs 'scroll_feed' for accounts assigned to the other 6 days
    - Concurrently runs accounts with dynamic proxy acquisition and auto-stop container.
    """
    from src.cli.run_cmd import _run_single_account

    plan = get_daily_rotation_plan(group_id=group_id, target_day=target_day, status_filter=status_filter)
    print_rotation_plan_table(plan)

    if dry_run:
        console.print("[yellow]🔍 [DRY RUN] Chế độ xem trước: Không thực thi action lên thiết bị/container.[/yellow]")
        return

    listing_accs = plan["listing_accounts"]
    feed_accs = plan["feed_accounts"]

    tasks: List[Tuple[str, str, Dict[str, Any]]] = []

    # 1. Prepare listing tasks
    if only_action in [None, "listing", "single_listing"]:
        for acc in listing_accs:
            params = {
                "group_count": single_listing_group_count,
                "transaction_type": acc.transaction_type or "rental",
                "use_ai": True,
                "use_v1_product": True,
            }
            tasks.append((acc.uid, "single_listing", params))

    # 2. Prepare scroll_feed tasks
    if only_action in [None, "feed", "scroll_feed"]:
        for acc in feed_accs:
            params = {
                "max_swipes": scroll_feed_swipes,
                "min_delay": 3.0,
                "max_delay": 8.0,
                "max_likes": 1,
            }
            tasks.append((acc.uid, "scroll_feed", params))

    console.print(
        f"\n[bold green]🚀 Bắt đầu thực thi {len(tasks)} tasks "
        f"({len(listing_accs)} single_listing + {len(feed_accs)} scroll_feed) "
        f"với Concurrency = {concurrency}...[/bold green]"
    )

    if concurrency > 1:
        with ThreadPoolExecutor(max_workers=concurrency) as executor:
            futures = [
                executor.submit(_run_single_account, uid, act, params, True)
                for (uid, act, params) in tasks
            ]
            for f in futures:
                try:
                    f.result()
                except Exception as e:
                    console.print(f"[bold red]Lỗi khi chạy task: {e}[/bold red]")
    else:
        for idx, (uid, act, params) in enumerate(tasks, 1):
            console.print(f"\n[bold cyan]━━━━━━━━━━━━━ [{idx}/{len(tasks)}] UID: {uid} | Action: {act.upper()} ━━━━━━━━━━━━━[/bold cyan]")
            _run_single_account(uid, act, params, auto_stop=True)

    console.print(f"\n[bold green]✅ Hoàn tất kịch bản xoay vòng cho tất cả {len(tasks)} tài khoản![/bold green]")
