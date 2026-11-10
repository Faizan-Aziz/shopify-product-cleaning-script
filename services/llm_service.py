"""
LLM enrichment service using the official OpenAI SDK.

Uses ``client.beta.chat.completions.parse`` with Pydantic response models
(OpenAI Structured Outputs) to guarantee type-safe, schema-conformant
responses from the language model.
"""

from __future__ import annotations

import json
import logging
from typing import Any, Optional

from openai import OpenAI
from tenacity import (
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
    before_sleep_log,
)

from config import settings
from models import LLMResponse

logger = logging.getLogger(__name__)

# ── OpenAI client (lazy singleton) ──────────────────────────────────────

_client: Optional[OpenAI] = None


def get_openai_client() -> OpenAI:
    """Return initialized OpenAI client, raising informative error if key is unset."""
    global _client
    if _client is None:
        if not settings.openai_api_key:
            raise ValueError(
                "OPENAI_API_KEY is not configured. Please set it in your .env file."
            )
        _client = OpenAI(
            api_key=settings.openai_api_key,
            timeout=settings.openai_timeout,
        )
    return _client


# ── System prompt ────────────────────────────────────────────────────────

SYSTEM_PROMPT = """\
You are an expert product catalog technician for motorcycle parts.
Refine and format the provided motorcycle part details into the
requested JSON structure.

CRITICAL RULES:
1. SUMMARY FIRST – Distil long descriptions to core technical facts,
   condition details, and key specs without fluff.
2. OPTIMISED TITLE – Generate a clean, high-converting, SEO-optimised
   product title (under 70 chars) formatted as:
   [Brand] [Product Name] [Part Number / Fitment].
3. META DESCRIPTION – Write a compelling search-engine meta description
   (under 160 chars) highlighting the product, key specs, and fitment.
4. TYPE & TAGS – Determine the standardised Product Type and generate
   relevant comma-separated tags (brand, fitment, condition, category).
5. HTML TABLE IS SOURCE OF TRUTH – If a field value is already present
   or derivable from the Description Table / Extracted Data, leave the
   corresponding metafield NULL.

STRICT INSTRUCTIONS:
- Do NOT invent values.
- Return null/empty for any field that cannot be determined or is
  already covered by the description table.
"""


# ── Retry-wrapped LLM call ──────────────────────────────────────────────

@retry(
    retry=retry_if_exception_type(Exception),
    wait=wait_exponential(multiplier=1, min=2, max=30),
    stop=stop_after_attempt(3),
    before_sleep=before_sleep_log(logger, logging.WARNING),
    reraise=True,
)
def _call_llm(user_prompt: str) -> LLMResponse:
    """
    Send *user_prompt* to the configured OpenAI model and parse the
    response into a validated ``LLMResponse`` instance.
    """
    client = get_openai_client()
    completion = client.beta.chat.completions.parse(
        model=settings.openai_model,
        messages=[
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": user_prompt},
        ],
        temperature=0.0,
        response_format=LLMResponse,
    )
    parsed = completion.choices[0].message.parsed
    if parsed is None:
        raise ValueError("LLM returned an unparseable response")
    return parsed


# ── Public API ───────────────────────────────────────────────────────────

def enhance_with_llm(
    base_data: dict[str, Any],
    raw_title: str,
    raw_description: str,
) -> dict[str, Any]:
    """
    Pass extracted product data and the raw description to the LLM for
    cleanup, SEO generation, and gap-filling.

    Returns the mutated *base_data* dict with ``seo``, ``llm_metafields``
    and a merged ``description`` dict.
    """
    user_prompt = (
        f"Raw Title: {raw_title}\n"
        f"Extracted Text: {raw_description[:3000]}\n"
        f"Base Extracted Description: {json.dumps(base_data['description'])}\n"
        f"Base Extracted Metafields: {json.dumps(base_data['metafields'])}"
    )

    try:
        llm_response: LLMResponse = _call_llm(user_prompt)

        # ── Merge description (parser-first, LLM as fallback) ────────
        llm_desc = llm_response.description.model_dump(by_alias=True)
        merged_description = dict(base_data["description"])
        for key, val in llm_desc.items():
            current_val = merged_description.get(key)
            if not current_val and val and str(val).strip():
                merged_description[key] = str(val).strip()

        base_data["description"] = merged_description
        base_data["llm_metafields"] = llm_response.metafields.model_dump(
            by_alias=True
        )
        base_data["seo"] = llm_response.seo.model_dump()

    except Exception as exc:
        logger.warning(
            "LLM processing skipped or failed (%s). Using base parsed data.",
            exc,
        )
        base_data["llm_metafields"] = {}
        base_data["seo"] = {}

    return base_data
