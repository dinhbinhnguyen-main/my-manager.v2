"""AI Prompt Helper and Anti-Spam / Meta Policy Filter Rules."""

import random
from typing import Optional, List, Dict

REAL_ESTATE_ANGLES = [
    {
        "name": "Thực tế & Súc tích",
        "description": "Đi thẳng vào thông số cốt lõi (vị trí, diện tích, công năng, giá), không văn vẻ rườm rà."
    },
    {
        "name": "Trải nghiệm sống & Tiện ích",
        "description": "Nêu bật không gian sống thoáng đãng, thuận tiện đi lại, gần trường, chợ, siêu thị."
    },
    {
        "name": "Góc nhìn giá trị & Tiềm năng",
        "description": "Sắc bén, nhấn mạnh vị trí đẹp, tính thanh khoản cao, phù hợp ở hoặc khai thác cho thuê."
    },
    {
        "name": "Gợi mở nhu cầu",
        "description": "Mở đầu tự nhiên bằng gợi ý tìm nhà an cư hoặc giữ tài sản hợp lý trong tầm tài chính."
    },
    {
        "name": "Review chân thực",
        "description": "Khách quan, gần gũi như người đi xem nhà thực tế chia sẻ lại các điểm cộng lớn."
    }
]

FORBIDDEN_CLICHES = [
    "siêu phẩm", "cực phẩm", "cơ hội vàng", "đẹp lung linh", "đẹp ngỡ ngàng",
    "không thể bỏ qua", "nhanh tay kẻo lỡ", "hoa hậu", "hàng hiếm",
    "đỉnh cao", "rẻ tụt quần", "rẻ sập sàn", "rẻ nhất quả đất", "sốc", "khủng",
    "vỡ nợ", "cắt lỗ", "bán tháo", "ngộp thở", "ngộp ngân hàng", "phát mãi",
    "túng tiền", "cam kết sinh lời", "bao lời", "lời gấp đôi",
    "chính chủ", "chia sẻ ngay", "tag bạn bè", "thả tim", "chấm bài"
]

RANDOM_ICONS_POOL = [
    "🏡", "📍", "🌿", "🔑", "✨", "📌", "☀️", "🏷️", "🏢", "🛋️",
    "📐", "🚗", "🌳", "🪴", "💎", "💰", "🎯", "🏠", "📜", "📞"
]


class AIPromptHelper:
    """Helper to generate concise, Facebook SEO-optimized, policy-compliant prompts for Gemini AI."""

    @staticmethod
    def build_real_estate_rewrite_prompt(
        raw_title: str,
        raw_desc: str,
        is_rental: bool = False
    ) -> str:
        angle = random.choice(REAL_ESTATE_ANGLES)
        cliches_sample = ", ".join([f'"{c}"' for c in random.sample(FORBIDDEN_CLICHES, min(6, len(FORBIDDEN_CLICHES)))])
        sample_icons = " ".join(random.sample(RANDOM_ICONS_POOL, min(4, len(RANDOM_ICONS_POOL))))

        contact_rule = (
            '5. Kêu gọi liên hệ (BẮT BUỘC): Cuối bài luôn phải có đầy đủ thông tin liên hệ chuẩn xác sau: '
            '"📞 LH: 0375 155 525 (Zalo, WhatsApp) | Telegram: @dinhbinhnguyen". '
            'Tuyệt đối không tự ý bịa số điện thoại khác hay bỏ thông tin Telegram.'
        )

        if is_rental:
            rental_rule = "- QUY ĐỊNH PHÁP LÝ (BẮT BUỘC): Đây là bài đăng CHO THUÊ BĐS. TUYỆT ĐỐI KHÔNG nhắc đến bất kỳ vấn đề pháp lý mua bán hay quyền sở hữu nào (như: mua bán vi bằng, sổ riêng xây dựng, sổ hồng, sổ đỏ, công chứng sang tên, đất thổ cư, quy hoạch...). Chỉ tập trung vào công năng, nội thất, tiện ích sinh hoạt, vị trí và giá thuê."
        else:
            rental_rule = "- QUY ĐỊNH PHÁP LÝ (BẮT BUỘC): Đây là bài đăng MUA BÁN BĐS. Trình bày rõ diện tích, vị trí, pháp lý nếu có."

        prompt = f"""Bạn là chuyên gia viết bài BĐS chuẩn SEO Facebook, tuân thủ nghiêm ngặt chính sách và thuật toán chống spam của Meta.

Nhiệm vụ: Viết lại tin BĐS sau thành bài đăng Facebook NGẮN GỌN, TỰ NHIÊN, DỄ ĐỌC VÀ HẤP DẪN.
Góc nhìn thể hiện: {angle['name']} ({angle['description']}).

TIÊU CHUẨN NỘI DUNG & SEO FACEBOOK:
1. Độ dài & Bố cục: Ngắn gọn (dưới 100 từ), 3-5 dòng/gạch đầu dòng ngắt quãng thoáng mắt, tối ưu hiển thị trên điện thoại.
2. Chuẩn SEO Facebook: Dòng đầu nêu rõ [Loại BĐS tiếng Việt] + [Vị trí/Quận/Đường] + Điểm sáng chính để tối ưu tìm kiếm trên Facebook.
3. Thân bài & Thông số: Đi thẳng vào thông tin người mua/thuê cần (diện tích, kết cấu, tiện ích nổi bật, giá bán/thuê). Giữ đúng thông số gốc, bỏ mục trống/0/mã tin/PID.
4. Thêm Icon (Emoji) sinh động & hấp dẫn: Bố trí icon trực quan ở đầu mỗi dòng/ý chính (ví dụ: 📍 vị trí, 📐 diện tích, 🏡 kết cấu/công năng, 💰 giá, 🌿 không gian/tiện ích, ✨ điểm nổi bật) giúp bài đăng bắt mắt, chuyên nghiệp và cuốn hút người đọc hơn.
{contact_rule}
6. Cuối bài: Kèm đúng 3-4 hashtag chuẩn SEO (ví dụ: #nhadep #bds_khuvuc #muabannhadat).

CHỐNG SPAM & TUÂN THỦ CHÍNH SÁCH FACEBOOK:
- CẤM TIẾNG ANH / TỪ LAI ENUM: Tuyệt đối KHÔNG dùng các từ tiếng Anh như "TOWN_HOUSE", "TOWNHOUSE", "HOMESTAY", "VILLA" nếu có từ tiếng Việt tương đương ("Nhà phố", "Căn hộ", "Biệt thự", "Đất nền", "Mặt bằng kinh doanh"). Toàn bộ bài đăng phải viết bằng 100% tiếng Việt tự nhiên.
- CẤM TỪ SÁO RỖNG & GIẬT TÍT: Không dùng {cliches_sample}.
- CẤM TỪ TIÊU CỰC / VI PHẠM TÀI CHÍNH: Tuyệt đối không dùng "vỡ nợ", "cắt lỗ", "bán tháo", "ngộp", "phát mãi", "cam kết lời".
- CẤM MỒI TƯƠNG TÁC (Engagement Bait): Không dùng "chia sẻ ngay", "tag bạn bè", "thả tim", "chấm bài".
- CẤM ĐỊNH DẠNG SPAM: Không dùng markdown (**), không viết hoa toàn bộ (ALL CAPS), không spam chuỗi icon dày đặc liên tiếp (như 🔥🔥🔥). Sử dụng các icon tinh tế, đúng ngữ cảnh cho từng ý ({sample_icons}).
{rental_rule}

DỮ LIỆU BẤT ĐỘNG SẢN GỐC:
- Tiêu đề gốc: {raw_title}
- Mô tả gốc: {raw_desc}

CHỈ TRẢ VỀ DUY NHẤT BÀI ĐĂNG HOÀN CHỈNH (Không lời chào, không giải thích thêm)."""
        return prompt

    @staticmethod
    def build_real_estate_listing_prompt(
        raw_title: str,
        raw_desc: str,
        is_rental: bool = False
    ) -> str:
        angle = random.choice(REAL_ESTATE_ANGLES)
        cliches_sample = ", ".join([f'"{c}"' for c in random.sample(FORBIDDEN_CLICHES, min(6, len(FORBIDDEN_CLICHES)))])
        sample_icons = " ".join(random.sample(RANDOM_ICONS_POOL, min(4, len(RANDOM_ICONS_POOL))))

        contact_rule = (
            '5. Kêu gọi liên hệ (BẮT BUỘC): Cuối bài luôn phải có đầy đủ thông tin liên hệ chuẩn xác sau: '
            '"📞 LH: 0375 155 525 (Zalo, WhatsApp) | Telegram: @dinhbinhnguyen". '
            'Tuyệt đối không tự ý bịa số điện thoại khác hay bỏ thông tin Telegram.'
        )

        if is_rental:
            rental_rule = "- QUY ĐỊNH PHÁP LÝ (BẮT BUỘC): Đây là bài đăng CHO THUÊ BĐS. TUYỆT ĐỐI KHÔNG nhắc đến bất kỳ vấn đề pháp lý mua bán hay quyền sở hữu nào (như: mua bán vi bằng, sổ riêng xây dựng, sổ hồng, sổ đỏ, công chứng sang tên, đất thổ cư, quy hoạch...). Chỉ tập trung vào công năng, nội thất, tiện ích sinh hoạt, vị trí và giá thuê."
        else:
            rental_rule = "- QUY ĐỊNH PHÁP LÝ (BẮT BUỘC): Đây là bài đăng MUA BÁN BĐS. Trình bày rõ diện tích, vị trí, pháp lý nếu có."

        prompt = f"""Bạn là chuyên gia viết bài BĐS chuẩn SEO Facebook, tuân thủ nghiêm ngặt chính sách và thuật toán chống spam của Meta.

Nhiệm vụ: Viết lại tin BĐS sau thành TIÊU ĐỀ (Title) và MÔ TẢ (Description) bài đăng Facebook.
Góc nhìn thể hiện: {angle['name']} ({angle['description']}).

YÊU CẦU TIÊU ĐỀ (Title):
1. Độ dài: Tối đa 90 ký tự (BẮT BUỘC <= 90 ký tự, đếm cả khoảng trắng, tuyệt đối không viết dài hơn 90 ký tự).
2. Nội dung: Hấp dẫn, nêu bật [Loại BĐS tiếng Việt] + [Vị trí/Quận/Đường] + [Điểm sáng chính].
3. Điểm nhấn: Có thể thêm 1 icon phù hợp ở đầu tiêu đề (ví dụ: 🏡, 📍, ✨) để tạo điểm nhấn bắt mắt khi lướt feed; không viết hoa toàn bộ (ALL CAPS), không giật tít sáo rỗng.

YÊU CẦU MÔ TẢ (Description):
1. Độ dài & Bố cục: Ngắn gọn (dưới 100 từ), 3-5 dòng/gạch đầu dòng ngắt quãng thoáng mắt, tối ưu hiển thị trên điện thoại.
2. Chuẩn SEO Facebook: Dòng đầu nêu rõ [Loại BĐS tiếng Việt] + [Vị trí/Quận/Đường] + Điểm sáng chính để tối ưu tìm kiếm trên Facebook.
3. Thân bài & Thông số: Đi thẳng vào thông tin người mua/thuê cần (diện tích, kết cấu, tiện ích nổi bật, giá bán/thuê). Giữ đúng thông số gốc, bỏ mục trống/0/mã tin/PID.
4. Thêm Icon (Emoji) sinh động & hấp dẫn: Bố trí icon trực quan ở đầu mỗi dòng/ý chính (ví dụ: 📍 vị trí, 📐 diện tích, 🏡 kết cấu/công năng, 💰 giá, 🌿 không gian/tiện ích, ✨ điểm nổi bật) giúp bài đăng bắt mắt, chuyên nghiệp và cuốn hút người đọc hơn.
{contact_rule}
6. Cuối bài: Kèm đúng 3-4 hashtag chuẩn SEO (ví dụ: #nhadep #bds_khuvuc #muabannhadat).

CHỐNG SPAM & TUÂN THỦ CHÍNH SÁCH FACEBOOK:
- CẤM TIẾNG ANH / TỪ LAI ENUM: Tuyệt đối KHÔNG dùng các từ tiếng Anh như "TOWN_HOUSE", "TOWNHOUSE", "HOMESTAY", "VILLA" nếu có từ tiếng Việt tương đương ("Nhà phố", "Căn hộ", "Biệt thự", "Đất nền", "Mặt bằng kinh doanh"). Toàn bộ bài đăng phải viết bằng 100% tiếng Việt tự nhiên.
- CẤM TỪ SÁO RỖNG & GIẬT TÍT: Không dùng {cliches_sample}.
- CẤM TỪ TIÊU CỰC / VI PHẠM TÀI CHÍNH: Tuyệt đối không dùng "vỡ nợ", "cắt lỗ", "bán tháo", "ngộp", "phát mãi", "cam kết lời".
- CẤM MỒI TƯƠNG TÁC (Engagement Bait): Không dùng "chia sẻ ngay", "tag bạn bè", "thả tim", "chấm bài".
- CẤM ĐỊNH DẠNG SPAM: Không dùng markdown (**), không viết hoa toàn bộ (ALL CAPS), không spam chuỗi icon dày đặc liên tiếp (như 🔥🔥🔥). Sử dụng các icon tinh tế, đúng ngữ cảnh cho từng ý ({sample_icons}).
{rental_rule}

DỮ LIỆU BẤT ĐỘNG SẢN GỐC:
- Tiêu đề gốc: {raw_title}
- Mô tả gốc: {raw_desc}

ĐỊNH DẠNG TRẢ VỀ:
Bắt buộc trả về đúng 1 JSON object hợp lệ duy nhất (không có lời mở đầu hay giải thích thêm, các dòng ngắt trong description dùng ký tự \\n):
{{
  "title": "Tiêu đề dưới 90 ký tự",
  "description": "Nội dung bài viết đầy đủ..."
}}"""
        return prompt
