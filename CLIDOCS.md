# 🛠 CLIDOCS - CLI Suite User Guide for `my-manager.v2`

Comprehensive guide covering all commands in the **CLI Suite** for **`my-manager.v2`** (Redroid FB Multi-Account & Automation Engine).

---

## 📑 Feature Index

1. [🔑 1. Facebook Account Management (`account`)](#-1-facebook-account-management-account)
2. [🌐 2. Proxy Rotation API Management (`proxy`)](#-2-proxy-rotation-api-management-proxy)
3. [🤖 3. Redroid Docker Container & Scrcpy GUI Management (`redroid`, `scrcpy`)](#-3-redroid-docker-container--scrcpy-gui-management-redroid-scrcpy)
4. [📋 4. Automation Scenario Batch & Progress Tracking (`automation`, `progress`)](#-4-automation-scenario-batch--progress-tracking-automation-progress)
5. [⚙️ 5. System Settings & V1 Database Paths (`setting`)](#️-5-system-settings--v1-database-paths-setting)
6. [🏠 6. V1 Real Estate Product Catalog (`product`)](#-6-v1-real-estate-product-catalog-product)
7. [🚀 7. Direct Single Task Execution (`run`)](#-7-direct-single-task-execution-run)
8. [📸 8. UI Hierarchy & Screen Dump Diagnostics (`dump`)](#-8-ui-hierarchy--screen-dump-diagnostics-dump)
9. [📅 9. 7-Day Account Rotation Scenario (`daily-rotation`)](#-9-7-day-account-rotation-scenario-daily-rotation)

---

## 🔑 1. Facebook Account Management (`account`)

```bash
# Add a new Facebook account with Category (real_estate, tire, fashion) & Transaction Type (rental, sale)
python main-cli.py account add --uid "61599900011122" --username "john.doe" --password "SecretPass123" --two-fa "JBSWY3DPEHPK3PXP" --category "real_estate" --transaction-type "rental" --note "FB Rental Account"

# Add account for Tire / Fashion niche
python main-cli.py account add --uid "61588800022233" --password "SecretPass123" --category "tire" --transaction-type "sale" --note "FB Tire Sale Account"

# List all accounts (includes Category & Trans. Type columns)
python main-cli.py account list

# Filter accounts by status (live, checkpoint, idle, warmup, banned)
python main-cli.py account list --status live

# Show account details by UID
python main-cli.py account show 61599900011122

# ❌ Delete account by UID or ID (automatically cleans up Docker container + data directory + releases proxy + removes jobs)
python main-cli.py account delete 61599900011122

# 🔄 Batch update account Group ID:
# Assign group_id = 0 to specific UIDs:
python main-cli.py account set-group --to 0 --uids 61588749472767,61593783300961

# Move all accounts from group -1 to group 0:
python main-cli.py account set-group --to 0 --from -1

# Move first 50 accounts from group -1 to group 0:
python main-cli.py account set-group --to 0 --from -1 --limit 50

# Move all accounts in database to group 0:
python main-cli.py account set-group --to 0 --all
```

---

## 🌐 2. Proxy Rotation API Management (`proxy`)

```bash
# Add a new Rotation Proxy API URL (with mnemonic name)
python main-cli.py proxy add --name "Proxy_Viettel_01" --url "https://proxyxoay.shop/api/get.php?key=YOUR_KEY&&nhamang=random&&tinhthanh=0"

# List all Proxy URLs (Name, API URL, Current Public IP, Status available/working/unavailable, Bound UID)
python main-cli.py proxy list

# Manually update Proxy status (available: idle, working: busy, unavailable: disabled)
python main-cli.py proxy set-status 1 unavailable
python main-cli.py proxy set-status "Proxy_Viettel_01" available

# ❌ Delete Proxy API URL by ID, Name, or URL
python main-cli.py proxy delete 1
python main-cli.py proxy delete "Proxy_Viettel_01"
```

---

## 🤖 3. Redroid Docker Container & Scrcpy GUI Management (`redroid`, `scrcpy`)

### 3.1. Redroid Docker Containers (`redroid`)
> [!IMPORTANT]
> **Resource Limits & Auto LRU Idle Eviction**: The system enforces **a maximum of 6 concurrent running Redroid containers** (`MAX_CONCURRENT_REDROID_CONTAINERS = 6`). When the limit is reached and a new container is requested, the engine **automatically identifies the oldest idle container (IDLE - no active jobs) with the earliest `StartedAt` timestamp, safely stops it, and releases its proxy**, allowing the new container to launch without errors.

```bash
# Create a new Redroid container bound to an account UID (automatically assigns an available proxy & installs Facebook APK)
python main-cli.py redroid create --uid "61599900011122"

# List all managed Redroid containers with live Docker status
python main-cli.py redroid list

# Check Android internal proxy configuration & actual Public IP across all containers
python main-cli.py redroid check-ip

# Stop container (accepts UID, ADB Port, or Container Name - releases proxy automatically)
python main-cli.py redroid stop 61599900011122
python main-cli.py redroid stop 5555

# 🛑 Stop ALL running Redroid containers and release all proxies
python main-cli.py redroid stop --all
python main-cli.py redroid stop all

# Restart a stopped container (automatically binds an available proxy from pool)
python main-cli.py redroid start 61599900011122

# Start container with a specific proxy override (by ID, Name, or Proxy URL)
python main-cli.py redroid start 61599900011122 --proxy 1
python main-cli.py redroid start 61599900011122 --proxy "Proxy_Viettel_01"

# 📲 Install APK on a container / account (auto-creates container if missing, starts it if stopped, skips if already installed)
python main-cli.py redroid install 61599900011122 --apk data/apks/facebook.apk
python main-cli.py redroid install-apk 5555 --apk /path/to/custom_app.apk

# 📲 Batch install APK for ALL accounts (iterates accounts, creates container if missing, verifies APK installation)
python main-cli.py redroid install --all --apk data/apks/facebook.apk
python main-cli.py redroid install all --apk data/apks/facebook.apk
python main-cli.py redroid install --uids "61599900011122,61599900033344" --apk data/apks/facebook.apk

# ❌ Completely remove container from Docker, DB, and DELETE DATA STORAGE DIRECTORY `data/containers/<uid>` ON DISK
python main-cli.py redroid remove 61599900011122
python main-cli.py redroid remove 5555
```

### 3.2. Scrcpy Process Supervisor - Real-Time GUI Screen Monitoring (`scrcpy`)
```bash
# [DEFAULT] Launch Real-Time Live Supervisor: continuously monitors containers, AUTO-OPENS scrcpy when container runs & AUTO-CLOSES when stopped
python main-cli.py scrcpy

# Synchronize once and exit (no persistent monitoring loop)
python main-cli.py scrcpy --once

# Customize real-time poll interval (e.g., 1.0 second)
python main-cli.py scrcpy --interval 1.0

# Manually open scrcpy GUI window for a specific container (by Port or UID)
python main-cli.py scrcpy --open 5555
python main-cli.py scrcpy 61599900011122 --open

# Manually close scrcpy GUI window for a specific container
python main-cli.py scrcpy --close 5555
python main-cli.py scrcpy 61599900011122 --close

# ⌨️ Hide soft virtual keyboard for all running containers (or a specific container)
python main-cli.py scrcpy --hide-keyboard
python main-cli.py scrcpy -k
python main-cli.py scrcpy 5555 -k

# ⌨️ Re-enable soft keyboard if needed
python main-cli.py scrcpy --show-keyboard
python main-cli.py scrcpy 5555 --show-keyboard

# 📋 Paste text directly into a running container
python main-cli.py scrcpy --paste "Text content to paste"
python main-cli.py scrcpy 61599900011122 --paste "Text content to paste"

# 📋 Paste current host machine clipboard into container
python main-cli.py scrcpy --paste-clipboard
python main-cli.py scrcpy -P
python main-cli.py scrcpy 61599900011122 -P
```

---

## 📋 4. Automation Scenario Batch & Progress Tracking (`automation`, `progress`)

### 4.1. Create, Run & Manage Batch Scenarios (`automation`)
```bash
# Create warm-up batch scenario (scroll feed & join groups) for group list_uid_01
python main-cli.py automation create-batch \
  --tag list_uid_01 \
  --uids "10001,10002" \
  --actions '[{"action": "scroll_feed", "params": {"scroll_count": 5}}, {"action": "join_group", "params": {"group_id": "123456"}}]' \
  --name "Feed & Join Group Scenario"

python main-cli.py automation create-batch \
  --tag "0923_list_group_share" \
  --uids "61592898754968, 61592910155352, 61592925664417" \
  --actions '[{"action": "list_group_share", "params": {"group_ids": ["5857815244230418"], "use_v1_product": true, "use_ai": true}}]' \
  --name "V1 Random Product + Gemini AI Listing Scenario"

python main-cli.py automation create-batch \
  --tag "0923_scroll_feed" \
  --uids "61592898754968, 61592910155352" \
  --actions '[{"action": "scroll_feed", "params": {"max_swipes": 25, "min_delay": 3.0, "max_delay": 8.0, "max_likes": 3}}]' \
  --name "Scroll Feed Scenario"

# List created scenarios (filter by Tag or Status)
python main-cli.py automation list --tag list_uid_01
python main-cli.py automation list --status pending

# Execute batch scenario (automatically adjusts concurrency to min(proxy_count, threads))
python main-cli.py automation run-batch --tag list_uid_01 --threads 4

# 🔄 Reset / Refresh scenarios back to 'pending' and clear error logs by Tag / UID
python main-cli.py automation reset --tag 0923_scroll_feed
python main-cli.py automation refresh --tag 0923_scroll_feed

# 🔄 Reset only failed jobs in tag
python main-cli.py automation reset --tag 0923_scroll_feed --failed

# 🔄 Reset specific job by Job ID or Account UID
python main-cli.py automation reset 5

# 🔄 Reset all jobs in Database to pending
python main-cli.py automation reset --all

# ❌ Delete scenarios by ID, Tag, or UID
python main-cli.py automation delete 1
python main-cli.py automation delete --tag list_uid_01

# ❌ Clean up completed jobs (status finished or failed)
python main-cli.py automation delete --clear

# ⚠️ Remove all scenarios from database
python main-cli.py automation delete --all
```

### 4.2. Real-Time Progress Dashboard (`progress`)
```bash
# Overview snapshot of current progress (Total, Pending, Running, Finished, Failed, Progress %)
python main-cli.py progress

# View progress for a specific batch tag
python main-cli.py progress --tag list_uid_01

# 🖥 Include real-time status of Docker Redroid containers & Proxy Pool
python main-cli.py progress --system
python main-cli.py progress --watch --system
```

### 4.3. Action Documentation & Examples (`actions`)
```bash
# View table overview of all Actions, Aliases, Required Parameters, and Descriptions
python main-cli.py actions

# View detailed documentation, parameters, single CLI usage, and script JSON examples for a specific action
python main-cli.py actions login
python main-cli.py actions scroll_feed
python main-cli.py actions marketplace
python main-cli.py actions group_share
python main-cli.py actions join_group
python main-cli.py actions post_group
python main-cli.py actions list_group_share
python main-cli.py actions reel_interactions
```

---

## ⚙️ 5. System Settings & V1 Database Paths (`setting`)

```bash
# List all system settings
python main-cli.py setting list

# Configure Gemini AI API Key
python main-cli.py setting set gemini_api_key "AIzaSyYourActualGeminiApiKeyHere"

# Configure SQLite Database path for my-manager.v1 / phonemanager.v1
python main-cli.py setting set v1_db_path "/home/dinhbinhnguyen/Devs/my-manager.v1/bin/products.db"

# Configure product images storage directory for my-manager.v1
python main-cli.py setting set v1_image_dir "/home/dinhbinhnguyen/Devs/my-manager.v1/bin/images"
```

---

## 🏠 6. V1 Real Estate Product Catalog (`product`)

```bash
# List all shared real estate products from V1 Database
python main-cli.py product list

# Show detailed product info and preview Gemini AI rewritten content
python main-cli.py product show 1
```

---

## 🚀 7. Direct Single Task Execution (`run`)

```bash
# Run automated login + 2FA TOTP bypass for single account
python main-cli.py run action --action login --uids "61599900011122"

# Run 7-step Group Share listing (Navigate -> Sell -> Push Images -> AI Rewrite -> Select Marketplace & Groups -> Publish)
python main-cli.py run action --action group_share --uids "61599900011122" --auto-stop
```

---

## 📸 8. UI Hierarchy & Screen Dump Diagnostics (`dump`)

Debugging tool for inspecting UI elements, buttons, input fields, and coordinates on Redroid / Android via ADB Port or UID:

```bash
# Dump screen via ADB Port (e.g., port 5555 or 5565)
python main-cli.py dump --port 5555
# Or call script in ./test directly:
python ./test/dump_view.py --port 5555

# Auto-resolve ADB Port from Facebook UID
python main-cli.py dump --uid "61592898754968"

# Add custom tag for directory categorization
python ./test/dump_view.py --port 5555 --tag "step_3_pick_photos"

# Skip screenshot capture (XML and JSON dump only)
python ./test/dump_view.py --port 5555 --no-photo
```

**Output files are saved to:**
- `tests/dumps/<tag>_<timestamp>/`:
  - `dumped_screen.png`: High-resolution screenshot.
  - `dumped_view.xml`: Raw Android UI hierarchy tree.
  - `dumped_view.json`: Parsed interactive elements with `center`, `bounds`, and `suggested_selector` for UIAutomator2.
- `tests/dumps/latest/`: Copy of the most recent dump for quick inspection.

---

## 💡 Global Help

```bash
# Global CLI overview
python main-cli.py --help

# Subcommand-specific help
python main-cli.py account delete --help
python main-cli.py proxy delete --help
python main-cli.py automation delete --help
python main-cli.py redroid remove --help
```

---

## 📅 9. 7-Day Account Rotation Scenario (`daily-rotation`)

Automated scenario dividing accounts by `group_id` (default: `group_id = 0`) into 7 fixed groups matching the 7 days of the week.
- On weekday X: Accounts assigned to day X run `single_listing`, the other 6 groups run `scroll_feed` for account warm-up.
- Automatically binds proxy, starts container, executes action, stops container, and releases proxy.

```bash
# Preview scenario allocation for today (default group_id = 0):
python main-cli.py run daily-rotation --dry-run

# Preview scenario for Monday (group_id = 0):
python main-cli.py run daily-rotation --day 2 --dry-run

# Preview scenario for group_id = -1:
python main-cli.py run daily-rotation -g -1 --dry-run

# Live execution for today (concurrency 1 or 2):
python main-cli.py run daily-rotation --concurrency 1

# Simulate run for Monday:
python main-cli.py run daily-rotation --day 2 --concurrency 1

# Run only today's listing accounts (skip scroll_feed):
python main-cli.py run daily-rotation --only listing

# Run only warm-up / scroll_feed accounts (skip listing):
python main-cli.py run daily-rotation --only feed

# Crontab schedule to run automatically daily at 08:00 AM:
# 0 8 * * * /Volumes/KINGSTON/miniconda3/envs/my-manager.v2/bin/python /Users/dinhbinhnguyen/Dev/my-manager.v2/scripts/daily_rotation.py >> /Users/dinhbinhnguyen/Dev/my-manager.v2/logs/daily_rotation.log 2>&1
```
