"""CLI Subcommands for Direct Automation Action Execution."""

import re
import time
import typer
from rich.console import Console
from typing import List, Optional
from concurrent.futures import ThreadPoolExecutor

from src.db.repository import AccountRepository, RedroidRepository, ProxyRepository
from src.automation.base_automator import BaseAutomator
from src.automation.facebook.login import FBLoginAction, record_login_result
from src.automation.facebook.warmup import FBWarmupAction
from src.automation.facebook.marketplace import FBMarketplaceAction

from src.redroid.manager import RedroidManager
from src.proxy.service import ProxyService
from src.redroid.proxy_configurator import ContainerProxyConfigurator

from src.automation.facebook.router import FBActionRouter

app = typer.Typer(help="Run automation actions directly.")
console = Console()
manager = RedroidManager()


def _parse_uids(uids: List[str]) -> List[str]:
    """Flattens and parses comma-separated UIDs, stripping spaces, quotes, and empty values."""
    parsed = []
    for item in uids:
        for u in str(item).split(","):
            clean = re.sub(r'[\'"\s]', '', u)
            if clean and clean not in parsed:
                parsed.append(clean)
    return parsed


def _run_single_account(uid: str, action: str, params: dict, auto_stop: bool = False):
    uid = re.sub(r'[\'"\s]', '', str(uid))
    """Worker task executing action on single account's Redroid container with auto-start & proxy."""
    acc = AccountRepository.get_by_uid(uid)
    if not acc:
        from src.core.models import Account
        console.print(f"[dim yellow]Account UID {uid} not in DB accounts table. Using transient account profile...[/dim yellow]")
        acc = Account(uid=uid, password="", username=f"User_{uid}")

    # 1. Acquire Proxy from pool for this account (Strict requirement: Mở app luôn phải sử dụng proxy)
    is_proxy_required = str(action).lower().strip() in [
        "open_facebook_scrcpy",
        "open_scrcpy",
        "open_facebook",
        "open_app",
        "view_account",
        "fb_scrcpy",
        "fb_open_scrcpy",
        "login",
        "fb_login",
    ] or params.get("require_proxy", False)

    proxy = None
    max_proxy_wait = 30
    poll_start = time.time()
    while time.time() - poll_start < max_proxy_wait:
        proxy = ProxyRepository.acquire_available_proxy(uid)
        if proxy:
            break
        if not is_proxy_required:
            break
        console.print(f"[dim yellow]Proxy is required for UID {uid}. Waiting for an available proxy in pool...[/dim yellow]")
        time.sleep(2.0)

    proxy_url = proxy.url if proxy else None
    if proxy:
        console.print(f"[green]Acquired proxy #{proxy.id} for UID {uid}: {proxy.name or proxy.url[:35]}...[/green]")
    else:
        if is_proxy_required:
            console.print(f"[bold red]❌ Cannot proceed for UID {uid}: Proxy is strictly required ('Mở app luôn phải sử dụng proxy') but no available proxy was found in pool![/bold red]")
            return False
        console.print(f"[yellow]No available proxy found in pool for UID {uid}. Running with default network.[/yellow]")

    redroid_inst = None
    automator = None
    res = False

    try:
        # 2. Check, start or auto-provision Redroid container with proxy
        redroid_inst = RedroidRepository.get_by_account_uid(uid)
        if not redroid_inst:
            console.print(f"[cyan]Account UID {uid} has no Redroid container. Auto-provisioning with proxy...[/cyan]")
            redroid_inst = manager.create_instance(account_uid=uid, proxy_url=proxy_url, use_proxy=True)
            AccountRepository.bind_container(uid, redroid_inst.container_id, redroid_inst.device_profile_id or "")
        else:
            live_status = manager.get_live_docker_status(redroid_inst.container_name)
            if live_status == "stopped":
                console.print(f"[cyan]Container '{redroid_inst.container_name}' is stopped. Starting container & applying proxy...[/cyan]")
                manager.start_instance(redroid_inst.container_name, proxy_url=proxy_url, use_proxy=True)
            elif live_status == "not_found":
                console.print(f"[yellow]Container '{redroid_inst.container_name}' not found on Docker. Auto-creating...[/yellow]")
                redroid_inst = manager.create_instance(account_uid=uid, proxy_url=proxy_url, use_proxy=True)
                AccountRepository.bind_container(uid, redroid_inst.container_id, redroid_inst.device_profile_id or "")
            else:
                console.print(f"[cyan]Container '{redroid_inst.container_name}' is already running.[/cyan]")
                if proxy_url:
                    try:
                        ContainerProxyConfigurator.configure_proxy_for_container(redroid_inst.container_name, proxy_url)
                    except Exception as pe:
                        console.print(f"[dim yellow]Warning applying dynamic proxy: {pe}[/dim yellow]")

        # 3. Connect ADB and UIAutomator2
        automator = BaseAutomator(adb_port=redroid_inst.adb_port)
        if not automator.initialize():
            console.print(f"[bold red]Failed to connect ADB/UIAutomator2 to port {redroid_inst.adb_port} for UID {uid}[/bold red]")
            if str(action).lower().strip() in ["login", "fb_login"]:
                record_login_result(uid, False, "ERROR", f"Failed to connect ADB/UIAutomator2 to port {redroid_inst.adb_port}")
            return False

        console.print(f"[bold cyan]Executing action '{action}' on UID {uid} (ADB Port {redroid_inst.adb_port})...[/bold cyan]")
        res = FBActionRouter.dispatch(automator, acc, action_name=action, params=params)

        # Sau khi login xong cần delay khoảng 10s sau đó đóng redroid để chuẩn bị login account mới
        if str(action).lower().strip() in ["login", "fb_login"]:
            if res:
                console.print(f"[bold green]✅ Login succeeded for UID {uid}. Waiting 10s before stopping Redroid container...[/bold green]")
                time.sleep(10.0)
            else:
                console.print(f"[yellow]⚠️ Login ended with failure for UID {uid}. Waiting 3s before closing container...[/yellow]")
                time.sleep(3.0)
            auto_stop = True

        if str(action).lower().strip() in [
            "open_facebook_scrcpy",
            "open_scrcpy",
            "open_facebook",
            "open_app",
            "view_account",
            "fb_scrcpy",
            "fb_open_scrcpy",
        ]:
            console.print(f"[bold green]✔ Scrcpy window closed for UID {uid}. Auto-stopping container to proceed to next UID...[/bold green]")
            auto_stop = True

        if str(action).lower().strip() in ["check_login", "is_logged_in"]:
            if res:
                console.print(f"[bold green]✅ UID {uid}: Logged In (Live)[/bold green]")
            else:
                console.print(f"[bold yellow]⚠️ UID {uid}: Not Logged In / Checkpoint / Expired[/bold yellow]")
            auto_stop = True

    except Exception as e:
        console.print(f"[bold red]Error executing action for UID {uid}: {e}[/bold red]")
        if str(action).lower().strip() in ["login", "fb_login"]:
            record_login_result(uid, False, "ERROR", f"Runner exception: {e}")
        res = False

    finally:
        if automator:
            try:
                automator.close()
            except Exception:
                pass

        if auto_stop and redroid_inst:
            console.print(f"[yellow]Auto-stopping container '{redroid_inst.container_name}' for UID {uid}...[/yellow]")
            manager.stop_instance(redroid_inst.container_name)

        if proxy and proxy.id:
            ProxyRepository.release_proxy_by_id(proxy.id)
            console.print(f"[dim]Released proxy #{proxy.id} for UID {uid}.[/dim]")

    return res


import json

@app.command("action")
def run_action(
    action: str = typer.Option(..., help="Action type: login, warmup, marketplace, list_group_share, list_marketplace_share, single_listing, discussion_group, scroll_feed, join_group, reel_interactions"),
    uids: List[str] = typer.Option(..., help="List of Facebook UIDs to execute action on"),
    params: str = typer.Option("{}", help="JSON string of parameters for the action"),
    concurrency: int = typer.Option(2, help="Number of concurrent workers"),
    auto_stop: bool = typer.Option(False, help="Automatically stop container and release proxy after action finishes"),
):
    """Run specified action on multiple accounts concurrently."""
    parsed_params = {}
    if params and params.strip() != "{}":
        try:
            parsed_params = json.loads(params)
        except Exception as e:
            console.print(f"[bold red]Failed to parse --params JSON: {e}[/bold red]")
            return

    target_uids = _parse_uids(uids)
    console.print(f"[bold green]Starting batch action '{action}' on {len(target_uids)} accounts with concurrency {concurrency}...[/bold green]")
    
    with ThreadPoolExecutor(max_workers=concurrency) as executor:
        futures = [executor.submit(_run_single_account, uid, action, parsed_params, auto_stop) for uid in target_uids]
        for f in futures:
            f.result()

    console.print(f"[bold green]Finished batch action '{action}'![/bold green]")


@app.command("login")
def run_login_cmd(
    uids: List[str] = typer.Option(..., "--uids", "-u", help="List of Facebook account UIDs to log in"),
    concurrency: int = typer.Option(1, "--concurrency", "-m", help="Number of concurrent workers (default: 1)"),
    auto_stop: bool = typer.Option(False, "--auto-stop", help="Auto stop container and release proxy after finish"),
):
    """Executes automated Facebook login with 2FA handling."""
    target_uids = _parse_uids(uids)
    if not target_uids:
        console.print("[bold red]No valid account UIDs provided.[/bold red]")
        return
    console.print(f"[bold green]🚀 Starting Facebook Login for {len(target_uids)} accounts (concurrency {concurrency})...[/bold green]")
    with ThreadPoolExecutor(max_workers=concurrency) as executor:
        futures = [executor.submit(_run_single_account, uid, "login", {}, auto_stop) for uid in target_uids]
        for f in futures:
            f.result()
    console.print("[bold green]✅ Finished Facebook Login execution![/bold green]")


@app.command("discussion-group")
def run_discussion_group_cmd(
    uids: List[str] = typer.Option(..., "--uids", "-u", help="List of Facebook account UIDs"),
    group_id: Optional[str] = typer.Option(None, "--group-id", "-g", help="Specific group ID/URL (or None to select random)"),
    transaction_type: str = typer.Option("rental", "--trans-type", "-t", help="Transaction type: rental or sale"),
    use_ai: bool = typer.Option(True, "--use-ai/--no-ai", help="Use Gemini AI to rewrite post"),
    use_v1_product: bool = typer.Option(True, "--v1-prod/--no-v1-prod", help="Fetch random product from v1 database"),
    content: Optional[str] = typer.Option(None, "--content", "-c", help="Custom text content if not using v1 product"),
    concurrency: int = typer.Option(2, "--concurrency", "-m", help="Number of concurrent workers"),
    auto_stop: bool = typer.Option(False, "--auto-stop", help="Auto stop container and release proxy after finish"),
):
    """Executes 10-step Discussion Group posting pipeline."""
    params = {
        "group_id": group_id,
        "transaction_type": transaction_type,
        "use_ai": use_ai,
        "use_v1_product": use_v1_product,
        "custom_content": content,
    }
    target_uids = _parse_uids(uids)
    console.print(f"[bold green]🚀 Running Discussion Group on {len(target_uids)} accounts (Trans: {transaction_type})...[/bold green]")
    with ThreadPoolExecutor(max_workers=concurrency) as executor:
        futures = [executor.submit(_run_single_account, uid, "discussion_group", params, auto_stop) for uid in target_uids]
        for f in futures:
            f.result()
    console.print("[bold green]✅ Finished Discussion Group execution![/bold green]")


@app.command("group-share")
def run_group_share_cmd(
    uids: List[str] = typer.Option(..., "--uids", "-u", help="List of Facebook account UIDs"),
    group_id: str = typer.Option("5857815244230418", "--group-id", "-g", help="Starting group ID to list item in"),
    share_count: int = typer.Option(5, "--share-count", "-s", help="Max number of top groups to cross-share"),
    transaction_type: str = typer.Option("rental", "--trans-type", "-t", help="Transaction type: rental or sale"),
    use_ai: bool = typer.Option(True, "--use-ai/--no-ai", help="Use Gemini AI rewriting"),
    use_v1_product: bool = typer.Option(True, "--v1-prod/--no-v1-prod", help="Fetch product from v1 database"),
    concurrency: int = typer.Option(2, "--concurrency", "-m", help="Number of concurrent workers"),
    auto_stop: bool = typer.Option(False, "--auto-stop", help="Auto stop container and release proxy after finish"),
):
    """Executes 7-step Buy/Sell Group Listing & Top Groups Cross-Sharing pipeline."""
    params = {
        "group_ids": [group_id],
        "share_groups_count": share_count,
        "transaction_type": transaction_type,
        "use_ai": use_ai,
        "use_v1_product": use_v1_product,
    }
    target_uids = _parse_uids(uids)
    console.print(f"[bold green]🚀 Running Group Share on {len(target_uids)} accounts (Group: {group_id}, Share Count: {share_count})...[/bold green]")
    with ThreadPoolExecutor(max_workers=concurrency) as executor:
        futures = [executor.submit(_run_single_account, uid, "list_group_share", params, auto_stop) for uid in target_uids]
        for f in futures:
            f.result()
    console.print("[bold green]✅ Finished Group Share execution![/bold green]")


@app.command("marketplace-share")
def run_marketplace_share_cmd(
    uids: List[str] = typer.Option(..., "--uids", "-u", help="List of Facebook account UIDs"),
    share_count: int = typer.Option(20, "--share-count", "-s", help="Max number of top groups to cross-share"),
    transaction_type: str = typer.Option("sale", "--trans-type", "-t", help="Transaction type: sale or rental"),
    location: str = typer.Option("Da Lat", "--location", "-l", help="Listing location city"),
    use_ai: bool = typer.Option(True, "--use-ai/--no-ai", help="Use Gemini AI rewriting"),
    use_v1_product: bool = typer.Option(True, "--v1-prod/--no-v1-prod", help="Fetch product from v1 database"),
    concurrency: int = typer.Option(2, "--concurrency", "-m", help="Number of concurrent workers"),
    auto_stop: bool = typer.Option(False, "--auto-stop", help="Auto stop container and release proxy after finish"),
):
    """Executes 11-step Facebook Marketplace Listing & Group Cross-Sharing pipeline."""
    params = {
        "share_groups_count": share_count,
        "transaction_type": transaction_type,
        "location": location,
        "use_ai": use_ai,
        "use_v1_product": use_v1_product,
    }
    target_uids = _parse_uids(uids)
    console.print(f"[bold green]🚀 Running Marketplace Listing & Share on {len(target_uids)} accounts (Location: {location})...[/bold green]")
    with ThreadPoolExecutor(max_workers=concurrency) as executor:
        futures = [executor.submit(_run_single_account, uid, "list_marketplace_share", params, auto_stop) for uid in target_uids]
        for f in futures:
            f.result()
    console.print("[bold green]✅ Finished Marketplace Listing & Share execution![/bold green]")


@app.command("single-listing")
def run_single_listing_cmd(
    uids: List[str] = typer.Option(..., "--uids", "-u", help="List of Facebook account UIDs"),
    group_count: int = typer.Option(3, "--groups-count", "-c", help="Number of groups to post individually"),
    transaction_type: str = typer.Option("rental", "--trans-type", "-t", help="Transaction type: rental or sale"),
    use_ai: bool = typer.Option(True, "--use-ai/--no-ai", help="Use Gemini AI rewriting"),
    use_v1_product: bool = typer.Option(True, "--v1-prod/--no-v1-prod", help="Fetch product from v1 database"),
    concurrency: int = typer.Option(2, "--concurrency", "-m", help="Number of concurrent workers"),
    auto_stop: bool = typer.Option(False, "--auto-stop", help="Auto stop container and release proxy after finish"),
):
    """Executes Multi-Group Single Listing pipeline (auto detects Sell vs Discussion)."""
    params = {
        "group_count": group_count,
        "transaction_type": transaction_type,
        "use_ai": use_ai,
        "use_v1_product": use_v1_product,
    }
    target_uids = _parse_uids(uids)
    console.print(f"[bold green]🚀 Running Single Listing on {len(target_uids)} accounts ({group_count} groups each)...[/bold green]")
    with ThreadPoolExecutor(max_workers=concurrency) as executor:
        futures = [executor.submit(_run_single_account, uid, "single_listing", params, auto_stop) for uid in target_uids]
        for f in futures:
            f.result()
    console.print("[bold green]✅ Finished Single Listing execution![/bold green]")


@app.command("join-group")
def run_join_group(
    uids: List[str] = typer.Option(..., "--uids", "-u", help="List of Facebook account UIDs to execute on"),
    keyword: str = typer.Option(..., "--keyword", "-k", help="Search keyword for finding groups (e.g. 'bán nhà đà lạt')"),
    group_count: int = typer.Option(3, "--count", "-c", help="Number of groups to join per account"),
    concurrency: int = typer.Option(2, "--concurrency", "-m", help="Number of accounts to run concurrently"),
    auto_stop: bool = typer.Option(False, "--auto-stop", help="Automatically stop container and release proxy after completion"),
):
    """Directly executes keyword-based group search and join action."""
    params = {"keyword": keyword, "group_count": group_count}
    target_uids = _parse_uids(uids)
    console.print(
        f"[bold green]🚀 Starting 'join_group' action with keyword '{keyword}' ({group_count} groups/acc) for {len(target_uids)} accounts (concurrency {concurrency})...[/bold green]"
    )

    with ThreadPoolExecutor(max_workers=concurrency) as executor:
        futures = [executor.submit(_run_single_account, uid, "join_group", params, auto_stop) for uid in target_uids]
        for f in futures:
            f.result()

    console.print(f"[bold green]✅ Finished 'join_group' action![/bold green]")


@app.command("reel-interactions")
def run_reel_interactions(
    uids: List[str] = typer.Option(..., "--uids", "-u", help="List of Facebook account UIDs to execute on"),
    reel_id: str = typer.Option(..., "--reel-id", "-r", help="Facebook Reel ID (e.g. '3046151639050612')"),
    like: bool = typer.Option(True, "--like/--no-like", help="Like the reel (skips if already liked)"),
    comment: bool = typer.Option(False, "--comment/--no-comment", help="Comment on the reel"),
    comment_content: str = typer.Option("", "--comment-content", "-c", help="Content of the comment (picks random from preset list if omitted or empty)"),
    share: bool = typer.Option(False, "--share/--no-share", help="Share reel to Facebook groups"),
    share_num: int = typer.Option(1, "--share-num", "-s", help="Number of groups to share to (max 10)"),
    save: bool = typer.Option(False, "--save/--no-save", help="Save reel to collections"),
    watch_delay: float = typer.Option(15.0, "--watch-delay", "-w", help="Delay seconds to simulate watching the reel"),
    concurrency: int = typer.Option(2, "--concurrency", "-m", help="Number of accounts to run concurrently"),
    auto_stop: bool = typer.Option(False, "--auto-stop", help="Automatically stop container and release proxy after completion"),
):
    """Executes full Facebook Reel interactions: watch simulation, like, save, comment, and share to groups."""
    params = {
        "reel_id": reel_id,
        "like": like,
        "comment": comment,
        "comment_content": comment_content,
        "share": share,
        "share_num": share_num,
        "save": save,
        "watch_delay": watch_delay,
    }
    target_uids = _parse_uids(uids)
    if not target_uids:
        console.print("[bold red]No valid account UIDs provided.[/bold red]")
        return

    console.print(
        f"[bold green]🚀 Starting 'reel_interactions' on Reel '{reel_id}' for {len(target_uids)} accounts (concurrency {concurrency})...[/bold green]"
    )

    with ThreadPoolExecutor(max_workers=concurrency) as executor:
        futures = [executor.submit(_run_single_account, uid, "reel_interactions", params, auto_stop) for uid in target_uids]
        for f in futures:
            f.result()

    console.print(f"[bold green]✅ Finished 'reel_interactions' action![/bold green]")


@app.command("open-facebook")
@app.command("open-scrcpy")
@app.command("open-app")
def run_open_facebook_scrcpy_cmd(
    uids: Optional[List[str]] = typer.Option(None, "--uids", "-u", help="List of Facebook account UIDs to open Facebook app & Scrcpy sequentially"),
    group_id: Optional[int] = typer.Option(None, "--group-id", "-g", help="Account group ID to fetch UIDs from"),
    all_accounts: bool = typer.Option(False, "--all", "-a", help="Run on all accounts in database"),
    deeplink: str = typer.Option("fb://feed", "--deeplink", "-d", help="Facebook deep link or target (default: fb://feed)"),
    concurrency: int = typer.Option(1, "--concurrency", "-m", help="Number of concurrent workers (default: 1 for sequential one-by-one)"),
    auto_stop: bool = typer.Option(True, "--auto-stop/--no-auto-stop", help="Automatically stop container and release proxy after scrcpy is closed (default: True)"),
):
    """
    Open Facebook app and Scrcpy window sequentially for a list of UIDs.
    For each UID: starts container (using available proxy) -> launches scrcpy -> opens Facebook app.
    When the user closes the Scrcpy window, the container automatically stops, releases the proxy, and opens the next UID.
    """
    target_uids = []
    if uids:
        target_uids = _parse_uids(uids)
    elif group_id is not None:
        accs = AccountRepository.list_by_group(group_id)
        target_uids = [acc.uid for acc in accs if acc.uid]
    elif all_accounts:
        accs = AccountRepository.list_all()
        target_uids = [acc.uid for acc in accs if acc.uid]

    if not target_uids:
        console.print("[bold red]Please provide account UIDs using --uids, --group-id, or --all.[/bold red]")
        return

    console.print(
        f"[bold green]🚀 Opening Facebook App & Scrcpy for {len(target_uids)} account(s) (concurrency: {concurrency})...[/bold green]\n"
        f"[dim]Note: Close the Scrcpy window when done with an account to automatically stop its container and proceed to the next.[/dim]"
    )

    params = {"deeplink": deeplink, "wait_for_close": True}

    if concurrency > 1:
        with ThreadPoolExecutor(max_workers=concurrency) as executor:
            futures = [executor.submit(_run_single_account, uid, "open_facebook_scrcpy", params, auto_stop) for uid in target_uids]
            for f in futures:
                f.result()
    else:
        for idx, uid in enumerate(target_uids, 1):
            console.print(f"\n[bold cyan]━━━━━━━━━━━━━ [{idx}/{len(target_uids)}] Processing UID: {uid} ━━━━━━━━━━━━━[/bold cyan]")
            _run_single_account(uid, "open_facebook_scrcpy", params, auto_stop=auto_stop)

    console.print(f"\n[bold green]✅ Finished Facebook & Scrcpy workflow for all {len(target_uids)} account(s)![/bold green]")


@app.command("check-login")
def run_check_login_cmd(
    uids: Optional[List[str]] = typer.Option(None, "--uids", "-u", help="List of Facebook account UIDs to check login status"),
    group_id: Optional[int] = typer.Option(None, "--group-id", "-g", help="Account group ID to fetch UIDs from"),
    all_accounts: bool = typer.Option(False, "--all", "-a", help="Check all accounts in database"),
    wait_time: int = typer.Option(10, "--wait", "-w", help="Seconds to wait after Facebook app launch before checking status (default: 10s)"),
    concurrency: int = typer.Option(2, "--concurrency", "-m", help="Concurrent workers (default: 2)"),
    auto_stop: bool = typer.Option(True, "--auto-stop/--no-auto-stop", help="Auto stop container and release proxy after checking (default: True)"),
):
    """
    Checks whether Facebook account(s) are logged in, logged out, or in checkpoint.
    """
    target_uids = []
    if uids:
        target_uids = _parse_uids(uids)
    elif group_id is not None:
        accs = AccountRepository.list_by_group(group_id)
        target_uids = [acc.uid for acc in accs if acc.uid]
    elif all_accounts:
        accs = AccountRepository.list_all()
        target_uids = [acc.uid for acc in accs if acc.uid]

    if not target_uids:
        console.print("[bold red]Please provide account UIDs using --uids, --group-id, or --all.[/bold red]")
        return

    console.print(f"[bold green]🔍 Checking Facebook login status for {len(target_uids)} account(s) (waiting {wait_time}s after app launch, concurrency: {concurrency})...[/bold green]")
    check_params = {"wait_after_launch": wait_time}
    with ThreadPoolExecutor(max_workers=concurrency) as executor:
        futures = [executor.submit(_run_single_account, uid, "check_login", check_params, auto_stop) for uid in target_uids]
        for f in futures:
            try:
                f.result()
            except Exception as e:
                console.print(f"[bold red]Worker error during check_login: {e}[/bold red]")

    # Print summary table
    from rich.table import Table
    table = Table(title="📊 Facebook Login Check Results Summary", show_lines=True)
    table.add_column("UID", style="cyan", no_wrap=True)
    table.add_column("Status", justify="center")
    table.add_column("Details / Diagnostic Note")
    table.add_column("Updated At", style="dim", justify="right")

    for uid in target_uids:
        acc = AccountRepository.get_by_uid(uid)
        if acc:
            st = acc.status.value if hasattr(acc.status, "value") else str(acc.status)
            color = "green" if st == "live" else "red" if st == "checkpoint" else "yellow"
            status_text = f"[{color}]{st.upper()}[/{color}]"
            table.add_row(uid, status_text, acc.note or "", str(acc.updated_at or "")[:19])
        else:
            table.add_row(uid, "[dim]UNKNOWN[/dim]", "Account not saved in DB", "")

    console.print(table)
    console.print(f"[bold green]✅ Finished checking login status for {len(target_uids)} account(s)![/bold green]")
    console.print(f"[dim]📁 Results are saved to SQLite DB (table 'accounts'), logs/login_results.json, and logs/login_results.log[/dim]")




