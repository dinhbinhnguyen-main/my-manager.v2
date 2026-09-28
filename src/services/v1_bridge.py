"""Bridge Service connecting my-manager.v2 to my-manager.v1 SQLite Database and Images Storage."""

import os
import sqlite3
import logging
import re
from pathlib import Path
from typing import Optional, List, Dict, Any, Tuple

from src.db.repository import SettingRepository

logger = logging.getLogger(__name__)

# Vietnamese mappings for database enums / keys
REAL_ESTATE_CATEGORY_MAP = {
    "townhouse": "Nhà phố",
    "street_front_house": "Nhà mặt tiền",
    "apartment_condo": "Căn hộ/Chung cư",
    "villa": "Biệt thự",
    "land_plot": "Đất nền",
    "warehouse_yard": "Kho/Bãi",
    "business_premises": "Mặt bằng kinh doanh",
    "hotel": "Khách sạn",
    "homestay": "Homestay",
}

TRANSACTION_TYPE_MAP = {
    "rental": "Cho thuê",
    "rent": "Cho thuê",
    "thue": "Cho thuê",
    "cho_thue": "Cho thuê",
    "1": "Cho thuê",
    "sale": "Bán",
    "ban": "Bán",
    "0": "Bán",
    "transfer": "Sang nhượng",
    "sang_nhuong": "Sang nhượng",
    "2": "Sang nhượng",
}

LEGAL_MAP = {
    "vi_bang_purchase": "Mua bán vi bằng",
    "shared_agriculture_deed": "Sổ nông nghiệp chung",
    "agricultural_land_shared": "Sổ nông nghiệp chung",
    "decentralized_agriculture_deed": "Sổ nông nghiệp phân quyền",
    "agricultural_land_fractional": "Sổ nông nghiệp phân quyền",
    "private_agriculture_deed": "Sổ nông nghiệp riêng",
    "agricultural_land_private": "Sổ nông nghiệp riêng",
    "shared_construction_deed": "Sổ xây dựng chung",
    "building_land_shared": "Sổ xây dựng chung",
    "decentralized_construction_deed": "Sổ xây dựng phân quyền",
    "building_land_fractional": "Sổ xây dựng phân quyền",
    "private_construction_deed": "Sổ xây dựng riêng",
    "building_land_private": "Sổ xây dựng riêng",
}

BUILDING_LINE_MAP = {
    "car_access_road": "Đường xe hơi",
    "motorbike_access_road": "Đường xe máy",
    "motorcycle_access_road": "Đường xe máy",
}

FURNITURE_MAP = {
    "no_furniture": "Không nội thất",
    "basic_furniture": "Nội thất cơ bản",
    "full_furniture": "Đầy đủ nội thất",
}


def _format_ward(ward_raw: Any) -> str:
    """Cleans and standardizes ward names (e.g. phuong_8_lam_vien -> Phường 8)."""
    if not ward_raw:
        return ""
    w = str(ward_raw).strip()
    if w.isdigit():
        return f"Phường {w}" if w != "0" else ""
    m = re.match(r"(?i)phuong_(\d+)", w)
    if m:
        return f"Phường {m.group(1)}"
    m_xa = re.match(r"(?i)xa_([^_]+)", w)
    if m_xa:
        return f"Xã {m_xa.group(1).title()}"
    m_tt = re.match(r"(?i)thi_tran_([^_]+)", w)
    if m_tt:
        return f"Thị trấn {m_tt.group(1).title()}"
    return w.replace("_", " ").title()


def _format_district(district_raw: Any) -> str:
    d = str(district_raw or "Đà Lạt").strip().lower()
    if d in ("0", "dac_lat", "da_lat", "đà lạt"):
        return "Đà Lạt"
    if d in ("lac_duong", "lạc dương"):
        return "Lạc Dương"
    return str(district_raw).replace("_", " ").title()


def _format_province(province_raw: Any) -> str:
    p = str(province_raw or "Lâm Đồng").strip().lower()
    if p in ("0", "lam_dong", "lâm đồng"):
        return "Lâm Đồng"
    return str(province_raw).replace("_", " ").title()


class V1DatabaseBridge:
    def __init__(self):
        self._db_path = SettingRepository.get(
            "v1_db_path", "/home/dinhbinhnguyen/Devs/my-manager.v1/bin/products.db"
        )
        self._image_dir = SettingRepository.get(
            "v1_image_dir", "/home/dinhbinhnguyen/Devs/my-manager.v1/bin/products"
        )

    def _get_v1_connection(self) -> Optional[sqlite3.Connection]:
        """Creates a SQLite connection to my-manager.v1 / phonemanager.v1 DB."""
        db_file = Path(self._db_path)
        if not db_file.exists():
            logger.error(f"v1 SQLite DB file not found at '{self._db_path}'. Check setting 'v1_db_path'.")
            return None

        try:
            conn = sqlite3.connect(str(db_file), timeout=10.0)
            conn.row_factory = sqlite3.Row
            return conn
        except Exception as e:
            logger.error(f"Failed to connect to v1 SQLite DB '{self._db_path}': {e}")
            return None

    def get_random_product_for_account(
        self, account: Any, allow_fallback: bool = False
    ) -> Optional[Dict[str, Any]]:
        """
        Retrieves a random product strictly matching account requirements:
        1. status must be 'selling' (or 1 / True in SQLite)
        2. category must match account.category ('real_estate', 'tire', etc.)
        3. transaction_type must match account.transaction_type ('rental', 'sale', etc.)
        """
        category = getattr(account, "category", "real_estate") or "real_estate"
        trans_type = getattr(account, "transaction_type", "rental") or "rental"
        return self.get_random_active_product(
            category=category, 
            transaction_type=trans_type,
            allow_fallback=allow_fallback
        )

    def get_random_active_product(
        self, category: str = "real_estate", transaction_type: str = "rental", allow_fallback: bool = False
    ) -> Optional[Dict[str, Any]]:
        conn = self._get_v1_connection()
        if not conn:
            return None

        try:
            cursor = conn.cursor()
            category_clean = str(category).lower().strip()
            trans_clean = str(transaction_type).lower().strip()

            if category_clean in ("real_estate", "realestate", "bds", "nha_dat"):
                cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND (name='RealEstateProducts' OR name='real_estate_products')")
                tables = [r[0] for r in cursor.fetchall()]
                tbl_name = "RealEstateProducts" if "RealEstateProducts" in tables else "real_estate_products"

                # Strict status filter: only products with status 'selling' (or integer 1)
                status_clause = "(status = 'selling' OR status = 1 OR status = '1')"

                # Map transaction_type: 1 for rental, 0 for sale, 2 for transfer
                if trans_clean in ("rental", "rent", "thue", "cho_thue", "1"):
                    trans_code = 1
                    trans_text = "rental"
                elif trans_clean in ("transfer", "sang_nhuong", "2"):
                    trans_code = 2
                    trans_text = "transfer"
                else:
                    trans_code = 0
                    trans_text = "sale"

                # 1. Strictly match category = real_estate, status = selling, transaction_type = rental/sale/transfer
                query = f"""
                    SELECT * FROM {tbl_name}
                    WHERE {status_clause}
                      AND (transaction_type = ? OR transaction_type = ? OR LOWER(CAST(transaction_type AS TEXT)) = ?)
                    ORDER BY RANDOM()
                    LIMIT 1
                """
                cursor.execute(query, (trans_code, str(trans_code), trans_text))
                row = cursor.fetchone()

                if not row:
                    if allow_fallback:
                        logger.warning(
                            f"No product with status='selling' found matching category='{category}' and transaction_type='{transaction_type}'. "
                            f"Fallback enabled: picking any active product with status='selling'..."
                        )
                        fallback_query = f"SELECT * FROM {tbl_name} WHERE {status_clause} ORDER BY RANDOM() LIMIT 1"
                        cursor.execute(fallback_query)
                        row = cursor.fetchone()
                    else:
                        logger.warning(
                            f"No product with status='selling' found strictly matching category='{category}' and transaction_type='{transaction_type}' in {tbl_name}."
                        )

                if row:
                    p = dict(row)
                    logger.info(
                        f"Retrieved real estate product ID '{p.get('id')}' (status='{p.get('status')}', trans_type='{p.get('transaction_type')}') "
                        f"strictly matching category='{category}', transaction_type='{transaction_type}'"
                    )
                    return p
            else:
                cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND (name='MiscProducts' OR name='misc_products')")
                tables = [r[0] for r in cursor.fetchall()]
                tbl_name = "MiscProducts" if "MiscProducts" in tables else "misc_products"

                cursor.execute(f"PRAGMA table_info({tbl_name})")
                cols = [c[1] for c in cursor.fetchall()]
                status_clause = "(status = 'selling' OR status = 1 OR status = '1')"

                if "category" in cols:
                    where_clause = "(category = ? OR name LIKE ? OR LOWER(category) = ?)"
                    params = (category, f"%{category}%", category_clean)
                else:
                    where_clause = "(name LIKE ? OR LOWER(name) = ?)"
                    params = (f"%{category}%", category_clean)

                query = f"""
                    SELECT * FROM {tbl_name}
                    WHERE {where_clause} AND {status_clause}
                    ORDER BY RANDOM()
                    LIMIT 1
                """
                cursor.execute(query, params)
                row = cursor.fetchone()
                if not row:
                    if allow_fallback:
                        cursor.execute(f"SELECT * FROM {tbl_name} WHERE {status_clause} ORDER BY RANDOM() LIMIT 1")
                        row = cursor.fetchone()
                    else:
                        logger.warning(
                            f"No misc product with status='selling' found matching category='{category}' in {tbl_name}."
                        )

                if row:
                    p = dict(row)
                    logger.info(f"Retrieved misc product ID '{p.get('id')}' for category '{category}'")
                    return p

            logger.warning(f"No product found strictly matching category='{category}', transaction_type='{transaction_type}' with status='selling'.")
            return None
        except Exception as e:
            logger.error(f"Error querying product from v1 DB: {e}")
            return None
        finally:
            conn.close()

    def get_random_active_real_estate(
        self, transaction_type: str = "rental"
    ) -> Optional[Dict[str, Any]]:
        return self.get_random_active_product(category="real_estate", transaction_type=transaction_type)

    def get_product_images(self, product_id: str) -> List[str]:
        """
        Retrieves absolute paths of image files for a specific product ID from v1_image_dir.
        Takes images strictly from the original source directory (source_*), avoiding watermark images.
        """
        image_base = Path(self._image_dir)
        valid_exts = {".jpg", ".jpeg", ".png", ".webp"}
        images = []

        target_dirs = [
            image_base / str(product_id),
            Path("/home/dinhbinhnguyen/Devs/my-manager.v1/bin/products") / str(product_id),
            Path("/home/dinhbinhnguyen/Devs/phonemanager.v1/repositories/images") / str(product_id),
            Path("/home/dinhbinhnguyen/Devs/my-manager.v1/assets/images") / str(product_id),
        ]

        for p_dir in target_dirs:
            if p_dir.exists():
                # 1. Prioritize source_* directory (source_<id>, source_*, etc.)
                src_dirs = [
                    d for d in p_dir.iterdir()
                    if d.is_dir() and d.name.lower().startswith("source")
                ]
                for s_dir in src_dirs:
                    found = [
                        str(f) for f in sorted(s_dir.iterdir())
                        if f.is_file() and f.suffix.lower() in valid_exts and not f.name.startswith(".")
                    ]
                    if found:
                        images = found
                        break

                # 2. Fallback: scan p_dir but explicitly exclude any watermark directory
                if not images:
                    for root, dirs, files in os.walk(p_dir):
                        # Filter out watermark directories in-place so os.walk does not traverse them
                        dirs[:] = [d for d in dirs if "watermark" not in d.lower()]
                        for fname in sorted(files):
                            if not fname.startswith(".") and Path(fname).suffix.lower() in valid_exts:
                                images.append(str(Path(root) / fname))

                if images:
                    break

        # Global fallback: if product dir had no images, grab sample images from image_base (excluding watermark)
        if not images and image_base.exists():
            logger.warning(f"No images found in product dir '{product_id}', searching global image_base '{image_base}'...")
            for root, dirs, files in os.walk(image_base):
                dirs[:] = [d for d in dirs if "watermark" not in d.lower()]
                for fname in sorted(files):
                    if not fname.startswith(".") and Path(fname).suffix.lower() in valid_exts:
                        images.append(str(Path(root) / fname))
                        if len(images) >= 5:
                            break
                if len(images) >= 5:
                    break

        images.sort()
        logger.info(f"Found {len(images)} source images for product ID '{product_id}'")
        return images

    def get_template(
        self, template_name: str = "description", transaction_type: str = "sale", category: str = "townhouse"
    ) -> Optional[str]:
        """Retrieves template format string from real_estate_templates / RealEstateTemplates in v1 DB."""
        conn = self._get_v1_connection()
        if not conn:
            return None

        try:
            cursor = conn.cursor()
            cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND (name='RealEstateTemplates' OR name='real_estate_templates')")
            tbl_res = cursor.fetchone()
            tbl = tbl_res[0] if tbl_res else "real_estate_templates"

            # 1. Exact match: name, transaction_type, category
            cursor.execute(
                f"SELECT value FROM {tbl} WHERE name = ? AND transaction_type = ? AND category = ? ORDER BY is_default DESC, id DESC LIMIT 1",
                (template_name, transaction_type, category)
            )
            row = cursor.fetchone()
            if row:
                return row["value"]

            # 2. Match name and transaction_type
            cursor.execute(
                f"SELECT value FROM {tbl} WHERE name = ? AND transaction_type = ? ORDER BY is_default DESC, id DESC LIMIT 1",
                (template_name, transaction_type)
            )
            row = cursor.fetchone()
            if row:
                return row["value"]

            # 3. Match name only
            cursor.execute(
                f"SELECT value FROM {tbl} WHERE name = ? ORDER BY is_default DESC, id DESC LIMIT 1",
                (template_name,)
            )
            row = cursor.fetchone()
            if row:
                return row["value"]

            return None
        except Exception as e:
            logger.error(f"Error querying templates from v1 DB: {e}")
            return None
        finally:
            conn.close()

    def format_product_summary(self, product: Dict[str, Any]) -> Tuple[str, str]:
        """
        Formats raw product dict into Title and detailed Description strings in 100% Vietnamese.
        Translates category/legal/building_line/furniture enums and applies real_estate_templates.
        """
        # 1. Contact Information
        contact_phone = SettingRepository.get("contact_phone", "0375 155 525") or "0375 155 525"
        contact_telegram = SettingRepository.get("contact_telegram", "@dinhbinhnguyen") or "@dinhbinhnguyen"
        contact_name = SettingRepository.get("contact_name", "Đ. Bình") or "Đ. Bình"
        phone = contact_phone

        # 2. Category & Transaction Type in Vietnamese
        raw_cat = str(product.get("category", "")).lower().strip()
        cat_vn = REAL_ESTATE_CATEGORY_MAP.get(raw_cat, raw_cat.replace("_", " ").title() if raw_cat else "Nhà đất")

        raw_trans = str(product.get("transaction_type", "")).lower().strip()
        trans_vn = TRANSACTION_TYPE_MAP.get(raw_trans, "Cho thuê" if raw_trans in ("1", "rental") else "Bán")
        trans_key = "rental" if trans_vn == "Cho thuê" else ("transfer" if trans_vn == "Sang nhượng" else "sale")
        is_rental = trans_key == "rental"

        # 3. Location Details
        street = str(product.get("street", "") or "").strip().title()
        ward = _format_ward(product.get("ward", ""))
        district = _format_district(product.get("district", "Đà Lạt"))
        province = _format_province(product.get("province", "Lâm Đồng"))

        location_parts = [p for p in [street, ward, district] if p]
        location_str = ", ".join(location_parts) or f"{district}, {province}"

        # 4. Specifications & Pricing
        area = product.get("area", 0)
        raw_price = product.get("price", 0)
        unit = str(product.get("unit", "")).lower().strip()

        try:
            p_val = float(raw_price)
            if "billion" in unit or (not is_rental and 0 < p_val < 1000):
                price_val_str = f"{p_val:g}"
                unit_str = "tỷ"
                price_label = "Giá bán"
            elif "million_per_month" in unit or (is_rental and 0 < p_val < 100):
                price_val_str = f"{p_val:g}"
                unit_str = "triệu/tháng"
                price_label = "Giá thuê"
            elif "million" in unit:
                price_val_str = f"{p_val:g}"
                unit_str = "triệu/tháng" if is_rental else "triệu"
                price_label = "Giá thuê" if is_rental else "Giá bán"
            elif p_val >= 1000:
                price_val_str = f"{p_val:,.0f} VNĐ"
                unit_str = ""
                price_label = "Giá thuê" if is_rental else "Giá bán"
            else:
                price_val_str = "Thỏa thuận"
                unit_str = ""
                price_label = "Giá thuê" if is_rental else "Giá bán"
        except Exception:
            price_val_str = str(raw_price)
            unit_str = ""
            price_label = "Giá thuê" if is_rental else "Giá bán"

        price_full = f"{price_val_str} {unit_str}".strip()

        # 5. Attributes (Legal, Structure, Furniture, Building Line)
        raw_legal = str(product.get("legal", "")).lower().strip()
        legal_vn = LEGAL_MAP.get(raw_legal, raw_legal.replace("_", " ").title() if raw_legal not in ("none", "", "0") else "")

        raw_bline = str(product.get("building_line", "")).lower().strip()
        bline_vn = BUILDING_LINE_MAP.get(raw_bline, raw_bline.replace("_", " ").title() if raw_bline not in ("none", "", "0") else "")

        raw_furn = str(product.get("furniture", "")).lower().strip()
        furn_vn = FURNITURE_MAP.get(raw_furn, raw_furn.replace("_", " ").title() if raw_furn not in ("none", "", "0") else "")

        structure = product.get("structure")
        struct_str = f"{int(structure)}" if structure and str(structure) not in ("0", "0.0") else "1"

        func_str = str(product.get("function", "") or "").strip()
        raw_desc = str(product.get("description", "") or "").strip()

        # 6. Apply Templates with Placeholders
        title_tpl = self.get_template("title", transaction_type=trans_key, category=raw_cat)
        desc_tpl = self.get_template("description", transaction_type=trans_key, category=raw_cat)

        replacements = {
            "<transaction_type>": trans_vn,
            "<category>": cat_vn,
            "<price>": price_val_str,
            "<unit>": f" {unit_str}".rstrip(),
            "<street>": street,
            "<ward>": ward,
            "<district>": district,
            "<province>": province,
            "<area>": f"{area:g}" if isinstance(area, (int, float)) else str(area),
            "<structure>": struct_str,
            "<function>": func_str,
            "<building_line>": bline_vn,
            "<furniture>": furn_vn,
            "<legal>": legal_vn,
            "<description>": raw_desc,
            "<phone_number>": f"{phone} (Zalo/WhatsApp)",
            "<name>": f"{contact_name} | Telegram: {contact_telegram}",
            "<phone_number_icon>": f"{phone} (Zalo/WhatsApp)",
            "<pid>": str(product.get("pid", "") or ""),
            "<icon>": "🏡",
        }

        if title_tpl:
            title = title_tpl
            for k, v in replacements.items():
                title = title.replace(k, str(v))
            # Clean up residual artifacts
            title = re.sub(r"\s+", " ", title).strip()
        else:
            title = f"[{trans_vn} {cat_vn} {price_full}] 🏡 {ward}, {district}, {province}".strip()

        if desc_tpl:
            desc = desc_tpl
            for k, v in replacements.items():
                desc = desc.replace(k, str(v))
            # Ensure contact and telegram are clearly present if template didn't have phone/name tags
            if contact_telegram not in desc:
                desc += f"\n☎️ Liên hệ: {phone} (Zalo/WhatsApp) - {contact_name} | Telegram: {contact_telegram}"
        else:
            desc_lines = [
                f"[{trans_vn} {cat_vn} {price_full}]",
                f"📍 Vị trí: {location_str}",
                f"📐 Diện tích: {area} m2",
                f"💰 {price_label}: {price_full}",
            ]
            if struct_str:
                desc_lines.append(f"🏗 Kết cấu: {struct_str} tầng")
            if func_str:
                desc_lines.append(f"🛏 Công năng: {func_str}")
            if bline_vn:
                desc_lines.append(f"🚗 Lối vào: {bline_vn}")
            if furn_vn:
                desc_lines.append(f"🛋 Nội thất: {furn_vn}")
            if legal_vn:
                desc_lines.append(f"📜 Pháp lý: {legal_vn}")
            if raw_desc:
                desc_lines.append(f"📝 Mô tả chi tiết:\n{raw_desc}")
            desc_lines.append(f"☎️ Liên hệ: {phone} (Zalo/WhatsApp) - {contact_name} | Telegram: {contact_telegram}")
            desc = "\n".join(desc_lines)

        return title, desc

