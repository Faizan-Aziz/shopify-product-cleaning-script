"""
Progress and execution-log state management.

Tracks how many products have been processed across runs via a small
JSON file, and appends structured run summaries to a human-readable
log file.
"""

from __future__ import annotations

import json
import logging
import os
from datetime import datetime

logger = logging.getLogger(__name__)


def load_progress(
    progress_file: str,
    default_batch_size: int = 1,
    default_processed_count: int = 0,
) -> tuple[int, int]:
    """
    Load ``(batch_size, processed_count)`` from *progress_file*.

    Returns the defaults when the file does not exist or is corrupt.
    """
    if os.path.exists(progress_file):
        try:
            with open(progress_file, "r", encoding="utf-8") as fh:
                data = json.load(fh)
                return (
                    data.get("batch_size", default_batch_size),
                    data.get("processed_count", default_processed_count),
                )
        except Exception as exc:
            logger.warning(
                "Error reading %s, using defaults: %s", progress_file, exc
            )

    return default_batch_size, default_processed_count


def save_progress(
    progress_file: str,
    batch_size: int,
    processed_count: int,
) -> None:
    """Overwrite *progress_file* with the latest state."""
    state = {"batch_size": batch_size, "processed_count": processed_count}
    with open(progress_file, "w", encoding="utf-8") as fh:
        json.dump(state, fh, indent=4)
    logger.info(
        "Progress saved → %s (batch=%d, processed=%d)",
        progress_file,
        batch_size,
        processed_count,
    )


def append_run_log(
    log_file: str,
    processed_items: list[dict],
    total_processed_count: int,
) -> None:
    """
    Append a detailed, timestamped execution summary to *log_file*,
    separated into *Successful* and *Failed* sections.
    """
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    successes = [
        i for i in processed_items if i.get("status") in ("SUCCESS", "DRY-RUN")
    ]
    failures = [i for i in processed_items if i.get("status") == "FAILED"]

    lines: list[str] = [
        "=" * 70,
        f"EXECUTION LOG - {timestamp}",
        "=" * 70,
        f"SUCCESSFUL UPDATES ({len(successes)}):",
    ]

    if successes:
        for item in successes:
            tag = f"[{item['status']}]"
            meta = (
                f" | Metafields Set: {item.get('metafields_count', 0)}"
                if "metafields_count" in item
                else ""
            )
            lines.append(
                f"  ✓ {tag} ID: {item['id']} | Title: {item['title']}{meta}"
            )
    else:
        lines.append("  None")

    lines.extend(
        ["-" * 70, f"FAILED UPDATES ({len(failures)}):"]
    )

    if failures:
        for item in failures:
            lines.append(
                f"  ✗ [FAILED] ID: {item['id']} | Title: {item['title']}"
            )
            lines.append(f"    Reason: {item.get('error', 'unknown')}")
    else:
        lines.append("  None")

    lines.extend(
        [
            "-" * 70,
            f"TOTAL PROCESSED PRODUCTS TO DATE: {total_processed_count}",
            "=" * 70 + "\n\n",
        ]
    )

    with open(log_file, "a", encoding="utf-8") as fh:
        fh.write("\n".join(lines))

    logger.info("Run summary appended to %s", log_file)
