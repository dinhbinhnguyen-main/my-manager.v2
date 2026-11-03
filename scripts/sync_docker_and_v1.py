"""Script to synchronize and restore manager.db from Docker containers and v1 databases."""

import os
import sys
import json
import sqlite3
import subprocess
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE_DIR))

from src.db.database import init_db, get_db_cursor


def sync_all():
    print("Initializing Database schema...")
    init_db(force=True)

    # 1. Import accounts from v1
    candidate_acc_dbs = [
        Path("/Users/dinhbinhnguyen/Dev/my-manager.v1/bin/accounts.db"),
        Path("/home/dinhbinhnguyen/Devs/my-manager.v1/bin/accounts.db"),
        BASE_DIR.parent / "my-manager.v1" / "bin" / "accounts.db",
    ]
    v1_acc_db = next((p for p in candidate_acc_dbs if p.exists()), candidate_acc_dbs[0])
    if v1_acc_db.exists():
        conn_v1 = sqlite3.connect(v1_acc_db)
        conn_v1.row_factory = sqlite3.Row
        c_v1 = conn_v1.cursor()
        c_v1.execute("SELECT * FROM facebook_accounts")
        rows = c_v1.fetchall()

        with get_db_cursor() as cur:
            for r in rows:
                uid = str(r["uid"]).strip()
                if not uid:
                    continue
                username = r["username"] or None
                password = r["password"] or "DefaultPassword123"
                two_fa = r["two_fa"] or None
                email = r["email"] or None
                email_password = r["email_password"] or None
                group_id = int(r["profile_group"]) if r["profile_group"] is not None else 1
                note = r["profile_note"] or None

                cur.execute(
                    """
                    INSERT INTO accounts (uid, username, password, two_fa, email, email_password, status, group_id, note, category, transaction_type)
                    VALUES (?, ?, ?, ?, ?, ?, 'idle', ?, ?, 'real_estate', 'rental')
                    ON CONFLICT(uid) DO UPDATE SET
                        username=coalesce(excluded.username, accounts.username),
                        password=excluded.password,
                        two_fa=excluded.two_fa,
                        email=excluded.email,
                        email_password=excluded.email_password,
                        group_id=excluded.group_id,
                        note=excluded.note;
                """,
                    (uid, username, password, two_fa, email, email_password, group_id, note),
                )
        print(f"Imported accounts from {v1_acc_db}.")

    # 2. Import proxies from v1 settings
    candidate_set_dbs = [
        Path("/Users/dinhbinhnguyen/Dev/my-manager.v1/bin/settings.db"),
        Path("/home/dinhbinhnguyen/Devs/my-manager.v1/bin/settings.db"),
        BASE_DIR.parent / "my-manager.v1" / "bin" / "settings.db",
    ]
    v1_set_db = next((p for p in candidate_set_dbs if p.exists()), candidate_set_dbs[0])
    if v1_set_db.exists():
        conn_v1_s = sqlite3.connect(v1_set_db)
        conn_v1_s.row_factory = sqlite3.Row
        c_v1_s = conn_v1_s.cursor()
        c_v1_s.execute("SELECT * FROM proxy")
        rows = c_v1_s.fetchall()

        with get_db_cursor() as cur:
            for r in rows:
                url = r["rotate_url"]
                if not url or not url.startswith("http"):
                    continue
                name = r["name"] or "Proxy API"
                cur.execute(
                    """
                    INSERT INTO proxies (name, url, status)
                    VALUES (?, ?, 'available')
                    ON CONFLICT(url) DO UPDATE SET name=excluded.name;
                """,
                    (name, url),
                )
        print(f"Imported proxies from {v1_set_db}.")

    # 3. Reconstruct Redroid containers and device profiles from Docker
    res = subprocess.run(
        ["docker", "ps", "-a", "--format", "{{.Names}}"],
        capture_output=True,
        text=True,
    )
    container_names = [
        line.strip()
        for line in res.stdout.split("\n")
        if line.startswith("redroid_fb_")
    ]

    print(f"Found {len(container_names)} Redroid containers in Docker.")
    batch_size = 50
    inspected = []
    for i in range(0, len(container_names), batch_size):
        batch = container_names[i : i + batch_size]
        res_insp = subprocess.run(
            ["docker", "inspect"] + batch, capture_output=True, text=True
        )
        if res_insp.returncode == 0:
            try:
                inspected.extend(json.loads(res_insp.stdout))
            except Exception as e:
                print(f"Batch parse error: {e}")

    with get_db_cursor() as cur:
        for c in inspected:
            c_id = c["Id"]
            c_name = c["Name"].lstrip("/")
            acc_uid = c_name.replace("redroid_fb_", "")

            state = c.get("State", {})
            status = "running" if state.get("Running") else "stopped"

            port_bindings = c.get("HostConfig", {}).get("PortBindings", {})
            adb_port = 5555
            scrcpy_port = 8000
            if "5555/tcp" in port_bindings and port_bindings["5555/tcp"]:
                try:
                    adb_port = int(port_bindings["5555/tcp"][0].get("HostPort", 5555))
                except Exception:
                    pass
            if "8000/tcp" in port_bindings and port_bindings["8000/tcp"]:
                try:
                    scrcpy_port = int(port_bindings["8000/tcp"][0].get("HostPort", 8000))
                except Exception:
                    pass

            cmd_args = c.get("Config", {}).get("Cmd", []) or c.get("Args", [])
            props = {}
            for arg in cmd_args:
                if "=" in arg:
                    k, v = arg.split("=", 1)
                    props[k] = v

            dp_id = f"dp_{acc_uid}"
            brand = props.get("ro.product.brand", "google")
            manufacturer = props.get("ro.product.manufacturer", "Google")
            model = props.get("ro.product.model", "Pixel 7a")
            product = props.get("ro.product.name", "lynx")
            device = props.get("ro.product.device", "lynx")
            fingerprint = props.get("ro.build.fingerprint", "")
            serial = props.get("ro.serialno", "")
            width = int(props.get("androidboot.redroid_width", 1080))
            height = int(props.get("androidboot.redroid_height", 1920))
            dpi = int(props.get("androidboot.redroid_dpi", 420))

            cur.execute(
                """
                INSERT INTO device_profiles (id, brand, manufacturer, model, product, device, board, hardware, fingerprint, android_id, imei, mac_address, serial, width, height, dpi, locale, timezone)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'vi-VN', 'Asia/Ho_Chi_Minh')
                ON CONFLICT(id) DO UPDATE SET
                    brand=excluded.brand,
                    manufacturer=excluded.manufacturer,
                    model=excluded.model,
                    fingerprint=excluded.fingerprint,
                    serial=excluded.serial;
            """,
                (
                    dp_id,
                    brand,
                    manufacturer,
                    model,
                    product,
                    device,
                    product,
                    brand,
                    fingerprint,
                    serial,
                    serial,
                    "",
                    serial,
                    width,
                    height,
                    dpi,
                ),
            )

            cur.execute(
                """
                INSERT INTO redroid_instances (container_id, container_name, adb_port, scrcpy_port, status, account_uid, device_profile_id)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(container_id) DO UPDATE SET
                    container_name=excluded.container_name,
                    adb_port=excluded.adb_port,
                    scrcpy_port=excluded.scrcpy_port,
                    status=excluded.status,
                    account_uid=excluded.account_uid,
                    device_profile_id=excluded.device_profile_id;
            """,
                (c_id, c_name, adb_port, scrcpy_port, status, acc_uid, dp_id),
            )

            cur.execute(
                """
                INSERT INTO accounts (uid, username, password, status, container_id, device_profile_id)
                VALUES (?, ?, 'DefaultPassword123', 'idle', ?, ?)
                ON CONFLICT(uid) DO UPDATE SET
                    container_id=excluded.container_id,
                    device_profile_id=excluded.device_profile_id;
            """,
                (acc_uid, acc_uid, c_id, dp_id),
            )

    print("Synchronization and reconstruction completed successfully!")


if __name__ == "__main__":
    sync_all()
