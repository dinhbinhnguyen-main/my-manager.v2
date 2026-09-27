"""CLI Subcommands for Proxy Management."""

import typer
from rich.console import Console
from rich.table import Table
from typing import Optional

from src.core.models import Proxy, ProxyStatus
from src.db.repository import ProxyRepository

app = typer.Typer(help="Manage Proxy servers and Rotation API URLs.")
console = Console()


@app.command("add")
def add_proxy(
    url: str = typer.Option(..., help="Proxy Rotation API URL (e.g. https://proxyxoay.shop/api/get.php?key=...)"),
    name: Optional[str] = typer.Option(None, help="Descriptive name (e.g. Proxy_Viettel_01)"),
    status: str = typer.Option("available", help="Initial status: available, working, unavailable"),
):
    """Add a new Proxy Rotation API URL."""
    p_status = ProxyStatus.AVAILABLE
    if status.lower() == "working":
        p_status = ProxyStatus.WORKING
    elif status.lower() == "unavailable":
        p_status = ProxyStatus.UNAVAILABLE

    proxy = Proxy(name=name, url=url, status=p_status)
    ProxyRepository.add(proxy)
    console.print(f"[bold green]Added Proxy API URL successfully: '{name or url}'[/bold green]")


@app.command("list")
def list_proxies():
    """List all stored Proxy Rotation API URLs."""
    proxies = ProxyRepository.list_all()
    table = Table(title="Proxy Rotation API URLs", show_lines=True)
    table.add_column("ID", style="cyan")
    table.add_column("Name", style="magenta")
    table.add_column("Rotation API URL", style="white")
    table.add_column("Current HTTP Proxy", style="yellow")
    table.add_column("Status", style="bold white")
    table.add_column("Assigned UID", style="green")

    for p in proxies:
        status_str = p.status.value if hasattr(p.status, 'value') else str(p.status)
        status_color = "green" if status_str == "available" else "yellow" if status_str == "working" else "red"

        table.add_row(
            str(p.id),
            p.name or "-",
            p.url[:45] + "..." if len(p.url) > 45 else p.url,
            p.current_proxy_http or "-",
            f"[{status_color}]{status_str}[/{status_color}]",
            p.assigned_account_uid or "-",
        )
    console.print(table)


@app.command("set-status")
def set_proxy_status(
    proxy_id_or_url: str = typer.Argument(..., help="Proxy ID or Rotation URL"),
    status: str = typer.Argument(..., help="Target status: available, working, unavailable"),
):
    """Set the status of a Proxy URL manually."""
    if status.lower() not in ["available", "working", "unavailable"]:
        console.print("[bold red]Invalid status. Must be one of: available, working, unavailable[/bold red]")
        return

    ProxyRepository.set_status(proxy_id_or_url, status.lower())
    console.print(f"[bold green]Updated status for Proxy '{proxy_id_or_url}' to '{status.lower()}'[/bold green]")


@app.command("delete")
def delete_proxy(
    target: str = typer.Argument(..., help="Proxy ID, Name, or Rotation URL to delete"),
):
    """Delete a Proxy API URL from database."""
    if ProxyRepository.delete(target):
        console.print(f"[bold green]Successfully deleted Proxy '{target}' from database.[/bold green]")
    else:
        console.print(f"[bold red]Proxy '{target}' not found in database.[/bold red]")

