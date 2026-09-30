"""CLI Subcommands for System Settings Management."""

import typer
from rich.console import Console
from rich.table import Table
from typing import Optional

from src.db.repository import SettingRepository

app = typer.Typer(help="Manage application settings (container storage path, Gemini API Key, v1 DB Path, v1 Image Dir).")
console = Console()


@app.command("list")
def list_settings():
    """List all application settings."""
    settings = SettingRepository.list_all()
    table = Table(title="Application Settings", show_lines=True)
    table.add_column("Setting Name", style="cyan", no_wrap=True)
    table.add_column("Value", style="magenta")
    table.add_column("Updated At", style="yellow")

    for s in settings:
        val = s["value"] or ""
        # Mask sensitive keys like API keys in list view
        if "key" in s["name"].lower() and len(val) > 8:
            display_val = val[:4] + "..." + val[-4:]
        else:
            display_val = val or "-"

        table.add_row(s["name"], display_val, str(s["updated_at"]))

    console.print(table)


@app.command("set")
def set_setting(
    name: str = typer.Option(..., help="Setting name (e.g. container, gemini_api_key, v1_db_path, v1_image_dir)"),
    value: str = typer.Option(..., help="Setting string value"),
):
    """Set or update a configuration setting."""
    SettingRepository.set(name, value)
    console.print(f"[bold green]Successfully updated setting '{name}'![/bold green]")


@app.command("get")
def get_setting(name: str):
    """Get value of a specific setting by name."""
    val = SettingRepository.get(name)
    console.print(f"[cyan]{name}[/cyan] = [yellow]{val}[/yellow]")
