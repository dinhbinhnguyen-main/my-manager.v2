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

RANDOM_ICONS_POOL = ["🏡", "📍", "🌿", "🔑", "✨", "📌", "☀️", "🏷️", "🏢", "🛋️", "📐", "🚗", "🌳", "🪴"]


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
        sample_icons = " ".join(random.sample(RANDOM_ICONS_POOL, min(3, len(RANDOM_ICONS_POOL))))

        contact_rule = (
            '4. Kêu gọi liên hệ (BẮT BUỘC): Cuối bài luôn phải có đầy đủ thông tin liên hệ chuẩn xác sau: '
            '"LH: 0375 155 525 (Zalo, WhatsApp) | Telegram: @dinhbinhnguyen". '
            'Tuyệt đối không tự ý bịa số điện thoại khác hay bỏ thông tin Telegram.'
        )

        if is_rental:
            rental_rule = "- QUY ĐỊNH PHÁP LÝ (BẮT BUỘC): Đây là bài đăng CHO THUÊ BĐS. TUYỆT ĐỐI KHÔNG nhắc đến bất kỳ vấn đề pháp lý mua bán hay quyền sở hữu nào (như: mua bán vi bằng, sổ riêng xây dựng, sổ hồng, sổ đỏ, công chứng sang tên, đất thổ cư, quy hoạch...). Chỉ tập trung vào công năng, nội thất, tiện ích sinh hoạt, vị trí và giá thuê."
        else:
            rental_rule = "- QUY ĐỊNH PHÁP LÝ (BẮT BUỘC): Đây là bài đăng MUA BÁN BĐS. Trình bày rõ diện tích, vị trí, pháp lý nếu có."

        prompt = f"""Bạn là chuyên gia viết bài BĐS chuẩn SEO Facebook, tuân thủ nghiêm ngặt chính sách và thuật toán chống spam của Meta.

Nhiệm vụ: Viết lại tin BĐS sau thành bài đăng Facebook NGẮN GỌN, TỰ NHIÊN, DỄ ĐỌC.
Góc nhìn thể hiện: {angle['name']} ({angle['description']}).

TIÊU CHUẨN NỘI DUNG & SEO FACEBOOK:
1. Độ dài & Bố cục: Ngắn gọn (dưới 100 từ), 3-5 dòng/gạch đầu dòng ngắt quãng thoáng mắt, tối ưu hiển thị trên điện thoại.
2. Chuẩn SEO Facebook: Dòng đầu nêu rõ [Loại BĐS tiếng Việt] + [Vị trí/Quận/Đường] + Điểm sáng chính để tối ưu tìm kiếm trên Facebook.
3. Thân bài: Đi thẳng vào thông tin người mua/thuê cần (diện tích, kết cấu, tiện ích nổi bật, giá bán/thuê). Giữ đúng thông số gốc, bỏ mục trống/0/mã tin/PID.
{contact_rule}
5. Cuối bài: Kèm đúng 3-4 hashtag chuẩn SEO (ví dụ: #nhadep #bds_khuvuc #muabannhadat).

CHỐNG SPAM & TUÂN THỦ CHÍNH SÁCH FACEBOOK:
- CẤM TIẾNG ANH / TỪ LAI ENUM: Tuyệt đối KHÔNG dùng các từ tiếng Anh như "TOWN_HOUSE", "TOWNHOUSE", "HOMESTAY", "VILLA" nếu có từ tiếng Việt tương đương ("Nhà phố", "Căn hộ", "Biệt thự", "Đất nền", "Mặt bằng kinh doanh"). Toàn bộ bài đăng phải viết bằng 100% tiếng Việt tự nhiên.
- CẤM TỪ SÁO RỖNG & GIẬT TÍT: Không dùng {cliches_sample}.
- CẤM TỪ TIÊU CỰC / VI PHẠM TÀI CHÍNH: Tuyệt đối không dùng "vỡ nợ", "cắt lỗ", "bán tháo", "ngộp", "phát mãi", "cam kết lời".
- CẤM MỒI TƯƠNG TÁC (Engagement Bait): Không dùng "chia sẻ ngay", "tag bạn bè", "thả tim", "chấm bài".
- CẤM ĐỊNH DẠNG SPAM: Không dùng markdown (**), không viết hoa toàn bộ (ALL CAPS), chỉ dùng 2-3 icon nhẹ nhàng ({sample_icons}).
{rental_rule}

DỮ LIỆU BẤT ĐỘNG SẢN GỐC:
- Tiêu đề gốc: {raw_title}
- Mô tả gốc: {raw_desc}

CHỈ TRẢ VỀ DUY NHẤT BÀI ĐĂNG HOÀN CHỈNH (Không lời chào, không giải thích thêm)."""
        return prompt
