"""CLI Subcommands for Account Management."""

import typer
from rich.console import Console
from rich.table import Table
from typing import Optional

from src.core.models import Account, AccountStatus
from src.db.repository import AccountRepository

app = typer.Typer(help="Manage Facebook accounts.")
console = Console()


@app.command("list")
def list_accounts(
    status: Optional[str] = typer.Option(None, help="Filter by status (live, checkpoint, idle, etc.)"),
    group: Optional[int] = typer.Option(None, help="Filter by group ID"),
    limit: int = typer.Option(50, help="Max records to return"),
):
    """List Facebook accounts in database."""
    accounts = AccountRepository.list_all(status=status, group_id=group, limit=limit)
    
    table = Table(title="Facebook Accounts", show_lines=True)
    table.add_column("UID", style="cyan", no_wrap=True)
    table.add_column("Username", style="bright_cyan")
    table.add_column("Password", style="magenta")
    table.add_column("Category (Niche)", style="yellow")
    table.add_column("Trans. Type", style="bright_yellow")
    table.add_column("Status", style="bold green")
    table.add_column("Container ID", style="blue")
    table.add_column("Note", style="white")

    for acc in accounts:
        status_color = "green" if acc.status == AccountStatus.LIVE else "red" if acc.status == AccountStatus.CHECKPOINT else "yellow"
        table.add_row(
            acc.uid,
            acc.username or "-",
            acc.password[:6] + "..." if len(acc.password) > 6 else acc.password,
            acc.category or "real_estate",
            acc.transaction_type or "rental",
            f"[{status_color}]{acc.status.value}[/{status_color}]",
            acc.container_id or "-",
            acc.note or "-",
        )

    console.print(table)


@app.command("add")
def add_account(
    uid: str = typer.Option(..., help="Facebook UID"),
    password: str = typer.Option(..., help="Account password"),
    username: Optional[str] = typer.Option(None, "--username", "-u", help="Facebook username / Vanity name"),
    two_fa: Optional[str] = typer.Option(None, help="2FA Secret Key"),
    category: str = typer.Option("real_estate", "--category", "-c", help="Product category niche: real_estate, tire, fashion"),
    transaction_type: str = typer.Option("rental", "--transaction-type", "-t", help="Target transaction type: rental, sale"),
    group: int = typer.Option(1, help="Group ID"),
    note: Optional[str] = typer.Option(None, help="Note"),
):
    """Add a new Facebook account with niche category and transaction type matching."""
    acc = Account(
        uid=uid,
        username=username,
        password=password,
        two_fa=two_fa,
        category=category,
        transaction_type=transaction_type,
        group_id=group,
        note=note,
    )
    AccountRepository.add(acc)
    console.print(f"[bold green]Successfully added account UID {uid} (Category: {category}, TransType: {transaction_type})[/bold green]")



@app.command("show")
def show_account(uid: str):
    """Display detailed info for a specific UID."""
    acc = AccountRepository.get_by_uid(uid)
    if not acc:
        console.print(f"[bold red]Account UID {uid} not found.[/bold red]")
        return
    console.print(acc.model_dump())


@app.command("delete")
def delete_account(
    target: Optional[str] = typer.Argument(None, help="Account UID or DB ID to delete (supports comma-separated list)"),
    delete_all: bool = typer.Option(False, "--all", help="Delete all accounts and associated containers"),
):
    """Delete account(s) by UID or ID, automatically purging Redroid Docker container and data/containers/<uid> storage."""
    from src.redroid.manager import RedroidManager

    docker_mgr = RedroidManager()

    if delete_all:
        accs = AccountRepository.list_all(limit=10000)
        if not accs:
            console.print("[yellow]No accounts found in database to delete.[/yellow]")
            return
        deleted_count = 0
        for acc in accs:
            # Purge Docker container & data/containers/<uid> directory on disk
            docker_mgr.remove_instance(acc.uid)
            # Remove account record from DB
            AccountRepository.delete(acc.uid)
            deleted_count += 1
        console.print(f"[bold red]Purged all {deleted_count} accounts, Docker containers, and disk storage directories![/bold red]")
        return

    if not target:
        console.print("[bold red]Please specify an account UID/ID or pass --all flag.[/bold red]")
        return

    targets = [t.strip() for t in target.split(",") if t.strip()]
    deleted_count = 0

    from src.core.constants import DATA_DIR

    for t in targets:
        acc = AccountRepository.get_by_id_or_uid(t)
        uid = acc.uid if acc else (t if t.isdigit() and len(t) > 5 else t)

        console.print(f"[cyan]Purging account UID/target '{uid}'...[/cyan]")

        # 1. Purge Redroid Docker Container & data/containers/<uid> on disk
        docker_mgr.remove_instance(uid)

        # Fallback disk cleanup if directory still exists
        storage_dir = docker_mgr.get_container_storage_dir(uid)
        if storage_dir.exists():
            docker_mgr._delete_container_storage(storage_dir)

        # 2. Delete DB records (accounts, automation_jobs, automation_tasks)
        db_deleted = AccountRepository.delete(uid)
        if db_deleted or not storage_dir.exists():
            console.print(f"[bold green]Successfully deleted account UID {uid}, Docker container, and data/containers/{uid} folder.[/bold green]")
            deleted_count += 1
        else:
            console.print(f"[yellow]Account UID {uid} processed.[/yellow]")

    console.print(f"[bold green]Completed account deletion operation. Total deleted: {deleted_count}[/bold green]")
    return True


@app.command("set-group")
def set_group_cmd(
    target_group: int = typer.Option(..., "--to", "-t", help="Target group_id to assign accounts to (e.g. 0, 1, 2)"),
    from_group: Optional[int] = typer.Option(None, "--from", "-f", help="Source group_id to move accounts from (e.g. -1)"),
    uids: Optional[str] = typer.Option(None, "--uids", "-u", help="Comma-separated account UIDs to assign"),
    limit: Optional[int] = typer.Option(None, "--limit", "-l", help="Limit number of accounts to move"),
    all_accounts: bool = typer.Option(False, "--all", "-a", help="Move all accounts in database to target group"),
):
    """
    Quickly adjust group_id for accounts:
    - Move accounts from one group to another (e.g. --from -1 --to 0)
    - Assign group_id to specific UIDs (e.g. --uids uid1,uid2 --to 0)
    - Move a specific number of accounts (e.g. --from -1 --to 0 --limit 50)
    """
    if not all_accounts and from_group is None and not uids:
        console.print("[bold red]Please specify --from <group_id>, --uids <uid1,uid2>, or --all.[/bold red]")
        return

    uid_list = None
    if uids:
        import re
        raw = [re.sub(r'[\'"\s]', '', u) for u in uids.split(",")]
        uid_list = [u for u in raw if u]

    updated = AccountRepository.update_group_id(
        target_group_id=target_group,
        uids=uid_list,
        from_group_id=from_group if not all_accounts else None,
        limit=limit,
    )

    console.print(f"[bold green]✅ Successfully updated {updated} account(s) to group_id = {target_group}![/bold green]")



