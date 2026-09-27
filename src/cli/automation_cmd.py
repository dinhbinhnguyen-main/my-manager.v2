"""CLI controller for Automation Scenario Jobs and Live Monitoring."""

import json
import time
import typer
from typing import Optional, List
from rich.console import Console
from rich.table import Table
from rich.live import Live
from rich.panel import Panel

from src.db.repository import AutomationJobRepository, AccountRepository, ProxyRepository, RedroidRepository
from src.core.models import AutomationJob, JobStatus
from src.automation.job_runner import JobRunner
from src.services.redis_tracker import RedisTracker

automation_app = typer.Typer(help="Manage Facebook Automation Jobs & Scenarios.")
console = Console()


@automation_app.command("create-batch")
def create_batch(
    tag: str = typer.Option("default", "--tag", "-t", help="Group tag for scenario (e.g. list_uid_01, list_uid_02)"),
    uids: Optional[str] = typer.Option(None, "--uids", "-u", help="Comma-separated account UIDs"),
    group_id: Optional[int] = typer.Option(None, "--group-id", "-g", help="Account group ID to fetch UIDs from"),
    actions_json: str = typer.Option(..., "--actions", "-a", help="JSON string representing list of actions in scenario"),
    name: str = typer.Option("Scenario Job", "--name", "-n", help="Name of scenario"),
):
    """Creates batch automation jobs for accounts under a scenario group tag."""
    # Validate actions_json
    try:
        actions_list = json.loads(actions_json)
        if not isinstance(actions_list, list):
            console.print("[red]Error: --actions must be a valid JSON list of action objects.[/red]")
            return
    except Exception as e:
        console.print(f"[red]Invalid JSON in --actions: {e}[/red]")
        return

    target_uids = []
    if uids:
        target_uids = [u.strip() for u in uids.split(",") if u.strip()]
    elif group_id is not None:
        accs = AccountRepository.list_by_group(group_id)
        target_uids = [acc.uid for acc in accs]
    else:
        accs = AccountRepository.list_all()
        target_uids = [acc.uid for acc in accs]

    if not target_uids:
        console.print("[yellow]No accounts found matching criteria.[/yellow]")
        return

    created_count = 0
    for uid in target_uids:
        job = AutomationJob(
            name=f"{name} ({uid})",
            group_tag=tag,
            account_uid=uid,
            actions_json=json.dumps(actions_list),
            status=JobStatus.PENDING,
        )
        AutomationJobRepository.create(job)
        created_count += 1

    console.print(
        f"[bold green]Successfully created {created_count} automation jobs under scenario tag '{tag}'![/bold green]"
    )


@automation_app.command("list")
def list_jobs(
    tag: Optional[str] = typer.Option(None, "--tag", "-t", help="Filter jobs by group tag (e.g. list_uid_01)"),
    status: Optional[str] = typer.Option(None, "--status", "-s", help="Filter by status (pending, running, finished, failed)"),
):
    """Lists automation jobs in database."""
    jobs = AutomationJobRepository.list_jobs(group_tag=tag, status=status)
    if not jobs:
        console.print("[yellow]No automation jobs found.[/yellow]")
        return

    table = Table(title=f"Automation Jobs (Tag: {tag or 'All'}, Status: {status or 'All'})")
    table.add_column("ID", style="cyan", justify="right")
    table.add_column("Tag", style="magenta")
    table.add_column("Account UID", style="green")
    table.add_column("Status", style="bold")
    table.add_column("Current Action", style="blue")
    table.add_column("Container", style="dim")
    table.add_column("Result Message", style="white")

    status_colors = {
        "pending": "yellow",
        "running": "bold blue",
        "finished": "bold green",
        "failed": "bold red",
    }

    for j in jobs:
        st_val = j.status.value if hasattr(j.status, 'value') else str(j.status)
        st_color = status_colors.get(st_val, "white")
        table.add_row(
            str(j.id),
            j.group_tag,
            j.account_uid,
            f"[{st_color}]{st_val}[/{st_color}]",
            j.current_action or "-",
            j.container_id or "-",
            j.result_message or "-",
        )

    console.print(table)


@automation_app.command("run-batch")
def run_batch(
    tag: Optional[str] = typer.Option(None, "--tag", "-t", help="Scenario tag to run (e.g. list_uid_01)"),
    threads: int = typer.Option(4, "--threads", "-m", help="Max concurrent threads (will be throttled to min(proxies, threads))"),
):
    """Runs pending automation jobs in parallel, automatically resource-throttled by min(proxies, threads)."""
    runner = JobRunner(threads=threads)
    runner.run_batch(group_tag=tag)


@automation_app.command("monitor")
def monitor_live():
    """Live terminal monitoring dashboard powered by Redis / SQLite status updates."""
    progress_cmd(watch=True)


@automation_app.command("progress")
def progress_cmd(
    tag: Optional[str] = typer.Option(None, "--tag", "-t", help="Filter by group tag (e.g. list_uid_01)"),
    watch: bool = typer.Option(False, "--watch", "-w", help="Continuous live watch mode (auto-refreshes every 2s)"),
    show_system: bool = typer.Option(False, "--system", "-sys", help="Include real-time Redroid containers on Docker and Proxy status tables"),
):
    """Tracking progress dashboard showing completion percentages, active containers, proxies, and live logs."""
    tracker = RedisTracker()

    def build_dashboard():
        from rich.layout import Layout
        from rich.progress import Progress, SpinnerColumn, BarColumn, TextColumn
        from src.redroid.manager import RedroidManager

        jobs = AutomationJobRepository.list_jobs(group_tag=tag)
        total_count = len(jobs)

        pending_jobs = [j for j in jobs if (j.status.value if hasattr(j.status, 'value') else j.status) == "pending"]
        running_jobs = [j for j in jobs if (j.status.value if hasattr(j.status, 'value') else j.status) == "running"]
        finished_jobs = [j for j in jobs if (j.status.value if hasattr(j.status, 'value') else j.status) == "finished"]
        failed_jobs = [j for j in jobs if (j.status.value if hasattr(j.status, 'value') else j.status) == "failed"]

        finished_cnt = len(finished_jobs)
        failed_cnt = len(failed_jobs)
        running_cnt = len(running_jobs)
        pending_cnt = len(pending_jobs)
        done_cnt = finished_cnt + failed_cnt

        percent = (done_cnt / total_count * 100) if total_count > 0 else 0.0

        # Summary Header Panel
        summary_text = (
            f"[bold white]Total Jobs:[/bold white] {total_count}  |  "
            f"[bold yellow]Pending:[/bold yellow] {pending_cnt}  |  "
            f"[bold blue]Running:[/bold blue] {running_cnt}  |  "
            f"[bold green]Finished:[/bold green] {finished_cnt}  |  "
            f"[bold red]Failed:[/bold red] {failed_cnt}  |  "
            f"[bold cyan]Progress:[/bold cyan] {percent:.1f}%"
        )
        summary_panel = Panel(summary_text, title=f"📊 Automation Progress Overview (Tag: {tag or 'All'})", style="bright_blue")

        # Table of Jobs
        table = Table(title="⚡ Execution Status & Step Details", expand=True)
        table.add_column("ID", justify="right", style="cyan", width=5)
        table.add_column("Tag", style="magenta", width=12)
        table.add_column("Account UID", style="green", width=16)
        table.add_column("Status", style="bold", width=10)
        table.add_column("Step Progress", style="bright_yellow", width=15)
        table.add_column("Current Action", style="blue", width=18)
        table.add_column("Container ID", style="dim", width=14)
        table.add_column("Live Output / Result Message", style="white")

        status_colors = {
            "pending": "yellow",
            "running": "bold blue",
            "finished": "bold green",
            "failed": "bold red",
        }

        # Check Redis active state first for live updates
        redis_active = {item.get("job_id"): item for item in tracker.get_all_active_jobs()}

        for j in jobs:
            st_val = j.status.value if hasattr(j.status, 'value') else str(j.status)

            # Overlay Redis data if available
            r_data = redis_active.get(str(j.id))
            if r_data:
                st_val = r_data.get("status", st_val)
                step_str = f"Step {r_data.get('current_step', 0)}/{r_data.get('total_steps', 1)}"
                cur_act = r_data.get("current_action", j.current_action or "-")
                c_id = r_data.get("container_id", j.container_id or "-")
                msg = r_data.get("message", j.result_message or "-")
            else:
                actions_cnt = len(json.loads(j.actions_json)) if j.actions_json else 1
                step_str = f"Step {j.current_step_index + 1}/{actions_cnt}" if st_val == "running" else f"{j.current_step_index}/{actions_cnt}"
                cur_act = j.current_action or "-"
                c_id = j.container_id or "-"
                msg = j.result_message or "-"

            st_color = status_colors.get(st_val, "white")
            table.add_row(
                str(j.id),
                j.group_tag,
                j.account_uid,
                f"[{st_color}]{st_val}[/{st_color}]",
                step_str,
                cur_act,
                c_id[:12] if c_id != "-" else "-",
                msg,
            )

        from rich.console import Group
        components = [summary_panel, table]

        if show_system:
            # 1. Redroid Containers Real-Time Status Table
            redroid_mgr = RedroidManager()
            instances = RedroidRepository.list_all()

            c_table = Table(title="🐳 Real-Time Redroid Containers on Docker", expand=True)
            c_table.add_column("Container Name", style="magenta")
            c_table.add_column("ADB Port", style="yellow", justify="right")
            c_table.add_column("Bound FB UID", style="green")
            c_table.add_column("Docker Live Status", style="bold")

            for inst in instances:
                live_st = redroid_mgr.get_live_docker_status(inst.container_name)
                st_str = "[bold green]● running[/bold green]" if live_st == "running" else ("[bold yellow]■ stopped[/bold yellow]" if live_st == "stopped" else "[bold red]✖ not found[/bold red]")
                c_table.add_row(
                    inst.container_name,
                    str(inst.adb_port),
                    inst.account_uid or "-",
                    st_str,
                )

            # 2. Proxy Status Overview Table
            all_proxies = ProxyRepository.list_all()
            avail_p = [p for p in all_proxies if (p.status.value if hasattr(p.status, 'value') else str(p.status)) == "available"]
            work_p = [p for p in all_proxies if (p.status.value if hasattr(p.status, 'value') else str(p.status)) == "working"]
            unavail_p = [p for p in all_proxies if (p.status.value if hasattr(p.status, 'value') else str(p.status)) == "unavailable"]

            p_summary = (
                f"[bold white]Total Registered Proxies:[/bold white] {len(all_proxies)}  |  "
                f"[bold green]Available (Rảnh):[/bold green] {len(avail_p)}  |  "
                f"[bold blue]Working (Bận):[/bold blue] {len(work_p)}  |  "
                f"[bold red]Unavailable (Lỗi):[/bold red] {len(unavail_p)}"
            )
            proxy_panel = Panel(p_summary, title="🌐 Proxy Pool Real-Time Status", style="bright_magenta")

            p_table = Table(title="🌐 Active Proxy Pool Allocation Details", expand=True)
            p_table.add_column("ID", justify="right", style="cyan", width=5)
            p_table.add_column("Proxy Name / URL", style="white")
            p_table.add_column("Status", style="bold")
            p_table.add_column("Current Rotated IP", style="yellow")
            p_table.add_column("Assigned Account UID", style="green")

            for p in all_proxies:
                p_st = p.status.value if hasattr(p.status, 'value') else str(p.status)
                if p_st == "available":
                    p_st_str = "[bold green]available[/bold green]"
                elif p_st == "working":
                    p_st_str = "[bold blue]working[/bold blue]"
                else:
                    p_st_str = "[bold red]unavailable[/bold red]"

                p_table.add_row(
                    str(p.id),
                    p.name or p.url[:40],
                    p_st_str,
                    p.current_proxy_http or "-",
                    p.assigned_account_uid or "-",
                )

            components.extend([c_table, proxy_panel, p_table])

        return Group(*components)

    if watch:
        console.print("[bold cyan]Starting Live Progress Monitor (Press Ctrl+C to exit)...[/bold cyan]")
        try:
            with Live(build_dashboard(), refresh_per_second=2) as live:
                while True:
                    time.sleep(1.0)
                    live.update(build_dashboard())
        except KeyboardInterrupt:
            console.print("\n[yellow]Monitor stopped.[/yellow]")
    else:
        console.print(build_dashboard())


@automation_app.command("delete")
def delete_jobs(
    target: Optional[str] = typer.Argument(None, help="Job ID, Tag, or Account UID to delete"),
    tag: Optional[str] = typer.Option(None, "--tag", "-t", help="Delete all jobs matching this group tag"),
    status: Optional[str] = typer.Option(None, "--status", "-s", help="Delete jobs with status (pending, running, finished, failed)"),
    clear_completed: bool = typer.Option(False, "--clear", "-c", help="Clear all completed (finished / failed) jobs"),
    delete_all: bool = typer.Option(False, "--all", help="Clear all automation jobs from database"),
):
    """Delete automation job(s) by ID, group tag, or clear completed jobs."""
    if delete_all:
        deleted = AutomationJobRepository.delete()
        console.print(f"[bold red]Cleared all {deleted} automation jobs from database.[/bold red]")
        return

    if clear_completed:
        d1 = AutomationJobRepository.delete(status="finished")
        d2 = AutomationJobRepository.delete(status="failed")
        console.print(f"[bold green]Cleared {d1 + d2} completed jobs ({d1} finished, {d2} failed).[/bold green]")
        return

    if not target and not tag and not status:
        console.print("[bold red]Please specify a Job ID/Tag, pass --tag, --status, --clear, or --all.[/bold red]")
        return


@automation_app.command("reset")
def reset_jobs(
    target: Optional[str] = typer.Argument(None, help="Job ID, Tag, Account UID, or 'all' to reset all jobs"),
    tag: Optional[str] = typer.Option(None, "--tag", "-t", help="Reset all jobs matching this group tag"),
    status: Optional[str] = typer.Option(None, "--status", "-s", help="Filter by current status to reset (e.g. failed, finished)"),
    reset_failed: bool = typer.Option(False, "--failed", "-f", help="Reset all failed jobs back to pending"),
    reset_all: bool = typer.Option(False, "--all", help="Reset all jobs in database back to pending"),
):
    """Reset / Refresh automation job(s) back to 'pending' status regardless of current status."""
    is_all = reset_all or (target and str(target).lower() == "all")

    if is_all:
        count = AutomationJobRepository.reset()
        console.print(f"[bold green]Successfully reset ALL {count} jobs in database back to 'pending'![/bold green]")
        return

    if reset_failed:
        count = AutomationJobRepository.reset(group_tag=tag, status_filter="failed")
        console.print(f"[bold green]Successfully reset {count} failed jobs back to 'pending'![/bold green]")
        return

    selected_tag = tag or target
    if not selected_tag and not status:
        console.print("[bold red]Please specify a Tag/Job ID/UID, 'all', or pass --tag, --status, --failed, --all.[/bold red]")
        return

    if tag:
        count = AutomationJobRepository.reset(group_tag=tag, status_filter=status)
        console.print(f"[bold green]Successfully reset {count} job(s) under tag '{tag}' back to 'pending'![/bold green]")
    else:
        count = AutomationJobRepository.reset(target=target, status_filter=status)
        console.print(f"[bold green]Successfully reset {count} job(s) for target '{target}' back to 'pending'![/bold green]")


@automation_app.command("refresh")
def refresh_jobs(
    target: Optional[str] = typer.Argument(None, help="Job ID, Tag, Account UID, or 'all' to refresh"),
    tag: Optional[str] = typer.Option(None, "--tag", "-t", help="Refresh all jobs matching this group tag"),
    status: Optional[str] = typer.Option(None, "--status", "-s", help="Filter by current status to refresh"),
    reset_failed: bool = typer.Option(False, "--failed", "-f", help="Refresh all failed jobs back to pending"),
    reset_all: bool = typer.Option(False, "--all", help="Refresh all jobs in database back to pending"),
):
    """Alias for reset: Refresh automation job(s) back to 'pending' status regardless of current status."""
    reset_jobs(target=target, tag=tag, status=status, reset_failed=reset_failed, reset_all=reset_all)

ACTION_REGISTRY = {
    "login": {
        "name": "login",
        "aliases": ["fb_login"],
        "summary": "Tự động đăng nhập tài khoản Facebook & vượt 2FA TOTP",
        "description": "Tự động mở ứng dụng Facebook, nhập UID/Password và tự động lấy mã OTP từ 2FA secret key lưu trong DB để đăng nhập và giữ phiên.",
        "params": [
            {"name": "None", "type": "N/A", "required": False, "default": "N/A", "desc": "Sử dụng dữ liệu UID, Password, 2FA lưu trực tiếp trong DB Account."}
        ],
        "single_cli": 'python main-cli.py run action --action login --uids "61599900011122"',
        "script_json": '{"action": "login"}',
    },
    "scroll_feed": {
        "name": "scroll_feed",
        "aliases": ["warmup", "scroll", "fb_scroll_feed"],
        "summary": "Nuôi nick: Lướt Newfeed mô phỏng người thật, đọc bài viết, thả tim & xem bình luận",
        "description": "Tự động mở Facebook Feed, cuộn trang ngẫu nhiên (lên/xuống), tự động bấm 'Xem thêm', thả tim/like bài viết, mở xem bình luận ngẫu nhiên để tăng độ trust tuyệt đối cho tài khoản.",
        "params": [
            {"name": "max_swipes", "type": "int", "required": False, "default": "20", "desc": "Tổng số lần vuốt cuộn Newfeed"},
            {"name": "min_delay", "type": "float", "required": False, "default": "3.0", "desc": "Thời gian dừng đọc bài viết tối thiểu (giây)"},
            {"name": "max_delay", "type": "float", "required": False, "default": "8.0", "desc": "Thời gian dừng đọc bài viết tối đa (giây)"},
            {"name": "max_likes", "type": "int", "required": False, "default": "3", "desc": "Số lượng thả tim/like ngẫu nhiên tối đa"}
        ],
        "single_cli": 'python main-cli.py run action --action scroll_feed --uids "61599900011122"',
        "script_json": '{"action": "scroll_feed", "params": {"max_swipes": 30, "min_delay": 3.0, "max_delay": 8.0, "max_likes": 3}}',
    },
    "marketplace": {
        "name": "marketplace",
        "aliases": ["marketplace_post", "fb_marketplace"],
        "summary": "Đăng bài niêm yết BĐS lên Marketplace + AI Gemini",
        "description": "Tự động lấy dữ liệu BĐS mới nhất từ my-manager.v1 DB, dùng AI Gemini 3.5 viết lại Tiêu đề/Nội dung chuẩn SEO Meta chống spam, đẩy ảnh vào Redroid gallery và niêm yết lên Marketplace.",
        "params": [
            {"name": "transaction_type", "type": "str", "required": False, "default": '"sale"', "desc": "Loại giao dịch: 'sale' (Bán) hoặc 'rent' (Cho thuê)"},
            {"name": "use_ai", "type": "bool", "required": False, "default": "true", "desc": "Tự động gọi AI Gemini viết lại mô tả BĐS chống trùng lặp"}
        ],
        "single_cli": 'python main-cli.py run action --action marketplace --uids "61599900011122"',
        "script_json": '{"action": "marketplace", "params": {"transaction_type": "sale", "use_ai": true}}',
    },
    "join_group": {
        "name": "join_group",
        "aliases": ["fb_join_group"],
        "summary": "Tham gia Nhóm Facebook qua Deeplink",
        "description": "Truy cập trực tiếp Nhóm mục tiêu qua URL Deeplink fb://group/<group_id> và tự động bấm nút Tham gia nhóm (Join).",
        "params": [
            {"name": "group_id", "type": "str", "required": True, "default": "N/A", "desc": "ID của Nhóm Facebook (Ví dụ: '123456789')"}
        ],
        "single_cli": 'python main-cli.py run action --action join_group --uids "61599900011122"',
        "script_json": '{"action": "join_group", "params": {"group_id": "123456789"}}',
    },
    "post_group": {
        "name": "post_group",
        "aliases": ["fb_post_group"],
        "summary": "Đăng bài viết kèm hình ảnh vào Nhóm Facebook",
        "description": "Truy cập Nhóm Facebook chỉ định qua Deeplink, viết văn bản bài viết và tải ảnh từ máy tính lên Nhóm.",
        "params": [
            {"name": "group_id", "type": "str", "required": True, "default": "N/A", "desc": "ID của Nhóm Facebook (Ví dụ: '123456789')"},
            {"name": "content", "type": "str", "required": False, "default": '"Bài viết chia sẻ BĐS"', "desc": "Nội dung văn bản bài viết"},
            {"name": "image_paths", "type": "list[str]", "required": False, "default": "[]", "desc": "Danh sách đường dẫn ảnh trên PC host để upload"}
        ],
        "single_cli": 'python main-cli.py run action --action post_group --uids "61599900011122"',
        "script_json": '{"action": "post_group", "params": {"group_id": "123456789", "content": "Bán nhà chính chủ."}}',
    },
    "list_group_share": {
        "name": "list_group_share",
        "aliases": ["group_share", "fb_list_group_share"],
        "summary": "Quy trình BĐS 7 bước: Đăng bài Nhóm & Chia sẻ chéo hàng loạt",
        "description": "Vào nhóm chính -> Chọn 'Bạn đang bán gì' -> Tải ảnh BĐS PC lên Gallery -> AI Gemini viết lại mô tả chuẩn SEO -> Bấm Next chọn Marketplace -> Chọn danh sách Nhóm chia sẻ -> Bấm Publish.",
        "params": [
            {"name": "group_ids", "type": "list[str]", "required": True, "default": "N/A", "desc": "Danh sách ID các Nhóm cần chia sẻ (Ví dụ: ['111222', '333444'])"},
            {"name": "use_v1_product", "type": "bool", "required": False, "default": "true", "desc": "Lấy dữ liệu BĐS ngẫu nhiên từ my-manager.v1 DB"},
            {"name": "use_ai", "type": "bool", "required": False, "default": "true", "desc": "Dùng AI Gemini 3.5 viết Tiêu đề IN HOA & Mô tả 5 góc nhìn anti-spam"},
            {"name": "custom_content", "type": "str", "required": False, "default": "None", "desc": "Tùy chỉnh nội dung thủ công thay vì lấy từ AI V1"}
        ],
        "single_cli": 'python main-cli.py run action --action group_share --uids "61599900011122" --auto-stop',
        "script_json": '{"action": "list_group_share", "params": {"group_ids": ["111222", "333444"], "use_ai": true}}',
    }
}


@automation_app.command("actions")
def actions_guide(
    name: Optional[str] = typer.Argument(None, help="Name of specific action to show detailed guide (e.g. warmup, group_share)"),
):
    """Guide for all Facebook automation actions, input parameters, single-run CLI, and scenario script usage."""
    if name:
        target_key = name.lower().strip()
        matched = None
        for key, act_info in ACTION_REGISTRY.items():
            if target_key == key or target_key in act_info["aliases"]:
                matched = act_info
                break

        if not matched:
            console.print(f"[bold red]Action '{name}' not found. Run 'python main-cli.py actions' to view all available actions.[/bold red]")
            return

        # Show detailed panel for single action
        console.print(Panel(f"[bold cyan]Action Name:[/bold cyan] [bold white]{matched['name']}[/bold white]\n[bold yellow]Aliases:[/bold yellow] {', '.join(matched['aliases'])}\n\n[white]{matched['description']}[/white]", title=f"📘 Facebook Action Guide: {matched['name']}", style="blue"))

        # Params table
        p_table = Table(title="Input Parameters Specification", expand=True)
        p_table.add_column("Parameter Name", style="cyan")
        p_table.add_column("Data Type", style="yellow")
        p_table.add_column("Required", style="bold")
        p_table.add_column("Default Value", style="magenta")
        p_table.add_column("Description", style="white")

        for p in matched["params"]:
            req_str = "[bold red]YES[/bold red]" if p["required"] else "[green]NO[/green]"
            p_table.add_row(p["name"], p["type"], req_str, str(p["default"]), p["desc"])
        console.print(p_table)

        # Examples
        console.print("\n[bold green]1. Single Action CLI Execution (Chạy Đơn Tác Vụ):[/bold green]")
        console.print(f"  [cyan]{matched['single_cli']}[/cyan]")

        console.print("\n[bold green]2. Batch Scenario Script Execution (Chạy Trong Kịch Bản Script JSON):[/bold green]")
        console.print(f"  [yellow]{matched['script_json']}[/yellow]")
        console.print("\n  [dim]Ví dụ tạo kịch bản batch đầy đủ:[/dim]")
        console.print(f"  [cyan]python main-cli.py automation create-batch --tag my_tag --uids \"10001\" --actions '[{matched['script_json']}]'[/cyan]\n")
        return

    # List all actions
    table = Table(title="📋 Facebook Automation Actions Registry", show_lines=True, expand=True)
    table.add_column("Action Name", style="bold cyan", width=16)
    table.add_column("Aliases", style="yellow", width=22)
    table.add_column("Required Params", style="bold red", width=18)
    table.add_column("Summary / Functionality Description", style="white")

    for key, act_info in ACTION_REGISTRY.items():
        req_params = [p["name"] for p in act_info["params"] if p["required"]]
        req_str = ", ".join(req_params) if req_params else "None"
        table.add_row(
            act_info["name"],
            ", ".join(act_info["aliases"]),
            req_str,
            act_info["summary"],
        )

    console.print(table)
    console.print("\n[bold yellow]💡 Tip:[/bold yellow] Run [cyan]python main-cli.py actions <action_name>[/cyan] (e.g. [cyan]python main-cli.py actions group_share[/cyan]) to view full parameter documentation and script usage examples!")



