# 🛠 CLIDOCS - Hướng dẫn Lệnh CLI Suite cho `my-manager.v2`

Tài liệu tổng hợp đầy đủ và chi tiết tất cả các lệnh **CLI Suite** của hệ thống **`my-manager.v2`** (Redroid FB Multi-Account & Automation Engine).

---

## 📑 Danh mục Tính năng CLI

1. [🔑 1. Quản lý & Xóa Tài khoản Facebook (`account`)](#-1-quản-lý--xóa-tài-khoản-facebook-account)
2. [🌐 2. Quản lý & Xóa Proxy Rotation API (`proxy`)](#-2-quản-lý--xóa-proxy-rotation-api-proxy)
3. [🤖 3. Quản lý Máy ảo Redroid Docker & Scrcpy GUI (`redroid`, `scrcpy`)](#-3-quản-lý-máy-ảo-redroid-docker--scrcpy-gui-redroid-scrcpy)
4. [📋 4. Quản lý, Reset/Refresh & Xóa Kịch bản Scenario Batch & Tiến trình (`automation`, `progress`)](#-4-quản-lý-resetrefresh--xóa-kịch-bản-scenario-batch--tiến-trình-automation-progress)
5. [⚙️ 5. Cấu hình Hệ thống & Đường dẫn V1 (`setting`)](#️-5-cấu-hình-hệ-thống--đường-dẫn-v1-setting)
6. [🏠 6. Tra cứu Sản phẩm BĐS từ V1 (`product`)](#-6-tra-cứu-sản-phẩm-bđs-từ-v1-product)
7. [🚀 7. Chạy Tác vụ Đơn lẻ (`run`)](#-7-chạy-tác-vụ-đơn-lẻ-run)

---

## 🔑 1. Quản lý & Xóa Tài khoản Facebook (`account`)

```bash
# Thêm tài khoản Facebook mới kèm theo Nhóm sản phẩm (Category: real_estate, tire, fashion) & Loại giao dịch (Transaction Type: rental, sale)
python main-cli.py account add --uid "61599900011122" --username "nguyenvan.a" --password "SecretPass123" --two-fa "JBSWY3DPEHPK3PXP" --category "real_estate" --transaction-type "rental" --note "FB Acc BĐS Cho Thê"

# Thêm tài khoản chạy nhóm ngành Lốp xe / Thời trang
python main-cli.py account add --uid "61588800022233" --password "SecretPass123" --category "tire" --transaction-type "sale" --note "FB Acc Lốp Xe"

# Xem danh sách tất cả tài khoản (Bao gồm cột Category & Trans. Type)
python main-cli.py account list

# Lọc tài khoản theo trạng thái (live, checkpoint, idle, warmup, banned)
python main-cli.py account list --status live

# Xem thông tin chi tiết của 1 tài khoản theo UID
python main-cli.py account show 61599900011122

# ❌ Xóa tài khoản theo UID hoặc ID (TỰ ĐỘNG XÓA Container Docker + Thư mục data/containers/<uid> + Nhả Proxy + Xóa Kịch bản)
python main-cli.py account delete 61599900011122
```


---

## 🌐 2. Quản lý & Xóa Proxy Rotation API (`proxy`)

```bash
# Thêm Proxy Rotation API URL mới (Kèm tên gợi nhớ)
python main-cli.py proxy add --name "Proxy_Viettel_01" --url "https://proxyxoay.shop/api/get.php?key=aaFRTbzxdBViCFjkUpFpDj&&nhamang=random&&tinhthanh=0"

# Xem danh sách tất cả Proxy URL (Tên, API URL, IP hiện tại, Trạng thái rảnh/bận, UID đang dùng)
python main-cli.py proxy list

# Đổi trạng thái Proxy thủ công (available: rảnh, working: bận, unavailable: khóa không dùng)
python main-cli.py proxy set-status 1 unavailable
python main-cli.py proxy set-status "Proxy_Viettel_01" available

# ❌ Xóa Proxy API URL theo ID, Tên gợi nhớ hoặc URL
python main-cli.py proxy delete 1
python main-cli.py proxy delete "Proxy_Viettel_01"
```

---

## 🤖 3. Quản lý Máy ảo Redroid Docker & Scrcpy GUI (`redroid`, `scrcpy`)

### 3.1. Quản lý Docker Container Redroid (`redroid`)
> [!IMPORTANT]
> **Giới hạn Tài nguyên & Tự động Xoay tua máy ảo (LRU Idle Eviction)**: Hệ thống giới hạn **tối đa 6 container Redroid chạy đồng thời cùng lúc** (`MAX_CONCURRENT_REDROID_CONTAINERS = 6`). Khi đạt ngưỡng 6 máy ảo, nếu có yêu cầu mở/tạo máy ảo mới, hệ thống sẽ **tự động tìm máy ảo rảnh rỗi (IDLE - không chạy job) có thời gian mở lâu nhất (`StartedAt` cũ nhất) để đóng lại và nhả Proxy**, mở đường cho máy ảo mới khởi chạy liền mạch mà **không hề báo lỗi**.

```bash
# Tạo mới 1 Redroid container gắn với UID tài khoản (Tự động nạp Proxy rảnh + cài đặt Facebook APK)
python main-cli.py redroid create --uid "61599900011122"


# Xem danh sách tất cả container Redroid đang quản lý kèm live status Docker
python main-cli.py redroid list

# Kiểm tra Proxy trong Android & IP Ngoại mạng (Public IP) thực tế của tất cả container
python main-cli.py redroid check-ip

# Đóng container (Hỗ trợ UID, Port ADB hoặc Tên container - Tự động nhả Proxy)
python main-cli.py redroid stop 61599900011122
python main-cli.py redroid stop 5555

# 🛑 Đóng TOÀN BỘ các Redroid container đang chạy trên hệ thống & nhả toàn bộ Proxy
python main-cli.py redroid stop --all
python main-cli.py redroid stop all

# Khởi động lại container đã dừng (Gán tự động Proxy khả dụng trong DB)
python main-cli.py redroid start 61599900011122

# Khởi động container với 1 Proxy chỉ định cụ thể (theo ID, Tên gợi nhớ hoặc Proxy API URL)
python main-cli.py redroid start 61599900011122 --proxy 1
python main-cli.py redroid start 61599900011122 --proxy "Proxy_Viettel_01"
python main-cli.py redroid start 61599900011122 --proxy "https://proxyxoay.shop/api/getproxy.php?key=YOUR_KEY"

# 📲 Cài đặt APK cho 1 container / account (Tự động tạo container nếu chưa có, khởi động nếu đang dừng, bỏ qua nếu app đã cài)
python main-cli.py redroid install 61599900011122 --apk data/apks/facebook.apk
python main-cli.py redroid install-apk 5555 --apk /path/to/custom_app.apk

# 📲 Cài đặt APK HÀNG LOẠT cho TOÀN BỘ ACCOUNT (Tự động duyệt danh sách account, tạo Redroid container tương ứng nếu chưa có, nếu đã có thì kiểm tra xem đã cài APK chưa: đã cài thì bỏ qua, chưa cài thì tiến hành cài đặt)
python main-cli.py redroid install --all --apk data/apks/facebook.apk
python main-cli.py redroid install all --apk data/apks/facebook.apk
python main-cli.py redroid install --uids "61599900011122,61599900033344" --apk data/apks/facebook.apk

# ❌ Xóa hoàn toàn container khỏi Docker, DB, và XÓA THƯ MỤC LƯU TRỮ DỮ LIỆU `data/containers/<uid>` TRÊN ĐĨA
python main-cli.py redroid remove 61599900011122
python main-cli.py redroid remove 5555
```

### 3.2. Scrcpy Process Supervisor - Giám sát Thời Gian Thực & Tự động Đóng/Mở Màn hình GUI (`scrcpy`)
```bash
# [MẶC ĐỊNH] Khởi chạy Live Supervisor THỜI GIAN THỰC: liên tục theo dõi container, TỰ ĐỘNG MỞ scrcpy khi container chạy & TỰ ĐỘNG ĐÓNG khi container dừng
python main-cli.py scrcpy

# Kiểm tra & đồng bộ 1 lần rồi thoát (không chạy vòng lặp giám sát liên tục)
python main-cli.py scrcpy --once

# Tùy chỉnh chu kỳ quét thời gian thực (ví dụ 1.0 giây / lần)
python main-cli.py scrcpy --interval 1.0

# Mở thủ công màn hình GUI scrcpy cho 1 container cụ thể (theo Port hoặc UID)
python main-cli.py scrcpy --open 5555
python main-cli.py scrcpy 61599900011122 --open

# Đóng thủ công màn hình GUI scrcpy của 1 container cụ thể
python main-cli.py scrcpy --close 5555
python main-cli.py scrcpy 61599900011122 --close

# ⌨️ Ẩn bàn phím ảo (Soft Keyboard) cho tất cả container đang chạy (hoặc 1 container chỉ định)
python main-cli.py scrcpy --hide-keyboard
python main-cli.py scrcpy -k
python main-cli.py scrcpy 5555 -k

# ⌨️ Bật lại bàn phím ảo nếu cần
python main-cli.py scrcpy --show-keyboard
python main-cli.py scrcpy 5555 --show-keyboard

# 📋 Dán nội dung text trực tiếp vào container đang chạy
python main-cli.py scrcpy --paste "Nội dung cần dán"
python main-cli.py scrcpy 61599900011122 --paste "Nội dung cần dán"

# 📋 Dán clipboard hiện tại của máy tính (PC clipboard) vào container
python main-cli.py scrcpy --paste-clipboard
python main-cli.py scrcpy -P
python main-cli.py scrcpy 61599900011122 -P
```

---

## 📋 4. Quản lý, Xóa Kịch bản Scenario Batch & Tiến trình (`automation`, `progress`)

### 4.1. Tạo, Chạy & Xóa Kịch bản theo Nhóm (`automation`)
```bash
# Tạo kịch bản Nuôi nick (Lướt Feed & Tham gia Nhóm) cho nhóm list_uid_01
python main-cli.py automation create-batch \
  --tag list_uid_01 \
  --uids "10001,10002" \
  --actions '[{"action": "scroll_feed", "params": {"scroll_count": 5}}, {"action": "join_group", "params": {"group_id": "123456"}}]' \
  --name "Kịch bản Feed & Join Group"

python main-cli.py automation create-batch \
  --tag "0923_list_group_share" \
  --uids "61592898754968, 61592910155352, 61592925664417, 61592938083539, 61593009841811, 61592814908663, " \
  --actions '[{"action": "list_group_share", "params": {"group_ids": ["5857815244230418"], "use_v1_product": true, "use_ai": true}}]' \
  --name "Kịch bản Bốc BĐS Ngẫu Nhiên v1 + AI Gemini"
python main-cli.py automation create-batch \
  --tag "0923_scroll_feed" \
  --uids "61592898754968, 61592910155352, 61592925664417, 61592938083539, 61593009841811, 61592814908663, " \
  --actions '[{"action": "scroll_feed", "params": {"max_swipes": 25, "min_delay": 3.0, "max_delay": 8.0, "max_likes": 3}}]' \
  --name "scroll feed"

# Xem danh sách kịch bản đã khởi tạo (Lọc theo Tag hoặc Status)
python main-cli.py automation list --tag list_uid_01
python main-cli.py automation list --status pending

# Thực thi kịch bản hàng loạt (Tự động điều tiết min(proxy_count, threads))
python main-cli.py automation run-batch --tag list_uid_01 --threads 4

# 🔄 Reset / Refresh kịch bản về trạng thái 'pending' & xóa dữ liệu lỗi cũ theo Tag / UID
python main-cli.py automation reset --tag 0923_scroll_feed
python main-cli.py automation refresh --tag 0923_scroll_feed

# 🔄 Chỉ Reset các job bị lỗi (status failed) trong tag
python main-cli.py automation reset --tag 0923_scroll_feed --failed

# 🔄 Reset 1 job chỉ định theo Job ID hoặc Account UID
python main-cli.py automation reset 5

# 🔄 Reset toàn bộ tất cả job trong Database về pending
python main-cli.py automation reset --all

# ❌ Xóa kịch bản theo ID, Group Tag hoặc Account UID
python main-cli.py automation delete 1
python main-cli.py automation delete --tag list_uid_01

# ❌ Dọn dẹp tất cả kịch bản đã hoàn thành (status finished hoặc failed)
python main-cli.py automation delete --clear

# ⚠️ Xóa toàn bộ kịch bản khỏi Database
python main-cli.py automation delete --all
```

### 4.2. Theo dõi Tiến trình Real-time Dashboard (`progress`)
```bash
# Xem tổng quan tiến trình hiện tại (Snapshot Overview: Total, Pending, Running, Finished, Failed, Progress %)
python main-cli.py progress

# Xem tiến trình của một nhóm kịch bản chỉ định
python main-cli.py progress --tag list_uid_01

# 🖥 Bổ sung quan sát thời gian thực các Redroid container trên Docker & Trạng thái toàn bộ Proxy Pool
python main-cli.py progress --system
python main-cli.py progress --watch --system
```

### 4.3. Tra cứu Hướng dẫn Action, Tham số & Ví dụ (`actions`)
```bash
# Xem bảng tổng quan danh sách tất cả Action, Aliases, Tham số bắt buộc & Mô tả chức năng
python main-cli.py actions

# Xem hướng dẫn chi tiết, tham số đầu vào, ví dụ chạy đơn CLI & ví dụ JSON kịch bản cho 1 Action cụ thể
python main-cli.py actions login
python main-cli.py actions scroll_feed
python main-cli.py actions marketplace
python main-cli.py actions group_share
python main-cli.py actions join_group
python main-cli.py actions post_group
python main-cli.py actions group_share
python main-cli.py actions list_group_share
```


---

## ⚙️ 5. Cấu hình Hệ thống & Đường dẫn V1 (`setting`)

```bash
# Xem tất cả các thiết lập cấu hình trong hệ thống
python main-cli.py setting list

# Cấu hình API Key AI Gemini
python main-cli.py setting set gemini_api_key "AIzaSyYourActualGeminiApiKeyHere"

# Cấu hình đường dẫn tới SQLite Database của dự án my-manager.v1
python main-cli.py setting set v1_db_path "/home/dinhbinhnguyen/Devs/my-manager.v1/bin/products.db"

# Cấu hình thư mục chứa hình ảnh BĐS của dự án my-manager.v1
python main-cli.py setting set v1_image_dir "/home/dinhbinhnguyen/Devs/my-manager.v1/bin/images"
```

---

## 🏠 6. Tra cứu Sản phẩm BĐS từ V1 (`product`)

```bash
# Danh sách tất cả sản phẩm BĐS dùng chung từ V1 Database
python main-cli.py product list

# Xem chi tiết thông tin sản phẩm & xem thử nội dung AI Gemini viết lại chuẩn Meta
python main-cli.py product show 1
```

---

## 🚀 7. Chạy Tác vụ Đơn lẻ (`run`)

```bash
# Chạy Đăng nhập tự động + Vượt 2FA TOTP cho 1 tài khoản
python main-cli.py run action --action login --uids "61599900011122"

# Chạy Action Group Share BĐS 7 bước (Vào nhóm -> Bán gì -> Đẩy ảnh -> Viết lại AI -> Chọn Marketplace & Nhóm -> Đăng)
python main-cli.py run action --action group_share --uids "61599900011122" --auto-stop
```

---

## 📸 8. Phân tích Giao diện, Chụp Màn hình & XML Hierarchy (`dump`)

Tool phục vụ gỡ lỗi (debug), kiểm tra phần tử UI (elements, buttons, input fields, coordinates) trên Redroid / Android thông qua ADB Port hoặc UID:

```bash
# Dump màn hình qua ADB Port (ví dụ port 5555 hoặc 5565)
python main-cli.py dump --port 5555
# hoặc gọi trực tiếp script trong ./test:
python ./test/dump_view.py --port 5555

# Dump tự động tìm ADB Port từ Facebook UID
python main-cli.py dump --uid "61592898754968"

# Thêm tag tên bước để dễ phân loại thư mục lưu
python ./test/dump_view.py --port 5555 --tag "step_3_pick_photos"

# Bỏ qua chụp ảnh màn hình (chỉ dump XML và JSON)
python ./test/dump_view.py --port 5555 --no-photo
```

**Kết quả được lưu tại:**
- `tests/dumps/<tag>_<timestamp>/`:
  - `dumped_screen.png`: Ảnh chụp màn hình sắc nét.
  - `dumped_view.xml`: Cây phân cấp UI gốc từ Android.
  - `dumped_view.json`: Danh sách các phần tử tương tác đã được phân tích kèm tọa độ `center`, `bounds`, và mã `suggested_selector` cho UIAutomator2.
- `tests/dumps/latest/`: Bản sao chép của lần dump gần nhất để kiểm tra nhanh.


---

## 💡 Mẹo Tiện ích (Global Help)

```bash
# Xem trợ giúp tổng quan
python main-cli.py --help

# Xem trợ giúp lệnh delete của từng nhóm
python main-cli.py account delete --help
python main-cli.py proxy delete --help
python main-cli.py automation delete --help
python main-cli.py redroid remove --help
```