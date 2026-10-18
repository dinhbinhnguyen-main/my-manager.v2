#!/usr/bin/env python3
import sys
import time
import subprocess
import pyotp


def get_totp(raw_secret: str) -> str:
    # Loại bỏ khoảng trắng và chuẩn hóa viết hoa
    clean_secret = raw_secret.replace(" ", "").strip().upper()

    if not clean_secret:
        print("Lỗi: Secret key không được để trống.")
        raise ValueError("Secret key không được để trống.")

    try:
        totp = pyotp.TOTP(clean_secret)
        code = totp.now()
        remaining = 30 - (int(time.time()) % 30)

        print(f"Mã OTP: \033[1;32m{code}\033[0m (Còn lại: {remaining}s)")

        # Tự động sao chép mã OTP vào Clipboard trên macOS
        try:
            subprocess.run("pbcopy", text=True, input=code, check=True)
            print("→ Đã tự động sao chép mã vào Clipboard (Cmd + V để dán).")
        except Exception:
            pass

        return code
    except Exception as e:
        print(f"Lỗi: Secret key không hợp lệ ({e})")
        raise


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Cách dùng:")
        print('  python3 2fa.py "<raw_secret>"')
        print("Ví dụ:")
        print('  python3 2fa.py "5IYN VBXI TEAG CQTK Y3KM ZLIB Y36F XL7U"')
        sys.exit(1)

    secret_arg = sys.argv[1]
    try:
        get_totp(secret_arg)
    except Exception:
        sys.exit(1)
