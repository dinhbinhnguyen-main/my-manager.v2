"""SQLite Database initialization and connection pool management."""

import sqlite3
import logging
from contextlib import contextmanager
from src.core.constants import DB_PATH

logger = logging.getLogger(__name__)


def get_db_connection() -> sqlite3.Connection:
    """Returns a SQLite connection configured with WAL mode and thread safety."""
    conn = sqlite3.connect(DB_PATH, timeout=30.0)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL;")
    conn.execute("PRAGMA foreign_keys=ON;")
    return conn


@contextmanager
def get_db_cursor():
    """Context manager for SQLite cursor with auto-commit/rollback."""
    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        yield cursor
        conn.commit()
    except Exception as e:
        conn.rollback()
        logger.error(f"Database error: {e}")
        raise e
    finally:
        conn.close()


def init_db():
    """Initializes SQLite database tables."""
    with get_db_cursor() as cursor:
        cursor.execute("""
        CREATE TABLE IF NOT EXISTS accounts (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            uid TEXT UNIQUE NOT NULL,
            username TEXT,
            password TEXT NOT NULL,
            two_fa TEXT,
            email TEXT,
            email_password TEXT,
            status TEXT DEFAULT 'idle',
            group_id INTEGER DEFAULT 1,
            note TEXT,
            category TEXT DEFAULT 'real_estate',
            transaction_type TEXT DEFAULT 'rental',
            proxy_id INTEGER,
            container_id TEXT,
            device_profile_id TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
        """)

        # Migration helper: ensure new columns exist in accounts table
        cursor.execute("PRAGMA table_info(accounts);")
        acc_cols = {col["name"] for col in cursor.fetchall()}
        if "username" not in acc_cols:
            cursor.execute("ALTER TABLE accounts ADD COLUMN username TEXT;")
        if "category" not in acc_cols:
            cursor.execute("ALTER TABLE accounts ADD COLUMN category TEXT DEFAULT 'real_estate';")
        if "transaction_type" not in acc_cols:
            cursor.execute("ALTER TABLE accounts ADD COLUMN transaction_type TEXT DEFAULT 'rental';")


        cursor.execute("""
        CREATE TABLE IF NOT EXISTS proxies (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT,
            url TEXT UNIQUE NOT NULL,
            status TEXT DEFAULT 'available',
            current_proxy_http TEXT,
            assigned_account_uid TEXT,
            last_rotated_at TIMESTAMP,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
        """)

        # Migration helper: ensure new columns exist in proxies table
        cursor.execute("PRAGMA table_info(proxies);")
        proxy_cols = {col["name"] for col in cursor.fetchall()}
        if "name" not in proxy_cols:
            cursor.execute("ALTER TABLE proxies ADD COLUMN name TEXT;")
        if "current_proxy_http" not in proxy_cols:
            cursor.execute("ALTER TABLE proxies ADD COLUMN current_proxy_http TEXT;")
        if "last_rotated_at" not in proxy_cols:
            cursor.execute("ALTER TABLE proxies ADD COLUMN last_rotated_at TIMESTAMP;")

        cursor.execute("""
        CREATE TABLE IF NOT EXISTS device_profiles (
            id TEXT PRIMARY KEY,
            brand TEXT,
            manufacturer TEXT,
            model TEXT,
            product TEXT,
            device TEXT,
            board TEXT,
            hardware TEXT,
            fingerprint TEXT,
            android_id TEXT,
            imei TEXT,
            mac_address TEXT,
            serial TEXT,
            width INTEGER DEFAULT 1080,
            height INTEGER DEFAULT 1920,
            dpi INTEGER DEFAULT 420,
            locale TEXT DEFAULT 'vi-VN',
            timezone TEXT DEFAULT 'Asia/Ho_Chi_Minh'
        );
        """)

        cursor.execute("""
        CREATE TABLE IF NOT EXISTS redroid_instances (
            container_id TEXT PRIMARY KEY,
            container_name TEXT NOT NULL,
            adb_port INTEGER NOT NULL,
            scrcpy_port INTEGER,
            status TEXT DEFAULT 'stopped',
            account_uid TEXT,
            proxy_url TEXT,
            device_profile_id TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
        """)

        cursor.execute("""
        CREATE TABLE IF NOT EXISTS automation_tasks (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            action_name TEXT NOT NULL,
            account_uid TEXT NOT NULL,
            status TEXT DEFAULT 'pending',
            result_message TEXT,
            params TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            completed_at TIMESTAMP
        );
        """)

        cursor.execute("""
        CREATE TABLE IF NOT EXISTS settings (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT UNIQUE NOT NULL,
            value TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
        """)

        cursor.execute("""
        CREATE TABLE IF NOT EXISTS automation_jobs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            group_tag TEXT DEFAULT 'default',
            account_uid TEXT NOT NULL,
            actions_json TEXT NOT NULL,
            current_step_index INTEGER DEFAULT 0,
            current_action TEXT,
            status TEXT CHECK(status IN ('pending', 'running', 'finished', 'failed')) DEFAULT 'pending',
            container_id TEXT,
            result_message TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            started_at TIMESTAMP,
            finished_at TIMESTAMP
        );
        """)

        # Insert default customizable settings if not exist
        default_settings = [
            ("gemini_api_key", ""),
            ("v1_db_path", "/home/dinhbinhnguyen/Devs/my-manager.v1/bin/products.db"),
            ("v1_image_dir", "/home/dinhbinhnguyen/Devs/my-manager.v1/bin/images"),
        ]
        for name, default_val in default_settings:
            cursor.execute(
                "INSERT INTO settings (name, value) VALUES (?, ?) ON CONFLICT(name) DO NOTHING;",
                (name, default_val),
            )
        logger.info("Database tables initialized successfully.")


# Auto-initialize database schema when module is loaded
try:
    init_db()
except Exception as e:
    logger.warning(f"Could not auto-initialize DB on import: {e}")

