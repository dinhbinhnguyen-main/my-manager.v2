Viewed run_cmd.py:60-151
Viewed run_cmd.py:100-151
Edited run_cmd.py
Ran command: `/Volumes/KINGSTON/miniconda3/envs/my-manager.v2/bin/python main-cli.py run --help`
Ran command: `/Volumes/KINGSTON/miniconda3/envs/my-manager.v2/bin/python main-cli.py run discussion-group --help`
Ran command: `/Volumes/KINGSTON/miniconda3/envs/my-manager.v2/bin/python main-cli.py run marketplace-share --help; /Volumes/KINGSTON/miniconda3/envs/my-manager.v2/bin/python main-cli.py run single-listing --help`

Dưới đây là các lệnh CLI `python main-cli.py run ...` đã được thiết kế sẵn để bạn có thể test trực tiếp từng action trên các Redroid container.

Bạn có thể sử dụng theo 2 cách: **Lệnh chuyên dụng trực tiếp** *(khuyên dùng vì ngắn gọn, rõ ràng)* hoặc **Lệnh tổng quát `run action`**.

---

### 1. Test Action `discussion_group` (Đăng bài thảo luận nhóm)

**Lệnh chuyên dụng:**
```bash
# 1.1. Đăng thảo luận vào nhóm ngẫu nhiên theo loại giao dịch (cho thuê / rental)
python main-cli.py run discussion-group -u 100089123456789 -t rental --use-ai --v1-prod

# 1.2. Đăng thảo luận bán đất/nhà (sale) vào 1 nhóm cụ thể (chỉ định group ID)
python main-cli.py run discussion-group -u 100089123456789 -g 5857815244230418 -t sale --use-ai --v1-prod

# 1.3. Đăng với nội dung custom (không lấy từ DB v1)
python main-cli.py run discussion-group -u 100089123456789 --no-v1-prod -c "Chính chủ cho thuê nhà nguyên căn view rừng thông Đà Lạt, giá 8tr/tháng."
```

---

### 2. Test Action `list_group_share` (Niêm yết Mua bán nhóm + Cross-share)

**Lệnh chuyên dụng:**
```bash
# 2.1. Niêm yết sản phẩm từ v1 DB vào nhóm gốc và cross-share sang 5 nhóm Top thành viên
python main-cli.py run group-share -u 100089123456789 -g 5857815244230418 -s 5 -t rental --use-ai --v1-prod

# 2.2. Chạy hàng loạt 3 tài khoản cùng lúc (concurrency = 3)
python main-cli.py run group-share -u 100089123456789 -u 100089123456780 -u 100089123456781 -s 10 -t sale -m 3
```

---

### 3. Test Action `list_marketplace_share` (Niêm yết Marketplace + Cross-share)

**Lệnh chuyên dụng:**
```bash
# 3.1. Đăng bài niêm yết lên Marketplace Đà Lạt và chia sẻ lên 20 nhóm liên quan
python main-cli.py run marketplace-share -u 100089123456789 -l "Da Lat" -s 20 -t sale --use-ai --v1-prod

# 3.2. Đăng bài cho thuê trên Marketplace
python main-cli.py run marketplace-share -u 100089123456789 -l "Da Lat" -s 15 -t rental --use-ai --v1-prod
```

---

### 4. Test Action `single_listing` (Đăng bài thông minh qua $N$ nhóm)

**Lệnh chuyên dụng:**
```bash
# 4.1. Đăng lần lượt qua 3 nhóm (tự động phát hiện Sell hay Discussion cho từng nhóm)
python main-cli.py run single-listing -u 100089123456789 -c 3 -t rental --use-ai --v1-prod

# 4.2. Đăng qua 5 nhóm mua bán đất (sale)
python main-cli.py run single-listing -u 100089123456789 -c 5 -t sale --use-ai --v1-prod
```

---

### 5. Cách gọi tổng quát qua `run action --action <TÊN_ACTION>`

Bạn cũng có thể truyền JSON params tùy ý qua lệnh `run action`:

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

> **Lưu ý:** Thêm cờ `--auto-stop` vào bất kỳ lệnh nào nếu bạn muốn hệ thống tự động tắt Redroid container và nhả Proxy sau khi hoàn thành.