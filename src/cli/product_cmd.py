"""CLI Subcommands for Real Estate Product Inspection from CRM Server / DB."""

import typer
from rich.console import Console
from rich.table import Table

from src.services.v1_bridge import V1DatabaseBridge

app = typer.Typer(help="Inspect real estate products from CRM Server (192.168.1.12) / DB.")
console = Console()


@app.command("sync")
def sync_crm(
    force: bool = typer.Option(True, "--force/--no-force", help="Force download latest snapshot from CRM server"),
):
    """Sync latest SQLite database snapshot from CRM server (192.168.1.12)."""
    bridge = V1DatabaseBridge()
    console.print(f"[cyan]Connecting to CRM server at {bridge._crm_url}...[/cyan]")
    success = bridge.sync_crm_database(force=force)
    if success:
        console.print(f"[bold green]✅ Synced CRM database successfully to {bridge._crm_db_path}[/bold green]")
    else:
        console.print(f"[bold red]❌ Failed to sync CRM database from {bridge._crm_url}[/bold red]")


@app.command("random")
def get_random_product(
    watermark: bool = typer.Option(True, "--watermark/--no-watermark", help="Prioritize watermarked images"),
):
    """Get a random active selling real estate product from v1 DB."""
    bridge = V1DatabaseBridge()
    product = bridge.get_random_active_real_estate()
    if not product:
        console.print("[bold red]No active real estate product found in v1 DB.[/bold red]")
        return

    title, desc = bridge.format_product_summary(product)
    images = bridge.get_product_images(str(product.get("id")), is_watermark=watermark)

    console.print(f"[bold cyan]Product ID:[/bold cyan] {product.get('id')} ({product.get('pid')})")
    console.print(f"[bold green]Title:[/bold green] {title}")
    console.print(f"[bold yellow]Price:[/bold yellow] {product.get('price')} {product.get('unit')}")
    console.print(f"[bold yellow]Area:[/bold yellow] {product.get('area')} m2")
    console.print(f"[bold magenta]Images ({len(images)}):[/bold magenta] {images[:3]}")
    console.print(f"[white]Description:[/white]\n{desc}")
