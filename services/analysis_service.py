"""
analysis_service.py — Orchestrates document analysis pipeline.
Coordinates between document_parser, gemini_service, and the database.
"""

import logging
import json

logger = logging.getLogger(__name__)


def run_full_analysis(document_text: str, document_type: str, db_conn) -> dict:
    """
    Run a full document analysis and persist the results.
    Returns the analysis dict.
    """
    from services import gemini_service

    analysis = gemini_service.analyze_document(document_text, document_type)
    return analysis


def get_analysis_stats(analysis: dict) -> dict:
    """Extract counts for dashboard statistics cards."""
    return {
        "clauses_count": len(analysis.get("important_clauses", [])),
        "points_count": len(analysis.get("points_to_review", [])),
        "dates_count": len(analysis.get("important_dates", [])),
        "financial_count": len(analysis.get("financial_terms", [])),
    }
