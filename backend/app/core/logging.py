import logging
import sys


def configure_logging(env: str) -> None:
    level = logging.DEBUG if env == "development" else logging.INFO
    logging.basicConfig(
        level=level,
        stream=sys.stdout,
        format="%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
    )
    # yt-dlp is noisy at DEBUG; keep it at INFO regardless of app level
    logging.getLogger("yt_dlp").setLevel(logging.WARNING)
