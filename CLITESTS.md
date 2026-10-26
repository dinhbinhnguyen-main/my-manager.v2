# 🧪 CLI Action Tests Guide

Below are the pre-configured CLI commands (`python main-cli.py run ...`) designed for testing each action directly on Redroid containers.

You can run them in two ways: **Dedicated Direct Commands** *(recommended for brevity and clarity)* or the **Generic `run action` Command**.

---

### 1. Test Action `discussion_group` (Group Discussion Post)

**Dedicated Commands:**
```bash
# 1.1. Post discussion to a random group by transaction type (rental)
python main-cli.py run discussion-group -u 100089123456789 -t rental --use-ai --v1-prod

# 1.2. Post real estate sale discussion to a specific group by ID
python main-cli.py run discussion-group -u 100089123456789 -g 5857815244230418 -t sale --use-ai --v1-prod

# 1.3. Post with custom content (not fetched from v1 DB)
python main-cli.py run discussion-group -u 100089123456789 --no-v1-prod -c "Private owner renting whole house with pine forest view in Da Lat, 8M/month."
```

---

### 2. Test Action `list_group_share` (Group Buy/Sell Listing + Cross-Share)

**Dedicated Commands:**
```bash
# 2.1. List product from v1 DB into primary group and cross-share to 5 top-member groups
python main-cli.py run group-share -u 100089123456789 -g 5857815244230418 -s 5 -t rental --use-ai --v1-prod

# 2.2. Batch run across 3 accounts concurrently (concurrency = 3)
python main-cli.py run group-share -u 100089123456789 -u 100089123456780 -u 100089123456781 -s 10 -t sale -m 3
```

---

### 3. Test Action `list_marketplace_share` (Marketplace Listing + Cross-Share)

**Dedicated Commands:**
```bash
# 3.1. Create listing on Da Lat Marketplace and share to 20 related groups
python main-cli.py run marketplace-share -u 100089123456789 -l "Da Lat" -s 20 -t sale --use-ai --v1-prod

# 3.2. Post rental listing on Marketplace
python main-cli.py run marketplace-share -u 100089123456789 -l "Da Lat" -s 15 -t rental --use-ai --v1-prod
```

---

### 4. Test Action `single_listing` (Smart Posting across N Groups)

**Dedicated Commands:**
```bash
# 4.1. Sequentially post across 3 groups (auto-detects Buy/Sell or Discussion format for each)
python main-cli.py run single-listing -u 100089123456789 -c 3 -t rental --use-ai --v1-prod

# 4.2. Post across 5 real estate sale groups
python main-cli.py run single-listing -u 100089123456789 -c 5 -t sale --use-ai --v1-prod
```

---

### 5. Generic Invocation via `run action --action <ACTION_NAME>`

You can also pass arbitrary JSON params via the `run action` command:

```bash
# 5.1. Test discussion_group
python main-cli.py run action --action discussion_group --uids 100089123456789 --params '{"transaction_type": "rental", "use_ai": true, "use_v1_product": true}'

# 5.2. Test list_group_share
python main-cli.py run action --action list_group_share --uids 100089123456789 --params '{"group_ids": ["5857815244230418"], "share_groups_count": 5, "transaction_type": "sale"}'

# 5.3. Test list_marketplace_share
python main-cli.py run action --action list_marketplace_share --uids 100089123456789 --params '{"transaction_type": "sale", "location": "Da Lat", "share_groups_count": 20}'

# 5.4. Test single_listing
python main-cli.py run action --action single_listing --uids 100089123456789 --params '{"group_count": 3, "transaction_type": "rental"}'
```

> **Note:** Add the `--auto-stop` flag to any command if you want the system to automatically stop the Redroid container and release the proxy upon completion.
