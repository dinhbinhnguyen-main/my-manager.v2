"""Bridge Service connecting my-manager.v2 to CRM Server (192.168.1.12) and v1 SQLite Database."""

import os
import time
import json
import sqlite3
import logging
import re
import requests
from pathlib import Path
from typing import Optional, List, Dict, Any, Tuple

from src.db.repository import SettingRepository
from src.core.constants import CRM_SERVER_URL, CRM_DB_PATH, CRM_IMAGES_DIR

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

CRM_PROPERTY_TYPE_MAP = {
    "TOWNHOUSE": "Nhà phố",
    "STREET_FRONT_HOUSE": "Nhà mặt tiền",
    "APARTMENT": "Căn hộ/Chung cư",
    "VILLA": "Biệt thự",
    "LAND": "Đất nền",
    "WAREHOUSE": "Kho/Bãi",
    "BUSINESS_PREMISES": "Mặt bằng kinh doanh",
    "HOTEL": "Khách sạn",
    "HOMESTAY": "Homestay",
}

CRM_ACCESS_TYPE_MAP = {
    "CAR_TO_DOOR": "Đường xe hơi tới cửa",
    "CAR_PARKING": "Đường ô tô tránh nhau",
    "MOTORBIKE": "Đường xe máy",
    "WALKING": "Đường đi bộ",
}

CRM_FURNITURE_MAP = {
    "FULL": "Đầy đủ nội thất",
    "BASIC": "Nội thất cơ bản",
    "EMPTY": "Không nội thất",
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
    """Cleans and standardizes ward names (e.g. phuong_8_lam_vien -> Ward 8)."""
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
        self._crm_url = SettingRepository.get("crm_server_url", CRM_SERVER_URL) or CRM_SERVER_URL
        self._data_source = SettingRepository.get("data_source", "crm") or "crm"
        self._crm_db_path = Path(SettingRepository.get("crm_db_path", str(CRM_DB_PATH)))
        self._crm_images_dir = Path(SettingRepository.get("crm_images_dir", str(CRM_IMAGES_DIR)))
        self._crm_images_dir.mkdir(parents=True, exist_ok=True)

        self._db_path = SettingRepository.get(
            "v1_db_path", "/Users/dinhbinhnguyen/Dev/my-manager.v1/bin/products.db"
        )
        self._image_dir = SettingRepository.get(
            "v1_image_dir", "/Users/dinhbinhnguyen/Dev/my-manager.v1/bin/products"
        )

    def sync_crm_database(self, force: bool = False, max_age_seconds: int = 1800) -> bool:
        """
        Synchronizes SQLite snapshot from real-estate-crm server (GET /api/crm/sync-db).
        Caches file at self._crm_db_path. Falls back to existing local snapshot if offline.
        """
        db_path = self._crm_db_path
        if not force and db_path.exists() and db_path.stat().st_size > 0:
            try:
                age = time.time() - db_path.stat().st_mtime
                if age < max_age_seconds:
                    return True
            except Exception:
                pass

        sync_url = f"{self._crm_url.rstrip('/')}/api/crm/sync-db"
        logger.info(f"Syncing CRM database from {sync_url}...")
        try:
            resp = requests.get(sync_url, timeout=10.0)
            if resp.status_code == 200 and len(resp.content) > 1000:
                db_path.parent.mkdir(parents=True, exist_ok=True)
                temp_path = db_path.with_suffix(".tmp")
                with open(temp_path, "wb") as f:
                    f.write(resp.content)
                temp_path.replace(db_path)
                logger.info(f"Successfully synced CRM DB ({len(resp.content):,} bytes) to {db_path}")
                return True
            else:
                logger.warning(f"CRM sync-db returned unexpected HTTP status {resp.status_code}")
        except Exception as e:
            if db_path.exists() and db_path.stat().st_size > 0:
                logger.warning(f"Could not reach CRM server {sync_url} ({e}). Using existing local cached snapshot.")
                return True
            logger.error(f"Failed to sync CRM database from {sync_url}: {e}")
            return False

        return db_path.exists()

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

    def get_random_crm_property(
        self, transaction_type: str = "rental", allow_fallback: bool = True
    ) -> Optional[Dict[str, Any]]:
        """Retrieves a random Property from synced CRM database."""
        self.sync_crm_database()
        if not self._crm_db_path.exists():
            return None

        trans_clean = str(transaction_type).lower().strip()
        if trans_clean in ("rental", "rent", "thue", "cho_thue", "1"):
            target_types = ("RENT", "RENTAL")
            standard_trans = "rental"
        elif trans_clean in ("transfer", "sang_nhuong", "2"):
            target_types = ("TRANSFER", "SANG_NHUONG")
            standard_trans = "transfer"
        else:
            target_types = ("SALE", "BAN")
            standard_trans = "sale"

        try:
            conn = sqlite3.connect(str(self._crm_db_path), timeout=10.0)
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()

            placeholders = ",".join("?" for _ in target_types)
            query = f"""
                SELECT * FROM Property
                WHERE status = 'SELLING'
                  AND approvalStatus = 'APPROVED'
                  AND UPPER(transactionType) IN ({placeholders})
                ORDER BY RANDOM()
                LIMIT 1
            """
            cursor.execute(query, target_types)
            row = cursor.fetchone()

            if not row and allow_fallback:
                logger.warning(
                    f"No CRM property with transactionType in {target_types} found. "
                    f"Fallback enabled: picking any active selling Property..."
                )
                cursor.execute(
                    "SELECT * FROM Property WHERE status = 'SELLING' AND approvalStatus = 'APPROVED' ORDER BY RANDOM() LIMIT 1"
                )
                row = cursor.fetchone()

            if not row:
                conn.close()
                return None

            r = dict(row)
            conn.close()

            prop_type = str(r.get("propertyType") or "TOWNHOUSE").upper()
            raw_cat = CRM_PROPERTY_TYPE_MAP.get(prop_type, "Nhà phố")
            category_key = prop_type.lower()

            price_vnd = r.get("priceVnd") or 0
            area = r.get("landAreaM2") or 0

            images_list = []
            raw_images = r.get("images")
            if raw_images:
                try:
                    images_list = json.loads(raw_images)
                except Exception:
                    pass
            thumb = r.get("thumbnailUrl")
            if thumb and thumb not in images_list:
                images_list.insert(0, thumb)

            return {
                "id": str(r.get("id")),
                "pid": r.get("productCode") or str(r.get("id")),
                "product_code": r.get("productCode"),
                "title": r.get("title") or f"{raw_cat} {r.get('fullAddress') or ''}",
                "category": category_key,
                "property_type": prop_type,
                "transaction_type": standard_trans,
                "price": price_vnd,
                "price_vnd": price_vnd,
                "unit": "VND",
                "area": area,
                "floor_area": r.get("floorAreaM2"),
                "floors": r.get("floors") or 1,
                "structure": r.get("floors") or 1,
                "bedrooms": r.get("totalBedrooms") or 0,
                "bathrooms": r.get("bathrooms") or 1,
                "function": f"{r.get('totalBedrooms', 0)} PN, {r.get('bathrooms', 1)} WC" if r.get("totalBedrooms") else "",
                "street": r.get("street") or "",
                "ward": _format_ward(r.get("ward") or ""),
                "district": _format_district(r.get("city") or "Đà Lạt"),
                "city": r.get("city") or "Đà Lạt",
                "province": _format_province(r.get("province") or "Lâm Đồng"),
                "full_address": r.get("fullAddress") or "",
                "legal": r.get("legalNotes") or r.get("ownershipForm") or "",
                "building_line": CRM_ACCESS_TYPE_MAP.get(str(r.get("accessType") or "").upper(), ""),
                "furniture": CRM_FURNITURE_MAP.get(str(r.get("furnitureStatus") or "").upper(), ""),
                "description": r.get("description") or "",
                "images": images_list,
                "thumbnail_url": thumb,
                "source": "crm",
            }
        except Exception as e:
            logger.error(f"Error querying CRM Property: {e}")
            return None

    def get_random_product_for_account(
        self, account: Any, allow_fallback: bool = True
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
        self, category: str = "real_estate", transaction_type: str = "rental", allow_fallback: bool = True
    ) -> Optional[Dict[str, Any]]:
        category_clean = str(category).lower().strip()
        trans_clean = str(transaction_type).lower().strip()

        # 1. Try CRM first if configured as data source
        if self._data_source == "crm" and category_clean in ("real_estate", "realestate", "bds", "nha_dat"):
            crm_prod = self.get_random_crm_property(transaction_type=trans_clean, allow_fallback=allow_fallback)
            if crm_prod:
                logger.info(f"Retrieved real estate Property from CRM: [{crm_prod.get('pid')}] {crm_prod.get('title')}")
                return crm_prod
            logger.warning("CRM returned no property, attempting fallback to v1 DB...")
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

    def _apply_watermark_to_image(
        self,
        source_path: str,
        dest_path: str,
        contact_name: Optional[str] = None,
        contact_phone: Optional[str] = None,
    ) -> bool:
        """
        Applies logo watermark (Screen blend mode at center) and contact badge (at bottom-right).
        Uses pure Pillow (ImageChops + ImageDraw) without external C/numpy dependencies.
        """
        from PIL import Image, ImageChops, ImageDraw, ImageFont

        dest_file = Path(dest_path)
        if dest_file.exists() and dest_file.stat().st_size > 0:
            return True

        if not os.path.exists(source_path):
            return False

        try:
            main_img = Image.open(source_path).convert("RGB")
            main_w, main_h = main_img.size

            # 1. Screen Blend Logo at center
            logo_candidates = [
                SettingRepository.get("watermark_logo_path"),
                "/Users/dinhbinhnguyen/Dev/my-manager.v1/assets/logos/logo_phone_number.png",
                "/Users/dinhbinhnguyen/Dev/real-estate-crm/public/uploads/logos/1793453163458-ysq9u-logo_un_color_white.png",
                "/Users/dinhbinhnguyen/Dev/real-estate-crm/public/logo-system.png",
                "/home/dinhbinhnguyen/Devs/my-manager.v1/assets/logos/logo_phone_number.png",
            ]
            logo_file = next((p for p in logo_candidates if p and os.path.exists(p)), None)

            if logo_file:
                try:
                    logo = Image.open(logo_file).convert("RGBA")
                    ps = float(SettingRepository.get("watermark_scale", 0.22) or 0.22)
                    opacity = float(SettingRepository.get("watermark_opacity", 0.75) or 0.75)

                    new_logo_w = max(40, int(main_w * ps))
                    new_logo_h = max(40, int(logo.height * (new_logo_w / logo.width)))
                    resized_logo = logo.resize((new_logo_w, new_logo_h), Image.LANCZOS)

                    pos_x = (main_w - new_logo_w) // 2
                    pos_y = (main_h - new_logo_h) // 2

                    area = main_img.crop((pos_x, pos_y, pos_x + new_logo_w, pos_y + new_logo_h))
                    logo_rgb = resized_logo.convert("RGB")
                    screened = ImageChops.screen(area, logo_rgb)

                    alpha = resized_logo.split()[-1].point(lambda p: int(p * opacity))
                    blended = Image.composite(screened, area, alpha)
                    main_img.paste(blended, (pos_x, pos_y))
                except Exception as le:
                    logger.warning(f"Error applying logo watermark from {logo_file}: {le}")

            # 2. Draw Contact Badge at bottom-right
            name = contact_name or SettingRepository.get("contact_name", "Đ. Bình") or "Đ. Bình"
            phone = contact_phone or SettingRepository.get("contact_phone", "0375 155 525") or "0375 155 525"

            if name or phone:
                try:
                    overlay = Image.new("RGBA", main_img.size, (0, 0, 0, 0))
                    draw = ImageDraw.Draw(overlay)

                    name_text = f"{name}"
                    phone_text = f"LH/Zalo: {phone}"

                    font_candidates = [
                        "/System/Library/Fonts/Supplemental/Arial Bold.ttf",
                        "/System/Library/Fonts/Supplemental/Arial.ttf",
                        "/System/Library/Fonts/Helvetica.ttc",
                        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
                        "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf",
                    ]
                    font_path = next((f for f in font_candidates if os.path.exists(f)), None)

                    scale_base = max(14, int(main_w * 0.022))
                    if font_path:
                        font_name = ImageFont.truetype(font_path, scale_base)
                        font_phone = ImageFont.truetype(font_path, int(scale_base * 1.2))
                    else:
                        font_name = ImageFont.load_default()
                        font_phone = ImageFont.load_default()

                    bbox_name = draw.textbbox((0, 0), name_text, font=font_name)
                    bbox_phone = draw.textbbox((0, 0), phone_text, font=font_phone)

                    text_w = max(bbox_name[2] - bbox_name[0], bbox_phone[2] - bbox_phone[0])
                    text_h = (bbox_name[3] - bbox_name[1]) + (bbox_phone[3] - bbox_phone[1]) + 10

                    pad_x = int(main_w * 0.02)
                    pad_y = int(main_h * 0.015)
                    box_w = text_w + pad_x * 2
                    box_h = text_h + pad_y * 2

                    margin = int(main_w * 0.025)
                    x1 = main_w - margin - box_w
                    y1 = main_h - margin - box_h
                    x2 = main_w - margin
                    y2 = main_h - margin

                    draw.rounded_rectangle(
                        [x1, y1, x2, y2],
                        radius=12,
                        fill=(15, 23, 42, 195),
                        outline=(255, 255, 255, 70),
                        width=1,
                    )
                    draw.text((x1 + pad_x, y1 + pad_y), name_text, font=font_name, fill=(226, 232, 240, 240))
                    draw.text(
                        (x1 + pad_x, y1 + pad_y + (bbox_name[3] - bbox_name[1]) + 8),
                        phone_text,
                        font=font_phone,
                        fill=(250, 204, 21, 255),
                    )

                    im_rgba = main_img.convert("RGBA")
                    main_img = Image.alpha_composite(im_rgba, overlay).convert("RGB")
                except Exception as be:
                    logger.warning(f"Error drawing contact badge: {be}")

            dest_file.parent.mkdir(parents=True, exist_ok=True)
            main_img.save(str(dest_file), "JPEG", quality=92)
            return True
        except Exception as e:
            logger.error(f"Error applying watermark to {source_path}: {e}")
            return False

    def _get_crm_product_images(self, product_id: str, is_watermark: bool = True) -> List[str]:
        """Queries, downloads, and watermarks images for a CRM Property ID or productCode from 192.168.1.12."""
        self.sync_crm_database()
        if not self._crm_db_path.exists():
            return []

        images_rel: List[str] = []
        code_label = str(product_id)
        try:
            conn = sqlite3.connect(str(self._crm_db_path), timeout=5.0)
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()
            cursor.execute(
                "SELECT id, productCode, thumbnailUrl, images FROM Property WHERE id = ? OR productCode = ? LIMIT 1",
                (str(product_id), str(product_id))
            )
            row = cursor.fetchone()
            conn.close()

            if not row:
                return []

            code_label = row["productCode"] or row["id"]
            thumb = row["thumbnailUrl"]
            raw_imgs = row["images"]
            if raw_imgs:
                try:
                    images_rel = json.loads(raw_imgs)
                except Exception:
                    pass
            if thumb and thumb not in images_rel:
                images_rel.insert(0, thumb)
        except Exception as e:
            logger.error(f"Error querying CRM images for {product_id}: {e}")
            return []

        if not images_rel:
            return []

        local_crm_public = Path("/Users/dinhbinhnguyen/Dev/real-estate-crm/public")
        local_files: List[str] = []

        for rel in images_rel:
            clean_rel = str(rel).strip().lstrip("/")
            if not clean_rel:
                continue

            # 1. Local copy in real-estate-crm public folder
            cand_local = local_crm_public / clean_rel
            if cand_local.exists() and cand_local.is_file() and cand_local.stat().st_size > 0:
                local_files.append(str(cand_local.resolve()))
                continue

            # 2. Local copy in crm_images cache
            cand_cache = self._crm_images_dir / clean_rel
            if cand_cache.exists() and cand_cache.is_file() and cand_cache.stat().st_size > 0:
                local_files.append(str(cand_cache.resolve()))
                continue

            # 3. Download via HTTP from CRM server
            img_url = f"{self._crm_url.rstrip('/')}/{clean_rel}"
            try:
                logger.info(f"Downloading product image from {img_url}...")
                resp = requests.get(img_url, timeout=10.0)
                if resp.status_code == 200 and len(resp.content) > 0:
                    cand_cache.parent.mkdir(parents=True, exist_ok=True)
                    with open(cand_cache, "wb") as f:
                        f.write(resp.content)
                    local_files.append(str(cand_cache.resolve()))
                else:
                    logger.warning(f"Failed to download image {img_url}: status {resp.status_code}")
            except Exception as e:
                logger.error(f"Error downloading image from {img_url}: {e}")

        # If watermark is requested (default), process and save to watermarked directory
        if is_watermark and local_files:
            watermarked_files: List[str] = []
            safe_code = re.sub(r'[^\w\-_\.]', '_', str(code_label))
            wm_dir = self._crm_images_dir / "watermarked" / safe_code

            contact_name = SettingRepository.get("contact_name", "Đ. Bình")
            contact_phone = SettingRepository.get("contact_phone", "0375 155 525")

            for src in local_files:
                src_p = Path(src)
                dest_p = wm_dir / f"wm_{src_p.name}"
                if self._apply_watermark_to_image(
                    source_path=src,
                    dest_path=str(dest_p),
                    contact_name=contact_name,
                    contact_phone=contact_phone,
                ):
                    watermarked_files.append(str(dest_p.resolve()))
                else:
                    watermarked_files.append(src)
            logger.info(f"Retrieved {len(watermarked_files)} watermarked image(s) for CRM Property '{product_id}'")
            return watermarked_files

        logger.info(f"Retrieved {len(local_files)} source image(s) for CRM Property '{product_id}'")
        return local_files

    def _get_v1_product_images(self, product_id: str, is_watermark: bool = True) -> List[str]:
        """
        Retrieves absolute paths of image files for a specific product ID from v1_image_dir.
        Prioritizes watermarked images (with_watermark_* or directories containing 'watermark') by default (is_watermark=True),
        with fallback to original source directory (source_*).
        If is_watermark=False, prioritizes the source directory with fallback to watermark.
        """
        image_base = Path(self._image_dir)
        valid_exts = {".jpg", ".jpeg", ".png", ".webp"}
        images = []

        target_dirs = [
            image_base / str(product_id),
            Path("/Volumes/KINGSTON/Ext_dev/python/my-manager.v1.repositories/images") / str(product_id),
            Path("/home/dinhbinhnguyen/Devs/my-manager.v1/bin/products") / str(product_id),
            Path("/home/dinhbinhnguyen/Devs/phonemanager.v1/repositories/images") / str(product_id),
            Path("/home/dinhbinhnguyen/Devs/my-manager.v1/assets/images") / str(product_id),
            Path("/Users/dinhbinhnguyen/Dev/my-manager.v1/bin/products") / str(product_id),
            Path("/Users/dinhbinhnguyen/Dev/phonemanager.v1/repositories/images") / str(product_id),
            Path("/Users/dinhbinhnguyen/Dev/my-manager.v1/assets/images") / str(product_id),
        ]

        primary_match = (
            (lambda d: "watermark" in d.name.lower())
            if is_watermark
            else (lambda d: d.name.lower().startswith("source") or "source" in d.name.lower())
        )
        fallback_match = (
            (lambda d: d.name.lower().startswith("source") or "source" in d.name.lower())
            if is_watermark
            else (lambda d: "watermark" in d.name.lower())
        )

        for p_dir in target_dirs:
            if p_dir.exists():
                # 1. Primary directory check (watermark by default, or source)
                primary_dirs = [
                    d for d in p_dir.iterdir()
                    if d.is_dir() and primary_match(d)
                ]
                for d in primary_dirs:
                    found = [
                        str(f) for f in sorted(d.iterdir())
                        if f.is_file() and f.suffix.lower() in valid_exts and not f.name.startswith(".")
                    ]
                    if found:
                        images = found
                        break

                # 2. Fallback directory check
                if not images:
                    fallback_dirs = [
                        d for d in p_dir.iterdir()
                        if d.is_dir() and fallback_match(d)
                    ]
                    for d in fallback_dirs:
                        found = [
                            str(f) for f in sorted(d.iterdir())
                            if f.is_file() and f.suffix.lower() in valid_exts and not f.name.startswith(".")
                        ]
                        if found:
                            images = found
                            break

                # 3. Direct files in p_dir or any remaining subfolder
                if not images:
                    for root, dirs, files in os.walk(p_dir):
                        for fname in sorted(files):
                            if not fname.startswith(".") and Path(fname).suffix.lower() in valid_exts:
                                images.append(str(Path(root) / fname))

                if images:
                    break

        # Global fallback: if product dir had no images, grab sample images from image_base
        if not images and image_base.exists():
            logger.warning(f"No images found in product dir '{product_id}', searching global image_base '{image_base}'...")
            if is_watermark:
                for root, dirs, files in os.walk(image_base):
                    if "watermark" in root.lower():
                        for fname in sorted(files):
                            if not fname.startswith(".") and Path(fname).suffix.lower() in valid_exts:
                                images.append(str(Path(root) / fname))
                                if len(images) >= 5:
                                    break
                    if len(images) >= 5:
                        break

            if not images:
                for root, dirs, files in os.walk(image_base):
                    for fname in sorted(files):
                        if not fname.startswith(".") and Path(fname).suffix.lower() in valid_exts:
                            images.append(str(Path(root) / fname))
                            if len(images) >= 5:
                                break
                    if len(images) >= 5:
                        break

        images.sort()
        img_type = "watermarked" if is_watermark else "source"
        logger.info(f"Found {len(images)} {img_type} images for product ID '{product_id}'")
        return images

    def get_product_images(self, product_id: str, is_watermark: bool = True) -> List[str]:
        """
        Retrieves image paths for a product ID (or productCode).
        Prioritizes CRM images (from 192.168.1.12), with fallback to v1 image directories.
        """
        # 1. Check CRM first if data_source is crm
        if self._data_source == "crm":
            crm_imgs = self._get_crm_product_images(product_id, is_watermark=is_watermark)
            if crm_imgs:
                return crm_imgs

        # 2. Try v1 image directories
        v1_imgs = self._get_v1_product_images(product_id, is_watermark=is_watermark)
        if v1_imgs:
            return v1_imgs

        # 3. Last fallback: try CRM if not tried yet
        if self._data_source != "crm":
            return self._get_crm_product_images(product_id, is_watermark=is_watermark)

        return []

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
            elif p_val >= 1_000_000_000:
                val_in_billions = p_val / 1_000_000_000
                price_val_str = f"{val_in_billions:g}"
                unit_str = "tỷ"
                price_label = "Giá bán" if not is_rental else "Giá thuê"
            elif p_val >= 1_000_000:
                val_in_millions = p_val / 1_000_000
                price_val_str = f"{val_in_millions:g}"
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

