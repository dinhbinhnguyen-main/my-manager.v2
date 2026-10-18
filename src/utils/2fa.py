#!/usr/bin/env python3
import subprocess
import sys
import time
import pyotp


def get_totp(raw_secret: str) -> str:
    # Remove whitespace and normalize to uppercase
    clean_secret = raw_secret.replace(" ", "").strip().upper()

    if not clean_secret:
        print("Error: Secret key cannot be empty.")
        raise ValueError("Secret key cannot be empty.")

    try:
        totp = pyotp.TOTP(clean_secret)
        code = totp.now()
        remaining = 30 - (int(time.time()) % 30)

        print(f"OTP Code: \033[1;32m{code}\033[0m (Remaining: {remaining}s)")

        # Automatically copy OTP to clipboard on macOS
        try:
            subprocess.run("pbcopy", text=True, input=code, check=True)
            print("→ Copied to clipboard automatically (Cmd + V to paste).")
        except Exception:
            pass

        return code
    except Exception as e:
        print(f"Error: Invalid secret key ({e})")
        raise


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage:")
        print('  python3 2fa.py "<raw_secret>"')
        print("Example:")
        print('  python3 2fa.py "5IYN VBXI TEAG CQTK Y3KM ZLIB Y36F XL7U"')
        sys.exit(1)

    secret_arg = sys.argv[1]
    try:
        get_totp(secret_arg)
    except Exception:
        sys.exit(1)
