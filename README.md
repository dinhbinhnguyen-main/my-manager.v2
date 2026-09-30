# Redroid Facebook Multi-Account & Automation Manager (`my-manager.v2`)

A high-performance system for managing Facebook accounts using containerized Android instances (**Redroid**) via Docker, ADB, and UIAutomator2. Designed to replace traditional desktop browser automation (Playwright/Cloackbrowser) to achieve superior anti-checkpoint and anti-spam protection.

---

## 🏛 Key Features & Architecture

- **Native Android Runtime**: Runs Facebook's official Android app (`com.facebook.katana` / `com.facebook.lite`) inside isolated Redroid Docker containers.
- **Hardware Device Fingerprint Generator**: Automatically generates realistic Android device profiles (`build.prop` parameters, Android ID, IMEI, MAC Address, Screen Resolution) per account.
- **Isolated Network per Container**: Route traffic for each Redroid instance through a dedicated HTTP / SOCKS5 proxy using transparent `redsocks2` / `tun2socks` and `iptables`.
- **Full Automation Engine**:
  - `FBLoginAction`: Automated login with 2FA TOTP code generation (`pyotp`).
  - `FBWarmupAction`: Natural feed scrolling, reels watching, and post interactions.
  - `FBMarketplaceAction`: Automated real-estate and product listing on Marketplace and Facebook Groups.
  - `FBCheckpointHandler`: Real-time detection of account locks, ID verification, and security prompts.
- **Modern CLI Suite**: Rich terminal interface built with `typer` and `rich`.

---

## 🚀 Quick Start Guide

### 1. Prerequisites

Ensure Docker and ADB are installed on your Linux system:

```bash
# Check Docker installation
docker --version

# Check ADB installation
adb version
```

### 2. Install Python Dependencies

```bash
cd /home/dinhbinhnguyen/Devs/my-manager.v2
pip install -r requirements.txt
```

### 3. Basic CLI Commands

#### Account Management
```bash
# Add a Facebook account
python main-cli.py account add --uid "61599900011122" --password "SecretPass123" --two-fa "JBSWY3DPEHPK3PXP" --note "FB Account 1"

# List all accounts
python main-cli.py account list
```

#### Redroid Container Management
```bash
# Create a Redroid container bound to an account UID
python main-cli.py redroid create --uid "61599900011122" --proxy "http://user:pass@1.2.3.4:8080"

# List active Redroid instances
python main-cli.py redroid list

# Start / Stop / Remove containers
python main-cli.py redroid start redroid_fb_61599900011122
python main-cli.py redroid stop redroid_fb_61599900011122
```

#### Automation Action Execution
```bash
# Run Login with 2FA
python main-cli.py run action --action login --uids "61599900011122"

# Run Feed Warmup
python main-cli.py run action --action warmup --uids "61599900011122" --concurrency 2
```

---

## 📂 Project Structure

```
my-manager.v2/
├── main-cli.py                   # Main CLI entry point
├── requirements.txt              # Project dependencies
├── README.md                     # Documentation
└── src/
    ├── core/                     # Constants, Device Fingerprints, Dataclass Models
    │   ├── constants.py
    │   ├── fingerprint.py
    │   └── models.py
    ├── db/                       # SQLite Database & Repositories
    │   ├── database.py
    │   └── repository.py
    ├── redroid/                  # Container Lifecycle & Proxy Configurator
    │   ├── manager.py
    │   └── proxy_configurator.py
    ├── automation/               # ADB & UIAutomator2 Controller
    │   ├── adb_client.py
    │   ├── base_automator.py
    │   ├── checkpoint_handler.py
    │   └── facebook/             # FB Actions (Login, Warmup, Marketplace)
    │       ├── login.py
    │       ├── warmup.py
    │       └── marketplace.py
    └── cli/                      # Typer CLI subcommands
        ├── account_cmd.py
        ├── redroid_cmd.py
        ├── proxy_cmd.py
        └── run_cmd.py
```

## MACOS start
mm-start