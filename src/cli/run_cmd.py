"""CLI Subcommands for Direct Automation Action Execution."""

import typer
from rich.console import Console
from typing import List, Optional
from concurrent.futures import ThreadPoolExecutor

from src.db.repository import AccountRepository, RedroidRepository
from src.automation.base_automator import BaseAutomator
from src.automation.facebook.login import FBLoginAction
from src.automation.facebook.warmup import FBWarmupAction
from src.automation.facebook.marketplace import FBMarketplaceAction

from src.redroid.manager import RedroidManager
from src.proxy.service import ProxyService

from src.automation.facebook.router import FBActionRouter

app = typer.Typer(help="Run automation actions directly.")
console = Console()
manager = RedroidManager()


def _run_single_account(uid: str, action: str, params: dict, auto_stop: bool = False):
    """Worker task executing action on single account's Redroid container."""
    acc = AccountRepository.get_by_uid(uid)
    if not acc:
        console.print(f"[bold red]Account UID {uid} not found.[/bold red]")
        return False

    redroid_inst = RedroidRepository.get_by_account_uid(uid)
    if not redroid_inst:
        console.print(f"[bold red]No Redroid instance bound to UID {uid}. Creating instance...[/bold red]")
        try:
            redroid_inst = manager.create_instance(account_uid=uid)
        except Exception as e:
            console.print(f"[bold red]Failed to create container for UID {uid}: {e}[/bold red]")
            return False

    automator = BaseAutomator(adb_port=redroid_inst.adb_port)
    if not automator.initialize():
        console.print(f"[bold red]Failed to connect ADB/UIAutomator2 to port {redroid_inst.adb_port}[/bold red]")
        return False

    console.print(f"[cyan]Executing action '{action}' on UID {uid} (ADB Port {redroid_inst.adb_port})...[/cyan]")

    try:
        res = FBActionRouter.dispatch(automator, acc, action_name=action, params=params)
    finally:
        if auto_stop and redroid_inst:
            console.print(f"[yellow]Auto-stopping container for UID {uid} and releasing proxy...[/yellow]")
            manager.stop_instance(redroid_inst.container_name)

    return res


import json

@app.command("action")
def run_action(
    action: str = typer.Option(..., help="Action type: login, warmup, marketplace, list_group_share, scroll_feed"),
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
