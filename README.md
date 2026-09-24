# LegalMinds — AI-Powered Legal Document Intelligence

![Python Version](https://img.shields.io/badge/Python-3.9%2B-blue.svg)
![Framework](https://img.shields.io/badge/Framework-Flask%203.0-green.svg)
![AI Model](https://img.shields.io/badge/AI%20SDK-Google%20Gemini%203.x-orange.svg)
![License](https://img.shields.io/badge/License-MIT-purple.svg)

**LegalMinds** is a resilient, accessible, and privacy-conscious web application designed to help ordinary individuals, business owners, and legal professionals understand, analyze, compare, and navigate complex legal documents without getting lost in legal jargon.

---

## 📑 Table of Contents

- [Overview & Problem Statement](#-overview--problem-statement)
- [Key Features](#-key-features)
- [Tech Stack](#-tech-stack)
- [System Architecture & Workflow](#-system-architecture--workflow)
- [Approach & Engineering Logic](#-approach--engineering-logic)
- [Directory Structure](#-directory-structure)
- [Installation & Setup](#-installation--setup)
- [Usage Guide](#-usage-guide)
- [Security & Privacy](#-security--privacy)
- [Legal Disclaimer](#-legal-disclaimer)

---

## 🎯 Overview & Problem Statement

### The Problem
Contracts, lease agreements, non-disclosure agreements (NDAs), and employment offers are filled with dense legalese, hidden penalties, ambiguous notice periods, and restrictive covenants. Non-lawyers struggle to:
- Identify high-risk clauses or unilateral modification rights.
- Keep track of financial commitments and strict deadlines.
- Prepare meaningful questions prior to expensive attorney consultations.
- Understand documents in their native regional language.

### The Solution
**LegalMinds** serves as an intelligent legal co-pilot:
1. **Simplifies Legalese**: Translates dense legal text into plain, everyday language.
2. **Flags Critical Items**: Automatically highlights high-risk "Points to Review", financial commitments, and key dates.
3. **Grounded Q&A**: Answers document questions based strictly on textual evidence, avoiding hallucinations.
4. **Factual Comparison**: Compares two versions of an agreement side-by-side using local Python line diffs and Gemini AI interpretation.
5. **Multilingual Support**: Supports 6 major languages (**English, Hindi, Kannada, Marathi, Tamil, Telugu**) across both the UI and AI-generated outputs.
6. **Hands-Free Speech Input**: Enables voice dictation via the browser's native Web Speech API without requiring third-party API keys.
7. **Resilient 3-Mode Architecture**: Operates in **Auto (Smart)**, **Gemini AI**, or **Offline Mode** (guaranteeing **ZERO Gemini API calls**).

---

## 🌟 Key Features

| Feature | Description |
| :--- | :--- |
| **📄 Automated Document Analysis** | Parses PDF, DOCX, and TXT files. Generates executive summaries, party identification, and key takeaways. |
| **⚖️ Clause Breakdown** | Extracts and explains key legal clauses (Termination, Non-Compete, Confidentiality, Governing Law, IP Rights). |
| **🚩 Points to Review** | Detects potential risk areas (penalties, unilateral changes, auto-renewals, broad indemnities). |
| **📅 Obligations & Financial Tracking** | Groups obligations by party and categorizes financial terms (salary, deposits, fees) and dates (notice periods, deadlines). |
| **💬 Grounded Q&A Assistant** | Interactive Q&A engine with session-scoped caching. Features a **↻ Get Fresh Answer** button to bypass cache. |
| **🎤 Voice Speech-to-Text** | Dictate questions using browser-native Web Speech API (`SpeechRecognition`) with zero API key dependencies. |
| **🌐 Multilingual AI & UI** | Instant UI localization and Gemini AI response generation in **English, Hindi, Kannada, Marathi, Tamil, and Telugu**. |
| **📊 Contract Comparison** | Side-by-side agreement comparison combining factual line diffs (`SequenceMatcher`) and Gemini AI reasoning. |
| **💼 Lawyer Prep & Brief PDF Export** | Generates consultation checklists and downloads formatted, publication-ready PDF reports via ReportLab. |
| **🌙 Pure-Black Dark Mode** | Built-in high-contrast theme switcher (`#0A0A0A` pure dark black palette) with `localStorage` persistence. |

---

## 🛠️ Tech Stack

### Backend & Core Logic
- **Framework**: [Flask 3.0+](https://flask.palletsprojects.com/) (Python)
- **Generative AI SDK**: [`google-genai`](https://pypi.org/project/google-genai/) (Google Gemini 3.x Flash-Lite APIs)
- **Document Parsers**:
  - `PyMuPDF` (`fitz`) — High-precision PDF text and page-marker extraction.
  - `python-docx` — Microsoft Word `.docx` document parsing.
  - Built-in Plain Text (`.txt`) reader.
- **PDF Report Generation**: `reportlab` — Dynamic, styled legal analysis report generation.
- **Database**: SQLite3 — Zero-configuration local storage for documents, analysis cache, chat history, and comparisons.
- **Environment Management**: `python-dotenv`

### Frontend & UI Design
- **Core**: Vanilla HTML5, Vanilla CSS3 (Custom Design System with CSS Variables).
- **CSS Framework**: Bootstrap 5.3 (Grid & Utilities).
- **Icons**: Bootstrap Icons (`bi-icon`).
- **Typography**: Google Fonts (*DM Serif Display*, *Inter*, *JetBrains Mono*).
- **Client Logic**: Vanilla JavaScript (ES6+), Web Speech API (`SpeechRecognition`), `localStorage`.
- **Localization**: Local JSON Translation Resources (`translations/*.json`) & DOM binder (`translations.js`).

---

## 🏗️ System Architecture & Workflow

```
                                 USER REQUEST
                                      │
                            REQUEST CLASSIFICATION
                                      │
            ┌─────────────────────────┴─────────────────────────┐
            ▼                                                   ▼
 Deterministic Task?                               Requires Interpretation?
 (Text Extract, Local Diff, Search)                (Summarization, Q&A, Brief)
            │                                                   │
            ▼                                                   ▼
     LOCAL PROCESSING                                  OPERATING MODE CHECK
  (Python Text Parsers)                                         │
                                          ┌─────────────────────┼─────────────────────┐
                                          ▼                     ▼                     ▼
                                      Auto Mode           Gemini AI Mode         Offline Mode
                                          │                     │                     │
                                          ▼                     ▼                     ▼
                                     Try Gemini             Try Gemini            STRICT ZERO
                                          │                     │                 GEMINI CALLS
                                    ┌─────┴─────┐         ┌─────┴─────┐               │
                                 Success     Error     Success     Error              │
                                    │           │         │           │               │
                                    ▼           ▼         ▼           ▼               ▼
                                 Gemini      Offline   Gemini     Offline       Offline Engine
                                 Output      Fallback  Output     Badge Msg
```

### End-to-End Application Flow
1. **Upload & Parse**: User uploads a PDF, DOCX, or TXT document (up to 20 MB). `document_parser.py` extracts raw text and injects page-location markers (`[Page N]`).
2. **Classification & Mode Check**: Document type is identified via rule-based heuristics or Gemini. Active mode (`auto`, `gemini`, or `offline`) determines routing.
3. **Analysis Engine**:
   - *Online/Auto*: Gemini analyzes the document, returning structured JSON for summary, clauses, dates, amounts, and points to review.
   - *Offline*: Rule-based extraction engine extracts factual sentences without external network requests.
4. **Multilingual Processing**: If the active language is non-English, `translations.js` updates static UI elements and Gemini receives prompt rules to output AI text in the selected target language.
5. **Report & Export**: ReportLab compiles document analysis into a clean PDF download.

---

## 🧠 Approach & Engineering Logic

### 1. Zero-Fabrication Local Q&A Engine
To prevent AI hallucinations when Gemini is unavailable or operating in Offline Mode:
- Text is split into paragraph blocks.
- Paragraphs are scored using query token overlap, phrase matching bonuses, and heading proximity.
- A confidence threshold is enforced: if top score < 2, the app responds explicitly with *"I couldn't find this information in the uploaded document."*

### 2. Sequential Model Registry & Automatic Recovery
Gemini API quota limits (`429 Resource Exhausted`) are handled gracefully:
- Models are ordered sequentially:
  1. `gemini-3.5-flash-lite` (Primary)
  2. `gemini-3.1-flash-lite` (Fallback 1)
  3. `gemini-3.8-flash` (Fallback 2)
  4. `gemini-3.7-flash` (Fallback 3)
  5. `gemini-3.6-flash` (Fallback 4)
- Cooldown timestamps are recorded per model during rate-limiting.
- The system automatically returns to the primary model as soon as its cooldown period expires.

### 3. Multilingual Prompt Injection
When a user selects a language (e.g., Marathi or Hindi):
- Backend helper `get_active_language()` detects preference.
- Gemini prompt builder injects:
  > *"CRITICAL LANGUAGE REQUIREMENT: The user's selected interface language is Marathi (mr). You MUST generate ALL your natural language response text in Marathi. Keep JSON keys in English, but write ALL string values strictly in Marathi."*

### 4. Browser-Native Speech-to-Text Fallback
Instead of requiring paid third-party speech API keys:
- The UI initializes `window.SpeechRecognition` or `window.webkitSpeechRecognition`.
- Dictation fills text directly into input fields with real-time interim recognition.
- Displays friendly toast alerts if browser speech capability is unsupported.

---

## 📁 Directory Structure

```text
LegalMinds/
├── app.py                      # Main Flask application & API routes
├── requirements.txt            # Python dependencies
├── .env.example                # Example environment variables template
├── .gitignore                  # Git ignore definitions (protects .env, DB, uploads)
├── README.md                   # Project documentation
│
├── database/                   # Relational database directory
│   ├── .gitkeep                # Directory placeholder
│   └── legal_ai.db             # SQLite database (generated at runtime)
│
├── services/                   # Modular service layer
│   ├── __init__.py
│   ├── gemini_service.py       # Gemini API client, model fallback & prompt logic
│   ├── document_parser.py      # PDF, DOCX, and TXT parsing utilities
│   ├── pdf_service.py          # ReportLab PDF report generator
│   ├── speech_service.py       # Speech API helpers
│   ├── translation_service.py  # Local & API translation utilities
│   └── analysis_service.py     # Document analysis pipeline
│
├── static/                     # Static frontend assets
│   ├── css/
│   │   └── style.css           # Main CSS stylesheet (Light & Pure-Black Dark Themes)
│   └── js/
│       ├── app.js              # Global theme, sidebar, modal, & language handlers
│       ├── translations.js     # Local UI translation dictionary & DOM binder
│       ├── dashboard.js        # Dashboard statistics & document loader
│       ├── document.js         # Document analysis, tabs, Q&A, and speech dictation
│       ├── compare.js          # Document comparison UI & upload logic
│       └── settings.js         # API key & mode settings handlers
│
├── templates/                  # Jinja2 HTML templates
│   ├── base.html               # Base layout with sidebar, topbar, & theme toggle
│   ├── index.html              # Landing page
│   ├── dashboard.html          # Main user dashboard
│   ├── upload.html             # Document upload interface
│   ├── document.html           # Document viewer, tabs, Q&A & lawyer prep
│   ├── compare.html            # Contract comparison interface
│   ├── saved.html              # Saved documents table
│   ├── settings.html           # Configuration page
│   ├── help.html               # User guide & FAQ
│   ├── 404.html                # Not Found page
│   └── 500.html                # Server Error page
│
├── translations/               # Local UI translation JSON resources
│   ├── en.json
│   ├── hi.json
│   ├── kn.json
│   ├── mr.json
│   ├── ta.json
│   └── te.json
│
├── uploads/                    # Directory for user-uploaded documents (gitignored)
│   └── .gitkeep
└── generated_reports/          # Directory for generated PDF reports (gitignored)
    └── .gitkeep
```

---

## ⚡ Installation & Setup

### Prerequisites
- **Python 3.9+** installed on your system.
- **Git** installed.

### 1. Clone the Repository
```bash
git clone https://github.com/Tejasdev-97/LegalMinds---AI-Powered-Legal-Document-Assistant.git
cd LegalMinds---AI-Powered-Legal-Document-Assistant
```

### 2. Create Virtual Environment
```bash
# Windows
python -m venv venv
venv\Scripts\activate

# macOS / Linux
python3 -m venv venv
source venv/bin/activate
```

### 3. Install Dependencies
```bash
pip install -r requirements.txt
```

### 4. Configure Environment Variables
Copy `.env.example` to `.env`:
```bash
cp .env.example .env
```
Edit `.env` to include your configuration:
```env
FLASK_SECRET_KEY=dev-secret-key-change-in-prod
GEMINI_API_KEY=your_gemini_api_key_here
GEMINI_MODEL=gemini-3.5-flash-lite
MAX_UPLOAD_SIZE_MB=20
FLASK_DEBUG=True
```
*(Note: If no `GEMINI_API_KEY` is provided, LegalMinds automatically runs seamlessly in **Offline Mode**).*

### 5. Run Application
```bash
python app.py
```
Open your browser and navigate to:
```text
http://127.0.0.1:5000
```

---

## 📖 Usage Guide

1. **Upload Document**: Click **Upload Document** and choose a PDF, DOCX, or TXT file.
2. **Run Analysis**: View the extracted text and click **Run AI Analysis** to generate summaries, clause breakdowns, dates, financial terms, and review points.
3. **Ask Questions**: Use the **Ask Questions** tab to query your document. Click the microphone icon to use speech dictation.
4. **Switch Language**: Select your preferred language (e.g., *हिन्दी* or *मराठी*) from the topbar dropdown to translate both the UI and AI answers.
5. **Compare Contracts**: Navigate to **Compare Documents** to upload or select two agreements and view a side-by-side factual diff.
6. **Download PDF Report**: Click **Download PDF** on any document page to save a styled PDF report.

---

## 🔒 Security & Privacy

- **Protected Secret Files**: The `.gitignore` configuration ensures `.env`, local database files (`*.db`), uploaded user documents (`uploads/`), and generated PDF reports (`generated_reports/`) are strictly kept out of version control.
- **Client Key Isolation**: API keys entered in the session UI are stored securely in browser session memory and never rendered in client-side HTML or logged.
- **Zero Network Exposure in Offline Mode**: Setting mode to `Offline` guarantees **ZERO network calls** to external AI servers.

---

## ⚖️ Legal Disclaimer

> **For informational use only. Not legal advice. Consult a qualified legal professional for specific advice.**
>
> LegalMinds is an AI-assisted document navigation and educational analysis tool. It does not provide formal legal representation, legal opinions, or legal advice, nor does it create an attorney-client relationship. Always verify findings with a licensed legal professional prior to signing agreements or making legal decisions.
