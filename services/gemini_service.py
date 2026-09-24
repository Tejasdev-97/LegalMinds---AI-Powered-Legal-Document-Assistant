"""
gemini_service.py — All Gemini AI interactions, centralized here.

Uses google-genai SDK. Prompts return structured JSON where possible.
Implements:
- Correct MODEL_REGISTRY (Gemini 3.x stable only)
- Strict sequential fallback (no random rotation)
- 3-mode routing: auto, gemini, offline
- Offline Mode = ZERO Gemini calls, enforced here
- Zero-fabrication local document retrieval
- Proper session question cache
- Document analysis cache check
- ReportLab-safe text escaping helpers
- Sanitized error messages (no raw API internals returned)
"""

import os
import re
import json
import time
import difflib
import hashlib
import logging
import threading
from collections import Counter
from dotenv import load_dotenv

try:
    from google import genai
    from google.genai import types
    _GENAI_AVAILABLE = True
except ImportError:
    genai = None
    types = None
    _GENAI_AVAILABLE = False

load_dotenv()
logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Model Registry — Gemini 3.x Flash-Lite first, ordered by preference
# ---------------------------------------------------------------------------

MODEL_REGISTRY = [
    "gemini-3.5-flash-lite",   # primary (lightweight, fast)
    "gemini-3.1-flash-lite",   # fallback 1
    "gemini-3.8-flash",        # fallback 2
    "gemini-3.7-flash",        # fallback 3
    "gemini-3.6-flash",        # fallback 4
]

PRIMARY_MODEL = os.environ.get("GEMINI_MODEL", MODEL_REGISTRY[0]).strip()

# Ensure primary is first in registry
_ordered_registry = [PRIMARY_MODEL] + [m for m in MODEL_REGISTRY if m != PRIMARY_MODEL]
SUPPORTED_MODELS = list(dict.fromkeys(_ordered_registry))

# Supported Languages for AI Generation & Local UI
SUPPORTED_LANGUAGES = {
    "en": "English",
    "hi": "Hindi",
    "kn": "Kannada",
    "mr": "Marathi",
    "ta": "Tamil",
    "te": "Telugu"
}


def _get_language_instruction(language: str) -> str:
    lang_code = (language or "en").lower().strip()
    if lang_code in SUPPORTED_LANGUAGES and lang_code != "en":
        lang_name = SUPPORTED_LANGUAGES[lang_code]
        return f"\n\nCRITICAL LANGUAGE REQUIREMENT: The user's selected interface language is {lang_name} ({lang_code}). You MUST generate ALL your natural language response text (including summary, explanations, answers, key_takeaways, points, notes, titles, questions) in {lang_name}. If JSON format is requested, keep JSON keys in English, but write ALL string values strictly in {lang_name}."
    return ""


# ---------------------------------------------------------------------------
# Model Availability State (thread-safe)
# ---------------------------------------------------------------------------

_availability_lock = threading.Lock()

# Error type → cooldown seconds
_COOLDOWN = {
    "rate_limit": 90,          # short-term rate limit
    "quota_daily": 3600 * 8,   # daily quota: mark unavailable for 8 hours
    "temp_error": 45,          # temporary server error
    "model_unavailable": 86400,# model deprecated/removed: 24 hours
}

_gemini_state = {
    "status": "unknown",
    "badge_color": "green",
    "message": "Gemini AI Status Ready",
    "current_model": PRIMARY_MODEL,
    "last_successful_request": None,
    "last_quota_error": None,
    "model_cooldowns": {},    # { model_name: timestamp_until_retry }
    "key_invalid": False,
}


def get_current_model() -> str:
    """
    Return the current preferred model.
    Always tries PRIMARY_MODEL first. Uses a fallback only when primary
    is in cooldown. Returns to primary automatically when cooldown expires.
    Never rotates randomly.
    """
    now = time.time()
    with _availability_lock:
        # Primary available?
        primary = SUPPORTED_MODELS[0]
        if now > _gemini_state["model_cooldowns"].get(primary, 0):
            _gemini_state["current_model"] = primary
            return primary
        # Try fallbacks in order
        for model in SUPPORTED_MODELS[1:]:
            if now > _gemini_state["model_cooldowns"].get(model, 0):
                _gemini_state["current_model"] = model
                return model
        # All in cooldown: return primary anyway (will fail fast, not loop)
        _gemini_state["current_model"] = primary
        return primary


def mark_model_success(model_name: str):
    """Record a successful API call; restore active state."""
    now = time.time()
    with _availability_lock:
        _gemini_state["status"] = "active"
        _gemini_state["badge_color"] = "green"
        _gemini_state["message"] = "Gemini AI Active"
        _gemini_state["last_successful_request"] = now
        _gemini_state["model_cooldowns"][model_name] = 0
        _gemini_state["key_invalid"] = False


def _classify_error(err_str: str) -> str:
    """Classify an error string into a category."""
    err_upper = err_str.upper()
    if "API_KEY_INVALID" in err_upper or ("400" in err_str and "key" in err_str.lower()):
        return "invalid_key"
    if "RESOURCE_EXHAUSTED" in err_upper or "429" in err_str or "quota" in err_str.lower():
        # Distinguish daily vs. per-minute rate limit
        if "daily" in err_str.lower() or "per day" in err_str.lower():
            return "quota_daily"
        return "rate_limit"
    if "503" in err_str or "UNAVAILABLE" in err_upper or "deprecated" in err_str.lower():
        return "model_unavailable"
    return "temp_error"


def mark_model_error(model_name: str, error: Exception):
    """Classify and record an error for a model; set appropriate cooldown."""
    err_str = str(error)
    error_type = _classify_error(err_str)
    now = time.time()

    with _availability_lock:
        if error_type == "invalid_key":
            _gemini_state["status"] = "invalid_key"
            _gemini_state["badge_color"] = "red"
            _gemini_state["message"] = "Invalid Gemini Key"
            _gemini_state["key_invalid"] = True
            # Don't set a cooldown — key is just wrong, not temporary
        elif error_type == "quota_daily":
            cooldown = now + _COOLDOWN["quota_daily"]
            _gemini_state["model_cooldowns"][model_name] = cooldown
            _gemini_state["status"] = "limit_reached"
            _gemini_state["badge_color"] = "orange"
            _gemini_state["message"] = "Gemini Daily Quota Reached"
            _gemini_state["last_quota_error"] = now
        elif error_type == "rate_limit":
            cooldown = now + _COOLDOWN["rate_limit"]
            _gemini_state["model_cooldowns"][model_name] = cooldown
            _gemini_state["status"] = "limit_reached"
            _gemini_state["badge_color"] = "orange"
            _gemini_state["message"] = "Gemini Limit Reached"
        elif error_type == "model_unavailable":
            cooldown = now + _COOLDOWN["model_unavailable"]
            _gemini_state["model_cooldowns"][model_name] = cooldown
            _gemini_state["status"] = "temp_unavailable"
            _gemini_state["badge_color"] = "orange"
            _gemini_state["message"] = "Gemini Model Unavailable"
        else:
            cooldown = now + _COOLDOWN["temp_error"]
            _gemini_state["model_cooldowns"][model_name] = cooldown
            _gemini_state["status"] = "temp_unavailable"
            _gemini_state["badge_color"] = "orange"
            _gemini_state["message"] = "Gemini Temporarily Unavailable"


def _sanitize_error_message(err_str: str) -> str:
    """
    Convert raw API error strings into safe user-friendly messages.
    Never expose quota internals, API key details, or stack traces.
    """
    error_type = _classify_error(err_str)
    if error_type == "invalid_key":
        return "The Gemini API key is invalid. Please check your key in Settings."
    if error_type in ("quota_daily", "rate_limit"):
        return "The AI service is temporarily unavailable due to usage limits. You can continue using Offline Mode."
    if error_type == "model_unavailable":
        return "The selected Gemini model is currently unavailable. Trying alternatives."
    return "The AI service is temporarily unavailable. You can continue using Offline Mode."


def get_gemini_status_summary(api_key: str = None) -> dict:
    """
    Return Gemini status WITHOUT making any API call.
    Safe for page load — consumes ZERO quota.
    """
    key = (api_key or "").strip() or os.environ.get("GEMINI_API_KEY", "").strip()
    if not key:
        return {
            "status": "unconfigured",
            "badge_color": "red",
            "message": "Gemini Not Configured",
            "current_model": get_current_model(),
            "has_key": False,
        }

    with _availability_lock:
        if _gemini_state["key_invalid"]:
            return {
                "status": "invalid_key",
                "badge_color": "red",
                "message": "Invalid Gemini Key",
                "current_model": get_current_model(),
                "has_key": True,
            }
        st = _gemini_state["status"]

    if st in ("unknown", "active"):
        return {"status": "active", "badge_color": "green", "message": "Gemini AI Active",
                "current_model": get_current_model(), "has_key": True}
    if st == "invalid_key":
        return {"status": "invalid_key", "badge_color": "red", "message": "Invalid Gemini Key",
                "current_model": get_current_model(), "has_key": True}
    if st == "limit_reached":
        return {"status": "limit_reached", "badge_color": "orange", "message": "Gemini Limit Reached",
                "current_model": get_current_model(), "has_key": True}
    return {"status": "temp_unavailable", "badge_color": "orange", "message": "Gemini Temporarily Unavailable",
            "current_model": get_current_model(), "has_key": True}


def _get_client(api_key: str = None):
    """Build and return a genai client."""
    if not _GENAI_AVAILABLE:
        raise RuntimeError("google-genai package is not installed.")
    key = (api_key or "").strip() or os.environ.get("GEMINI_API_KEY", "").strip()
    if not key:
        raise RuntimeError("GEMINI_API_KEY is not configured.")
    return genai.Client(api_key=key)


def test_gemini_api_key(api_key: str = None) -> dict:
    """
    Explicit key test — makes ONE real API call.
    Only called when user explicitly requests 'Test Gemini'.
    """
    key = (api_key or "").strip() or os.environ.get("GEMINI_API_KEY", "").strip()
    if not key:
        return {"valid": False, "status": "unconfigured", "badge_color": "red",
                "message": "Gemini Not Configured"}
    try:
        client = _get_client(key)
        model = get_current_model()
        if types:
            cfg = types.GenerateContentConfig(max_output_tokens=10)
        else:
            cfg = None
        kwargs = {"model": model, "contents": "Reply with: OK"}
        if cfg:
            kwargs["config"] = cfg
        response = client.models.generate_content(**kwargs)
        if response and response.text:
            mark_model_success(model)
            return {"valid": True, "status": "active", "badge_color": "green",
                    "message": "Gemini AI Active", "current_model": model}
        return {"valid": False, "status": "temp_unavailable", "badge_color": "orange",
                "message": "Gemini Temporarily Unavailable"}
    except Exception as e:
        model = get_current_model()
        mark_model_error(model, e)
        return {"valid": False, "status": _classify_error(str(e)).replace("_", " "),
                "badge_color": "red" if "invalid" in str(e).lower() else "orange",
                "message": _sanitize_error_message(str(e))}


# ---------------------------------------------------------------------------
# Core Gemini Caller — Correct Sequential Fallback
# ---------------------------------------------------------------------------

def _build_config(max_tokens: int):
    """Build a generation config compatible with available Gemini 2.x/1.5 models."""
    if not types:
        return None
    return types.GenerateContentConfig(
        max_output_tokens=max_tokens,
        temperature=0.2,
        # Do NOT include candidate_count, top_k, thinking_config
        # as these may not be supported in all flash-lite variants
    )


def _call_gemini(prompt: str, max_tokens: int = 8192, api_key: str = None, mode: str = "auto") -> str:
    """
    Call Gemini with strict mode enforcement and sequential fallback.

    Rules:
    - mode == 'offline': ZERO calls, raises immediately
    - Invalid key: stop after first attempt, do not try all models
    - Rate-limited model: skip to next model in registry order
    - Successful fallback: return immediately (don't try more)
    - Primary automatically preferred again once cooldown expires
    """
    if mode == "offline":
        raise RuntimeError("Offline Mode is active — Gemini API calls are disabled.")

    with _availability_lock:
        if _gemini_state["key_invalid"]:
            raise RuntimeError("Invalid Gemini API key — cannot make requests.")

    key = (api_key or "").strip() or os.environ.get("GEMINI_API_KEY", "").strip()
    if not key:
        raise RuntimeError("GEMINI_API_KEY is not configured.")

    client = _get_client(key)
    cfg = _build_config(max_tokens)

    now = time.time()
    last_err = None

    for model in SUPPORTED_MODELS:
        # Skip if model is in cooldown
        cooldown_until = _gemini_state["model_cooldowns"].get(model, 0)
        if now < cooldown_until:
            logger.debug(f"Model '{model}' in cooldown, skipping.")
            continue

        try:
            kwargs = {"model": model, "contents": prompt}
            if cfg:
                kwargs["config"] = cfg
            response = client.models.generate_content(**kwargs)
            text = (response.text or "").strip()
            if text:
                mark_model_success(model)
                # If we used a fallback, log it
                if model != SUPPORTED_MODELS[0]:
                    logger.info(f"Gemini: used fallback model '{model}' (primary in cooldown).")
                return text
            # Empty response — treat as temp error
            last_err = RuntimeError(f"Empty response from {model}")
            mark_model_error(model, last_err)
            continue
        except Exception as e:
            last_err = e
            err_type = _classify_error(str(e))
            mark_model_error(model, e)
            logger.warning(f"Gemini model '{model}' failed ({err_type}): {_sanitize_error_message(str(e))}")
            # For invalid key, stop immediately — no point trying other models
            if err_type == "invalid_key":
                raise RuntimeError("Invalid Gemini API key.") from e
            # For daily quota, try next model
            continue

    if last_err:
        raise RuntimeError(_sanitize_error_message(str(last_err))) from last_err
    raise RuntimeError("All Gemini models are currently unavailable. Please use Offline Mode.")


# ---------------------------------------------------------------------------
# JSON Parser
# ---------------------------------------------------------------------------

def _parse_json(text: str):
    """Extract and parse JSON from a model response."""
    text = re.sub(r"```(?:json)?\s*", "", text)
    text = re.sub(r"```", "", text).strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        match = re.search(r"(\{.*\}|\[.*\])", text, re.DOTALL)
        if match:
            try:
                return json.loads(match.group(0))
            except json.JSONDecodeError:
                pass
    return None


# ---------------------------------------------------------------------------
# ReportLab Safety — Escape user content before passing to Paragraph()
# ---------------------------------------------------------------------------

def escape_for_reportlab(text: str) -> str:
    """
    Escape characters that would be interpreted as ReportLab markup.
    Prevents malformed legal documents from breaking PDF generation.
    """
    if not text:
        return ""
    text = str(text)
    text = text.replace("&", "&amp;")
    text = text.replace("<", "&lt;")
    text = text.replace(">", "&gt;")
    return text


# ---------------------------------------------------------------------------
# Question Cache (session-scoped)
# ---------------------------------------------------------------------------

_question_cache: dict = {}
_cache_lock = threading.Lock()


def _make_cache_key(session_id: str, doc_id: str, doc_text: str, question: str, mode: str, language: str = "en") -> str:
    norm_q = re.sub(r"\s+", " ", question.strip().lower())
    text_hash = hashlib.md5(doc_text.encode("utf-8", errors="ignore")).hexdigest()[:10]
    return f"{session_id or 'anon'}:{doc_id}:{text_hash}:{norm_q}:{mode}:{language}"


def get_cached_question_answer(session_id: str, doc_id: str, doc_text: str, question: str, mode: str, language: str = "en"):
    key = _make_cache_key(session_id, doc_id, doc_text, question, mode, language)
    with _cache_lock:
        if key in _question_cache:
            res = dict(_question_cache[key])
            res["cached"] = True
            return res
    return None


def set_cached_question_answer(session_id: str, doc_id: str, doc_text: str, question: str, mode: str, answer_dict: dict, language: str = "en"):
    key = _make_cache_key(session_id, doc_id, doc_text, question, mode, language)
    with _cache_lock:
        _question_cache[key] = dict(answer_dict)


# ---------------------------------------------------------------------------
# Document Classification
# ---------------------------------------------------------------------------

def classify_document(text_sample: str, api_key: str = None, mode: str = "auto") -> str:
    """Classify document type. Offline Mode uses rule-based only."""
    if mode == "offline":
        return _rule_based_classification(text_sample)

    prompt = """You are a legal document classifier.

Read the excerpt below and identify the document type.
Choose ONE from:
Employment Agreement, Rental Agreement, Loan Agreement, Insurance Policy,
Privacy Policy, Service Agreement, Offer Letter, Legal Notice,
NDA (Non-Disclosure Agreement), Terms & Conditions, Partnership Agreement,
Purchase Agreement, Lease Agreement, Consulting Agreement, Other

Return ONLY valid JSON:
{"document_type": "Employment Agreement", "confidence": "high"}

If uncertain, use "Other" with confidence "low".

Document excerpt:
---
""" + text_sample[:2500] + "\n---"

    try:
        result = _call_gemini(prompt, max_tokens=150, api_key=api_key, mode=mode)
        parsed = _parse_json(result)
        if parsed and isinstance(parsed, dict) and parsed.get("document_type"):
            return parsed["document_type"]
    except Exception as e:
        logger.info(f"classify_document: using rule-based fallback ({_sanitize_error_message(str(e))})")

    return _rule_based_classification(text_sample)


def _rule_based_classification(text_sample: str) -> str:
    """Deterministic classification from keywords. Returns 'Unknown' when ambiguous."""
    lower = text_sample.lower()
    scores = {
        "Employment Agreement": sum(1 for w in ["employment", "employee", "employer", "salary", "probation"] if w in lower),
        "Rental Agreement": sum(1 for w in ["rental", "lease", "tenant", "landlord", "rent"] if w in lower),
        "Loan Agreement": sum(1 for w in ["loan", "borrower", "lender", "repay", "principal", "interest"] if w in lower),
        "NDA (Non-Disclosure Agreement)": sum(1 for w in ["non-disclosure", "nondisclosure", "confidential", "proprietary"] if w in lower),
        "Service Agreement": sum(1 for w in ["service agreement", "contractor", "deliverable", "scope of work"] if w in lower),
        "Partnership Agreement": sum(1 for w in ["partnership", "partner", "profit sharing", "joint venture"] if w in lower),
        "Purchase Agreement": sum(1 for w in ["purchase", "buyer", "seller", "sale of", "consideration"] if w in lower),
    }
    best = max(scores, key=scores.get)
    return best if scores[best] >= 2 else "Unknown / General Legal Document"


# ---------------------------------------------------------------------------
# Offline Analysis Engine — Zero Fabrication
# ---------------------------------------------------------------------------

def _extract_parties(document_text: str) -> list:
    """Extract party names from text. Returns [] if none found — NO fallback fabrication."""
    patterns = [
        r"(?:between|by and between)\s+([A-Z][A-Za-z0-9\s\.,&]{3,50}?)\s+(?:and|,|\(\")",
        r"(?:Employer|Landlord|Lender|Client|Company|Licensor):\s*([A-Z][A-Za-z0-9\s\.,&]{3,50}?)(?:\n|,|\()",
        r"(?:Employee|Tenant|Borrower|Vendor|Licensee):\s*([A-Z][A-Za-z0-9\s\.,&]{3,50}?)(?:\n|,|\()",
    ]
    parties = []
    for pat in patterns:
        matches = re.findall(pat, document_text)
        for m in matches:
            clean = m.strip().rstrip(",.")
            # Reject obviously wrong matches
            if (clean and len(clean) > 3 and len(clean) < 80
                    and clean.upper() not in ("THIS", "THE", "THAT", "HEREIN", "HEREINAFTER", "AGREEMENT")
                    and clean not in parties):
                parties.append(clean)
        if len(parties) >= 4:
            break
    return parties[:4]


def _extract_dates(document_text: str) -> list:
    """Extract dates from document text. Returns [] if none found."""
    date_patterns = [
        r"\b(?:January|February|March|April|May|June|July|August|September|October|November|December)\s+\d{1,2},?\s+\d{4}\b",
        r"\b\d{1,2}\s+(?:January|February|March|April|May|June|July|August|September|October|November|December),?\s+\d{4}\b",
        r"\b\d{4}-\d{2}-\d{2}\b",
        r"\b\d{1,2}/\d{1,2}/\d{2,4}\b",
        r"\b\d{1,2}-\d{1,2}-\d{4}\b",
    ]
    dates = []
    for pat in date_patterns:
        for match in re.finditer(pat, document_text, re.IGNORECASE):
            date_str = match.group(0).strip()
            if date_str not in [d["date"] for d in dates]:
                # Find a small context around the date
                start = max(0, match.start() - 50)
                end = min(len(document_text), match.end() + 80)
                context = document_text[start:end].strip().replace("\n", " ")
                dates.append({"label": "Date Found", "date": date_str, "context": context[:120]})
    return dates[:6]


def _extract_financials(document_text: str) -> list:
    """Extract monetary amounts. Returns [] if none found."""
    patterns = [
        r"(?:₹|Rs\.?|INR)\s*[\d,]+(?:\.\d{1,2})?(?:\s*(?:per month|monthly|per annum|annually|lakh|lakhs|crore|crores|thousand))?\b",
        r"\$\s*[\d,]+(?:\.\d{1,2})?(?:\s*(?:per month|monthly|per annum|annually|thousand|million))?\b",
        r"(?:USD|EUR|GBP)\s*[\d,]+(?:\.\d{1,2})?\b",
    ]
    financials = []
    for pat in patterns:
        for match in re.finditer(pat, document_text, re.IGNORECASE):
            amount = match.group(0).strip()
            if amount not in [f["amount"] for f in financials]:
                start = max(0, match.start() - 60)
                end = min(len(document_text), match.end() + 80)
                context = document_text[start:end].strip().replace("\n", " ")
                financials.append({"label": "Financial Term", "amount": amount, "context": context[:120]})
    return financials[:6]


def _extract_clauses(document_text: str) -> list:
    """Extract clauses. Only returns clauses with actual text evidence."""
    lines = document_text.split("\n")
    clause_keywords = [
        ("Termination Clause", "Termination", ["terminat", "notice period", "cancel"]),
        ("Confidentiality Clause", "Confidentiality", ["confidential", "secret", "proprietary", "disclose"]),
        ("Payment & Compensation", "Payment", ["salary", "rent", "payment", "fee", "compensation", "remuneration"]),
        ("Non-Compete / Non-Solicit", "Restrictive Covenant", ["non-compete", "compete", "solicit"]),
        ("Intellectual Property", "IP Rights", ["intellectual property", "inventions", "copyright", "patent", "trademark"]),
        ("Governing Law", "Jurisdiction", ["governing law", "jurisdiction", "arbitration", "courts of"]),
        ("Indemnification", "Liability", ["indemnif", "hold harmless", "liability"]),
        ("Force Majeure", "Force Majeure", ["force majeure", "act of god", "beyond control"]),
    ]
    clauses = []
    for name, category, keywords in clause_keywords:
        for i, line in enumerate(lines):
            line_lower = line.lower()
            if any(kw in line_lower for kw in keywords) and len(line.strip()) > 20:
                excerpt_lines = lines[max(0, i - 1):min(len(lines), i + 4)]
                excerpt = " ".join([l.strip() for l in excerpt_lines if l.strip()])
                # Determine location — only use page numbers for PDF (detected by [Page N] markers)
                section_ref = f"Section {len(clauses) + 1}"
                clauses.append({
                    "name": name,
                    "category": category,
                    "section": section_ref,
                    "page": None,   # page = None unless PDF page markers exist
                    "explanation": excerpt[:300] + ("..." if len(excerpt) > 300 else ""),
                    "original_text": line.strip()[:250],
                })
                break

    # For PDF documents, extract real page numbers from [Page N] markers
    page_marker_re = re.compile(r"\[Page (\d+)\]")
    page_positions = {}
    for match in page_marker_re.finditer(document_text):
        page_num = int(match.group(1))
        page_positions[match.start()] = page_num

    if page_positions:
        for clause in clauses:
            if clause["original_text"]:
                # Find where in doc this text appears
                pos = document_text.find(clause["original_text"][:50])
                if pos >= 0:
                    # Find the page marker before this position
                    prev_page = None
                    for marker_pos, pnum in sorted(page_positions.items()):
                        if marker_pos <= pos:
                            prev_page = pnum
                    if prev_page is not None:
                        clause["page"] = prev_page

    return clauses[:8]


def _extract_points_to_review(document_text: str) -> list:
    """Extract points deserving attention. Evidence-based only."""
    lines = document_text.split("\n")
    review_triggers = [
        ("Penalty / Liquidated Damages", ["penalty", "forfeit", "liquidated damages", "breach"], "high"),
        ("Strict Notice Period", ["notice period", "prior notice", "days written notice", "days notice"], "medium"),
        ("Non-Compete Restriction", ["non-compete", "shall not engage", "shall not work", "not compete"], "high"),
        ("Unilateral Modification Right", ["reserves the right", "sole discretion", "at its option", "unilateral"], "medium"),
        ("Arbitration / Dispute Forum", ["arbitration", "exclusive jurisdiction", "exclusive court"], "medium"),
        ("Automatic Renewal", ["auto-renew", "automatic renewal", "unless terminated prior"], "medium"),
        ("Intellectual Property Assignment", ["assigns all", "work for hire", "all rights", "irrevocably assign"], "high"),
    ]
    points = []
    for title, keywords, severity in review_triggers:
        for line in lines:
            line_lower = line.lower()
            if any(kw in line_lower for kw in keywords) and len(line.strip()) > 20:
                points.append({
                    "title": title,
                    "description": line.strip()[:220],
                    "section": "Found in document",
                    "severity": severity,
                })
                break
    return points[:6]


def _offline_fallback_analysis(document_text: str, document_type: str = "") -> dict:
    """
    Evidence-based offline document analysis.
    NEVER fabricates parties, dates, amounts, or summaries.
    Returns 'Not found in document.' for any field with no evidence.
    """
    if not document_type or document_type in ("Unknown", "Other", ""):
        document_type = _rule_based_classification(document_text[:3000])

    parties = _extract_parties(document_text)
    dates = _extract_dates(document_text)
    financials = _extract_financials(document_text)
    clauses = _extract_clauses(document_text)
    points_to_review = _extract_points_to_review(document_text)

    # Build factual summary only from what was found
    summary_parts = [f"This appears to be a {document_type}."]
    if parties:
        summary_parts.append(f"Identified parties: {', '.join(parties)}.")
    if clauses:
        summary_parts.append(f"Found {len(clauses)} clause(s) of potential importance.")
    if dates:
        summary_parts.append(f"Found {len(dates)} date(s) referenced in the document.")
    if financials:
        summary_parts.append(f"Found {len(financials)} financial term(s).")
    summary_parts.append("This is a document-extracted summary. For legal interpretation, consult a qualified legal professional.")

    summary = " ".join(summary_parts)

    # Obligations — only from explicit "shall" / "agrees to" / "must" lines
    lines = document_text.split("\n")
    party_a_obls, party_b_obls = [], []
    party_a_name = parties[0] if parties else None
    party_b_name = parties[1] if len(parties) > 1 else None
    role_a_words = ["company", "employer", "landlord", "lender", "licensor", "service provider"]
    role_b_words = ["employee", "tenant", "borrower", "client", "licensee", "contractor"]

    for line in lines:
        stripped = line.strip()
        if len(stripped) > 25:
            l_lower = stripped.lower()
            if any(w in l_lower for w in ["shall", "agrees to", "must", "is required to"]):
                if any(w in l_lower for w in role_a_words):
                    party_a_obls.append(stripped[:180])
                elif any(w in l_lower for w in role_b_words):
                    party_b_obls.append(stripped[:180])

    return {
        "document_type": document_type,
        "parties": parties if parties else [],
        "summary": summary,
        "key_takeaways": [
            f"Document type identified as: {document_type}.",
            f"Parties found: {', '.join(parties) if parties else 'Not found in document.'}",
            f"Key clauses identified: {len(clauses)}. Review highlighted items carefully.",
        ],
        "important_clauses": clauses,
        "points_to_review": points_to_review,
        "obligations": {
            "party_a": {
                "name": party_a_name or "First Party",
                "obligations": party_a_obls[:5] if party_a_obls else []
            },
            "party_b": {
                "name": party_b_name or "Second Party",
                "obligations": party_b_obls[:5] if party_b_obls else []
            },
        },
        "important_dates": dates if dates else [],
        "financial_terms": financials if financials else [],
        "mode": "offline",
        "processing_badge": "⚫ Offline Document Mode",
    }


# ---------------------------------------------------------------------------
# Document Analysis
# ---------------------------------------------------------------------------

def analyze_document(document_text: str, document_type: str = "", api_key: str = None, mode: str = "auto", language: str = "en") -> dict:
    """
    Full document analysis with strict 3-mode routing.
    mode='offline' → ZERO Gemini calls.
    """
    if mode == "offline":
        res = _offline_fallback_analysis(document_text, document_type)
        res["mode"] = "offline"
        res["processing_badge"] = "⚫ Offline Document Mode"
        return res

    lang_inst = _get_language_instruction(language)
    prompt = f"""You are an expert legal document analyst. Analyze the provided document and return structured JSON.

Document Type: {document_type or "Legal Document"}
{lang_inst}

Return ONLY a valid JSON object:
{{
  "document_type": "Identified type",
  "parties": ["Party 1 name", "Party 2 name"],
  "summary": "2-3 paragraph plain-language summary of the document",
  "key_takeaways": ["Takeaway 1", "Takeaway 2", "Takeaway 3"],
  "important_clauses": [
    {{
      "name": "Clause Name",
      "category": "Category",
      "section": "Section number or title",
      "page": null,
      "original_text": "Exact text excerpt from document",
      "explanation": "Plain language explanation"
    }}
  ],
  "obligations": {{
    "party_a": {{"name": "Name", "obligations": ["obligation 1"]}},
    "party_b": {{"name": "Name", "obligations": ["obligation 1"]}}
  }},
  "important_dates": [
    {{"label": "Date label", "date": "date as in document", "context": "brief context"}}
  ],
  "financial_terms": [
    {{"label": "Term label", "amount": "amount as in document", "context": "brief context"}}
  ],
  "points_to_review": [
    {{"title": "Title", "description": "Why this deserves attention", "section": "section reference", "severity": "low/medium/high"}}
  ]
}}

CRITICAL RULES:
- Only report information that is ACTUALLY present in the document.
- Do NOT invent clauses, dates, amounts, parties, or legal conclusions.
- For page numbers: use actual page numbers if visible in document text, otherwise use null.
- Return ONLY the JSON object, no other text.

Document:
---
{document_text[:15000]}
---
"""
    try:
        result = _call_gemini(prompt, max_tokens=8192, api_key=api_key, mode=mode)
        parsed = _parse_json(result)
        if parsed and isinstance(parsed, dict) and parsed.get("summary"):
            parsed["mode"] = "gemini"
            parsed["processing_badge"] = "🟢 Gemini AI"
            return parsed
    except Exception as e:
        logger.warning(f"analyze_document: Gemini unavailable ({_sanitize_error_message(str(e))}). Using offline engine.")

    res = _offline_fallback_analysis(document_text, document_type)
    if mode == "gemini":
        res["mode"] = "offline_fallback"
        res["processing_badge"] = "🟠 Gemini unavailable — Offline answer"
    else:
        res["mode"] = "offline"
        res["processing_badge"] = "⚫ Offline Document Mode"
    return res


# ---------------------------------------------------------------------------
# Local Q&A Retrieval Engine — Zero Fabrication
# ---------------------------------------------------------------------------

def _tokenize(text: str) -> list:
    """Simple word tokenizer, lowercase, removes stop words."""
    stop_words = {
        "can", "this", "agreement", "be", "what", "happens", "if", "the", "is", "are",
        "does", "you", "your", "my", "i", "a", "an", "of", "in", "to", "for", "with",
        "on", "at", "by", "from", "document", "about", "please", "tell", "me", "do",
        "has", "have", "had", "was", "were", "it", "its", "that", "which", "or", "and",
        "but", "not", "no", "how", "when", "where", "who", "will", "would", "could",
        "should", "may", "might", "shall", "get", "give", "show", "find", "list",
    }
    words = re.findall(r"\b[a-z]{2,}\b", text.lower())
    return [w for w in words if w not in stop_words]


def _extract_page_from_context(doc_text: str, char_pos: int) -> int | None:
    """
    If the document has [Page N] markers (PDF), find the page for a character position.
    Returns None for DOCX/TXT (no real page numbers).
    """
    page_markers = list(re.finditer(r"\[Page (\d+)\]", doc_text))
    if not page_markers:
        return None
    current_page = None
    for marker in page_markers:
        if marker.start() <= char_pos:
            current_page = int(marker.group(1))
        else:
            break
    return current_page


def _smart_offline_qa(document_text: str, question: str, document_type: str = "") -> dict:
    """
    Zero-fabrication rule-based Q&A engine.

    Pipeline:
    1. Tokenize question
    2. Score each paragraph by token overlap + phrase matching + heading proximity
    3. Select top evidence
    4. Apply confidence threshold
    5. If confidence insufficient → "I couldn't find this information"

    NEVER invents facts, legal conclusions, or generic assumptions.
    """
    query_tokens = _tokenize(question)
    if not query_tokens:
        return {
            "answer": "I couldn't find this information in the uploaded document.",
            "sources": [], "found_in_document": False, "confidence": "none",
        }

    # Build paragraphs (split on blank lines or [Page N] markers)
    raw_paras = re.split(r"\n\s*\n|\[Page \d+\]", document_text)
    paragraphs = [p.strip() for p in raw_paras if len(p.strip()) > 30]

    # Score each paragraph
    scored = []
    for i, para in enumerate(paragraphs):
        para_lower = para.lower()
        para_tokens = Counter(_tokenize(para))

        # Token overlap score
        overlap = sum(min(para_tokens.get(t, 0), 1) for t in query_tokens)

        # Phrase match bonus: consecutive query tokens appearing together
        phrase_bonus = 0
        if len(query_tokens) >= 2:
            for j in range(len(query_tokens) - 1):
                phrase = query_tokens[j] + " " + query_tokens[j + 1]
                if phrase in para_lower:
                    phrase_bonus += 2

        total_score = overlap + phrase_bonus
        if total_score > 0:
            scored.append((total_score, i, para))

    scored.sort(key=lambda x: -x[0])

    if not scored or scored[0][0] < 1:
        return {
            "answer": "I couldn't find this information in the uploaded document.",
            "sources": [], "found_in_document": False, "confidence": "none",
        }

    # Confidence threshold: need score >= 2 to report confidently
    top_score = scored[0][0]
    confidence = "high" if top_score >= 3 else "medium" if top_score >= 2 else "low"

    if confidence == "low":
        return {
            "answer": "I couldn't find this information in the uploaded document.",
            "sources": [], "found_in_document": False, "confidence": "low",
        }

    # Build answer from top matching paragraphs
    top_paragraphs = [para for _, _, para in scored[:4]]
    bullet_list = "\n".join([f"- {p[:200]}" for p in top_paragraphs])
    answer = f"**Based on the uploaded document:**\n\n{bullet_list}"

    # Build sources — determine location
    sources = []
    for _, para_idx, para in scored[:3]:
        # Find position in original text
        pos = document_text.find(para[:60])
        page = _extract_page_from_context(document_text, pos) if pos >= 0 else None
        source = {"excerpt": para[:150]}
        if page is not None:
            source["page"] = page
            source["section"] = f"Page {page}"
        else:
            source["section"] = "Document"
        sources.append(source)

    return {
        "answer": answer,
        "sources": sources,
        "found_in_document": True,
        "confidence": confidence,
    }


def _select_relevant_context(document_text: str, question: str, max_chars: int = 10000) -> str:
    """
    Select the most relevant portions of a document for a question.
    Sends relevant evidence to Gemini, not the first N characters blindly.
    """
    if len(document_text) <= max_chars:
        return document_text

    query_tokens = _tokenize(question)
    lines = document_text.split("\n")
    scored_lines = []
    for i, line in enumerate(lines):
        line_lower = line.lower()
        score = sum(1 for t in query_tokens if t in line_lower)
        scored_lines.append((score, i, line))
    scored_lines.sort(key=lambda x: -x[0])

    selected = set()
    for score, idx, line in scored_lines[:25]:
        if score > 0:
            for j in range(max(0, idx - 2), min(len(lines), idx + 5)):
                selected.add(j)

    # Always include document start (definitions, parties)
    for j in range(min(30, len(lines))):
        selected.add(j)

    selected_lines = [lines[i] for i in sorted(selected)]
    context = "\n".join(selected_lines)
    return context[:max_chars]


# ---------------------------------------------------------------------------
# Document Q&A
# ---------------------------------------------------------------------------

def ask_document(document_text: str, question: str, document_type: str = "",
                 api_key: str = None, mode: str = "auto",
                 bypass_cache: bool = False, session_id: str = None,
                 language: str = "en") -> dict:
    """
    Answer a document question with caching, 3-mode routing, and zero-fabrication retrieval.
    """
    # Cache check (skip if bypassing)
    if not bypass_cache:
        cached = get_cached_question_answer(session_id, "doc", document_text, question, mode, language)
        if cached:
            return cached

    # Always run local retrieval first (deterministic, zero-quota)
    offline_res = _smart_offline_qa(document_text, question, document_type)

    # Offline Mode: return local result, ZERO Gemini
    if mode == "offline":
        offline_res["mode"] = "offline"
        offline_res["processing_badge"] = "⚫ Offline Document Mode"
        set_cached_question_answer(session_id, "doc", document_text, question, mode, offline_res, language)
        return offline_res

    # Auto Mode: if local retrieval found high-confidence answer, use it (save quota)
    if mode == "auto" and offline_res.get("found_in_document") and offline_res.get("confidence") == "high":
        offline_res["mode"] = "local"
        offline_res["processing_badge"] = "⚡ Local Retrieval"
        set_cached_question_answer(session_id, "doc", document_text, question, mode, offline_res, language)
        return offline_res

    # Gemini Q&A with relevant evidence only
    relevant_context = _select_relevant_context(document_text, question, max_chars=10000)
    lang_inst = _get_language_instruction(language)

    prompt = f"""You are a legal document assistant. Answer the user's question based ONLY on the provided document excerpt.

Document Type: {document_type or "Legal Document"}
{lang_inst}

RULES:
- Answer ONLY from the document content below.
- If the answer is not in the document, say exactly: "I couldn't find this information in the uploaded document."
- Do NOT invent facts, dates, amounts, obligations, parties, penalties, or legal conclusions.
- Use plain language. Cite section numbers if visible.
- Provide a complete, thorough answer. Do not cut off mid-sentence.

Return JSON:
{{
  "answer": "your detailed answer",
  "sources": [
    {{"section": "Section title or Page N", "excerpt": "relevant text excerpt"}}
  ],
  "found_in_document": true
}}

If not found: set found_in_document to false and answer to "I couldn't find this information in the uploaded document."

Document excerpt:
---
{relevant_context}
---

User question: {question}
"""
    try:
        result = _call_gemini(prompt, max_tokens=4096, api_key=api_key, mode=mode)
        parsed = _parse_json(result)
        if parsed and isinstance(parsed, dict) and parsed.get("answer"):
            parsed["mode"] = "gemini"
            parsed["processing_badge"] = "🟢 Gemini AI"
            set_cached_question_answer(session_id, "doc", document_text, question, mode, parsed, language)
            return parsed
    except Exception as e:
        logger.warning(f"ask_document: Gemini unavailable ({_sanitize_error_message(str(e))}). Using local Q&A.")

    # Fallback
    if mode == "gemini":
        offline_res["mode"] = "offline_fallback"
        offline_res["processing_badge"] = "🟠 Gemini unavailable — Offline answer"
    else:
        offline_res["mode"] = "offline"
        offline_res["processing_badge"] = "⚫ Offline Document Mode"
    set_cached_question_answer(session_id, "doc", document_text, question, mode, offline_res, language)
    return offline_res


# ---------------------------------------------------------------------------
# Document Comparison
# ---------------------------------------------------------------------------

def _local_compare_documents(text_a: str, text_b: str, name_a: str = "Document A", name_b: str = "Document B") -> dict:
    """
    Factual document comparison using difflib.SequenceMatcher.
    Compares full document text without artificial character truncation.
    Returns factual diff table without automatic legal significance ratings.
    """
    # Split into meaningful lines (filter blanks)
    lines_a = [l.strip() for l in text_a.split("\n") if len(l.strip()) > 20]
    lines_b = [l.strip() for l in text_b.split("\n") if len(l.strip()) > 20]

    set_a = set(lines_a)
    set_b = set(lines_b)

    added = [l for l in lines_b if l not in set_a]
    removed = [l for l in lines_a if l not in set_b]

    # SequenceMatcher ratio calculated over complete document text
    matcher = difflib.SequenceMatcher(None, text_a, text_b, autojunk=False)
    similarity = round(matcher.ratio() * 100, 1)

    # Extract dates & amounts for structured diff
    date_re = re.compile(
        r"\b(?:January|February|March|April|May|June|July|August|September|October|November|December)\s+\d{1,2},?\s+\d{4}\b"
        r"|\b\d{4}-\d{2}-\d{2}\b"
        r"|\b\d{1,2}/\d{1,2}/\d{2,4}\b",
        re.IGNORECASE,
    )
    amount_re = re.compile(r"(?:₹|Rs\.?|INR|\$|USD|EUR)\s*[\d,]+(?:\.\d{1,2})?", re.IGNORECASE)
    pct_re = re.compile(r"\b\d+(?:\.\d+)?%")

    dates_a = set(date_re.findall(text_a))
    dates_b = set(date_re.findall(text_b))
    amounts_a = set(amount_re.findall(text_a))
    amounts_b = set(amount_re.findall(text_b))
    pcts_a = set(pct_re.findall(text_a))
    pcts_b = set(pct_re.findall(text_b))

    diff_table = []
    if dates_a != dates_b:
        only_in_a = dates_a - dates_b
        only_in_b = dates_b - dates_a
        if only_in_a or only_in_b:
            diff_table.append({
                "category": "Date Difference",
                "document_a": ", ".join(sorted(only_in_a)) if only_in_a else "Same as Document B",
                "document_b": ", ".join(sorted(only_in_b)) if only_in_b else "Same as Document A",
                "note": "Different date values appear in each document.",
            })

    if amounts_a != amounts_b:
        only_in_a = amounts_a - amounts_b
        only_in_b = amounts_b - amounts_a
        if only_in_a or only_in_b:
            diff_table.append({
                "category": "Amount Difference",
                "document_a": ", ".join(sorted(only_in_a)) if only_in_a else "Same as Document B",
                "document_b": ", ".join(sorted(only_in_b)) if only_in_b else "Same as Document A",
                "note": "Financial figures differ between documents.",
            })

    if pcts_a != pcts_b:
        diff_table.append({
            "category": "Percentage Difference",
            "document_a": ", ".join(sorted(pcts_a - pcts_b)) if (pcts_a - pcts_b) else "None unique",
            "document_b": ", ".join(sorted(pcts_b - pcts_a)) if (pcts_b - pcts_a) else "None unique",
            "note": "Percentage figures differ between documents.",
        })

    # Clause-level wording differences
    important_headings = ["notice", "termination", "salary", "rent", "jurisdiction", "probation", "penalty", "arbitration"]
    checked_categories = set()
    for la in lines_a:
        la_lower = la.lower()
        for heading in important_headings:
            if heading in la_lower and heading not in checked_categories:
                for lb in lines_b:
                    lb_lower = lb.lower()
                    if heading in lb_lower and la != lb:
                        diff_table.append({
                            "category": f"Wording Difference ({heading.title()})",
                            "document_a": la[:150],
                            "document_b": lb[:150],
                            "note": f"Text of '{heading}' section differs between documents.",
                        })
                        checked_categories.add(heading)
                        break

    n_added = len(added)
    n_removed = len(removed)
    summary = (
        f"Comparison of {name_a} vs {name_b}. "
        f"Documents are approximately {similarity}% similar. "
        f"{n_added} line(s) found only in {name_b}; {n_removed} line(s) found only in {name_a}."
    )

    return {
        "summary": summary,
        "differences": diff_table[:8] if diff_table else [],
        "added_in_b": added[:6] if added else [],
        "removed_in_b": removed[:6] if removed else [],
        "recommendation": None,   # No fabricated recommendation
        "similarity_pct": similarity,
        "mode": "offline",
        "processing_badge": "⚫ Offline Document Comparison",
    }


def compare_documents(text_a: str, text_b: str, name_a: str = "Document A", name_b: str = "Document B",
                      api_key: str = None, mode: str = "auto", language: str = "en") -> dict:
    """
    Compare two legal documents.
    Local diff is always run for factual accuracy.
    Gemini provides practical interpretation if mode allows.
    """
    local_diff = _local_compare_documents(text_a, text_b, name_a, name_b)

    if mode == "offline":
        local_diff["mode"] = "offline"
        local_diff["processing_badge"] = "⚫ Offline Document Comparison"
        return local_diff

    # Use full document text for Gemini context
    sample_a = _select_relevant_context(text_a, f"{name_a} comparison", max_chars=5000)
    sample_b = _select_relevant_context(text_b, f"{name_b} comparison", max_chars=5000)

    lang_inst = _get_language_instruction(language)
    prompt = f"""You are a legal document comparison expert.

Compare these two legal documents. Focus on actual textual differences.
{lang_inst}

Return JSON:
{{
  "summary": "Brief overall factual comparison",
  "differences": [
    {{
      "category": "Factual category e.g. Date Difference / Amount Difference / Wording Difference",
      "document_a": "What {name_a} says",
      "document_b": "What {name_b} says",
      "note": "Factual description or AI interpretation (clearly labeled)"
    }}
  ],
  "added_in_b": ["Text/clauses present in {name_b} but not in {name_a}"],
  "removed_in_b": ["Text/clauses present in {name_a} but not in {name_b}"],
  "recommendation": "Key points to review — label interpretation clearly as 'AI interpretation'"
}}

RULES:
- Do NOT invent differences.
- Only report factual differences present in the text.
- Do NOT assign arbitrary legal severity rankings (e.g., high/medium/low significance or high risk).
- Label interpretations clearly as 'AI interpretation:'.
- Do NOT call one document 'better', 'safer', or 'more favorable' without explicit evidence.
- Return ONLY valid JSON.

{name_a}:
---
{sample_a}
---

{name_b}:
---
{sample_b}
---
"""
    try:
        result = _call_gemini(prompt, max_tokens=4096, api_key=api_key, mode=mode)
        parsed = _parse_json(result)
        if parsed and isinstance(parsed, dict) and parsed.get("summary"):
            # Merge local factual diffs if Gemini found none
            if not parsed.get("differences") and local_diff.get("differences"):
                parsed["differences"] = local_diff["differences"]
            if not parsed.get("added_in_b") and local_diff.get("added_in_b"):
                parsed["added_in_b"] = local_diff["added_in_b"]
            if not parsed.get("removed_in_b") and local_diff.get("removed_in_b"):
                parsed["removed_in_b"] = local_diff["removed_in_b"]
            parsed["mode"] = "gemini"
            parsed["processing_badge"] = "🟢 Gemini AI Comparison"
            parsed["similarity_pct"] = local_diff.get("similarity_pct")
            return parsed
    except Exception as e:
        logger.warning(f"compare_documents: Gemini unavailable ({_sanitize_error_message(str(e))}). Using local diff.")

    if mode == "gemini":
        local_diff["mode"] = "offline_fallback"
        local_diff["processing_badge"] = "🟠 Gemini unavailable — Offline answer"
    else:
        local_diff["mode"] = "offline"
        local_diff["processing_badge"] = "⚫ Offline Document Comparison"
    return local_diff


# ---------------------------------------------------------------------------
# Lawyer Preparation
# ---------------------------------------------------------------------------

def _offline_lawyer_prep(document_text: str, analysis: dict) -> dict:
    """
    Offline lawyer prep. Grounded strictly in extracted document facts.
    Does NOT invent generic legal requirements or unsupported documents to bring.
    """
    doc_type = analysis.get("document_type", "legal document")
    parties = analysis.get("parties", [])
    clauses = analysis.get("important_clauses", [])
    points = analysis.get("points_to_review", [])
    dates = analysis.get("important_dates", [])

    # Generate questions only from identified clauses/points
    questions = []
    for clause in clauses[:4]:
        orig = clause.get("original_text") or clause.get("explanation") or ""
        if orig:
            questions.append({
                "question": f"What are the implications of: \"{orig[:120]}\"?",
                "context": f"Identified in section: {clause.get('name', 'Clause')}",
            })
    for point in points[:3]:
        desc = point.get("description", "")
        if desc:
            questions.append({
                "question": f"How should we address: \"{desc[:120]}\"?",
                "context": f"Flagged review item: {point.get('title', 'Item')}",
            })

    important_facts = [f"Document type: {doc_type}"]
    if parties:
        important_facts.append(f"Parties identified: {', '.join(parties)}")
    if clauses:
        important_facts.append(f"{len(clauses)} clause(s) identified for review.")

    # Ground documents to bring strictly in document text (e.g. mentioned exhibits)
    docs_to_bring = ["Original uploaded document or draft"]
    exhibits = re.findall(r"\b(?:Exhibit|Annexure|Schedule|Attachment)\s+[A-Z0-9]+\b", document_text, re.IGNORECASE)
    for ex in set(exhibits[:3]):
        docs_to_bring.append(ex.title())

    date_reminders = [f"{d.get('label', 'Date')}: {d.get('date', '—')}" for d in dates[:3] if d.get("date")]
    key_concerns = [p.get("title", "") for p in points[:4] if p.get("title")]

    return {
        "important_facts": important_facts,
        "questions_for_lawyer": questions if questions else [],
        "documents_to_bring": docs_to_bring,
        "dates_to_remember": date_reminders if date_reminders else ["Not identified in document."],
        "key_concerns": key_concerns if key_concerns else ["Not identified in document."],
        "mode": "offline",
        "processing_badge": "⚫ Offline Document Mode",
    }


def generate_lawyer_questions(document_text: str, analysis: dict, api_key: str = None, mode: str = "auto", language: str = "en") -> dict:
    """Generate lawyer consultation prep. Offline Mode = ZERO Gemini."""
    if mode == "offline":
        return _offline_lawyer_prep(document_text, analysis)

    doc_type = analysis.get("document_type", "legal document")
    clauses_json = json.dumps(analysis.get("important_clauses", [])[:5])
    points_json = json.dumps(analysis.get("points_to_review", [])[:4])

    lang_inst = _get_language_instruction(language)
    prompt = f"""You are helping someone prepare for a legal consultation about a {doc_type}.

Based on the actual document content below, generate specific questions and preparation items.
{lang_inst}

Return JSON:
{{
  "important_facts": ["fact 1", "fact 2"],
  "questions_for_lawyer": [
    {{
      "question": "Specific question derived from actual document text",
      "context": "Which clause or section this relates to"
    }}
  ],
  "documents_to_bring": ["document 1"],
  "dates_to_remember": ["date 1"],
  "key_concerns": ["concern 1"]
}}

RULES:
- Base every question on actual identified clauses below.
- Do NOT generate generic legal questions unrelated to the document.
- Do NOT add unsupported requirements like Government ID unless explicitly mentioned in the text.
- Encourage consulting a qualified legal professional.

Identified clauses: {clauses_json}
Points to review: {points_json}

Document excerpt:
---
{document_text[:3500]}
---
"""
    try:
        result = _call_gemini(prompt, max_tokens=3000, api_key=api_key, mode=mode)
        parsed = _parse_json(result)
        if parsed and isinstance(parsed, dict) and parsed.get("questions_for_lawyer"):
            parsed["mode"] = "gemini"
            parsed["processing_badge"] = "🟢 Gemini AI"
            return parsed
    except Exception as e:
        logger.warning(f"generate_lawyer_questions: Gemini unavailable ({_sanitize_error_message(str(e))}).")

    return _offline_lawyer_prep(document_text, analysis)


# ---------------------------------------------------------------------------
# Legal Brief
# ---------------------------------------------------------------------------

def _offline_legal_brief(document_text: str, analysis: dict) -> dict:
    """
    Offline legal brief. Based entirely on extracted analysis.
    Does NOT claim legal conclusions not supported by the document.
    """
    doc_type = analysis.get("document_type", "Legal Document")
    parties = analysis.get("parties", [])
    clauses = analysis.get("important_clauses", [])
    dates = analysis.get("important_dates", [])
    financials = analysis.get("financial_terms", [])
    points = analysis.get("points_to_review", [])
    summary = analysis.get("summary", "")

    parties_str = ", ".join(parties) if parties else "Not identified in document"
    purpose = f"This document appears to be a {doc_type}" + (f" involving {parties_str}." if parties else ".")

    dates_summary = (
        "; ".join([f"{d.get('label', 'Date')}: {d.get('date', '—')}" for d in dates])
        if dates else "Not found in document."
    )
    financials_summary = (
        "; ".join([f"{f.get('label', 'Term')}: {f.get('amount', '—')}" for f in financials])
        if financials else "Not found in document."
    )
    points_summary = (
        "; ".join([p.get("title", "") for p in points if p.get("title")])
        if points else "No specific points flagged."
    )

    # Derive questions strictly from extracted clauses and points
    recommended_questions = []
    for clause in clauses:
        c_name = clause.get("name", "").lower()
        if any(w in c_name for w in ["termination", "notice", "cancel"]):
            recommended_questions.append("What are the specific notice period and termination terms stated in the document?")
        elif any(w in c_name for w in ["confidential", "secret", "proprietary"]):
            recommended_questions.append("What duration and scope apply to the confidentiality obligations?")
        elif any(w in c_name for w in ["payment", "rent", "salary", "fee", "compensation"]):
            recommended_questions.append("What are the exact payment terms and schedules specified in the document?")
        elif any(w in c_name for w in ["compete", "solicit", "restrict"]):
            recommended_questions.append("What geographic or temporal limits apply to the restrictive covenants in this document?")

    for point in points:
        p_title = point.get("title", "")
        if p_title and f"What specific conditions apply to the '{p_title}' provision?" not in recommended_questions:
            recommended_questions.append(f"What specific conditions apply to the '{p_title}' provision?")

    if not recommended_questions:
        recommended_questions = ["No specific clause-derived questions identified from the document."]

    return {
        "title": f"Document Brief — {doc_type}",
        "document_type": doc_type,
        "parties": parties,
        "purpose": purpose,
        "executive_summary": summary or "Document summary not available.",
        "key_provisions": [
            {"title": c.get("name", "Provision"), "description": c.get("explanation", "Clause details")}
            for c in clauses[:6]
        ],
        "obligations_summary": "Obligations identified from document text. Review with a legal professional.",
        "important_dates_summary": dates_summary,
        "financial_summary": financials_summary,
        "points_to_review_summary": points_summary,
        "recommended_questions": recommended_questions[:5],
        "disclaimer": "This brief is for informational purposes only and does not constitute legal advice. Consult a qualified legal professional.",
        "mode": "offline",
        "processing_badge": "⚫ Offline Document Brief",
    }


def generate_legal_brief(document_text: str, analysis: dict, api_key: str = None, mode: str = "auto", language: str = "en") -> dict:
    """Generate a legal brief. Offline Mode = ZERO Gemini."""
    if mode == "offline":
        return _offline_legal_brief(document_text, analysis)

    lang_inst = _get_language_instruction(language)
    prompt = f"""You are a legal document specialist. Create a structured legal brief from the analysis below.
{lang_inst}

Return JSON:
{{
  "title": "Brief title",
  "document_type": "...",
  "parties": ["Party 1", "Party 2"],
  "purpose": "One sentence — document purpose",
  "executive_summary": "2-3 paragraph plain-language summary",
  "key_provisions": [
    {{"title": "Provision name", "description": "Plain language description from document"}}
  ],
  "obligations_summary": "Summary of main obligations found in document",
  "important_dates_summary": "Summary of key dates found in document",
  "financial_summary": "Summary of financial terms found in document",
  "points_to_review_summary": "Summary of flagged review items",
  "recommended_questions": ["Question 1", "Question 2"],
  "disclaimer": "This brief is for informational purposes only and does not constitute legal advice."
}}

RULES:
- Do NOT claim enforceability, legality, or legal conclusions beyond what the document states.
- Use factual language: 'The document states...', 'The document provides for...'
- Label any interpretation as 'AI interpretation:'.
- Return ONLY valid JSON.

Analysis data:
{json.dumps(analysis, indent=2)[:5000]}
"""
    try:
        result = _call_gemini(prompt, max_tokens=4000, api_key=api_key, mode=mode)
        parsed = _parse_json(result)
        if parsed and isinstance(parsed, dict) and parsed.get("executive_summary"):
            parsed["mode"] = "gemini"
            parsed["processing_badge"] = "🟢 Gemini AI"
            return parsed
    except Exception as e:
        logger.warning(f"generate_legal_brief: Gemini unavailable ({_sanitize_error_message(str(e))}).")

    return _offline_legal_brief(document_text, analysis)


# ---------------------------------------------------------------------------
# Clause Explanation
# ---------------------------------------------------------------------------

def explain_clause_simply(clause_text: str, api_key: str = None, mode: str = "auto", language: str = "en") -> str:
    """Explain a legal clause in plain language. Offline Mode = ZERO Gemini."""
    if mode == "offline":
        if clause_text:
            return (
                "I can identify the relevant clause text, but a reliable plain-language interpretation "
                "requires Gemini AI or professional legal review. The clause reads: "
                f"\"{clause_text[:150]}...\""
            )
        return "No clause text provided."

    lang_inst = _get_language_instruction(language)
    prompt = f"""Explain the following legal clause in simple, everyday language (2-3 sentences max).
Do not change the meaning. Do not provide legal advice.
{lang_inst}

Legal clause:
\"{clause_text}\"

Return ONLY the plain-language explanation.
"""
    try:
        res = _call_gemini(prompt, max_tokens=300, api_key=api_key, mode=mode).strip()
        if res:
            return res
    except Exception as e:
        logger.warning(f"explain_clause_simply: Gemini unavailable ({_sanitize_error_message(str(e))}).")

    return (
        "I can identify the relevant clause text, but a reliable plain-language interpretation "
        "requires Gemini AI or professional legal review."
    )
