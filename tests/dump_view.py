#!/usr/bin/env python3
"""
tests/dump_view.py - UI Hierarchy Dump & Screenshot Tool for Redroid & Android Devices.

Dumps:
1. Screen snapshot (PNG)
2. Raw UI hierarchy (XML)
3. Structured parsed elements with coordinates & suggested selectors (JSON)
4. Terminal summary table for rapid analysis of buttons, fields, and text
"""

import os
import sys
import json
import time
import argparse
import subprocess
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import List, Dict, Any, Optional, Tuple

# Ensure project root is in sys.path
root_dir = Path(__file__).resolve().parent.parent
if str(root_dir) not in sys.path:
    sys.path.append(str(root_dir))

import uiautomator2 as u2
from adbutils import adb

try:
    from rich.console import Console
    from rich.table import Table
    from rich.panel import Panel
    from rich import box
    RICH_AVAILABLE = True
except ImportError:
    RICH_AVAILABLE = False


console = Console() if RICH_AVAILABLE else None


def resolve_port_from_uid(uid: str) -> Optional[int]:
    """Looks up ADB port for a given Facebook UID from data/manager.db."""
    import sqlite3
    db_path = root_dir / "data" / "manager.db"
    if not db_path.exists():
        return None
    try:
        conn = sqlite3.connect(str(db_path))
        cursor = conn.cursor()
        cursor.execute("SELECT adb_port FROM redroid_instances WHERE fb_uid = ? LIMIT 1", (str(uid),))
        row = cursor.fetchone()
        if row and row[0]:
            return int(row[0])
        cursor.execute(
            """SELECT r.adb_port FROM redroid_instances r 
               JOIN accounts a ON a.container_id = r.container_id 
               WHERE a.uid = ? LIMIT 1""",
            (str(uid),)
        )
        row = cursor.fetchone()
        if row and row[0]:
            return int(row[0])
    except Exception as e:
        if console:
            console.print(f"[yellow]⚠️ Could not query manager.db: {e}[/yellow]")
        else:
            print(f"⚠️ Could not query manager.db: {e}")
    finally:
        conn.close()
    return None


def ensure_adb_connected(port: int, host: str = "127.0.0.1") -> str:
    """Runs adb connect on the target port if not already connected."""
    device_serial = f"{host}:{port}"
    try:
        subprocess.run(["adb", "connect", device_serial], stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=5)
    except Exception:
        pass
    return device_serial


def get_available_devices() -> List[str]:
    """Retrieves list of connected ADB device serials."""
    try:
        return [d.serial for d in adb.device_list()]
    except Exception:
        pass
    try:
        out = subprocess.check_output(["adb", "devices"], universal_newlines=True)
        devices = []
        for line in out.strip().split("\n")[1:]:
            parts = line.split()
            if len(parts) >= 2 and parts[1] == "device":
                devices.append(parts[0])
        return devices
    except Exception:
        return []


def parse_bounds(bounds_str: str) -> Tuple[Optional[Tuple[int, int]], Optional[Tuple[int, int]]]:
    """
    Parses bounds string '[x1,y1][x2,y2]' to:
    (center_x, center_y), (width, height)
    """
    import re
    match = re.match(r"\[(\d+),(\d+)\]\[(\d+),(\d+)\]", bounds_str)
    if match:
        x1, y1, x2, y2 = map(int, match.groups())
        cx = (x1 + x2) // 2
        cy = (y1 + y2) // 2
        w = x2 - x1
        h = y2 - y1
        return (cx, cy), (w, h)
    return None, None


def parse_hierarchy_node(node: ET.Element, depth: int = 0) -> List[Dict[str, Any]]:
    """Recursively parses XML node into structured element dictionaries."""
    elements = []
    attrib = node.attrib

    class_name = attrib.get("class", "")
    resource_id = attrib.get("resource-id", "")
    text = attrib.get("text", "")
    desc = attrib.get("content-desc", "")
    clickable = attrib.get("clickable", "false").lower() == "true"
    enabled = attrib.get("enabled", "true").lower() == "true"
    checked = attrib.get("checked", "false").lower() == "true"
    scrollable = attrib.get("scrollable", "false").lower() == "true"
    focusable = attrib.get("focusable", "false").lower() == "true"
    bounds = attrib.get("bounds", "")

    center, size = parse_bounds(bounds)
    short_class = class_name.split(".")[-1] if class_name else ""

    # Keep nodes with actionable attributes or textual/semantic content
    has_info = bool(
        text or desc or resource_id or 
        (clickable and class_name not in ["android.view.View", "android.widget.FrameLayout", "android.view.ViewGroup"]) or
        focusable
    )

    if has_info:
        # Generate optimal uiautomator2 selector suggestion
        suggested_selector = ""
        xpath_selector = ""
        if resource_id:
            suggested_selector = f'd(resourceId="{resource_id}")'
            xpath_selector = f'//*[@resource-id="{resource_id}"]'
        elif text:
            clean_text = text.replace('"', '\\"')
            suggested_selector = f'd(text="{clean_text}")'
            xpath_selector = f'//*[@text="{clean_text}"]'
        elif desc:
            clean_desc = desc.replace('"', '\\"')
            suggested_selector = f'd(description="{clean_desc}")'
            xpath_selector = f'//*[@content-desc="{clean_desc}"]'
        elif short_class:
            suggested_selector = f'd(className="{class_name}")'

        elements.append({
            "class": class_name,
            "short_class": short_class,
            "resource_id": resource_id,
            "text": text,
            "content_desc": desc,
            "clickable": clickable,
            "enabled": enabled,
            "checked": checked,
            "scrollable": scrollable,
            "bounds": bounds,
            "center": list(center) if center else None,
            "size": list(size) if size else None,
            "suggested_selector": suggested_selector,
            "xpath": xpath_selector,
        })

    for child in node:
        elements.extend(parse_hierarchy_node(child, depth + 1))

    return elements


def dump_screen(
    device_target: str,
    output_dir_name: str = "dumps",
    take_screenshot: bool = True,
    tag: Optional[str] = None
) -> Dict[str, Any]:
    """
    Connects to the specified target (port or serial), captures XML + PNG, parses elements,
    and returns a summary dict.
    """
    timestamp = time.strftime("%Y%m%d_%H%M%S")
    folder_name = f"{tag}_{timestamp}" if tag else timestamp
    base_dumps_dir = root_dir / "tests" / output_dir_name
    output_dir = base_dumps_dir / folder_name
    output_dir.mkdir(parents=True, exist_ok=True)

    latest_dir = base_dumps_dir / "latest"
    latest_dir.mkdir(parents=True, exist_ok=True)

    msg = f"Connecting to Android Device / Redroid on: {device_target}"
    if console:
        console.print(Panel(f"[bold cyan]{msg}[/bold cyan]\n[dim]Target Folder: {output_dir}[/dim]", title="📱 UI Dump Tool"))
    else:
        print(f"\n=== {msg} ===\nTarget: {output_dir}")

    try:
        d = u2.connect(device_target)
        # Verify connection
        _ = d.info
    except Exception as e:
        err_msg = f"❌ Failed to connect to '{device_target}': {e}\nPlease verify the Redroid container is running and ADB port is accessible."
        if console:
            console.print(f"[bold red]{err_msg}[/bold red]")
        else:
            print(err_msg)
        return {}

    app_info = {}
    try:
        app_info = d.app_current()
    except Exception:
        pass

    # 1. Capture XML Hierarchy
    xml_dump = d.dump_hierarchy()
    xml_file = output_dir / "dumped_view.xml"
    with open(xml_file, "w", encoding="utf-8") as f:
        f.write(xml_dump)

    # 2. Parse elements
    root = ET.fromstring(xml_dump)
    elements = parse_hierarchy_node(root)

    json_data = {
        "device": device_target,
        "timestamp": timestamp,
        "app_current": app_info,
        "total_elements": len(elements),
        "elements": elements
    }
    json_file = output_dir / "dumped_view.json"
    with open(json_file, "w", encoding="utf-8") as f:
        json.dump(json_data, f, ensure_ascii=False, indent=2)

    # 3. Screenshot
    png_file = output_dir / "dumped_screen.png"
    if take_screenshot:
        try:
            d.screenshot(str(png_file))
        except Exception as e:
            if console:
                console.print(f"[yellow]⚠️ Failed to capture screenshot: {e}[/yellow]")
            else:
                print(f"⚠️ Failed to capture screenshot: {e}")

    # 4. Mirror to 'latest/' directory for instant reference
    import shutil
    try:
        shutil.copy2(xml_file, latest_dir / "dumped_view.xml")
        shutil.copy2(json_file, latest_dir / "dumped_view.json")
        if png_file.exists():
            shutil.copy2(png_file, latest_dir / "dumped_screen.png")
    except Exception:
        pass

    # 5. Display Element Table
    if RICH_AVAILABLE:
        table = Table(title=f"Detected UI Elements ({len(elements)} items)", box=box.ROUNDED)
        table.add_column("#", style="dim", width=4)
        table.add_column("Widget", style="cyan", width=18)
        table.add_column("Text / Content-Desc", style="bold white", width=34)
        table.add_column("Resource-ID", style="yellow", width=22)
        table.add_column("Click", style="green", width=6)
        table.add_column("Center", style="magenta", width=12)
        table.add_column("Suggested Selector", style="dim white", width=35)

        for idx, el in enumerate(elements, start=1):
            content = el["text"] or el["content_desc"] or ""
            if len(content) > 32:
                content = content[:30] + "..."

            res_id = el["resource_id"]
            if len(res_id) > 20:
                res_id = "..." + res_id[-18:]

            clk_str = "[bold green]YES[/bold green]" if el["clickable"] else "[dim]NO[/dim]"
            center_str = f"({el['center'][0]},{el['center'][1]})" if el["center"] else ""
            selector_str = el["suggested_selector"] or ""
            if len(selector_str) > 33:
                selector_str = selector_str[:31] + "..."

            table.add_row(
                str(idx),
                el["short_class"],
                content,
                res_id,
                clk_str,
                center_str,
                selector_str
            )
        console.print(table)

        summary_panel = (
            f"[bold green]✓ UI Dump Complete![/bold green]\n\n"
            f"📄 [bold]XML View:[/bold]       {xml_file}\n"
            f"📊 [bold]JSON Details:[/bold]   {json_file}\n"
            f"📸 [bold]Screenshot:[/bold]     {png_file if png_file.exists() else 'N/A'}\n"
            f"🔗 [bold]Latest Mirror:[/bold]  {latest_dir}/"
        )
        console.print(Panel(summary_panel, title="📁 Output Files"))
    else:
        print(f"\n{'#':<4} | {'Widget':<18} | {'Text / Content-Desc':<32} | {'Resource-ID':<20} | {'Click':<5} | {'Center':<10}")
        print("-" * 95)
        for idx, el in enumerate(elements, start=1):
            content = el["text"] or el["content_desc"] or ""
            if len(content) > 30:
                content = content[:28] + "..."
            res_id = el["resource_id"]
            if len(res_id) > 18:
                res_id = "..." + res_id[-16:]
            clk = "YES" if el["clickable"] else "NO"
            center_str = f"({el['center'][0]},{el['center'][1]})" if el["center"] else ""
            print(f"{idx:<4} | {el['short_class']:<18} | {content:<32} | {res_id:<20} | {clk:<5} | {center_str:<10}")

        print(f"\n✓ Dumped {len(elements)} elements to: {output_dir}")
        print(f"  - XML : {xml_file}")
        print(f"  - JSON: {json_file}")
        print(f"  - PNG : {png_file}")

    return {
        "output_dir": str(output_dir),
        "xml_file": str(xml_file),
        "json_file": str(json_file),
        "png_file": str(png_file) if png_file.exists() else None,
        "total_elements": len(elements)
    }


def main():
    parser = argparse.ArgumentParser(description="Dump screen screenshot, XML hierarchy, and interactive elements via port or serial")
    parser.add_argument("-p", "--port", type=str, default=None, help="ADB Port of device (e.g. 5555, 5565, or 127.0.0.1:5555)")
    parser.add_argument("-u", "--uid", type=str, default=None, help="Facebook UID (resolves ADB port automatically)")
    parser.add_argument("-d", "--device", type=str, default=None, help="ADB Serial of device")
    parser.add_argument("--tag", type=str, default=None, help="Optional tag for output folder (e.g. step_3_photos)")
    parser.add_argument("--no-photo", action="store_true", help="Skip capturing screenshot PNG")
    parser.add_argument("--dir", type=str, default="dumps", help="Subdirectory inside tests/ for output (default: dumps)")

    args = parser.parse_args()

    target = None

    # 1. Resolve from UID
    if args.uid:
        resolved_port = resolve_port_from_uid(args.uid)
        if resolved_port:
            target = ensure_adb_connected(resolved_port)
            if console:
                console.print(f"[green]✓ Resolved UID {args.uid} -> ADB Port {resolved_port}[/green]")
        else:
            if console:
                console.print(f"[bold red]❌ Could not find ADB Port for UID {args.uid} in manager.db[/bold red]")
            sys.exit(1)

    # 2. Resolve from Port
    elif args.port:
        port_clean = str(args.port).strip()
        if ":" in port_clean:
            host, p_str = port_clean.split(":", 1)
            target = ensure_adb_connected(int(p_str), host=host)
        else:
            target = ensure_adb_connected(int(port_clean))

    # 3. Direct device serial
    elif args.device:
        target = args.device

    # 4. Auto-detect from connected devices
    if not target:
        available = get_available_devices()
        if len(available) == 1:
            target = available[0]
            if console:
                console.print(f"[cyan]ℹ️ Auto-selected single connected device: [bold]{target}[/bold][/cyan]")
        elif len(available) > 1:
            if console:
                console.print("\n[bold yellow]Multiple ADB devices detected:[/bold yellow]")
                for i, dev in enumerate(available, 1):
                    console.print(f"  [[bold cyan]{i}[/bold cyan]] {dev}")
            else:
                print("Multiple ADB devices detected:")
                for i, dev in enumerate(available, 1):
                    print(f"  [{i}] {dev}")

            try:
                choice = input(f"Select device (1-{len(available)}, default 1): ").strip()
                if choice.isdigit() and 1 <= int(choice) <= len(available):
                    target = available[int(choice) - 1]
                else:
                    target = available[0]
            except Exception:
                target = available[0]
        else:
            msg = "❌ No ADB device specified and none connected. Use --port <PORT> or --uid <UID>."
            if console:
                console.print(f"[bold red]{msg}[/bold red]")
            else:
                print(msg)
            sys.exit(1)

    dump_screen(
        device_target=target,
        output_dir_name=args.dir,
        take_screenshot=not args.no_photo,
        tag=args.tag or (f"port_{args.port}" if args.port else None)
    )


if __name__ == "__main__":
    main()
