"""Generate PDF report from collected data and AI analysis."""
import logging
import os
from datetime import datetime
from pathlib import Path

from jinja2 import Environment, FileSystemLoader

logger = logging.getLogger(__name__)

TEMPLATES_DIR = Path(__file__).parent.parent / "templates"


def render_html(data: dict, ai: dict) -> str:
    env = Environment(loader=FileSystemLoader(str(TEMPLATES_DIR)))
    template = env.get_template("report.html")

    report_date_fmt = datetime.strptime(data["date"], "%Y%m%d").strftime("%Y년 %m월 %d일")
    publish_date_fmt = datetime.today().strftime("%Y년 %m월 %d일")

    return template.render(
        report_date=report_date_fmt,
        publish_date=publish_date_fmt,
        market=data["market"],
        fx_gold=data["fx_gold"],
        stocks=data["stocks"],
        market_analysis=ai["market_analysis"],
        shinsegae_analysis=ai["shinsegae_analysis"],
        sector_issues=ai["sector_issues"],
        references=ai["references"],
    )


def generate_pdf(html: str, output_path: str) -> str:
    try:
        from weasyprint import HTML
        HTML(string=html).write_pdf(output_path)
        logger.info(f"PDF saved to {output_path}")
        return output_path
    except ImportError:
        logger.error("weasyprint not installed")
        raise
    except Exception as e:
        logger.error(f"PDF generation failed: {e}")
        raise


def build_report(data: dict, ai: dict, output_dir: str = "/tmp") -> str:
    html = render_html(data, ai)
    filename = f"shinsegae_report_{data['date']}.pdf"
    output_path = os.path.join(output_dir, filename)
    return generate_pdf(html, output_path)
