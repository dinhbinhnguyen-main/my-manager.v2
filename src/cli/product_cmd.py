"""CLI Subcommands for Real Estate Product Inspection from v1 DB."""

import typer
from rich.console import Console
from rich.table import Table

from src.services.v1_bridge import V1DatabaseBridge

app = typer.Typer(help="Inspect real estate products from my-manager.v1 DB.")
console = Console()


@app.command("random")
def get_random_product():
    """Get a random active selling real estate product from v1 DB."""
    bridge = V1DatabaseBridge()
    product = bridge.get_random_active_real_estate()
    if not product:
        console.print("[bold red]No active real estate product found in v1 DB.[/bold red]")
        return

    title, desc = bridge.format_product_summary(product)
    images = bridge.get_product_images(str(product.get("id")))

    console.print(f"[bold cyan]Product ID:[/bold cyan] {product.get('id')} ({product.get('pid')})")
    console.print(f"[bold green]Title:[/bold green] {title}")
    console.print(f"[bold yellow]Price:[/bold yellow] {product.get('price')} {product.get('unit')}")
    console.print(f"[bold yellow]Area:[/bold yellow] {product.get('area')} m2")
    console.print(f"[bold magenta]Images ({len(images)}):[/bold magenta] {images[:3]}")
    console.print(f"[white]Description:[/white]\n{desc}")
