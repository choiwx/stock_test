"""Orchestrator: collect data → AI analysis → PDF → email."""
import logging
import os
import sys
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)

sys.path.insert(0, str(Path(__file__).parent))

from data_collector import collect_all
from ai_analyzer import market_summary_analysis, shinsegae_analysis, retail_sector_issues
from report_generator import build_report
from email_sender import send_report


def run(date_str: str = None) -> None:
    logger.info("=== Starting daily report generation ===")

    # 1. Collect market data
    logger.info("Step 1: Collecting market data...")
    data = collect_all(date_str)
    logger.info(f"Data collected for date: {data['date']}")

    # 2. Generate AI analysis
    logger.info("Step 2: Generating AI analysis...")
    market_analysis = market_summary_analysis(data)
    shin_analysis = shinsegae_analysis(data)
    sector_text, references = retail_sector_issues(report_date=data["date"])

    ai = {
        "market_analysis": market_analysis,
        "shinsegae_analysis": shin_analysis,
        "sector_issues": sector_text,
        "references": references,
    }

    # 3. Generate PDF
    logger.info("Step 3: Generating PDF report...")
    pdf_path = build_report(data, ai, output_dir="/tmp")
    logger.info(f"PDF generated: {pdf_path}")

    # 4. Send email
    logger.info("Step 4: Sending email...")
    send_report(pdf_path, data["date"])

    logger.info("=== Report generation complete ===")


if __name__ == "__main__":
    date_arg = sys.argv[1] if len(sys.argv) > 1 else None
    run(date_arg)
