"""TOTP helper re-exporting logic from src/utils/2fa.py."""

import importlib

_two_fa_mod = importlib.import_module("src.utils.2fa")
get_totp = _two_fa_mod.get_totp

__all__ = ["get_totp"]
