"""
Shopify Product Catalog Enrichment Pipeline
============================================

Async orchestrator that:

1. Loads configuration & validates environment variables.
2. Fetches a batch of products from Shopify (paginated, resumable).
3. Parses each product's HTML description into structured fields.
4. Enriches data via an OpenAI LLM call (Structured Outputs).
5. Merges parser + LLM results with strict priority resolution.
6. Writes back the updated product, metafields, and SEO data to Shopify.
7. Logs results and persists progress for the next run.

Usage::

    python main.py                # process next batch
    DRY_RUN=true python main.py   # preview without writing to Shopify
"""

from __future__ import annotations

import asyncio
import logging
from functools import partial

from config import settings
from services.shopify_client import (
    build_description_html,
    fetch_products_after_skipping,
    update_product_details,
    update_product_metafields,
)
from services.llm_service import enhance_with_llm
from services.text_parser import build_metafields, normalize_product
from utils.logger import setup_logging
from utils.state_manager import append_run_log, load_progress, save_progress

logger = logging.getLogger(__name__)


# ── Single-product processor ────────────────────────────────────────────

async def process_product(product: dict, loop: asyncio.AbstractEventLoop) -> dict:
    """
    Run the full enrichment pipeline for a single product.

    Heavy I/O calls (Shopify writes, OpenAI) are offloaded to the
    default thread-pool executor so the event loop stays responsive.
    """
    product_id = product["id"]
    title = product["title"]
    existing_tags = product.get("tags", [])

    # 1. Base extraction (CPU-bound, fast)
    normalized = normalize_product(product)

    # 2. LLM enrichment (I/O-bound)
    normalized = await loop.run_in_executor(
        None,
        partial(
            enhance_with_llm,
            normalized,
            title,
            product.get("descriptionHtml", ""),
        ),
    )

    # 3. Final metafields (strict priority merge)
    final_metafields = build_metafields(
        normalized["description"],
        normalized["metafields"],
        normalized.get("llm_metafields", {}),
    )
    normalized["metafields"] = final_metafields

    # 4. HTML description from finalised data
    description_html = build_description_html(normalized["description"])
    seo_info = normalized.get("seo", {})

    # ── Console summary ──────────────────────────────────────────────
    logger.info("=" * 90)
    logger.info("PRODUCT TITLE : %s", seo_info.get("title") or title)
    logger.info("PRODUCT ID    : %s", product_id)
    logger.info("META DESC     : %s", seo_info.get("meta_description"))
    logger.info(
        "PRODUCT TYPE  : %s",
        seo_info.get("product_type")
        or normalized["description"].get("Product Type"),
    )
    logger.info("TAGS          : %s", seo_info.get("tags"))

    for key, value in normalized["description"].items():
        logger.debug("  %-24s: %s", key, value)
    for key, value in normalized["metafields"].items():
        logger.debug("  %-32s: %s", key, value)

    # ── Dry-run guard ────────────────────────────────────────────────
    if settings.dry_run:
        logger.info("DRY RUN – Skipping Shopify writes for %s", title)
        return {
            "id": product_id,
            "title": title,
            "status": "DRY-RUN",
        }

    # ── Write to Shopify ─────────────────────────────────────────────
    try:
        updated = await loop.run_in_executor(
            None,
            partial(
                update_product_details,
                product_id=product_id,
                description_html=description_html,
                seo_data=seo_info,
                fallback_title=title,
                fallback_type=normalized["description"].get("Product Type", ""),
                existing_tags=existing_tags,
            ),
        )
        metafields_result = await loop.run_in_executor(
            None,
            partial(update_product_metafields, product_id, normalized["metafields"]),
        )
        logger.info(
            "✓ Updated: %s  (metafields: %d)",
            updated["title"],
            len(metafields_result),
        )
        return {
            "id": product_id,
            "title": title,
            "status": "SUCCESS",
            "metafields_count": len(metafields_result),
        }

    except Exception as exc:
        logger.error("✗ FAILED: %s – %s", title, exc)
        return {
            "id": product_id,
            "title": title,
            "status": "FAILED",
            "error": str(exc),
        }


# ── Main pipeline ────────────────────────────────────────────────────────

async def run_pipeline() -> None:
    """
    Orchestrate a single batch run of the enrichment pipeline.

    * Validates required environment variables.
    * Loads progress state from ``progress.json``.
    * Fetches the next batch of products from Shopify.
    * Processes each product concurrently.
    * Persists results and progress.
    """
    setup_logging()
    settings.validate_credentials()

    batch_size, processed_count = load_progress(
        settings.progress_file,
        default_batch_size=settings.batch_size,
        default_processed_count=0,
    )

    logger.info(
        "Starting run – batch_size=%d, already_processed=%d, dry_run=%s",
        batch_size,
        processed_count,
        settings.dry_run,
    )

    # Fetch products (I/O-bound → run in executor)
    loop = asyncio.get_running_loop()
    products = await loop.run_in_executor(
        None,
        partial(fetch_products_after_skipping, processed_count, batch_size),
    )

    if not products:
        logger.info("No products to process. Catalog may be fully processed.")
        return

    logger.info("Fetched %d product(s) to process.", len(products))

    # Process each product (sequentially to respect API rate limits)
    results: list[dict] = []
    for product in products:
        result = await process_product(product, loop)
        results.append(result)
        processed_count += 1

    # Persist state
    append_run_log(settings.log_file, results, processed_count)
    save_progress(settings.progress_file, batch_size, processed_count)

    successes = sum(1 for r in results if r["status"] in ("SUCCESS", "DRY-RUN"))
    failures = sum(1 for r in results if r["status"] == "FAILED")
    logger.info(
        "Run complete – %d succeeded, %d failed, %d total processed",
        successes,
        failures,
        processed_count,
    )


def main() -> None:
    """Entry point."""
    asyncio.run(run_pipeline())


if __name__ == "__main__":
    main()
