"""Data models for Accounts, Proxies, Containers, and Automation Jobs."""

import datetime
from enum import Enum
from typing import Optional, Dict, Any
from pydantic import BaseModel, Field


class AccountStatus(str, Enum):
    LIVE = "live"
    CHECKPOINT = "checkpoint"
    BANNED = "banned"
    WARMUP = "warmup"
    IDLE = "idle"


class ProxyType(str, Enum):
    HTTP = "http"
    SOCKS5 = "socks5"


class Account(BaseModel):
    id: Optional[int] = None
    uid: str
    password: str
    username: Optional[str] = None

    two_fa: Optional[str] = Field(default=None, description="2FA secret key")
    email: Optional[str] = None
    email_password: Optional[str] = None
    status: AccountStatus = AccountStatus.IDLE
    group_id: int = 1
    note: Optional[str] = None
    category: str = Field(default="real_estate", description="Account niche/product category: real_estate, tire, fashion")
    transaction_type: str = Field(default="rental", description="Property transaction type: rental, sale")
    proxy_id: Optional[int] = None
    container_id: Optional[str] = None
    device_profile_id: Optional[str] = None
    created_at: datetime.datetime = Field(default_factory=datetime.datetime.now)
    updated_at: datetime.datetime = Field(default_factory=datetime.datetime.now)


class ProxyStatus(str, Enum):
    AVAILABLE = "available"
    WORKING = "working"
    UNAVAILABLE = "unavailable"


class Proxy(BaseModel):
    id: Optional[int] = None
    name: Optional[str] = Field(default=None, description="Descriptive name for proxy")
    url: str  # Proxy Rotation API URL (e.g. https://proxyxoay.shop/api/get.php?key=...)
    status: ProxyStatus = ProxyStatus.AVAILABLE
    current_proxy_http: Optional[str] = Field(default=None, description="Extracted IP:PORT:USER:PASS string")
    assigned_account_uid: Optional[str] = None
    last_rotated_at: Optional[datetime.datetime] = None


class RedroidInstance(BaseModel):
    container_id: str
    container_name: str
    adb_port: int
    scrcpy_port: Optional[int] = None
    status: str  # running, stopped, creating, error
    account_uid: Optional[str] = None
    proxy_url: Optional[str] = None
    device_profile_id: Optional[str] = None
    created_at: datetime.datetime = Field(default_factory=datetime.datetime.now)


class AutomationTask(BaseModel):
    id: Optional[int] = None
    action_name: str
    account_uid: str
    status: str = "pending"  # pending, running, completed, failed
    result_message: Optional[str] = None
    params: Dict[str, Any] = Field(default_factory=dict)
    created_at: datetime.datetime = Field(default_factory=datetime.datetime.now)
    completed_at: Optional[datetime.datetime] = None


class JobStatus(str, Enum):
    PENDING = "pending"
    RUNNING = "running"
    FINISHED = "finished"
    FAILED = "failed"


class AutomationJob(BaseModel):
    id: Optional[int] = None
    name: str
    group_tag: str = "default"
    account_uid: str
    actions_json: str  # JSON list of action steps e.g. [{"action": "scroll_feed", "params": {...}}, ...]
    current_step_index: int = 0
    current_action: Optional[str] = None
    status: JobStatus = JobStatus.PENDING
    container_id: Optional[str] = None
    result_message: Optional[str] = None
    created_at: Optional[str] = None
    started_at: Optional[str] = None
    finished_at: Optional[str] = None

