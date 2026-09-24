"""
app.py — Legal AI Assistant Flask Application
Main entry point. All API routes and page routes are defined here.
"""

import os
import json
import sqlite3
import uuid
import logging
from datetime import datetime
from pathlib import Path

from flask import (
    Flask, request, jsonify, render_template, send_file,
    redirect, url_for, abort, session
)
from werkzeug.utils import secure_filename
from dotenv import load_dotenv

# Load environment variables from .env
load_dotenv()

# ---------------------------------------------------------------------------
# App setup
# ---------------------------------------------------------------------------

app = Flask(__name__)
app.secret_key = os.environ.get("FLASK_SECRET_KEY", "dev-secret-key-change-in-prod")
app.config["MAX_CONTENT_LENGTH"] = int(os.environ.get("MAX_UPLOAD_SIZE_MB", 20)) * 1024 * 1024

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Directories
# ---------------------------------------------------------------------------

BASE_DIR = Path(__file__).parent
UPLOAD_FOLDER = BASE_DIR / "uploads"
DB_FOLDER = BASE_DIR / "database"
REPORTS_FOLDER = BASE_DIR / "generated_reports"
SAMPLE_DOCS_FOLDER = BASE_DIR / "sample_documents"

for folder in [UPLOAD_FOLDER, DB_FOLDER, REPORTS_FOLDER, SAMPLE_DOCS_FOLDER]:
    folder.mkdir(exist_ok=True)

ALLOWED_EXTENSIONS = {"pdf", "docx", "txt"}
DB_PATH = DB_FOLDER / "legal_ai.db"

# ---------------------------------------------------------------------------
# Database initialization
# ---------------------------------------------------------------------------

def get_db():
    """Get a database connection."""
    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    """Initialize the SQLite database schema."""
    conn = get_db()
    cursor = conn.cursor()

    cursor.executescript("""
        CREATE TABLE IF NOT EXISTS documents (
            id TEXT PRIMARY KEY,
            filename TEXT NOT NULL,
            original_filename TEXT NOT NULL,
            file_type TEXT NOT NULL,
            document_type TEXT,
            file_path TEXT NOT NULL,
            uploaded_at TEXT NOT NULL,
            extracted_text TEXT,
            total_pages INTEGER DEFAULT 0,
            language TEXT DEFAULT 'en',
            analysis_status TEXT DEFAULT 'pending'
        );

        CREATE TABLE IF NOT EXISTS analyses (
            id TEXT PRIMARY KEY,
            document_id TEXT NOT NULL,
            summary TEXT,
            key_takeaways TEXT,
            important_clauses TEXT,
            points_to_review TEXT,
            obligations TEXT,
            important_dates TEXT,
            financial_terms TEXT,
            document_type TEXT,
            parties TEXT,
            created_at TEXT NOT NULL,
            FOREIGN KEY (document_id) REFERENCES documents(id)
        );

        CREATE TABLE IF NOT EXISTS chat_history (
            id TEXT PRIMARY KEY,
            document_id TEXT NOT NULL,
            question TEXT NOT NULL,
            answer TEXT NOT NULL,
            sources TEXT,
            created_at TEXT NOT NULL,
            FOREIGN KEY (document_id) REFERENCES documents(id)
        );

        CREATE TABLE IF NOT EXISTS comparisons (
            id TEXT PRIMARY KEY,
            document_1_id TEXT NOT NULL,
            document_2_id TEXT NOT NULL,
            comparison_result TEXT,
            created_at TEXT NOT NULL,
            FOREIGN KEY (document_1_id) REFERENCES documents(id),
            FOREIGN KEY (document_2_id) REFERENCES documents(id)
        );
    """)
    # Ensure cache validation columns exist on analyses table
    cursor.execute("PRAGMA table_info(analyses)")
    cols = [col[1] for col in cursor.fetchall()]
    if "content_hash" not in cols:
        cursor.execute("ALTER TABLE analyses ADD COLUMN content_hash TEXT")
    if "analysis_version" not in cols:
        cursor.execute("ALTER TABLE analyses ADD COLUMN analysis_version TEXT DEFAULT 'v1'")
    if "mode" not in cols:
        cursor.execute("ALTER TABLE analyses ADD COLUMN mode TEXT")
    if "model" not in cols:
        cursor.execute("ALTER TABLE analyses ADD COLUMN model TEXT")

    conn.commit()
    conn.close()
    logger.info("Database initialized.")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def allowed_file(filename: str) -> bool:
    return "." in filename and filename.rsplit(".", 1)[1].lower() in ALLOWED_EXTENSIONS


def get_file_type(filename: str) -> str:
    return filename.rsplit(".", 1)[1].lower() if "." in filename else ""


def doc_to_dict(row) -> dict:
    """Convert a documents row to a plain dict."""
    d = dict(row)
    # Don't expose extracted text in list endpoints
    d.pop("extracted_text", None)
    return d


def analysis_to_dict(row) -> dict:
    """Convert an analyses row, parsing JSON fields."""
    if row is None:
        return None
    d = dict(row)
    for field in ["key_takeaways", "important_clauses", "points_to_review",
                  "obligations", "important_dates", "financial_terms", "parties"]:
        if d.get(field):
            try:
                d[field] = json.loads(d[field])
            except (json.JSONDecodeError, TypeError):
                d[field] = []
    return d


def now_iso() -> str:
    return datetime.utcnow().isoformat()


def get_active_gemini_key() -> str:
    """Return session user key if present, otherwise .env key. Never exposed to frontend."""
    user_key = (session.get("user_gemini_api_key") or "").strip()
    if user_key:
        return user_key
    return (os.environ.get("GEMINI_API_KEY") or "").strip()


def get_active_translate_key() -> str:
    """
    Return the active Google Cloud Translation API key.
    Env variable name: GOOGLE_TRANSLATE_API_KEY (canonical name used everywhere).
    """
    user_key = (session.get("user_translate_api_key") or "").strip()
    if user_key:
        return user_key
    return (os.environ.get("GOOGLE_TRANSLATE_API_KEY") or "").strip()


def get_active_tts_credentials() -> str:
    """
    Return the active Google Cloud TTS credentials path.
    Env variable name: GOOGLE_TTS_CREDENTIALS (canonical name used everywhere).
    """
    user_creds = (session.get("user_tts_credentials") or "").strip()
    if user_creds:
        return user_creds
    return (os.environ.get("GOOGLE_TTS_CREDENTIALS") or "").strip()


def ensure_session_id() -> str:
    """Return a stable session identifier. Creates one if not present."""
    if "_sid" not in session:
        session["_sid"] = str(uuid.uuid4())
    return session["_sid"]


def get_active_language() -> str:
    """Extract active language code from headers, query params, JSON, or session."""
    lang = None
    if request.is_json:
        d = request.get_json(silent=True)
        if isinstance(d, dict):
            lang = d.get("language")
    if not lang:
        lang = request.args.get("language") or request.headers.get("X-Language") or session.get("user_language", "en")
    lang = (lang or "en").lower().strip()
    if lang in ("en", "hi", "kn", "mr", "ta", "te"):
        session["user_language"] = lang
        return lang
    return session.get("user_language", "en")


# ---------------------------------------------------------------------------
# Page Routes
# ---------------------------------------------------------------------------

@app.route("/")
def index():
    return render_template("index.html")


@app.route("/dashboard")
def dashboard():
    conn = get_db()
    docs = conn.execute(
        "SELECT id, original_filename, document_type, uploaded_at, total_pages, language, analysis_status "
        "FROM documents ORDER BY uploaded_at DESC LIMIT 10"
    ).fetchall()
    conn.close()
    documents = [dict(d) for d in docs]
    return render_template("dashboard.html", documents=documents)


@app.route("/upload")
def upload_page():
    return render_template("upload.html")


@app.route("/document/<doc_id>")
def document_page(doc_id):
    conn = get_db()
    doc = conn.execute("SELECT * FROM documents WHERE id = ?", (doc_id,)).fetchone()
    conn.close()
    if not doc:
        abort(404)
    return render_template("document.html", document=dict(doc), doc_id=doc_id)


@app.route("/compare")
def compare_page():
    conn = get_db()
    docs = conn.execute(
        "SELECT id, original_filename, document_type, uploaded_at FROM documents ORDER BY uploaded_at DESC"
    ).fetchall()
    conn.close()
    return render_template("compare.html", documents=[dict(d) for d in docs])


@app.route("/saved")
def saved_documents():
    conn = get_db()
    docs = conn.execute(
        "SELECT id, original_filename, document_type, uploaded_at, total_pages, analysis_status "
        "FROM documents ORDER BY uploaded_at DESC"
    ).fetchall()
    conn.close()
    return render_template("saved.html", documents=[dict(d) for d in docs])


@app.route("/settings")
def settings_page():
    return render_template("settings.html")


@app.route("/help")
def help_page():
    return render_template("help.html")


# ---------------------------------------------------------------------------
# API: API Key Credentials & Status
# ---------------------------------------------------------------------------

def get_active_mode() -> str:
    """Return session user mode if present, otherwise default 'auto'."""
    if request.is_json:
        d = request.get_json(silent=True)
        if isinstance(d, dict):
            m = d.get("mode")
            if m in ("auto", "gemini", "offline"):
                return m
    m = request.args.get("mode")
    if m in ("auto", "gemini", "offline"):
        return m
    return session.get("user_mode", "auto")


@app.route("/api/key-status", methods=["GET"])
def get_key_status():
    user_key = (session.get("user_gemini_api_key") or "").strip()
    env_key = (os.environ.get("GEMINI_API_KEY") or "").strip()
    active_key = user_key or env_key

    # Page load must consume ZERO Gemini quota. Only /api/key-status?test=true makes a real call.
    run_test = request.args.get("test", "").lower() in ("true", "1")
    from services.gemini_service import test_gemini_api_key, get_gemini_status_summary

    if run_test:
        res = test_gemini_api_key(active_key)
    else:
        res = get_gemini_status_summary(active_key)

    key_source = "user" if user_key else ("env" if env_key else "none")
    return jsonify({
        "status": res["status"],
        "badge_color": res["badge_color"],
        "message": res["message"],
        "source": key_source,
        "has_gemini_key": bool(active_key),
        "active_mode": get_active_mode(),
        "current_model": res.get("current_model", MODEL_NAME_DEFAULT),
        "translate_key_configured": bool(get_active_translate_key()),
        "tts_key_configured": bool(get_active_tts_credentials()),
    })


@app.route("/api/set-mode", methods=["POST"])
def set_mode():
    data = request.get_json(silent=True) or {}
    mode = data.get("mode", "auto").lower()
    if mode not in ("auto", "gemini", "offline"):
        return jsonify({"error": "Invalid mode"}), 400

    session["user_mode"] = mode
    logger.info(f"User mode set to: {mode}")
    return jsonify({"success": True, "mode": mode, "message": f"Operating mode set to {mode.upper()}"})


@app.route("/api/set-language", methods=["POST"])
def set_language():
    data = request.get_json(silent=True) or {}
    lang = data.get("language", "en").lower().strip()
    if lang not in ("en", "hi", "kn", "mr", "ta", "te"):
        return jsonify({"error": "Invalid language"}), 400
    session["user_language"] = lang
    return jsonify({"success": True, "language": lang})


@app.route("/api/set-keys", methods=["POST"])
def set_keys():
    data = request.get_json(silent=True) or {}
    gemini_key = data.get("gemini_api_key", "").strip()
    translate_key = data.get("translate_api_key", "").strip()
    tts_creds = data.get("tts_credentials", "").strip()

    # Store in session only — keys NEVER sent to frontend, never logged
    if gemini_key:
        session["user_gemini_api_key"] = gemini_key
    if translate_key:
        session["user_translate_api_key"] = translate_key
    if tts_creds:
        session["user_tts_credentials"] = tts_creds

    active_key = get_active_gemini_key()
    from services.gemini_service import test_gemini_api_key
    res = test_gemini_api_key(active_key)

    return jsonify({
        "success": True,
        "message": "API credentials saved for this session.",
        "gemini_status": {"valid": res.get("valid", False), "status": res.get("status"), "message": res.get("message"), "badge_color": res.get("badge_color")}
    })


@app.route("/api/clear-keys", methods=["POST"])
def clear_keys():
    session.pop("user_gemini_api_key", None)
    session.pop("user_translate_api_key", None)
    session.pop("user_tts_credentials", None)

    env_key = (os.environ.get("GEMINI_API_KEY") or "").strip()
    from services.gemini_service import get_gemini_status_summary
    res = get_gemini_status_summary(env_key)

    return jsonify({
        "success": True,
        "message": "Custom API keys cleared. Using environment defaults.",
        "gemini_status": {"valid": res.get("status") == "active", "status": res.get("status"), "message": res.get("message"), "badge_color": res.get("badge_color")}
    })


@app.route("/api/test-gemini-key", methods=["POST"])
def test_key_endpoint():
    data = request.get_json(silent=True) or {}
    test_key = data.get("api_key", "").strip() or get_active_gemini_key()

    from services.gemini_service import test_gemini_api_key
    res = test_gemini_api_key(test_key)
    return jsonify(res)


# ---------------------------------------------------------------------------
# API: Documents
# ---------------------------------------------------------------------------

# Add default model name constant for status responses
MODEL_NAME_DEFAULT = os.environ.get("GEMINI_MODEL", "gemini-3.5-flash-lite").strip()


@app.route("/api/documents/upload", methods=["POST"])
def upload_document():
    if "file" not in request.files:
        return jsonify({"error": "No file provided"}), 400

    file = request.files["file"]
    if not file or file.filename == "":
        return jsonify({"error": "No file selected"}), 400

    if not allowed_file(file.filename):
        return jsonify({"error": "Unsupported file type. Please upload a PDF, DOCX, or TXT file."}), 400

    original_filename = secure_filename(file.filename)
    if not original_filename:
        return jsonify({"error": "Invalid filename."}), 400

    file_type = get_file_type(original_filename)
    doc_id = str(uuid.uuid4())
    stored_filename = f"{doc_id}.{file_type}"
    file_path = UPLOAD_FOLDER / stored_filename

    file.save(str(file_path))
    logger.info(f"Saved uploaded file: {stored_filename}")

    # Extract text — clean up on failure
    try:
        from services.document_parser import extract_text_from_file
        parsed = extract_text_from_file(str(file_path), file_type)
        extracted_text = parsed["text"]
        total_pages = parsed["metadata"]["total_pages"]
    except Exception as e:
        logger.error(f"Text extraction failed for {stored_filename}: {e}")
        try:
            file_path.unlink(missing_ok=True)
        except Exception:
            pass
        return jsonify({"error": "Could not extract readable text from this document. Please ensure it is a valid PDF, DOCX, or TXT file."}), 422

    if not extracted_text.strip():
        try:
            file_path.unlink(missing_ok=True)
        except Exception:
            pass
        return jsonify({"error": "The document appears to be empty or contains no readable text."}), 422

    # Classify document type — respects active mode (no Gemini in Offline Mode)
    mode = get_active_mode()
    try:
        from services.gemini_service import classify_document
        document_type = classify_document(extracted_text[:2500], api_key=get_active_gemini_key(), mode=mode)
    except Exception as e:
        logger.warning(f"Classification failed: {e}")
        document_type = "Unknown / General Legal Document"

    # Save to database
    conn = get_db()
    conn.execute(
        """INSERT INTO documents
           (id, filename, original_filename, file_type, document_type, file_path, uploaded_at, extracted_text, total_pages, language, analysis_status)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (doc_id, stored_filename, original_filename, file_type, document_type,
         str(file_path), now_iso(), extracted_text, total_pages, "en", "pending")
    )
    conn.commit()
    conn.close()

    return jsonify({
        "id": doc_id,
        "original_filename": original_filename,
        "document_type": document_type,
        "total_pages": total_pages,
        "message": "Document uploaded and text extracted successfully.",
    })


@app.route("/api/documents", methods=["GET"])
def list_documents():
    conn = get_db()
    docs = conn.execute(
        "SELECT id, original_filename, document_type, uploaded_at, total_pages, language, analysis_status "
        "FROM documents ORDER BY uploaded_at DESC"
    ).fetchall()
    conn.close()
    return jsonify([dict(d) for d in docs])


@app.route("/api/documents/<doc_id>", methods=["GET"])
def get_document(doc_id):
    conn = get_db()
    doc = conn.execute("SELECT * FROM documents WHERE id = ?", (doc_id,)).fetchone()
    conn.close()
    if not doc:
        return jsonify({"error": "Document not found"}), 404
    d = dict(doc)
    d.pop("extracted_text", None)
    return jsonify(d)


@app.route("/api/documents/<doc_id>", methods=["DELETE"])
def delete_document(doc_id):
    conn = get_db()
    doc = conn.execute("SELECT * FROM documents WHERE id = ?", (doc_id,)).fetchone()
    if not doc:
        conn.close()
        return jsonify({"error": "Document not found"}), 404

    # Delete file
    try:
        file_path = Path(doc["file_path"])
        if file_path.exists():
            file_path.unlink()
    except Exception as e:
        logger.warning(f"Could not delete file: {e}")

    # Delete from DB
    conn.execute("DELETE FROM analyses WHERE document_id = ?", (doc_id,))
    conn.execute("DELETE FROM chat_history WHERE document_id = ?", (doc_id,))
    conn.execute("DELETE FROM documents WHERE id = ?", (doc_id,))
    conn.commit()
    conn.close()

    return jsonify({"message": "Document deleted successfully."})


# ---------------------------------------------------------------------------
# API: Analysis
# ---------------------------------------------------------------------------

@app.route("/api/documents/<doc_id>/analyze", methods=["POST"])
def analyze_document(doc_id):
    data = request.get_json(silent=True) or {}
    force_reanalyze = data.get("force", False)
    mode = get_active_mode()

    conn = get_db()
    doc = conn.execute("SELECT * FROM documents WHERE id = ?", (doc_id,)).fetchone()
    if not doc:
        conn.close()
        return jsonify({"error": "Document not found"}), 404

    document_text = doc["extracted_text"] or ""
    document_type = doc["document_type"] or ""

    if not document_text.strip():
        conn.close()
        return jsonify({"error": "No text found in this document."}), 422

    # Compute cache validation tokens: content_hash, version, mode, model
    import hashlib
    content_hash = hashlib.md5(document_text.encode("utf-8", errors="ignore")).hexdigest()
    analysis_version = "v1"
    from services.gemini_service import get_current_model
    current_model = get_current_model() if mode != "offline" else "offline"

    # Check Document Analysis Cache: validates doc_id, content_hash, version, mode, and model
    if not force_reanalyze:
        existing_row = conn.execute(
            """SELECT * FROM analyses 
               WHERE document_id = ? 
                 AND (content_hash IS NULL OR content_hash = ?)
                 AND (analysis_version IS NULL OR analysis_version = ?)
                 AND (mode IS NULL OR mode = ?)
                 AND (model IS NULL OR mode = 'offline' OR model = ?)
               ORDER BY created_at DESC LIMIT 1""",
            (doc_id, content_hash, analysis_version, mode, current_model)
        ).fetchone()
        if existing_row:
            existing_analysis = analysis_to_dict(existing_row)
            conn.close()
            return jsonify({
                "message": "Analysis loaded from cache.",
                "analysis": existing_analysis,
                "cached": True
            })

    # Run AI / Offline analysis
    try:
        from services.gemini_service import analyze_document as ai_analyze
        analysis = ai_analyze(document_text, document_type, api_key=get_active_gemini_key(), mode=mode, language=get_active_language())
    except Exception as e:
        conn.close()
        logger.error(f"Analysis failed: {e}")
        return jsonify({"error": "Document analysis failed. Please try again or switch to Offline Mode."}), 500

    # Persist analysis with cache validation metadata
    analysis_id = str(uuid.uuid4())
    detected_type = analysis.get("document_type", document_type)

    conn.execute(
        """INSERT OR REPLACE INTO analyses
           (id, document_id, summary, key_takeaways, important_clauses, points_to_review,
            obligations, important_dates, financial_terms, document_type, parties,
            content_hash, analysis_version, mode, model, created_at)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (
            analysis_id, doc_id,
            analysis.get("summary", ""),
            json.dumps(analysis.get("key_takeaways", [])),
            json.dumps(analysis.get("important_clauses", [])),
            json.dumps(analysis.get("points_to_review", [])),
            json.dumps(analysis.get("obligations", {})),
            json.dumps(analysis.get("important_dates", [])),
            json.dumps(analysis.get("financial_terms", [])),
            detected_type,
            json.dumps(analysis.get("parties", [])),
            content_hash,
            analysis_version,
            mode,
            current_model,
            now_iso(),
        )
    )

    # Update document status
    conn.execute(
        "UPDATE documents SET analysis_status = 'analyzed', document_type = ? WHERE id = ?",
        (detected_type, doc_id)
    )
    conn.commit()
    conn.close()

    return jsonify({
        "message": "Analysis complete.",
        "analysis": analysis,
        "cached": False
    })


@app.route("/api/documents/<doc_id>/analysis", methods=["GET"])
def get_analysis(doc_id):
    conn = get_db()
    row = conn.execute(
        "SELECT * FROM analyses WHERE document_id = ? ORDER BY created_at DESC LIMIT 1",
        (doc_id,)
    ).fetchone()
    conn.close()

    if not row:
        return jsonify({"error": "No analysis found for this document. Please run analysis first."}), 404

    return jsonify(analysis_to_dict(row))


# ---------------------------------------------------------------------------
# API: Q&A
# ---------------------------------------------------------------------------

@app.route("/api/documents/<doc_id>/ask", methods=["POST"])
def ask_document(doc_id):
    data = request.get_json(silent=True) or {}
    question = data.get("question", "").strip()
    bypass_cache = data.get("bypass_cache", False)
    mode = get_active_mode()

    if not question:
        return jsonify({"error": "Please provide a question."}), 400

    conn = get_db()
    doc = conn.execute("SELECT * FROM documents WHERE id = ?", (doc_id,)).fetchone()
    if not doc:
        conn.close()
        return jsonify({"error": "Document not found"}), 404

    document_text = doc["extracted_text"] or ""
    document_type = doc["document_type"] or ""

    try:
        from services.gemini_service import ask_document as ai_ask
        sess_id = ensure_session_id()
        result = ai_ask(
            document_text, question, document_type,
            api_key=get_active_gemini_key(), mode=mode,
            bypass_cache=bypass_cache, session_id=sess_id,
            language=get_active_language()
        )
    except Exception as e:
        conn.close()
        logger.error(f"Q&A failed: {e}")
        return jsonify({"error": "We couldn't process your question right now. Please try again or switch to Offline Mode."}), 500

    # Save to chat history
    chat_id = str(uuid.uuid4())
    conn.execute(
        "INSERT INTO chat_history (id, document_id, question, answer, sources, created_at) VALUES (?, ?, ?, ?, ?, ?)",
        (chat_id, doc_id, question, result.get("answer", ""),
         json.dumps(result.get("sources", [])), now_iso())
    )
    conn.commit()
    conn.close()

    return jsonify(result)


@app.route("/api/documents/<doc_id>/chat-history", methods=["GET"])
def get_chat_history(doc_id):
    conn = get_db()
    rows = conn.execute(
        "SELECT question, answer, sources, created_at FROM chat_history WHERE document_id = ? ORDER BY created_at ASC",
        (doc_id,)
    ).fetchall()
    conn.close()

    history = []
    for row in rows:
        item = dict(row)
        if item.get("sources"):
            try:
                item["sources"] = json.loads(item["sources"])
            except Exception:
                item["sources"] = []
        history.append(item)

    return jsonify(history)


# ---------------------------------------------------------------------------
# API: Search
# ---------------------------------------------------------------------------

@app.route("/api/documents/<doc_id>/search", methods=["GET"])
def search_document(doc_id):
    query = request.args.get("q", "").strip()
    if not query:
        return jsonify({"results": [], "count": 0})

    conn = get_db()
    doc = conn.execute("SELECT extracted_text FROM documents WHERE id = ?", (doc_id,)).fetchone()
    conn.close()

    if not doc or not doc["extracted_text"]:
        return jsonify({"results": [], "count": 0})

    from services.document_parser import search_in_text
    results = search_in_text(doc["extracted_text"], query)
    return jsonify({"results": results, "count": len(results), "query": query})


# ---------------------------------------------------------------------------
# API: Comparison
# ---------------------------------------------------------------------------

@app.route("/api/compare", methods=["POST"])
def compare_documents():
    data = request.get_json(silent=True) or {}
    doc_1_id = data.get("document_1_id")
    doc_2_id = data.get("document_2_id")
    mode = get_active_mode()

    if not doc_1_id or not doc_2_id:
        return jsonify({"error": "Please provide both document IDs."}), 400

    if doc_1_id == doc_2_id:
        return jsonify({"error": "Please select two different documents."}), 400

    conn = get_db()
    doc1 = conn.execute("SELECT * FROM documents WHERE id = ?", (doc_1_id,)).fetchone()
    doc2 = conn.execute("SELECT * FROM documents WHERE id = ?", (doc_2_id,)).fetchone()

    if not doc1 or not doc2:
        conn.close()
        return jsonify({"error": "One or both documents not found."}), 404

    try:
        from services.gemini_service import compare_documents as ai_compare
        result = ai_compare(
            doc1["extracted_text"] or "",
            doc2["extracted_text"] or "",
            doc1["original_filename"],
            doc2["original_filename"],
            api_key=get_active_gemini_key(),
            mode=mode,
            language=get_active_language(),
        )
    except Exception as e:
        conn.close()
        logger.error(f"Comparison failed: {e}")
        return jsonify({"error": "Document comparison failed. Please try again."}), 500

    # Save comparison
    comp_id = str(uuid.uuid4())
    conn.execute(
        "INSERT INTO comparisons (id, document_1_id, document_2_id, comparison_result, created_at) VALUES (?, ?, ?, ?, ?)",
        (comp_id, doc_1_id, doc_2_id, json.dumps(result), now_iso())
    )
    conn.commit()
    conn.close()

    return jsonify({
        "comparison_id": comp_id,
        "document_1": doc1["original_filename"],
        "document_2": doc2["original_filename"],
        "result": result,
    })


@app.route("/api/compare/upload", methods=["POST"])
def upload_and_compare():
    """Upload two files at once and compare them. Respects active mode (Offline = no Gemini)."""
    if "file1" not in request.files or "file2" not in request.files:
        return jsonify({"error": "Please upload two documents."}), 400

    mode = get_active_mode()
    results = {}
    uploaded_paths = []

    for key in ["file1", "file2"]:
        file = request.files[key]
        if not file or file.filename == "":
            return jsonify({"error": f"No file selected for {key}"}), 400
        if not allowed_file(file.filename):
            return jsonify({"error": f"Unsupported file type for {key}. Use PDF, DOCX, or TXT."}), 400

        original_filename = secure_filename(file.filename)
        if not original_filename:
            return jsonify({"error": f"Invalid filename for {key}."}), 400

        file_type = get_file_type(original_filename)
        doc_id = str(uuid.uuid4())
        stored_filename = f"{doc_id}.{file_type}"
        file_path = UPLOAD_FOLDER / stored_filename
        file.save(str(file_path))
        uploaded_paths.append(file_path)

        try:
            from services.document_parser import extract_text_from_file
            parsed = extract_text_from_file(str(file_path), file_type)
            extracted_text = parsed["text"]
            total_pages = parsed["metadata"]["total_pages"]
        except Exception as e:
            logger.error(f"Text extraction failed for compare upload {key}: {e}")
            for p in uploaded_paths:
                try: p.unlink(missing_ok=True)
                except: pass
            return jsonify({"error": f"Could not extract text from {original_filename}. Please check the file."}), 422

        if not extracted_text.strip():
            for p in uploaded_paths:
                try: p.unlink(missing_ok=True)
                except: pass
            return jsonify({"error": f"No readable text found in {original_filename}."}), 422

        from services.gemini_service import classify_document
        document_type = classify_document(extracted_text[:2000], api_key=get_active_gemini_key(), mode=mode)

        conn = get_db()
        conn.execute(
            """INSERT INTO documents
               (id, filename, original_filename, file_type, document_type, file_path, uploaded_at, extracted_text, total_pages, language, analysis_status)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (doc_id, stored_filename, original_filename, file_type, document_type,
             str(file_path), now_iso(), extracted_text, total_pages, "en", "pending")
        )
        conn.commit()
        conn.close()

        results[key] = {"id": doc_id, "name": original_filename, "type": document_type}

    return jsonify({
        "document_1": results["file1"],
        "document_2": results["file2"],
        "message": "Both documents uploaded. Ready to compare.",
    })


# ---------------------------------------------------------------------------
# API: Translation
# ---------------------------------------------------------------------------

@app.route("/api/translate", methods=["POST"])
def translate():
    data = request.get_json(silent=True) or {}
    text = data.get("text", "")
    target_language = data.get("target_language", "en")

    if not text:
        return jsonify({"error": "No text provided."}), 400

    from services.translation_service import translate_text
    result = translate_text(text, target_language)
    return jsonify(result)


# ---------------------------------------------------------------------------
# API: Text-to-Speech
# ---------------------------------------------------------------------------

@app.route("/api/speak", methods=["POST"])
def speak():
    data = request.get_json(silent=True) or {}
    text = data.get("text", "")
    language = data.get("language", "en")

    if not text:
        return jsonify({"error": "No text provided."}), 400

    from services.speech_service import text_to_speech
    result = text_to_speech(text[:3000], language)
    return jsonify(result)


# ---------------------------------------------------------------------------
# API: Lawyer Preparation
# ---------------------------------------------------------------------------

@app.route("/api/documents/<doc_id>/lawyer-prep", methods=["POST"])
def lawyer_prep(doc_id):
    mode = get_active_mode()
    conn = get_db()
    doc = conn.execute("SELECT * FROM documents WHERE id = ?", (doc_id,)).fetchone()
    analysis_row = conn.execute(
        "SELECT * FROM analyses WHERE document_id = ? ORDER BY created_at DESC LIMIT 1",
        (doc_id,)
    ).fetchone()
    conn.close()

    if not doc:
        return jsonify({"error": "Document not found"}), 404

    analysis = analysis_to_dict(analysis_row) if analysis_row else {}

    try:
        from services.gemini_service import generate_lawyer_questions
        result = generate_lawyer_questions(doc["extracted_text"] or "", analysis, api_key=get_active_gemini_key(), mode=mode, language=get_active_language())
    except Exception as e:
        logger.error(f"Lawyer prep failed: {e}")
        return jsonify({"error": "Could not generate lawyer preparation guide. Please try again."}), 500

    return jsonify(result)


# ---------------------------------------------------------------------------
# API: Legal Brief
# ---------------------------------------------------------------------------

@app.route("/api/documents/<doc_id>/brief", methods=["POST"])
def generate_brief(doc_id):
    mode = get_active_mode()
    conn = get_db()
    doc = conn.execute("SELECT * FROM documents WHERE id = ?", (doc_id,)).fetchone()
    analysis_row = conn.execute(
        "SELECT * FROM analyses WHERE document_id = ? ORDER BY created_at DESC LIMIT 1",
        (doc_id,)
    ).fetchone()
    conn.close()

    if not doc:
        return jsonify({"error": "Document not found"}), 404

    analysis = analysis_to_dict(analysis_row) if analysis_row else {}

    try:
        from services.gemini_service import generate_legal_brief
        brief = generate_legal_brief(doc["extracted_text"] or "", analysis, api_key=get_active_gemini_key(), mode=mode, language=get_active_language())
    except Exception as e:
        logger.error(f"Brief generation failed: {e}")
        return jsonify({"error": "Could not generate legal brief. Please try again."}), 500

    return jsonify(brief)


# ---------------------------------------------------------------------------
# API: PDF Report
# ---------------------------------------------------------------------------

@app.route("/api/documents/<doc_id>/report", methods=["GET"])
def download_report(doc_id):
    """
    Generate and download a PDF report.
    Uses cached analysis — does NOT regenerate Gemini analysis.
    Respects active mode: Offline Mode = ZERO Gemini calls.
    """
    mode = get_active_mode()
    conn = get_db()
    doc = conn.execute("SELECT * FROM documents WHERE id = ?", (doc_id,)).fetchone()
    analysis_row = conn.execute(
        "SELECT * FROM analyses WHERE document_id = ? ORDER BY created_at DESC LIMIT 1",
        (doc_id,)
    ).fetchone()
    conn.close()

    if not doc:
        return jsonify({"error": "Document not found"}), 404

    # Use cached analysis — do NOT regenerate Gemini analysis for report download
    analysis = analysis_to_dict(analysis_row) if analysis_row else {}

    # Generate brief — respects mode (offline = local brief only)
    try:
        from services.gemini_service import generate_legal_brief
        brief = generate_legal_brief(
            doc["extracted_text"] or "",
            analysis,
            api_key=get_active_gemini_key(),
            mode=mode,
            language=get_active_language()
        )
    except Exception as e:
        logger.warning(f"Brief generation for report failed: {e}")
        brief = {}

    report_filename = f"legal_brief_{doc_id[:8]}.pdf"
    output_path = str(REPORTS_FOLDER / report_filename)

    try:
        from services.pdf_service import generate_report_pdf
        generate_report_pdf(dict(doc), analysis, brief, output_path)
    except Exception as e:
        logger.error(f"PDF generation failed: {e}")
        return jsonify({"error": "Could not generate PDF report. Please try again."}), 500

    safe_name = doc["original_filename"].rsplit(".", 1)[0]
    return send_file(
        output_path,
        as_attachment=True,
        download_name=f"Legal_Analysis_{safe_name}.pdf",
        mimetype="application/pdf",
    )


# ---------------------------------------------------------------------------
# Error handlers
# ---------------------------------------------------------------------------

@app.errorhandler(404)
def not_found(e):
    if request.path.startswith("/api/"):
        return jsonify({"error": "Not found"}), 404
    return render_template("404.html"), 404


@app.errorhandler(413)
def too_large(e):
    return jsonify({"error": "File is too large. Maximum size is 20 MB."}), 413


@app.errorhandler(500)
def server_error(e):
    if request.path.startswith("/api/"):
        return jsonify({"error": "An internal error occurred. Please try again."}), 500
    return render_template("500.html"), 500


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    init_db()
    logger.info("Starting Legal AI Assistant...")
    app.run(debug=os.environ.get("FLASK_DEBUG", "True") == "True", host="127.0.0.1", port=5000)
