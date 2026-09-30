"""Scrcpy Process Supervisor for Redroid Containers - High Performance Version."""

import os
import re
import time
import signal
import logging
import subprocess
from datetime import datetime
from typing import Dict, List, Optional, Any, Set
from pathlib import Path
from rich.console import Console
from rich.table import Table

from src.db.repository import RedroidRepository
from src.redroid.manager import RedroidManager

logger = logging.getLogger(__name__)
console = Console()


class ScrcpyManager:
    """Manages scrcpy GUI process windows bound to Redroid containers."""

    def __init__(self):
        self.docker_mgr = RedroidManager()
        self._keyboard_hidden_targets: Set[str] = set()

    def hide_virtual_keyboard(self, target: Any) -> bool:
        """Disables virtual on-screen soft keyboard for target container/port."""
        target_str = str(target)
        if target_str in self._keyboard_hidden_targets:
            return True
        ok = self.docker_mgr.hide_virtual_keyboard(target_str)
        if ok:
            self._keyboard_hidden_targets.add(target_str)
        return ok

    def show_virtual_keyboard(self, target: Any) -> bool:
        """Re-enables virtual on-screen soft keyboard for target container/port."""
        target_str = str(target)
        ok = self.docker_mgr.show_virtual_keyboard(target_str)
        if ok and target_str in self._keyboard_hidden_targets:
            self._keyboard_hidden_targets.discard(target_str)
        return ok

    def get_running_scrcpy_pids(self) -> Dict[int, List[int]]:
        """Returns a mapping of {adb_port: [pid_1, pid_2, ...]} for active scrcpy processes."""
        port_to_pids: Dict[int, List[int]] = {}
        try:
            res = subprocess.run(["ps", "-eo", "pid,args"], capture_output=True, text=True, timeout=2)
            for line in res.stdout.splitlines():
                if "scrcpy" in line and "defunct" not in line and "grep" not in line:
                    parts = line.strip().split(None, 1)
                    if len(parts) >= 2 and parts[0].isdigit():
                        pid = int(parts[0])
                        cmdline = parts[1]
                        m = re.search(r"(?:127\.0\.0\.1|localhost):(\d+)", cmdline)
                        if m:
                            port = int(m.group(1))
                            port_to_pids.setdefault(port, []).append(pid)
        except Exception as e:
            logger.error(f"Error checking running scrcpy processes: {e}")
        return port_to_pids

    def open_scrcpy(self, adb_port: int, window_title: Optional[str] = None) -> bool:
        """Launches a scrcpy window for a given ADB port if not already open."""
        pids = self.get_running_scrcpy_pids().get(adb_port, [])
        if pids:
            logger.debug(f"scrcpy already running for port {adb_port} (PID: {pids}).")
            return True

        # Ensure virtual keyboard is disabled
        self.hide_virtual_keyboard(adb_port)

        adb_target = f"127.0.0.1:{adb_port}"
        # Connect ADB target with short timeout
        try:
            subprocess.run(["adb", "connect", adb_target], capture_output=True, timeout=2)
        except Exception:
            return False

        # Fast check if adb is ready
        try:
            state_res = subprocess.run(
                ["adb", "-s", adb_target, "get-state"],
                capture_output=True,
                text=True,
                timeout=2,
            )
            if "device" not in state_res.stdout:
                logger.debug(f"ADB device {adb_target} not ready (state='{state_res.stdout.strip()}'). Skipping scrcpy launch.")
                return False
        except Exception:
            return False

        title = window_title or f"Redroid Container (Port {adb_port})"
        cmd = [
            "scrcpy",
            "-s",
            adb_target,
            "--window-title",
            title,
            "--no-audio",
            "--max-size",
            "960",
            "--max-fps",
            "30",
            "--shortcut-mod=lctrl,rctrl,lalt,lsuper",
            "--prefer-text",
            "--keyboard=sdk",
        ]

        env = os.environ.copy()
        if "DISPLAY" not in env or not env["DISPLAY"]:
            env["DISPLAY"] = ":0"

        try:
            logger.info(f"Opening scrcpy window for {adb_target} ('{title}')...")
            logs_dir = Path("data/logs/scrcpy")
            logs_dir.mkdir(parents=True, exist_ok=True)
            log_file = logs_dir / f"scrcpy_{adb_port}.log"
            log_handle = open(log_file, "a")

            # Launch detached GUI process
            subprocess.Popen(
                cmd,
                env=env,
                stdout=log_handle,
                stderr=log_handle,
                preexec_fn=os.setpgrp,
            )
            return True
        except Exception as e:
            logger.error(f"Failed to open scrcpy for port {adb_port}: {e}")
            return False

    def get_host_clipboard(self) -> Optional[str]:
        """Reads host clipboard using xclip across various targets and selections."""
        for sel in ["clipboard", "primary"]:
            for target in [None, "UTF8_STRING", "STRING", "TEXT"]:
                cmd = ["xclip", "-selection", sel]
                if target:
                    cmd.extend(["-t", target])
                cmd.append("-o")
                try:
                    res = subprocess.run(cmd, capture_output=True, text=True, timeout=1)
                    if res.returncode == 0 and res.stdout:
                        return res.stdout
                except Exception:
                    pass
        return None

    def paste_to_device(self, adb_port: int, text: Optional[str] = None) -> bool:
        """Copies text (or host clipboard) directly into the Android device clipboard and triggers paste."""
        if not text:
            text = self.get_host_clipboard()

        if not text:
            logger.warning("No text provided and host clipboard is empty.")
            return False

        try:
            import uiautomator2 as u2
            d = u2.connect(f"127.0.0.1:{adb_port}")
            d.set_clipboard(text)
            subprocess.run(["adb", "-s", f"127.0.0.1:{adb_port}", "shell", "input", "keyevent", "279"], capture_output=True, timeout=2)
            logger.info(f"Successfully pasted text into Redroid (Port {adb_port}): {text[:50]}...")
            return True
        except Exception as e:
            logger.error(f"Failed to paste text into Redroid {adb_port}: {e}")
            return False

    def close_scrcpy(self, adb_port: int) -> int:
        """Terminates all scrcpy windows associated with a given ADB port."""
        pids = self.get_running_scrcpy_pids().get(adb_port, [])
        killed = 0
        for pid in pids:
            try:
                logger.info(f"Closing scrcpy process PID {pid} for port {adb_port}...")
                os.kill(pid, signal.SIGTERM)
                killed += 1
            except ProcessLookupError:
                pass
            except Exception as e:
                logger.warning(f"Failed to terminate scrcpy PID {pid}: {e}")
        return killed

    def sync_auto_scrcpy(
        self,
        running_containers: Optional[Set[str]] = None,
        scrcpy_pids: Optional[Dict[int, List[int]]] = None
    ) -> Dict[str, Any]:
        """Auto opens scrcpy for running containers and auto closes scrcpy for stopped containers in O(1) in-memory checks."""
        instances = RedroidRepository.list_all()

        if running_containers is None:
            running_containers = self.docker_mgr.get_running_container_names()

        if scrcpy_pids is None:
            scrcpy_pids = self.get_running_scrcpy_pids()

        opened = 0
        closed = 0
        active_ports = set()

        for inst in instances:
            try:
                is_running = inst.container_name in running_containers
                port = inst.adb_port

                if is_running:
                    active_ports.add(port)
                    # Automatically ensure virtual keyboard is hidden for running container (once per run)
                    if inst.container_name not in self._keyboard_hidden_targets:
                        self.hide_virtual_keyboard(inst.container_name)

                    # Container is running, open scrcpy if not running
                    if port not in scrcpy_pids:
                        title = f"Redroid [UID: {inst.account_uid or 'Unknown'}] (Port: {port})"
                        if self.open_scrcpy(port, window_title=title):
                            opened += 1
                else:
                    self._keyboard_hidden_targets.discard(inst.container_name)
                    # Container is not running, close scrcpy if open
                    if port in scrcpy_pids:
                        closed += self.close_scrcpy(port)
            except Exception as e:
                logger.warning(f"Error syncing container {inst.container_name}: {e}")

        # Also close any orphaned scrcpy processes for ports not in registered running instances
        for port, pids in scrcpy_pids.items():
            if port not in active_ports:
                closed += self.close_scrcpy(port)

        return {"opened": opened, "closed": closed, "running_containers": len(active_ports)}

    def watch_loop(self, interval_seconds: float = 1.0):
        """Continuously monitors Redroid processes and auto toggles scrcpy windows in real-time with instant in-memory rendering."""
        from rich.live import Live

        def generate_dashboard(
            running_containers: Set[str],
            scrcpy_pids: Dict[int, List[int]],
            instances: list
        ) -> Table:
            now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

            running_containers_count = sum(1 for inst in instances if inst.container_name in running_containers)
            open_scrcpy_count = sum(1 for inst in instances if inst.adb_port in scrcpy_pids)

            table = Table(
                title=f"🖥  [bold cyan]Redroid Container & Scrcpy Live Supervisor[/bold cyan] (Real-time) — [yellow]{now_str}[/yellow]\n"
                      f"[dim]Running Containers: [green]{running_containers_count}[/green] | Open Scrcpy Windows: [green]{open_scrcpy_count}[/green] | Press [red]Ctrl+C[/red] to exit[/dim]",
                expand=True,
                show_lines=True,
            )
            table.add_column("Container ID", style="cyan", width=14)
            table.add_column("Container Name", style="magenta", width=28)
            table.add_column("ADB Port", style="yellow", justify="center", width=10)
            table.add_column("FB UID", style="green", width=18)
            table.add_column("Container Status", style="bold", justify="center", width=18)
            table.add_column("Scrcpy GUI Status", style="bold", width=30)

            for inst in instances:
                live_status = "running" if inst.container_name in running_containers else "stopped"
                pids = scrcpy_pids.get(inst.adb_port, [])

                if live_status == "running":
                    c_status = "[bold green]● RUNNING[/bold green]"
                else:
                    c_status = "[dim yellow]■ STOPPED[/dim yellow]"

                if pids:
                    pid_str = ", ".join(map(str, pids))
                    s_status = f"[bold bright_green]▶ OPEN (PID: {pid_str})[/bold bright_green]"
                else:
                    if live_status == "running":
                        s_status = "[bold yellow]⏳ CONNECTING...[/bold yellow]"
                    else:
                        s_status = "[dim white]⏹ CLOSED[/dim white]"

                table.add_row(
                    inst.container_id[:12] if inst.container_id else "-",
                    inst.container_name,
                    str(inst.adb_port),
                    inst.account_uid or "-",
                    c_status,
                    s_status,
                )
            return table

        console.print("[bold cyan]🚀 Starting Scrcpy Supervisor (Ultra-Fast Real-Time Monitor)...[/bold cyan]")
        console.print("[dim]Monitoring Redroid containers... Press Ctrl+C to exit.[/dim]\n")

        # Initial fast snapshot
        init_instances = RedroidRepository.list_all()
        init_running = self.docker_mgr.get_running_container_names()
        init_pids = self.get_running_scrcpy_pids()

        try:
            with Live(generate_dashboard(init_running, init_pids, init_instances), refresh_per_second=2) as live:
                while True:
                    # 1. Fetch live system states in only 2 fast calls total
                    instances = RedroidRepository.list_all()
                    running_containers = self.docker_mgr.get_running_container_names()
                    scrcpy_pids = self.get_running_scrcpy_pids()

                    # 2. Sync scrcpy processes
                    try:
                        self.sync_auto_scrcpy(running_containers=running_containers, scrcpy_pids=scrcpy_pids)
                    except Exception as e:
                        logger.warning(f"Supervisor sync cycle encountered an error: {e}")

                    # 3. Update dashboard in-memory (0ms lag)
                    live.update(generate_dashboard(running_containers, scrcpy_pids, instances))
                    time.sleep(interval_seconds)
        except KeyboardInterrupt:
            console.print("\n[yellow]Scrcpy Supervisor stopped.[/yellow]")
