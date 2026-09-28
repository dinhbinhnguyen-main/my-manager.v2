"""CLI Subcommands for Redroid Container Management."""

import typer
from rich.console import Console
from rich.table import Table
from typing import Optional

from src.redroid.manager import RedroidManager
from src.db.repository import RedroidRepository, AccountRepository

app = typer.Typer(help="Manage Redroid Docker containers.")
console = Console()
manager = RedroidManager()


@app.command("create")
def create_container(
    uid: str = typer.Option(..., help="Facebook UID bound to this container"),
    proxy: Optional[str] = typer.Option(None, help="Proxy URL (http://user:pass@host:port)"),
    apk: Optional[str] = typer.Option(None, help="Path to Facebook APK file (default: data/apks/facebook.apk)"),
):
    """Create and provision a new Redroid container bound to an account and install Facebook APK."""
    acc = AccountRepository.get_by_uid(uid)
    if not acc:
        console.print(f"[bold red]Account UID {uid} not found in DB. Add account first.[/bold red]")
        return

    console.print(f"[cyan]Provisioning Redroid container for UID {uid}...[/cyan]")
    try:
        inst = manager.create_instance(account_uid=uid, proxy_url=proxy, apk_path=apk)
        AccountRepository.bind_container(uid, inst.container_id, inst.device_profile_id or "")
        console.print(f"[bold green]Redroid Container Created & Facebook APK Installed! ID: {inst.container_id}, ADB Port: {inst.adb_port}[/bold green]")
    except RuntimeError as e:
        console.print(f"[bold red]{e}[/bold red]")


@app.command("list")
def list_containers():
    """List all managed Redroid instances with real-time Docker live status."""
    instances = RedroidRepository.list_all()
    table = Table(title="Redroid Docker Instances", show_lines=True)
    table.add_column("Container ID", style="cyan")
    table.add_column("Container Name", style="magenta")
    table.add_column("ADB Port", style="yellow")
    table.add_column("FB UID", style="green")
    table.add_column("Live Status", style="bold")

    for inst in instances:
        live_status = manager.get_live_docker_status(inst.container_id)
        if live_status == "not_found":
            # Fallback check by name
            live_status = manager.get_live_docker_status(inst.container_name)

        if live_status == "running":
            status_display = "[bold green]● running[/bold green]"
        elif live_status == "stopped":
            status_display = "[bold yellow]■ stopped[/bold yellow]"
        else:
            status_display = "[bold red]✖ not found[/bold red]"

        table.add_row(
            inst.container_id[:10],
            inst.container_name,
            str(inst.adb_port),
            inst.account_uid or "-",
            status_display,
        )
    console.print(table)


@app.command("stop")
def stop_container(
    target: Optional[str] = typer.Argument(None, help="Container Name, ID, FB UID, or ADB Port to stop (or 'all' to stop all)"),
    stop_all: bool = typer.Option(False, "--all", "-a", help="Stop all currently running Redroid containers"),
):
    """Stop a running Redroid container (or stop all running containers with --all)."""
    if stop_all or target == "all":
        count = manager.stop_all_instances()
        console.print(f"[bold yellow]Successfully stopped all {count} running Redroid containers and released proxies.[/bold yellow]")
        return

    if not target:
        console.print("[bold red]Please specify a target container (UID, Port, Name) or pass --all.[/bold red]")
        return

    manager.stop_instance(target)
    console.print(f"[bold yellow]Successfully stopped container '{target}' and released Proxy.[/bold yellow]")


@app.command("start")
def start_container(
    target: str = typer.Argument(..., help="Container Name, ID, FB UID, or ADB Port to start"),
    proxy: Optional[str] = typer.Option(None, "--proxy", "-p", help="Specific Proxy URL, ID, or Name to assign and configure upon start"),
):
    """Start an existing stopped Redroid container with optional specific Proxy URL/ID/Name."""
    try:
        manager.start_instance(target, proxy_url=proxy)
        console.print(f"[bold green]Successfully started container '{target}' with assigned proxy.[/bold green]")
    except RuntimeError as e:
        console.print(f"[bold red]{e}[/bold red]")



@app.command("install-apk")
@app.command("install")
def install_apk_cmd(
    target: Optional[str] = typer.Argument(None, help="Target container (FB UID, Container ID, Name, ADB Port, or 'all')"),
    uids: Optional[str] = typer.Option(None, "--uids", "-u", help="Comma-separated list of account UIDs to install APK for"),
    install_all: bool = typer.Option(False, "--all", help="Install APK on ALL managed containers in database"),
    apk: str = typer.Option(..., "--apk", "-a", help="Path to APK file on PC host to install"),
):
    """Install an APK file onto single or multiple Redroid containers (auto-starts stopped containers if needed)."""
    target_uids = []
    if install_all or target == "all":
        instances = RedroidRepository.list_all()
        target_uids = [inst.account_uid or inst.container_name for inst in instances]
    elif uids:
        target_uids = [u.strip() for u in uids.split(",") if u.strip()]
    elif target:
        target_uids = [target]

    if not target_uids:
        console.print("[bold red]Please specify a target container (UID/Port/Name), pass --uids 'uid1,uid2', or pass --all.[/bold red]")
        return

    if len(target_uids) == 1:
        tgt = target_uids[0]
        console.print(f"[cyan]Installing APK '{apk}' on container '{tgt}' (auto-starting if stopped)...[/cyan]")
        try:
            success = manager.install_apk(tgt, apk, auto_start=True)
            if success:
                console.print(f"[bold green]Successfully installed APK '{apk}' on container '{tgt}'![/bold green]")
            else:
                console.print(f"[bold red]Failed to install APK '{apk}' on container '{tgt}'. Check ADB logs.[/bold red]")
        except Exception as e:
            console.print(f"[bold red]Error installing APK: {e}[/bold red]")
    else:
        console.print(f"[bold cyan]Starting batch APK installation on {len(target_uids)} profiles/containers...[/bold cyan]")
        results = manager.install_apk_batch(target_uids, apk_path=apk)

        table = Table(title=f"Batch APK Installation Results ({apk})", show_lines=True)
        table.add_column("Target Profile / Container", style="cyan")
        table.add_column("Result Status", style="bold")

        success_count = 0
        for tgt, ok in results.items():
            if ok:
                success_count += 1
                status_str = "[bold green]✔ Installed Successfully[/bold green]"
            else:
                status_str = "[bold red]✖ Failed / Error[/bold red]"
            table.add_row(tgt, status_str)

        console.print(table)
        console.print(f"[bold green]Completed Batch APK Install: {success_count}/{len(target_uids)} successful.[/bold green]")


@app.command("remove")
def remove_container(
    target: str = typer.Argument(..., help="Container Name, ID, FB UID, or ADB Port to remove"),
):
    """Remove a Redroid container from Docker and DB (accepts UID, Port, or Name)."""
    manager.remove_instance(target)
    console.print(f"[bold red]Successfully removed container '{target}' from Docker & Database.[/bold red]")


@app.command("check-ip")
def check_container_ip(
    target: Optional[str] = typer.Argument(None, help="Container name, ID, UID, or ADB port (leave blank to check all running)"),
):
    """Check Android system HTTP proxy and verify outbound Public IP for Redroid container(s)."""
    import subprocess
    import requests

    instances = RedroidRepository.list_all()
    if target:
        instances = [
            i for i in instances
            if target in (i.container_id, i.container_name, i.account_uid, str(i.adb_port))
        ]
        if not instances:
            # Fallback if user passed raw port like 5555
            try:
                raw_port = int(target)
                from src.core.models import RedroidInstance
                instances = [RedroidInstance(container_id="custom", container_name=f"port_{raw_port}", adb_port=raw_port, scrcpy_port=raw_port+2000, status="running")]
            except ValueError:
                console.print(f"[bold red]No matching container found for target '{target}'.[/bold red]")
                return

    if not instances:
        console.print("[bold yellow]No Redroid containers registered in database.[/bold yellow]")
        return

    table = Table(title="Redroid Outbound IP & Proxy Verification", show_lines=True)
    table.add_column("Container", style="magenta")
    table.add_column("ADB Port", style="yellow")
    table.add_column("FB UID", style="green")
    table.add_column("Android Setting (http_proxy)", style="cyan")
    table.add_column("Public Outbound IP", style="bold white")
    table.add_column("Location & ISP", style="bright_blue")
    table.add_column("Status", style="bold")

    for inst in instances:
        adb_target = f"127.0.0.1:{inst.adb_port}"
        # Ensure ADB connected
        subprocess.run(["adb", "connect", adb_target], capture_output=True)

        # 1. Read proxy from Android settings
        res = subprocess.run(
            ["adb", "-s", adb_target, "shell", "settings", "get", "global", "http_proxy"],
            capture_output=True,
            text=True,
            timeout=5,
        )
        android_proxy = res.stdout.strip()
        if android_proxy == "null" or not android_proxy or android_proxy == ":0":
            android_proxy = "None (Direct Connection)"
            is_proxy = False
        else:
            is_proxy = True

        # 2. Test outbound IP via that proxy
        public_ip = "-"
        location_isp = "-"
        status_text = "[red]Offline / Error[/red]"

        try:
            if is_proxy:
                proxy_url = f"http://{android_proxy}" if not android_proxy.startswith("http") else android_proxy
                resp = requests.get(
                    "http://ip-api.com/json",
                    proxies={"http": proxy_url, "https": proxy_url},
                    timeout=10,
                ).json()
                public_ip = resp.get("query", "Unknown")
                country = resp.get("country", "")
                city = resp.get("city", "")
                isp = resp.get("isp", "")
                location_isp = f"{city}, {country} ({isp})" if country else isp
                status_text = "[bold green]Proxy Working[/bold green]"
            else:
                # Direct check
                resp = requests.get("http://ip-api.com/json", timeout=10).json()
                public_ip = resp.get("query", "Unknown")
                location_isp = f"{resp.get('city', '')}, {resp.get('country', '')} ({resp.get('isp', '')})"
                status_text = "[yellow]Direct (Host IP)[/yellow]"
        except Exception as e:
            public_ip = "[red]Connection Failed[/red]"
            location_isp = str(e)[:30]
            status_text = "[bold red]Proxy Error[/bold red]"

        table.add_row(
            inst.container_name,
            str(inst.adb_port),
            inst.account_uid or "-",
            android_proxy,
            public_ip,
            location_isp,
            status_text,
        )

    console.print(table)


@app.command("scrcpy")
def scrcpy_cmd(
    target: Optional[str] = typer.Argument(None, help="Target container (UID, Container ID, Name, or ADB Port)"),
    target_opt: Optional[str] = typer.Option(None, "--target", "-t", help="Target container option"),
    open_win: bool = typer.Option(False, "--open", "-o", help="Explicitly open scrcpy window for target"),
    close_win: bool = typer.Option(False, "--close", "-c", help="Explicitly close scrcpy window for target"),
    hide_keyboard: bool = typer.Option(False, "--hide-keyboard", "-k", help="Force disable on-screen virtual keyboard for container(s)"),
    show_keyboard: bool = typer.Option(False, "--show-keyboard", help="Re-enable on-screen virtual keyboard for container(s)"),
    paste: Optional[str] = typer.Option(None, "--paste", "-p", help="Text to paste into container (or use -P to paste PC clipboard)"),
    paste_clip: bool = typer.Option(False, "--paste-clipboard", "-P", help="Paste current PC clipboard into target container"),
    once: bool = typer.Option(False, "--once", "-1", help="Sync once and display table without continuous watching"),
    interval: float = typer.Option(1.5, "--interval", "-i", help="Watch loop refresh interval in seconds"),
):
    """Real-time process supervisor to track Redroid containers and auto open/close scrcpy GUI windows."""
    from src.redroid.scrcpy_manager import ScrcpyManager

    scrcpy_mgr = ScrcpyManager()
    resolved_target = target or target_opt

    # Action: Explicitly hide on-screen virtual keyboard
    if hide_keyboard:
        targets_to_act = []
        if resolved_target:
            targets_to_act = [resolved_target]
        else:
            targets_to_act = [
                i.container_name for i in RedroidRepository.list_all()
                if manager.get_live_docker_status(i.container_name) == "running"
            ]

        if not targets_to_act:
            console.print("[bold yellow]No running containers found to disable virtual keyboard.[/bold yellow]")
            return

        table = Table(title="Disable Virtual Soft Keyboard", show_lines=True)
        table.add_column("Container / Target", style="cyan")
        table.add_column("ADB Port", style="yellow")
        table.add_column("FB UID", style="green")
        table.add_column("Virtual Keyboard Status", style="bold")

        for tgt in targets_to_act:
            c_name, acc_uid = manager.resolve_target(tgt)
            inst = RedroidRepository.get_by_identifier(tgt)
            port_str = str(inst.adb_port) if inst else (tgt if tgt.isdigit() and len(tgt) <= 5 else "-")
            ok = scrcpy_mgr.hide_virtual_keyboard(tgt)
            status_str = "[bold green]✔ DISABLED[/bold green]" if ok else "[bold red]✖ FAILED[/bold red]"
            table.add_row(c_name or tgt, port_str, acc_uid or (inst.account_uid if inst else "-") or "-", status_str)

        console.print(table)
        console.print(f"[bold green]✔ Successfully disabled virtual keyboard on {len(targets_to_act)} container(s).[/bold green]")
        return

    # Action: Explicitly show/re-enable virtual keyboard
    if show_keyboard:
        targets_to_act = []
        if resolved_target:
            targets_to_act = [resolved_target]
        else:
            targets_to_act = [
                i.container_name for i in RedroidRepository.list_all()
                if manager.get_live_docker_status(i.container_name) == "running"
            ]

        if not targets_to_act:
            console.print("[bold yellow]No running containers found to re-enable virtual keyboard.[/bold yellow]")
            return

        table = Table(title="Enable Virtual Soft Keyboard", show_lines=True)
        table.add_column("Container / Target", style="cyan")
        table.add_column("ADB Port", style="yellow")
        table.add_column("FB UID", style="green")
        table.add_column("Virtual Keyboard Status", style="bold")

        for tgt in targets_to_act:
            c_name, acc_uid = manager.resolve_target(tgt)
            inst = RedroidRepository.get_by_identifier(tgt)
            port_str = str(inst.adb_port) if inst else (tgt if tgt.isdigit() and len(tgt) <= 5 else "-")
            ok = scrcpy_mgr.show_virtual_keyboard(tgt)
            status_str = "[bold green]✔ ENABLED[/bold green]" if ok else "[bold red]✖ FAILED[/bold red]"
            table.add_row(c_name or tgt, port_str, acc_uid or (inst.account_uid if inst else "-") or "-", status_str)

        console.print(table)
        return

    # Action: Paste text or PC clipboard into container
    if paste is not None or paste_clip:
        adb_port = None
        if resolved_target:
            inst = RedroidRepository.get_by_identifier(resolved_target)
            adb_port = inst.adb_port if inst else (int(resolved_target) if resolved_target.isdigit() else None)
        else:
            running = [i for i in RedroidRepository.list_all() if manager.get_live_docker_status(i.container_name) == "running"]
            if len(running) == 1:
                adb_port = running[0].adb_port
                resolved_target = running[0].account_uid or str(adb_port)
            elif len(running) > 1:
                console.print(f"[bold red]Multiple running containers detected ({len(running)}). Please specify target UID or Port.[/bold red]")
                return
            else:
                console.print("[bold red]No running containers found to paste into.[/bold red]")
                return

        if not adb_port:
            console.print(f"[bold red]Could not resolve container for target '{resolved_target}'.[/bold red]")
            return

        text_to_paste = paste if (paste is not None and paste != "") else None
        if scrcpy_mgr.paste_to_device(adb_port, text=text_to_paste):
            console.print(f"[bold green]✔ Successfully pasted into Redroid (Target: {resolved_target}, Port: {adb_port})![/bold green]")
        else:
            console.print(f"[bold red]✖ Failed to paste into Redroid (Port: {adb_port}). Make sure clipboard has content or pass text with --paste 'text'.[/bold red]")
        return

    # 1. Action: Explicitly open scrcpy window for target
    if open_win or (resolved_target and not close_win and not once):
        c_name, acc_uid = manager.resolve_target(resolved_target)
        inst = RedroidRepository.get_by_identifier(resolved_target) if resolved_target else None
        if not inst and acc_uid:
            inst = RedroidRepository.get_by_account_uid(acc_uid)

        # Auto-create if container not created yet
        if not inst and acc_uid:
            from src.db.repository import AccountRepository
            acc = AccountRepository.get_by_uid(acc_uid)
            if acc:
                console.print(f"[cyan]Container for UID '{acc_uid}' ({acc.username}) does not exist. Auto-provisioning new container...[/cyan]")
                try:
                    inst = manager.create_instance(account_uid=acc_uid)
                    AccountRepository.bind_container(acc_uid, inst.container_id, inst.device_profile_id or "")
                except Exception as e:
                    console.print(f"[bold red]Failed to create container: {e}[/bold red]")
                    return

        # Auto-start if container is currently stopped
        if inst and manager.get_live_docker_status(inst.container_name) != "running":
            console.print(f"[cyan]Container '{inst.container_name}' is currently stopped. Auto-starting...[/cyan]")
            try:
                manager.start_instance(inst.container_name)
            except Exception as e:
                console.print(f"[bold red]Failed to start container: {e}[/bold red]")
                return

        adb_port = inst.adb_port if inst else (int(resolved_target) if resolved_target and resolved_target.isdigit() and len(resolved_target) <= 5 else None)
        if adb_port:
            # Ensure virtual keyboard is hidden for target
            scrcpy_mgr.hide_virtual_keyboard(adb_port)
            title = f"Redroid [UID: {inst.account_uid if inst else resolved_target}] (Port: {adb_port})"
            if scrcpy_mgr.open_scrcpy(adb_port, window_title=title):
                console.print(f"[bold green]Successfully opened scrcpy for target '{resolved_target}' (Port {adb_port}) [Virtual keyboard: DISABLED].[/bold green]")
            return
        elif resolved_target and open_win:
            console.print(f"[bold red]Could not resolve container for target '{resolved_target}'.[/bold red]")
            return

    # 2. Action: Explicitly close scrcpy window for target
    if close_win and resolved_target:
        inst = RedroidRepository.get_by_identifier(resolved_target)
        adb_port = inst.adb_port if inst else (int(resolved_target) if resolved_target.isdigit() else None)
        if adb_port:
            killed = scrcpy_mgr.close_scrcpy(adb_port)
            console.print(f"[bold yellow]Closed {killed} scrcpy window(s) for target '{resolved_target}' (Port {adb_port}).[/bold yellow]")
        else:
            console.print(f"[bold red]Could not resolve container for target '{resolved_target}'.[/bold red]")
        return

    # 3. Action: One-off sync and table print if --once is requested
    if once:
        res = scrcpy_mgr.sync_auto_scrcpy()
        console.print(f"[bold cyan]Scrcpy Process Auto-Sync Completed:[/bold cyan] Opened={res['opened']}, Closed={res['closed']}, Active Running Containers={res['running_containers']}")

        table = Table(title="Redroid Container Scrcpy Process Status", show_lines=True)
        table.add_column("Container", style="cyan")
        table.add_column("ADB Port", style="yellow")
        table.add_column("FB UID", style="green")
        table.add_column("Container Status", style="bold")
        table.add_column("Scrcpy GUI Status", style="bold white")
        table.add_column("Bàn Phím Ảo (IME)", style="bold")

        instances = RedroidRepository.list_all()
        scrcpy_pids = scrcpy_mgr.get_running_scrcpy_pids()

        for inst in instances:
            live_status = manager.get_live_docker_status(inst.container_name)
            pids = scrcpy_pids.get(inst.adb_port, [])

            c_status = "[bold green]● running[/bold green]" if live_status == "running" else "[yellow]■ stopped[/yellow]"
            s_status = f"[bold green]▶ OPEN (PID: {', '.join(map(str, pids))})[/bold green]" if pids else "[dim white]⏹ CLOSED[/dim white]"
            
            if live_status == "running":
                is_hidden = manager.is_virtual_keyboard_hidden(inst.container_name)
                kb_status = "[bold green]✔ ĐÃ ẨN[/bold green]" if is_hidden else "[bold yellow]⚠ HIỂN THỊ[/bold yellow]"
            else:
                kb_status = "[dim]-[/dim]"

            table.add_row(
                inst.container_name,
                str(inst.adb_port),
                inst.account_uid or "-",
                c_status,
                s_status,
                kb_status,
            )

        console.print(table)
        return

    # 4. DEFAULT: Run continuous real-time watch loop
    scrcpy_mgr.watch_loop(interval_seconds=interval)


