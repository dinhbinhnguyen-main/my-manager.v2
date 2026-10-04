"""CLI Subcommands for Direct Automation Action Execution."""

import re
import typer
from rich.console import Console
from typing import List, Optional
from concurrent.futures import ThreadPoolExecutor

from src.db.repository import AccountRepository, RedroidRepository, ProxyRepository
from src.automation.base_automator import BaseAutomator
from src.automation.facebook.login import FBLoginAction
from src.automation.facebook.warmup import FBWarmupAction
from src.automation.facebook.marketplace import FBMarketplaceAction

from src.redroid.manager import RedroidManager
from src.proxy.service import ProxyService
from src.redroid.proxy_configurator import ContainerProxyConfigurator

from src.automation.facebook.router import FBActionRouter

app = typer.Typer(help="Run automation actions directly.")
console = Console()
manager = RedroidManager()


def _run_single_account(uid: str, action: str, params: dict, auto_stop: bool = False):
    uid = re.sub(r'[\'"\s]', '', str(uid))
    """Worker task executing action on single account's Redroid container with auto-start & proxy."""
    acc = AccountRepository.get_by_uid(uid)
    if not acc:
        console.print(f"[bold red]Account UID {uid} not found in database.[/bold red]")
        return False

    # 1. Acquire Proxy from pool for this account
    proxy = ProxyRepository.acquire_available_proxy(uid)
    proxy_url = proxy.url if proxy else None
    if proxy:
        console.print(f"[green]Acquired proxy #{proxy.id} for UID {uid}: {proxy.name or proxy.url[:35]}...[/green]")
    else:
        console.print(f"[yellow]No available proxy found in pool for UID {uid}. Running with default network.[/yellow]")

    redroid_inst = None
    automator = None
    res = False

    try:
        # 2. Check, start or auto-provision Redroid container with proxy
        redroid_inst = RedroidRepository.get_by_account_uid(uid)
        if not redroid_inst:
            console.print(f"[cyan]Account UID {uid} has no Redroid container. Auto-provisioning with proxy...[/cyan]")
            redroid_inst = manager.create_instance(account_uid=uid, proxy_url=proxy_url)
            AccountRepository.bind_container(uid, redroid_inst.container_id, redroid_inst.device_profile_id or "")
        else:
            live_status = manager.get_live_docker_status(redroid_inst.container_name)
            if live_status == "stopped":
                console.print(f"[cyan]Container '{redroid_inst.container_name}' is stopped. Starting container & applying proxy...[/cyan]")
                manager.start_instance(redroid_inst.container_name, proxy_url=proxy_url)
            elif live_status == "not_found":
                console.print(f"[yellow]Container '{redroid_inst.container_name}' not found on Docker. Auto-creating...[/yellow]")
                redroid_inst = manager.create_instance(account_uid=uid, proxy_url=proxy_url)
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
            return False

        console.print(f"[bold cyan]Executing action '{action}' on UID {uid} (ADB Port {redroid_inst.adb_port})...[/bold cyan]")
        res = FBActionRouter.dispatch(automator, acc, action_name=action, params=params)

    except Exception as e:
        console.print(f"[bold red]Error executing action for UID {uid}: {e}[/bold red]")
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
    action: str = typer.Option(..., help="Action type: login, warmup, marketplace, list_group_share, discussion_group, scroll_feed"),
    uids: List[str] = typer.Option(..., help="List of Facebook UIDs to execute action on"),
    params: str = typer.Option("{}", help="JSON string of parameters for the action, e.g. '{\"group_ids\": [\"5857815244230418\"], \"use_v1_product\": true}'"),
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

    console.print(f"[bold green]Starting batch action '{action}' on {len(uids)} accounts with concurrency {concurrency}...[/bold green]")
    
    with ThreadPoolExecutor(max_workers=concurrency) as executor:
        futures = [executor.submit(_run_single_account, uid, action, parsed_params, auto_stop) for uid in uids]
        for f in futures:
            f.result()

    console.print(f"[bold green]Finished batch action '{action}'![/bold green]")


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
    console.print(
        f"[bold green]🚀 Starting 'join_group' action with keyword '{keyword}' ({group_count} groups/acc) for {len(uids)} accounts (concurrency {concurrency})...[/bold green]"
    )

    with ThreadPoolExecutor(max_workers=concurrency) as executor:
        futures = [executor.submit(_run_single_account, uid, "join_group", params, auto_stop) for uid in uids]
        for f in futures:
            f.result()

    console.print(f"[bold green]✅ Finished 'join_group' action![/bold green]")

