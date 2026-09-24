"""
translation_service.py — Multilingual translation using Google Cloud Translation.
Falls back gracefully if API is not configured.
"""

import os
import logging
import requests

logger = logging.getLogger(__name__)

SUPPORTED_LANGUAGES = {
    "en": "English",
    "hi": "Hindi",
    "kn": "Kannada",
    "mr": "Marathi",
    "ta": "Tamil",
    "te": "Telugu",
}


def is_translation_configured() -> bool:
    """Check if translation API is configured."""
    return bool(os.environ.get("GOOGLE_TRANSLATE_API_KEY", "").strip())


def translate_text(text: str, target_language: str, source_language: str = "en") -> dict:
    """
    Translate text to the target language.
    Returns {'translated': str, 'success': bool, 'error': str|None}
    """
    if target_language == "en" or target_language == source_language:
        return {"translated": text, "success": True, "error": None}

    if not is_translation_configured():
        return {
            "translated": text,
            "success": False,
            "error": "Translation service is not configured. Showing English version.",
        }

    api_key = os.environ.get("GOOGLE_TRANSLATE_API_KEY")
    url = "https://translation.googleapis.com/language/translate/v2"

    try:
        response = requests.post(
            url,
            params={"key": api_key},
            json={
                "q": text,
                "source": source_language,
                "target": target_language,
                "format": "text",
            },
            timeout=15,
        )
        response.raise_for_status()
        data = response.json()
        translated = data["data"]["translations"][0]["translatedText"]
        return {"translated": translated, "success": True, "error": None}
    except Exception as e:
        logger.error(f"Translation error: {e}")
        return {
            "translated": text,
            "success": False,
            "error": "Translation is currently unavailable. Showing the English version.",
        }


def translate_analysis(analysis: dict, target_language: str) -> dict:
    """
    Translate the key user-facing fields of an analysis dict.
    Non-translatable fields (dates, amounts, ids) are left as-is.
    """
    if target_language == "en" or not is_translation_configured():
        return analysis

    translated = dict(analysis)

    # Translate summary
    if analysis.get("summary"):
        result = translate_text(analysis["summary"], target_language)
        translated["summary"] = result["translated"]

    # Translate key takeaways
    if analysis.get("key_takeaways"):
        translated_takeaways = []
        for item in analysis["key_takeaways"]:
            r = translate_text(item, target_language)
            translated_takeaways.append(r["translated"])
        translated["key_takeaways"] = translated_takeaways

    return translated
