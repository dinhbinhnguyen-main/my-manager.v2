"""Device fingerprint generator for Redroid instances."""

import random
import uuid
import secrets
from typing import Dict, Any, List, Optional
from pydantic import BaseModel, Field

from src.core.device_templates import DEVICE_TEMPLATES


class DeviceProfile(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    brand: str
    manufacturer: str
    model: str
    product: str
    device: str
    board: str
    hardware: str
    fingerprint: str
    android_id: str
    imei: str
    mac_address: str
    serial: str
    width: int = 1080
    height: int = 1920
    dpi: int = 420
    locale: str = "vi-VN"
    timezone: str = "Asia/Ho_Chi_Minh"

    def to_build_prop_dict(self) -> Dict[str, str]:
        return {
            "ro.product.brand": self.brand,
            "ro.product.manufacturer": self.manufacturer,
            "ro.product.model": self.model,
            "ro.product.name": self.product,
            "ro.product.device": self.device,
            "ro.build.fingerprint": self.fingerprint,
            "ro.serialno": self.serial,
        }


def generate_random_mac() -> str:
    """Generates a random valid MAC address."""
    prefix = [0x00, 0x16, 0x3E]
    suffix = [random.randint(0x00, 0xFF) for _ in range(3)]
    mac = prefix + suffix
    return ":".join(f"{b:02x}" for b in mac)


def generate_random_imei() -> str:
    """Generates a realistic 15-digit IMEI with Luhn check digit."""
    tac = str(random.choice([352099, 354890, 864201, 359281]))
    fac_serial = f"{random.randint(0, 999999):06d}"
    raw = tac + fac_serial

    # Luhn algorithm to compute check digit
    total = 0
    for i, digit in enumerate(raw):
        n = int(digit)
        if i % 2 != 0:
            n *= 2
            if n > 9:
                n -= 9
        total += n

    check_digit = (10 - (total % 10)) % 10
    return raw + str(check_digit)


def generate_device_profile(template_index: Optional[int] = None) -> DeviceProfile:
    """Generates a unique realistic Device Profile for Redroid."""
    if template_index is None or template_index >= len(DEVICE_TEMPLATES):
        tmpl = random.choice(DEVICE_TEMPLATES)
    else:
        tmpl = DEVICE_TEMPLATES[template_index]

    android_id = secrets.token_hex(8)
    serial = secrets.token_hex(6).upper()

    return DeviceProfile(
        brand=tmpl["brand"],
        manufacturer=tmpl["manufacturer"],
        model=tmpl["model"],
        product=tmpl["product"],
        device=tmpl["device"],
        board=tmpl["board"],
        hardware=tmpl["hardware"],
        fingerprint=tmpl["fingerprint"],
        android_id=android_id,
        imei=generate_random_imei(),
        mac_address=generate_random_mac(),
        serial=serial,
    )
