"""
Shopify Admin GraphQL client with automatic retry and rate-limit handling.

All Shopify API interactions are centralised here. The client uses
``tenacity`` for exponential back-off on transient failures and HTTP 429
rate-limit responses.
"""

from __future__ import annotations

import logging
from html import escape
from typing import Any, Optional

import requests
from tenacity import (
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
    before_sleep_log,
)

from config import settings

logger = logging.getLogger(__name__)

# ── Shopify metafield type registry ──────────────────────────────────────

METAFIELD_TYPES: dict[str, str] = {
    "custom.spec_material": "single_line_text_field",
    "custom.spec_color": "single_line_text_field",
    "custom.condition_notes": "single_line_text_field",
    "custom.condition_grade": "single_line_text_field",
    "custom.condition_status": "single_line_text_field",
    "custom.manufacturer_type": "single_line_text_field",
    "custom.manufacturer_name": "single_line_text_field",
    "custom.part_part_number": "single_line_text_field",
    "custom.part_part_type": "single_line_text_field",
    "custom.part_sub_category": "single_line_text_field",
    "custom.part_category": "single_line_text_field",
    "custom.vehicle_removed_from_year": "single_line_text_field",
    "custom.vehicle_year_from": "single_line_text_field",
    "custom.vehicle_year_to": "single_line_text_field",
    "custom.vehicle_make": "single_line_text_field",
    "custom.vehicle_model": "single_line_text_field",
}


# ── Custom exception for rate-limiting ───────────────────────────────────

class ShopifyRateLimitError(Exception):
    """Raised when the Shopify API returns HTTP 429."""


class ShopifyGraphQLError(Exception):
    """Raised when the Shopify GraphQL response contains errors."""


# ── Low-level GraphQL executor ───────────────────────────────────────────

@retry(
    retry=retry_if_exception_type((ShopifyRateLimitError, requests.ConnectionError)),
    wait=wait_exponential(multiplier=1, min=2, max=30),
    stop=stop_after_attempt(6),
    before_sleep=before_sleep_log(logger, logging.WARNING),
    reraise=True,
)
def graphql_request(query: str, variables: dict[str, Any] | None = None) -> dict:
    """
    Execute a GraphQL query/mutation against the Shopify Admin API.

    Retries automatically on connection errors and 429 rate-limit responses
    with exponential back-off (up to 6 attempts).
    """
    response = requests.post(
        settings.graphql_url,
        headers={
            "X-Shopify-Access-Token": settings.shopify_access_token,
            "Content-Type": "application/json",
        },
        json={"query": query, "variables": variables or {}},
        timeout=settings.shopify_timeout,
    )

    if response.status_code == 429:
        raise ShopifyRateLimitError("Shopify rate limit exceeded – will retry")

    response.raise_for_status()
    result = response.json()

    if result.get("errors"):
        raise ShopifyGraphQLError(f"Shopify GraphQL errors: {result['errors']}")

    return result["data"]


# ── GraphQL queries & mutations ──────────────────────────────────────────

PRODUCTS_QUERY = """\
query FetchProducts($first: Int!, $after: String) {
  products(first: $first, after: $after) {
    nodes {
      id
      title
      descriptionHtml
      vendor
      productType
      tags
      variants(first: 1) {
        nodes { id title sku }
      }
    }
    pageInfo { hasNextPage endCursor }
  }
}
"""

PRODUCT_UPDATE_MUTATION = """\
mutation UpdateProduct($product: ProductInput!) {
  productUpdate(input: $product) {
    product {
      id
      title
      productType
      tags
      seo { title description }
      descriptionHtml
    }
    userErrors { field message }
  }
}
"""

METAFIELDS_SET_MUTATION = """\
mutation SetMetafields($metafields: [MetafieldsSetInput!]!) {
  metafieldsSet(metafields: $metafields) {
    metafields { id namespace key type value }
    userErrors { field message code }
  }
}
"""

SEARCH_PRODUCTS_QUERY = """\
query GetProducts($cursor: String) {
  products(first: 250, after: $cursor, sortKey: ID) {
    nodes {
      id
      title
      handle
    }
    pageInfo {
      hasNextPage
      endCursor
    }
  }
}
"""


# ── High-level operations ────────────────────────────────────────────────

def fetch_products_after_skipping(
    skip_count: int,
    product_limit: int,
) -> list[dict]:
    """
    Paginate through the catalog, skip *skip_count* products, then return
    the next *product_limit* products.
    """
    cursor: Optional[str] = None
    remaining = skip_count

    while remaining > 0:
        batch = min(remaining, 250)
        data = graphql_request(PRODUCTS_QUERY, {"first": batch, "after": cursor})
        page = data["products"]
        nodes = page["nodes"]

        if not nodes:
            return []

        remaining -= len(nodes)
        cursor = page["pageInfo"]["endCursor"]

        if remaining > 0 and not page["pageInfo"]["hasNextPage"]:
            return []

    data = graphql_request(PRODUCTS_QUERY, {"first": product_limit, "after": cursor})
    return data["products"]["nodes"]


def find_product_position(target_title: str) -> dict | None:
    """
    Find product position, title, ID, and handle by title.
    Preserved from legacy utility script with dynamic configuration.
    """
    cursor = None
    position = 0

    while True:
        data = graphql_request(SEARCH_PRODUCTS_QUERY, {"cursor": cursor})
        products = data["products"]["nodes"]

        for product in products:
            position += 1
            if product["title"].strip().lower() == target_title.strip().lower():
                return {
                    "position": position,
                    "title": product["title"],
                    "id": product["id"],
                    "handle": product["handle"],
                }

        page_info = data["products"]["pageInfo"]
        if not page_info["hasNextPage"]:
            break
        cursor = page_info["endCursor"]

    return None


def update_product_details(
    product_id: str,
    description_html: str,
    seo_data: dict,
    fallback_title: str,
    fallback_type: str,
    existing_tags: list[str],
) -> dict:
    """
    Update a product's title, type, tags, description HTML, and SEO
    meta fields via the Shopify GraphQL Admin API.
    """
    title = seo_data.get("title") or fallback_title
    product_type = seo_data.get("product_type") or fallback_type
    meta_description = seo_data.get("meta_description") or ""

    new_tags = seo_data.get("tags") or []
    combined_tags = list(
        {t.strip() for t in (existing_tags + new_tags) if t and t.strip()}
    )

    product_input = {
        "id": product_id,
        "title": title,
        "productType": product_type,
        "tags": combined_tags,
        "descriptionHtml": description_html,
        "seo": {
            "title": title[:70],
            "description": meta_description[:160],
        },
    }

    data = graphql_request(PRODUCT_UPDATE_MUTATION, {"product": product_input})
    result = data["productUpdate"]

    if result["userErrors"]:
        raise ShopifyGraphQLError(
            f"Product update errors: {result['userErrors']}"
        )
    return result["product"]


def update_product_metafields(product_id: str, metafields: dict) -> list[dict]:
    """Set metafields on a product, skipping any ``None`` / empty values."""
    prepared = prepare_metafields(product_id, metafields)
    if not prepared:
        return []

    data = graphql_request(METAFIELDS_SET_MUTATION, {"metafields": prepared})
    result = data["metafieldsSet"]

    if result["userErrors"]:
        raise ShopifyGraphQLError(
            f"Metafield update errors: {result['userErrors']}"
        )
    return result["metafields"]


# ── HTML builder ─────────────────────────────────────────────────────────

def build_description_html(normalized_description: dict) -> str:
    """
    Render a normalised description dict into a Shopify-ready HTML table
    with optional Description, Features, and Condition Notes sections.
    """
    specification_labels = [
        "Product Name",
        "Product Type",
        "Brand",
        "Part Number",
        "Removed From",
        "Condition",
        "Condition Grade",
        "Color",
        "Material",
        "Fitment",
    ]

    rows: list[str] = []
    for label in specification_labels:
        value = normalized_description.get(label)
        if not value:
            continue
        value = str(value).strip()
        if value:
            rows.append(
                f'<tr><th style="text-align:left;padding:6px;">{escape(label)}</th>'
                f'<td style="padding:6px;">{escape(value)}</td></tr>'
            )

    html = (
        '<div class="normalized-product-description">\n'
        "<table>\n<tbody>\n" + "\n".join(rows) + "\n</tbody>\n</table>"
    )

    description = normalized_description.get("Description")
    if description:
        paragraphs = [p.strip() for p in description.split("\n") if p.strip()]
        if paragraphs:
            html += "\n<h3>Description</h3>" + "".join(
                [f"\n<p>{escape(p)}</p>" for p in paragraphs]
            )

    features = normalized_description.get("Features")
    if features:
        lines = [l.strip(" •-*") for l in features.split("\n") if l.strip(" •-*")]
        if lines:
            html += "\n<h3>Features</h3>\n<ul>" + "".join(
                [f"\n<li>{escape(f)}</li>" for f in lines]
            ) + "\n</ul>"

    notes = normalized_description.get("Condition Notes")
    if notes:
        html += f"\n<h3>Condition Notes</h3>\n<p>{escape(notes)}</p>"

    html += "\n</div>"
    return html


# ── Helpers ──────────────────────────────────────────────────────────────

def prepare_metafields(product_id: str, metafields: dict) -> list[dict]:
    """Convert the flat metafield dict into Shopify ``MetafieldsSetInput`` items."""
    prepared = []
    for full_key, value in metafields.items():
        if value is None:
            continue
        value = str(value).strip()
        if not value:
            continue
        namespace, key = full_key.split(".", 1)
        metafield_type = METAFIELD_TYPES.get(full_key)
        if not metafield_type:
            continue
        prepared.append(
            {
                "ownerId": product_id,
                "namespace": namespace,
                "key": key,
                "type": metafield_type,
                "value": value,
            }
        )
    return prepared
