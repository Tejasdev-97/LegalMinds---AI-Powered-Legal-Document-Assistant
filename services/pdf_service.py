"""
pdf_service.py — Generate professional PDF reports using ReportLab.
Supports both single-document analysis reports and document comparison reports.
Uses ReportLab Flowables, custom NumberedCanvas for 'Page X of Y', and text wrapping in tables.
"""

import os
import json
import logging
from datetime import datetime
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import cm
from reportlab.lib import colors
from reportlab.platypus import (
    SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle,
    HRFlowable, KeepTogether,
)
from reportlab.lib.enums import TA_LEFT, TA_CENTER, TA_RIGHT
from reportlab.pdfgen import canvas

logger = logging.getLogger(__name__)


def _rl_escape(text) -> str:
    """
    Escape user/document-derived text before passing to ReportLab Paragraph.
    Legal documents may contain <, >, & which would be interpreted as XML markup.
    """
    if not text:
        return ""
    text = str(text)
    text = text.replace("&", "&amp;")
    text = text.replace("<", "&lt;")
    text = text.replace(">", "&gt;")
    return text

# Color palette
PRIMARY = colors.HexColor("#2D6A4F")
ACCENT = colors.HexColor("#E76F51")
GOLD = colors.HexColor("#F4A261")
BG_LIGHT = colors.HexColor("#FAF7F2")
TEXT_DARK = colors.HexColor("#1A1A1A")
TEXT_MUTED = colors.HexColor("#4A4A4A")
BORDER = colors.HexColor("#E8E0D5")
SUCCESS = colors.HexColor("#059669")
WARNING = colors.HexColor("#D97706")


class NumberedCanvas(canvas.Canvas):
    """Two-pass canvas to dynamically compute and print 'Page X of Y' on every page."""
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._saved_page_states = []

    def showPage(self):
        self._saved_page_states.append(dict(self.__dict__))
        self._startPage()

    def save(self):
        num_pages = len(self._saved_page_states)
        for state in self._saved_page_states:
            self.__dict__.update(state)
            self.draw_page_decorations(num_pages)
            super().showPage()
        super().save()

    def draw_page_decorations(self, page_count):
        self.saveState()
        self.setFont("Helvetica", 8)
        self.setFillColor(TEXT_MUTED)

        # Footer text & page numbers
        page_text = f"Page {self._pageNumber} of {page_count}"
        self.drawRightString(21.0 * cm - 2 * cm, 1 * cm, page_text)
        self.drawString(2 * cm, 1 * cm, "LegalMinds — AI Legal Document Assistant")

        # Footer divider line
        self.setStrokeColor(BORDER)
        self.setLineWidth(0.5)
        self.line(2 * cm, 1.3 * cm, 21.0 * cm - 2 * cm, 1.3 * cm)
        self.restoreState()


def _build_styles():
    """Build custom paragraph styles."""
    styles = getSampleStyleSheet()

    custom = {
        "Title": ParagraphStyle(
            "Title",
            parent=styles["Title"],
            fontSize=24,
            textColor=PRIMARY,
            spaceAfter=6,
            fontName="Helvetica-Bold",
        ),
        "Subtitle": ParagraphStyle(
            "Subtitle",
            parent=styles["Normal"],
            fontSize=12,
            textColor=TEXT_MUTED,
            spaceAfter=16,
            fontName="Helvetica",
        ),
        "SectionHeader": ParagraphStyle(
            "SectionHeader",
            parent=styles["Heading2"],
            fontSize=13,
            textColor=PRIMARY,
            spaceBefore=14,
            spaceAfter=8,
            fontName="Helvetica-Bold",
        ),
        "SubHeader": ParagraphStyle(
            "SubHeader",
            parent=styles["Normal"],
            fontSize=10,
            textColor=TEXT_DARK,
            spaceBefore=6,
            spaceAfter=4,
            fontName="Helvetica-Bold",
        ),
        "TableHeader": ParagraphStyle(
            "TableHeader",
            parent=styles["Normal"],
            fontSize=9,
            textColor=colors.white,
            fontName="Helvetica-Bold",
        ),
        "TableCell": ParagraphStyle(
            "TableCell",
            parent=styles["Normal"],
            fontSize=9,
            textColor=TEXT_DARK,
            leading=12,
            fontName="Helvetica",
        ),
        "Body": ParagraphStyle(
            "Body",
            parent=styles["Normal"],
            fontSize=10,
            textColor=TEXT_DARK,
            spaceAfter=6,
            leading=14,
            fontName="Helvetica",
        ),
        "Bullet": ParagraphStyle(
            "Bullet",
            parent=styles["Normal"],
            fontSize=10,
            textColor=TEXT_DARK,
            spaceAfter=4,
            leftIndent=14,
            bulletIndent=4,
            fontName="Helvetica",
        ),
        "Caption": ParagraphStyle(
            "Caption",
            parent=styles["Normal"],
            fontSize=8,
            textColor=TEXT_MUTED,
            spaceAfter=4,
            fontName="Helvetica-Oblique",
        ),
        "Disclaimer": ParagraphStyle(
            "Disclaimer",
            parent=styles["Normal"],
            fontSize=8,
            textColor=TEXT_MUTED,
            spaceAfter=4,
            fontName="Helvetica-Oblique",
            borderColor=BORDER,
            borderWidth=1,
            borderPad=8,
            backColor=colors.HexColor("#FFF8F0"),
        ),
    }
    return custom


def generate_report_pdf(document: dict, analysis: dict, brief: dict, output_path: str) -> str:
    """
    Generate a comprehensive PDF report for a legal document analysis.
    Returns the path to the generated PDF.
    """
    styles = _build_styles()
    story = []

    # ---- HEADER ----
    story.append(Paragraph(_rl_escape("LegalMinds"), styles["Title"]))
    story.append(Paragraph(_rl_escape("Document Analysis Report"), styles["Subtitle"]))
    story.append(HRFlowable(width="100%", thickness=2, color=PRIMARY, spaceAfter=14))

    # Report metadata
    doc_type = _rl_escape(analysis.get("document_type", document.get("document_type", "Legal Document")))
    filename = _rl_escape(document.get("original_filename", "Unknown"))
    generated_at = datetime.now().strftime("%B %d, %Y at %I:%M %p")

    meta_data = [
        [Paragraph(_rl_escape("Document:"), styles["SubHeader"]), Paragraph(filename, styles["TableCell"])],
        [Paragraph(_rl_escape("Type:"), styles["SubHeader"]), Paragraph(doc_type, styles["TableCell"])],
        [Paragraph(_rl_escape("Generated:"), styles["SubHeader"]), Paragraph(_rl_escape(generated_at), styles["TableCell"])],
    ]
    meta_table = Table(meta_data, colWidths=[4 * cm, 13 * cm])
    meta_table.setStyle(TableStyle([
        ("TOPPADDING", (0, 0), (-1, -1), 2),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 2),
    ]))
    story.append(meta_table)
    story.append(Spacer(1, 14))

    # ---- DISCLAIMER ----
    story.append(Paragraph(
        "⚠ DISCLAIMER: This report is generated by LegalMinds for informational purposes only. "
        "It does not constitute legal advice and does not replace consultation with a qualified legal professional. "
        "Always verify important information with a licensed attorney.",
        styles["Disclaimer"]
    ))
    story.append(Spacer(1, 16))

    # ---- EXECUTIVE SUMMARY ----
    story.append(Paragraph("Executive Summary", styles["SectionHeader"]))
    summary = brief.get("executive_summary") or analysis.get("summary", "No summary available.")
    story.append(Paragraph(_rl_escape(summary), styles["Body"]))

    # Key takeaways
    takeaways = analysis.get("key_takeaways", [])
    if takeaways:
        story.append(Spacer(1, 6))
        story.append(Paragraph("Key Takeaways", styles["SubHeader"]))
        for item in takeaways:
            story.append(Paragraph(f"\u2022 {_rl_escape(item)}", styles["Bullet"]))

    story.append(Spacer(1, 12))
    story.append(HRFlowable(width="100%", thickness=1, color=BORDER))

    # ---- PARTIES ----
    parties = analysis.get("parties", brief.get("parties", []))
    if parties:
        story.append(Paragraph("Parties Involved", styles["SectionHeader"]))
        for party in parties:
            story.append(Paragraph(f"\u2022 {_rl_escape(str(party))}", styles["Bullet"]))

    # ---- IMPORTANT CLAUSES ----
    clauses = analysis.get("important_clauses", [])
    if clauses:
        story.append(Paragraph("Important Clauses", styles["SectionHeader"]))
        for clause in clauses[:10]:
            name = _rl_escape(clause.get("name", "Unnamed Clause"))
            section = _rl_escape(clause.get("section", ""))
            page = clause.get("page", "")
            explanation = _rl_escape(clause.get("explanation", ""))
            ref = f" | {section}" if section else ""
            ref += f" | Page {page}" if page else ""

            story.append(Paragraph(f"{name}{ref}", styles["SubHeader"]))
            if explanation:
                story.append(Paragraph(explanation, styles["Body"]))
            story.append(Spacer(1, 4))

    # ---- POINTS TO REVIEW ----
    points = analysis.get("points_to_review", [])
    if points:
        story.append(HRFlowable(width="100%", thickness=1, color=BORDER))
        story.append(Paragraph("Points to Review", styles["SectionHeader"]))
        story.append(Paragraph(
            "The following items may deserve careful attention. Consider discussing them with a legal professional.",
            styles["Body"]
        ))
        story.append(Spacer(1, 6))

        for point in points:
            title = _rl_escape(point.get("title", "Review Item"))
            description = _rl_escape(point.get("description", ""))
            section = _rl_escape(point.get("section", ""))
            severity = point.get("severity", "medium")

            sev_color = ACCENT if severity == "high" else (GOLD if severity == "medium" else TEXT_MUTED)
            story.append(Paragraph(f"\u2691 {title}", ParagraphStyle(
                "PointTitle", parent=_build_styles()["SubHeader"], textColor=sev_color
            )))
            if section:
                story.append(Paragraph(f"Reference: {section}", styles["Caption"]))
            if description:
                story.append(Paragraph(description, styles["Body"]))
            story.append(Spacer(1, 4))

    # ---- OBLIGATIONS ----
    obligations = analysis.get("obligations", {})
    party_a = obligations.get("party_a", {})
    party_b = obligations.get("party_b", {})

    if party_a or party_b:
        story.append(HRFlowable(width="100%", thickness=1, color=BORDER))
        story.append(Paragraph("Obligations", styles["SectionHeader"]))

        if party_a and party_a.get("obligations"):
            story.append(Paragraph(_rl_escape(party_a.get("name", "First Party")), styles["SubHeader"]))
            for ob in party_a["obligations"]:
                story.append(Paragraph(f"\u2022 {_rl_escape(str(ob))}", styles["Bullet"]))

        if party_b and party_b.get("obligations"):
            story.append(Paragraph(_rl_escape(party_b.get("name", "Second Party")), styles["SubHeader"]))
            for ob in party_b["obligations"]:
                story.append(Paragraph(f"\u2022 {_rl_escape(str(ob))}", styles["Bullet"]))

    # ---- IMPORTANT DATES ----
    dates = analysis.get("important_dates", [])
    if dates:
        story.append(HRFlowable(width="100%", thickness=1, color=BORDER))
        story.append(Paragraph("Important Dates", styles["SectionHeader"]))

        date_table_data = [[
            Paragraph("Date / Period", styles["TableHeader"]),
            Paragraph("Label", styles["TableHeader"]),
            Paragraph("Context", styles["TableHeader"])
        ]]
        for d in dates:
            date_table_data.append([
                Paragraph(_rl_escape(d.get("date", "")), styles["TableCell"]),
                Paragraph(_rl_escape(d.get("label", "")), styles["TableCell"]),
                Paragraph(_rl_escape(d.get("context", "")), styles["TableCell"]),
            ])

        t = Table(date_table_data, colWidths=[4.5 * cm, 5.5 * cm, 7 * cm], repeatRows=1)
        t.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, 0), PRIMARY),
            ("GRID", (0, 0), (-1, -1), 0.5, BORDER),
            ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#F7F3EE")]),
            ("TOPPADDING", (0, 0), (-1, -1), 5),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
        ]))
        story.append(t)

    # ---- FINANCIAL TERMS ----
    financial = analysis.get("financial_terms", [])
    if financial:
        story.append(HRFlowable(width="100%", thickness=1, color=BORDER))
        story.append(Paragraph("Financial Terms", styles["SectionHeader"]))

        fin_table_data = [[
            Paragraph("Amount / Value", styles["TableHeader"]),
            Paragraph("Term", styles["TableHeader"]),
            Paragraph("Context", styles["TableHeader"])
        ]]
        for f in financial:
            fin_table_data.append([
                Paragraph(_rl_escape(f.get("amount", "")), styles["TableCell"]),
                Paragraph(_rl_escape(f.get("label", "")), styles["TableCell"]),
                Paragraph(_rl_escape(f.get("context", "")), styles["TableCell"]),
            ])

        t = Table(fin_table_data, colWidths=[4.5 * cm, 5.5 * cm, 7 * cm], repeatRows=1)
        t.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, 0), SUCCESS),
            ("GRID", (0, 0), (-1, -1), 0.5, BORDER),
            ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#F0FBF5")]),
            ("TOPPADDING", (0, 0), (-1, -1), 5),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
        ]))
        story.append(t)

    # ---- RECOMMENDED QUESTIONS ----
    questions = brief.get("recommended_questions", [])
    if questions:
        story.append(HRFlowable(width="100%", thickness=1, color=BORDER))
        story.append(Paragraph("Questions for Your Legal Professional", styles["SectionHeader"]))
        for i, q in enumerate(questions, 1):
            story.append(Paragraph(f"{i}. {_rl_escape(str(q))}", styles["Bullet"]))

    # Build PDF with canvasmaker for Page X of Y footer
    doc = SimpleDocTemplate(
        output_path,
        pagesize=A4,
        rightMargin=2 * cm,
        leftMargin=2 * cm,
        topMargin=2 * cm,
        bottomMargin=2 * cm,
    )
    doc.build(story, canvasmaker=NumberedCanvas)
    return output_path


def generate_comparison_pdf(comparison: dict, name_a: str = "Document A", name_b: str = "Document B", output_path: str = "comparison_report.pdf") -> str:
    """
    Generate an A4 Legal-style comparison report PDF.
    Flow:
    Summary -> Key Differences -> Factual/Topic Differences -> Document A-only Content -> Document B-only Content -> Processing Mode -> Disclaimer
    """
    styles = _build_styles()
    story = []

    # Header
    story.append(Paragraph(_rl_escape("LegalMinds"), styles["Title"]))
    story.append(Paragraph(_rl_escape("Document Comparison Report"), styles["Subtitle"]))
    story.append(HRFlowable(width="100%", thickness=2, color=PRIMARY, spaceAfter=14))

    # Metadata table
    generated_at = datetime.now().strftime("%B %d, %Y at %I:%M %p")
    meta_data = [
        [Paragraph(_rl_escape("Document A:"), styles["SubHeader"]), Paragraph(_rl_escape(name_a), styles["TableCell"])],
        [Paragraph(_rl_escape("Document B:"), styles["SubHeader"]), Paragraph(_rl_escape(name_b), styles["TableCell"])],
        [Paragraph(_rl_escape("Generated:"), styles["SubHeader"]), Paragraph(_rl_escape(generated_at), styles["TableCell"])],
        [Paragraph(_rl_escape("Processing Mode:"), styles["SubHeader"]), Paragraph(_rl_escape(comparison.get("processing_badge", "Offline Comparison")), styles["TableCell"])],
    ]
    meta_table = Table(meta_data, colWidths=[4 * cm, 13 * cm])
    meta_table.setStyle(TableStyle([
        ("TOPPADDING", (0, 0), (-1, -1), 2),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 2),
    ]))
    story.append(meta_table)
    story.append(Spacer(1, 12))

    # Disclaimer
    story.append(Paragraph(
        "⚠ DISCLAIMER: This comparison report is generated by LegalMinds for informational purposes only. "
        "Textual similarity and diffs are non-binding technical metrics, not legal advice.",
        styles["Disclaimer"]
    ))
    story.append(Spacer(1, 14))

    # 1. Summary
    story.append(Paragraph("1. Summary of Comparison", styles["SectionHeader"]))
    summary_text = comparison.get("summary", "Comparison completed.")
    sim_pct = comparison.get("similarity_pct")
    if sim_pct is not None:
        summary_text += f" (Textual similarity: {sim_pct}% — text match metric)."
    story.append(Paragraph(_rl_escape(summary_text), styles["Body"]))
    story.append(Spacer(1, 10))

    # 2. Key Differences / Factual Differences Table
    diffs = comparison.get("differences", [])
    if diffs:
        story.append(Paragraph("2. Key & Factual Differences", styles["SectionHeader"]))
        table_data = [[
            Paragraph("Category", styles["TableHeader"]),
            Paragraph(_rl_escape(name_a), styles["TableHeader"]),
            Paragraph(_rl_escape(name_b), styles["TableHeader"]),
            Paragraph("Type / Note", styles["TableHeader"]),
        ]]
        for diff in diffs[:12]:
            cat = _rl_escape(diff.get("category", "Difference"))
            doc_a_val = _rl_escape(diff.get("document_a", "—"))
            doc_b_val = _rl_escape(diff.get("document_b", "—"))
            note = _rl_escape(diff.get("note", "Factual Diff"))
            table_data.append([
                Paragraph(cat, styles["TableCell"]),
                Paragraph(doc_a_val, styles["TableCell"]),
                Paragraph(doc_b_val, styles["TableCell"]),
                Paragraph(note, styles["TableCell"]),
            ])
        t = Table(table_data, colWidths=[3.5 * cm, 5 * cm, 5 * cm, 3.5 * cm], repeatRows=1)
        t.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, 0), PRIMARY),
            ("GRID", (0, 0), (-1, -1), 0.5, BORDER),
            ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#F9F8F6")]),
            ("TOPPADDING", (0, 0), (-1, -1), 4),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
        ]))
        story.append(t)
        story.append(Spacer(1, 12))

    # 3. Document A-only Content
    only_a = comparison.get("removed_in_b", [])
    if only_a:
        story.append(Paragraph(f"3. Present Only in {name_a}", styles["SectionHeader"]))
        for item in only_a[:8]:
            story.append(Paragraph(f"\u2022 {_rl_escape(str(item))}", styles["Bullet"]))
        story.append(Spacer(1, 10))

    # 4. Document B-only Content
    only_b = comparison.get("added_in_b", [])
    if only_b:
        story.append(Paragraph(f"4. Present Only in {name_b}", styles["SectionHeader"]))
        for item in only_b[:8]:
            story.append(Paragraph(f"\u2022 {_rl_escape(str(item))}", styles["Bullet"]))
        story.append(Spacer(1, 10))

    # 5. Processing Mode Details
    story.append(Paragraph("5. Processing Mode & Verification", styles["SectionHeader"]))
    mode_str = comparison.get("mode", "offline")
    badge = comparison.get("processing_badge", "Offline Document Comparison")
    story.append(Paragraph(f"Mode: {_rl_escape(mode_str.upper())} ({_rl_escape(badge)})", styles["Body"]))

    doc = SimpleDocTemplate(
        output_path,
        pagesize=A4,
        rightMargin=2 * cm,
        leftMargin=2 * cm,
        topMargin=2 * cm,
        bottomMargin=2 * cm,
    )
    doc.build(story, canvasmaker=NumberedCanvas)
    return output_path
