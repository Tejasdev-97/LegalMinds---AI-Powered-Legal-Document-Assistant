"""
pdf_service.py — Generate professional PDF reports using ReportLab.
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
            spaceAfter=20,
            fontName="Helvetica",
        ),
        "SectionHeader": ParagraphStyle(
            "SectionHeader",
            parent=styles["Heading2"],
            fontSize=14,
            textColor=PRIMARY,
            spaceBefore=16,
            spaceAfter=8,
            fontName="Helvetica-Bold",
            borderPad=4,
        ),
        "SubHeader": ParagraphStyle(
            "SubHeader",
            parent=styles["Normal"],
            fontSize=11,
            textColor=TEXT_DARK,
            spaceBefore=8,
            spaceAfter=4,
            fontName="Helvetica-Bold",
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
            leftIndent=16,
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
        "Highlight": ParagraphStyle(
            "Highlight",
            parent=styles["Normal"],
            fontSize=10,
            textColor=ACCENT,
            fontName="Helvetica-Bold",
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
    story.append(HRFlowable(width="100%", thickness=2, color=PRIMARY, spaceAfter=16))

    # Report metadata
    doc_type = _rl_escape(analysis.get("document_type", document.get("document_type", "Legal Document")))
    filename = _rl_escape(document.get("original_filename", "Unknown"))
    generated_at = datetime.now().strftime("%B %d, %Y at %I:%M %p")

    meta_data = [
        ["Document:", filename],
        ["Type:", doc_type],
        ["Generated:", generated_at],
    ]
    meta_table = Table(meta_data, colWidths=[4 * cm, 13 * cm])
    meta_table.setStyle(TableStyle([
        ("FONTNAME", (0, 0), (0, -1), "Helvetica-Bold"),
        ("FONTSIZE", (0, 0), (-1, -1), 10),
        ("TEXTCOLOR", (0, 0), (0, -1), TEXT_MUTED),
        ("TEXTCOLOR", (1, 0), (1, -1), TEXT_DARK),
        ("TOPPADDING", (0, 0), (-1, -1), 3),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
    ]))
    story.append(meta_table)
    story.append(Spacer(1, 16))

    # ---- DISCLAIMER ----
    story.append(Paragraph(
        "⚠ DISCLAIMER: This report is generated by an AI assistant for informational purposes only. "
        "It does not constitute legal advice and does not replace consultation with a qualified legal professional. "
        "Always verify important information with a licensed attorney.",
        styles["Disclaimer"]
    ))
    story.append(Spacer(1, 20))

    # ---- EXECUTIVE SUMMARY ----
    story.append(Paragraph("Executive Summary", styles["SectionHeader"]))
    summary = brief.get("executive_summary") or analysis.get("summary", "No summary available.")
    story.append(Paragraph(_rl_escape(summary), styles["Body"]))

    # Key takeaways
    takeaways = analysis.get("key_takeaways", [])
    if takeaways:
        story.append(Spacer(1, 8))
        story.append(Paragraph("Key Takeaways", styles["SubHeader"]))
        for item in takeaways:
            story.append(Paragraph(f"\u2022 {_rl_escape(item)}", styles["Bullet"]))

    story.append(Spacer(1, 16))
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
        story.append(Spacer(1, 8))

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

        date_table_data = [["Date / Period", "Label", "Context"]]
        for d in dates:
            date_table_data.append([
                d.get("date", ""),
                d.get("label", ""),
                d.get("context", ""),
            ])

        t = Table(date_table_data, colWidths=[5 * cm, 6 * cm, 6 * cm])
        t.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, 0), PRIMARY),
            ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
            ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
            ("FONTSIZE", (0, 0), (-1, -1), 9),
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

        fin_table_data = [["Amount / Value", "Term", "Context"]]
        for f in financial:
            fin_table_data.append([
                f.get("amount", ""),
                f.get("label", ""),
                f.get("context", ""),
            ])

        t = Table(fin_table_data, colWidths=[5 * cm, 6 * cm, 6 * cm])
        t.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, 0), SUCCESS),
            ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
            ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
            ("FONTSIZE", (0, 0), (-1, -1), 9),
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

    # ---- FOOTER ----
    story.append(Spacer(1, 24))
    story.append(HRFlowable(width="100%", thickness=1, color=BORDER))
    story.append(Spacer(1, 8))
    story.append(Paragraph(
        f"Generated by LegalMinds • {generated_at} • For informational purposes only",
        ParagraphStyle("Footer", parent=_build_styles()["Caption"], alignment=TA_CENTER)
    ))

    # Build PDF
    doc = SimpleDocTemplate(
        output_path,
        pagesize=A4,
        rightMargin=2 * cm,
        leftMargin=2 * cm,
        topMargin=2 * cm,
        bottomMargin=2 * cm,
    )
    doc.build(story)
    return output_path
