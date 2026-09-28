#!/usr/bin/env python3
"""
Main CLI entry point for Redroid Facebook Multi-Account Manager (my-manager.v2).
"""

import sys
import logging
import typer
from rich.console import Console

from src.db.database import init_db

from src.core.logger import setup_logging

# Configure real-time colored logging format
setup_logging()

# Initialize database schema immediately on startup
init_db()

from src.cli.account_cmd import app as account_app
from src.cli.redroid_cmd import app as redroid_app
from src.cli.proxy_cmd import app as proxy_app
from src.cli.run_cmd import app as run_app
from src.cli.setting_cmd import app as setting_app
from src.cli.product_cmd import app as product_app
from src.cli.automation_cmd import automation_app, progress_cmd

console = Console()

app = typer.Typer(
    name="my-manager",
    help="High-Performance Redroid FB Multi-Account & Automation Manager",
    add_completion=False,
)

# Register sub-command groups
app.add_typer(account_app, name="account")
app.add_typer(redroid_app, name="redroid")
app.add_typer(proxy_app, name="proxy")
app.add_typer(run_app, name="run")
app.add_typer(setting_app, name="setting")
app.add_typer(product_app, name="product")
app.add_typer(automation_app, name="automation")

from src.cli.automation_cmd import automation_app, progress_cmd, actions_guide
from src.cli.redroid_cmd import app as redroid_app, scrcpy_cmd

# Top-level shortcut commands for live monitoring & action documentation
app.command("progress")(progress_cmd)
app.command("scrcpy")(scrcpy_cmd)
app.command("actions")(actions_guide)


@app.command("dump", help="Dump screen snapshot, XML hierarchy, and interactive elements via port or UID")
def dump_cmd(
    port: int = typer.Option(None, "--port", "-p", help="ADB Port of device (e.g. 5555, 5565)"),
    uid: str = typer.Option(None, "--uid", "-u", help="Facebook UID (resolves ADB port automatically)"),
    tag: str = typer.Option(None, "--tag", help="Optional tag for output folder (e.g. step_3)"),
    no_photo: bool = typer.Option(False, "--no-photo", help="Skip capturing screenshot PNG"),
):
    from tests.dump_view import dump_screen, ensure_adb_connected, resolve_port_from_uid, get_available_devices
    target = None
    if uid:
        resolved = resolve_port_from_uid(uid)
        if resolved:
            target = ensure_adb_connected(resolved)
        else:
            console.print(f"[bold red]❌ Could not find ADB Port for UID {uid}[/bold red]")
            raise typer.Exit(1)
    elif port:
        target = ensure_adb_connected(port)
    else:
        devs = get_available_devices()
        if len(devs) == 1:
            target = devs[0]
        elif len(devs) > 1:
            target = devs[0]
        else:
            console.print("[bold red]❌ No ADB device specified and none connected. Use --port <PORT> or --uid <UID>[/bold red]")
            raise typer.Exit(1)

    dump_screen(target, take_screenshot=not no_photo, tag=tag)

@app.callback(invoke_without_command=True)
def main(ctx: typer.Context):
    """Initializes system database before running commands."""
    init_db()
    if ctx.invoked_subcommand is None:
        console.print("[bold blue]Redroid FB Multi-Account Manager CLI Suite (my-manager.v2)[/bold blue]")
        console.print("Run [cyan]python main-cli.py --help[/cyan] to display available options.")


if __name__ == "__main__":
    app()
