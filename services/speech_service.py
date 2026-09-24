"""
speech_service.py — Text-to-speech using Google Cloud TTS or browser Web Speech API fallback.
"""

import os
import logging
import base64

logger = logging.getLogger(__name__)


def is_tts_configured() -> bool:
    """Check if Google Cloud TTS is configured."""
    credentials = os.environ.get("GOOGLE_TTS_CREDENTIALS", "").strip()
    return bool(credentials and os.path.exists(credentials))


def text_to_speech(text: str, language_code: str = "en-US") -> dict:
    """
    Convert text to speech audio.
    Returns {'audio_base64': str, 'success': bool, 'use_browser_tts': bool}
    """
    if not is_tts_configured():
        # Signal to the frontend to use browser Web Speech API
        return {
            "audio_base64": None,
            "success": False,
            "use_browser_tts": True,
            "text": text,
            "language": language_code,
        }

    try:
        from google.cloud import texttospeech
        import json

        credentials_path = os.environ.get("GOOGLE_TTS_CREDENTIALS")
        os.environ["GOOGLE_APPLICATION_CREDENTIALS"] = credentials_path

        client = texttospeech.TextToSpeechClient()

        synthesis_input = texttospeech.SynthesisInput(text=text[:5000])

        lang_map = {
            "en": "en-US",
            "hi": "hi-IN",
            "kn": "kn-IN",
            "mr": "mr-IN",
            "ta": "ta-IN",
            "te": "te-IN",
        }
        lang_code = lang_map.get(language_code, language_code)

        voice = texttospeech.VoiceSelectionParams(
            language_code=lang_code,
            ssml_gender=texttospeech.SsmlVoiceGender.NEUTRAL,
        )

        audio_config = texttospeech.AudioConfig(
            audio_encoding=texttospeech.AudioEncoding.MP3
        )

        response = client.synthesize_speech(
            input=synthesis_input,
            voice=voice,
            audio_config=audio_config,
        )

        audio_base64 = base64.b64encode(response.audio_content).decode("utf-8")
        return {
            "audio_base64": audio_base64,
            "success": True,
            "use_browser_tts": False,
            "text": text,
            "language": lang_code,
        }
    except Exception as e:
        logger.error(f"TTS error: {e}")
        return {
            "audio_base64": None,
            "success": False,
            "use_browser_tts": True,
            "text": text,
            "language": language_code,
        }
