from datetime import datetime
from pathlib import Path

from app.core.logging import get_logger

logger = get_logger(__name__)


def save_html_file(content: str, output_dir: str = "output") -> str:
    """Save html content to output/test_plan_<timestamp>.html and return path."""
    out_dir = Path(output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    file_path = out_dir / f"test_plan_{timestamp}.html"
    file_path.write_text(content, encoding="utf-8")
    logger.info("Html file saved to %s", file_path)
    return str(file_path.resolve())
