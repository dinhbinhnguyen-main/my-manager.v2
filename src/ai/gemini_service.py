"""Gemini AI Service for content generation and multimodal image parsing."""

import os
import re
import base64
import logging
import requests
from pathlib import Path
from typing import Optional

from src.db.repository import SettingRepository
from src.ai.prompt_helper import AIPromptHelper

logger = logging.getLogger(__name__)


class GeminiService:
    def __init__(self):
        pass

    def get_api_key(self) -> Optional[str]:
        """Retrieves Gemini API Key from settings DB or system environment."""
        # 1. Try DB settings
        key = SettingRepository.get("gemini_api_key")
        if key and key.strip():
            return key.strip()

        # 2. Try environment variables
        env_key = os.getenv("GEMINI_API_KEY")
        if env_key and env_key.strip():
            return env_key.strip()

        # 3. Try parsing .env file in root
        root_env = Path(__file__).resolve().parent.parent.parent / ".env"
        if root_env.exists():
            with open(root_env, "r", encoding="utf-8") as f:
                for line in f:
                    if line.strip().startswith("GEMINI_API_KEY="):
                        val = line.strip().split("=", 1)[1].strip()
                        return val.strip("'\"")
        return None

    def _clean_response(self, text: str) -> str:
        """Cleans up markdown fences, quotes, and introductory filler text."""
        if not text:
            return ""

        # Remove markdown code blocks (e.g. ```text ... ```)
        text = re.sub(r"^```[a-zA-Z]*\n", "", text)
        text = re.sub(r"\n```$", "", text)
        text = text.strip()

        # Remove wrapping quotes
        if (text.startswith('"') and text.endswith('"')) or (text.startswith("'") and text.endswith("'")):
            text = text[1:-1].strip()

        # Remove introductory prefixes
        prefixes = [
            r"^dưới đây là[^:\n]*[:\n]*",
            r"^đây là[^:\n]*[:\n]*",
            r"^bài viết thảo luận[^:\n]*[:\n]*",
            r"^bài viết viết lại[^:\n]*[:\n]*",
            r"^đoạn viết lại[^:\n]*[:\n]*",
            r"^gửi bạn[^:\n]*[:\n]*"
        ]
        for p in prefixes:
            text = re.sub(p, "", text, flags=re.IGNORECASE).strip()

        return text

    def rewrite_real_estate_post(self, title: str, description: str, is_rental: bool = False) -> str:
        """Calls Gemini API to rewrite raw real estate post into SEO-optimized, policy-compliant post."""
        api_key = self.get_api_key()
        if not api_key:
            logger.warning("GEMINI_API_KEY is not set. Returning raw template title and description.")
            return f"{title}\n\n{description}"

        prompt = AIPromptHelper.build_real_estate_rewrite_prompt(title, description, is_rental=is_rental)
        url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-3.5-flash-lite:generateContent?key={api_key}"

        payload = {
            "contents": [{"parts": [{"text": prompt}]}],
            "generationConfig": {
                "temperature": 0.85,
                "topP": 0.95,
                "topK": 40
            }
        }

        logger.info("Sending prompt to Gemini 3.5 Flash for post rewrite...")
        try:
            resp = requests.post(url, json=payload, timeout=25.0)
            if resp.status_code != 200:
                logger.error(f"Gemini API returned status {resp.status_code}: {resp.text}")
                return f"{title}\n\n{description}"

            data = resp.json()
            candidates = data.get("candidates", [])
            if candidates:
                parts = candidates[0].get("content", {}).get("parts", [])
                if parts:
                    gen_text = parts[0].get("text", "").strip()
                    cleaned = self._clean_response(gen_text)
                    logger.info("Gemini post rewrite succeeded!")
                    return cleaned
        except Exception as e:
            logger.error(f"Gemini API call failed: {e}")

        return f"{title}\n\n{description}"

    def generate_discussion_from_image(self, image_path: str, custom_prompt: Optional[str] = None) -> str:
        """Calls Gemini Multimodal API to generate a post based on image content."""
        api_key = self.get_api_key()
        if not api_key:
            logger.warning("GEMINI_API_KEY is not set.")
            return "Thảo luận bài viết bất động sản."

        if not os.path.exists(image_path):
            logger.error(f"Image not found at path: {image_path}")
            return "Thảo luận bài viết bất động sản."

        with open(image_path, "rb") as f:
            img_b64 = base64.b64encode(f.read()).decode("utf-8")

        mime_type = "image/png" if image_path.lower().endswith(".png") else "image/jpeg"
        prompt = custom_prompt or (
            "Viết bài thảo luận Facebook ngắn gọn, tự nhiên bằng tiếng Việt theo hình ảnh BĐS này. "
            "Văn phong gần gũi, thoáng mắt, không hashtag quá 3 từ, không quảng cáo sáo rỗng."
        )

        url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-3.5-flash-lite:generateContent?key={api_key}"
        payload = {
            "contents": [{
                "parts": [
                    {"text": prompt},
                    {"inlineData": {"mimeType": mime_type, "data": img_b64}}
                ]
            }],
            "generationConfig": {"temperature": 1.0}
        }

        try:
            resp = requests.post(url, json=payload, timeout=30.0)
            if resp.status_code == 200:
                data = resp.json()
                candidates = data.get("candidates", [])
                if candidates:
                    parts = candidates[0].get("content", {}).get("parts", [])
                    if parts:
                        return self._clean_response(parts[0].get("text", ""))
        except Exception as e:
            logger.error(f"Gemini multimodal API call failed: {e}")

        return "Thảo luận bài viết bất động sản."
