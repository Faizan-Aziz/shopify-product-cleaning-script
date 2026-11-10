"""
HTML and text parsing utilities for Shopify product descriptions.

All BeautifulSoup processing, regex-based field extraction, and
vehicle / part detection logic from the legacy codebase is preserved
here in a clean, testable module.
"""

from __future__ import annotations

import re
from typing import Optional

from bs4 import BeautifulSoup
from services.shopify_client import METAFIELD_TYPES


# ── Ordered labels for field extraction (longest-first for greedy match) ─

LABELS: list[str] = sorted(
    [
        "Product Name",
        "Product Type",
        "Brand",
        "MFG Part Number",
        "Part Number",
        "Removed From",
        "Condition Grade",
        "Condition Notes",
        "Condition",
        "Color",
        "Material",
        "Fitment",
        "Vehicle",
        "Features",
        "Description",
        "Notes",
    ],
    key=len,
    reverse=True,
)

# ── Known makes and models ──────────────────────────────────────────────

_KNOWN_MAKES: list[str] = [
    "Yamaha",
    "Honda",
    "Suzuki",
    "Kawasaki",
    "KTM",
    "BMW",
    "Ducati",
    "Triumph",
    "Harley-Davidson",
    "Harley",
    "Aprilia",
    "Husqvarna",
    "Indian",
    "Polaris",
    "Can-Am",
]

_KNOWN_MODELS: list[str] = sorted(
    [
        "YZF-R6",
        "YZF-R1",
        "GSX-R1000",
        "GSX-R750",
        "GSX-R600",
        "CBR1000RR",
        "CBR600RR",
        "ZX-10R",
        "ZX10R",
        "ZX-6R",
        "ZX6R",
        "MT-09",
        "MT09",
        "MT-07",
        "MT07",
        "GSXR",
        "R6",
        "R1",
    ],
    key=len,
    reverse=True,
)

# ── Multi-line field names (value lines joined with newlines) ────────────

_MULTILINE_FIELDS = frozenset(
    {"Features", "Description", "Condition Notes", "Notes"}
)


# ── HTML cleaning ────────────────────────────────────────────────────────

def clean_html(html: str | None) -> str:
    """
    Strip all HTML tags from *html* and normalise whitespace.

    Handles the common ``MFG Part\\nNumber`` line-break artefact found
    in legacy Shopify descriptions.
    """
    soup = BeautifulSoup(html or "", "html.parser")
    text = soup.get_text("\n")
    text = text.replace("\r", "")
    text = re.sub(r"\n+", "\n", text)
    text = re.sub(r"[ \t]+", " ", text)
    text = text.replace("MFG Part\nNumber", "MFG Part Number")
    return text.strip()


# ── Structured field parser ──────────────────────────────────────────────

def parse_description(text: str) -> dict[str, str]:
    """
    Parse a cleaned plain-text description into labelled fields using
    the known ``LABELS`` list.

    Returns a dict mapping label names to their extracted values.
    """
    fields: dict[str, str] = {}
    current_label: str | None = None

    for raw_line in text.split("\n"):
        line = raw_line.strip()
        if not line:
            continue

        matched_label: str | None = None
        for label in LABELS:
            if line.lower().startswith(label.lower()):
                matched_label = label
                value = line[len(label) :].strip(" :")
                fields[label] = value
                current_label = label
                break

        if matched_label:
            continue

        if current_label:
            existing = fields.get(current_label, "")
            sep = "\n" if current_label in _MULTILINE_FIELDS else " "
            fields[current_label] = (
                (existing + sep + line) if existing else line
            )

    return fields


# ── Tag helpers ──────────────────────────────────────────────────────────

def tag_lookup(tags: list[str], prefix: str) -> str | None:
    """Return the value after *prefix* for the first tag that matches."""
    for tag in tags:
        cleaned = tag.strip()
        if cleaned.lower().startswith(prefix.lower()):
            return cleaned[len(prefix) :].strip()
    return None


# ── Vehicle / part detection ─────────────────────────────────────────────

def detect_make(text: str) -> str | None:
    """Return the first known motorcycle make found in *text*."""
    for make in _KNOWN_MAKES:
        if re.search(rf"\b{re.escape(make)}\b", text, flags=re.IGNORECASE):
            return make
    return None


def detect_model(text: str) -> str | None:
    """Return the first known motorcycle model found in *text*."""
    for model in _KNOWN_MODELS:
        if re.search(rf"\b{re.escape(model)}\b", text, flags=re.IGNORECASE):
            return model
    return None


def detect_years(text: str) -> tuple[str | None, str | None]:
    """
    Extract a year range (or a single year) from *text*.

    Returns ``(year_from, year_to)``; both ``None`` when no year is found.
    """
    range_match = re.search(
        r"\b((?:19|20)\d{2})\s*[-–—/]\s*((?:19|20)\d{2})\b", text
    )
    if range_match:
        return range_match.group(1), range_match.group(2)

    single_match = re.search(r"\b((?:19|20)\d{2})\b", text)
    if single_match:
        year = single_match.group(1)
        return year, year

    return None, None


def detect_removed_year(text: str | None) -> str | None:
    """Extract the first four-digit year from a *Removed From* string."""
    if not text:
        return None
    match = re.search(r"\b(?:19|20)\d{2}\b", text)
    return match.group(0) if match else None


def detect_part_type(title: str, product_type: str | None) -> str | None:
    """Heuristically detect the part type from the title and product type."""
    text = f"{title} {product_type or ''}".lower()
    keywords = [
        "crankcase",
        "transmission",
        "clutch",
        "wheel",
        "brake",
        "fairing",
        "tire",
        "tyre",
        "bolt",
        "stator",
        "fork",
        "shock",
        "engine",
        "radiator",
        "caliper",
        "swingarm",
        "exhaust",
        "fuel tank",
        "seat",
        "handlebar",
        "light",
    ]
    for keyword in keywords:
        if keyword in text:
            return keyword.title()
    return product_type


# ── Full product normalisation ───────────────────────────────────────────

def normalize_product(product: dict) -> dict:
    """
    Extract, clean, and normalise all fields from a raw Shopify product
    node into a structured dict ready for LLM enrichment.

    Returns a dict with keys: ``cleaned``, ``parsed``, ``description``,
    ``metafields``.
    """
    cleaned = clean_html(product.get("descriptionHtml"))
    parsed = parse_description(cleaned)
    title = product.get("title", "")
    vendor = product.get("vendor")
    product_type = product.get("productType")
    tags = product.get("tags") or []
    variants = product.get("variants", {}).get("nodes", [])
    first_variant = variants[0] if variants else {}
    sku = first_variant.get("sku")

    brand = parsed.get("Brand") or tag_lookup(tags, "Brand_") or vendor
    part_number = (
        parsed.get("Part Number") or parsed.get("MFG Part Number") or sku
    )
    condition = parsed.get("Condition") or tag_lookup(tags, "Condition_")
    grade = parsed.get("Condition Grade")
    color = parsed.get("Color")
    material = parsed.get("Material")
    notes = parsed.get("Condition Notes") or parsed.get("Notes")
    removed_from = parsed.get("Removed From")
    fitment = parsed.get("Fitment")

    search_text = f"{title}\n{cleaned}"
    make = detect_make(search_text)
    model = detect_model(search_text)
    year_from, year_to = detect_years(search_text)

    if not fitment and make and model and year_from:
        fitment = (
            f"{make} {model} {year_from}"
            if year_from == year_to
            else f"{make} {model} {year_from}-{year_to}"
        )

    normalized_description: dict[str, str | None] = {
        "Product Name": parsed.get("Product Name") or title,
        "Product Type": parsed.get("Product Type") or product_type,
        "Brand": brand,
        "Part Number": part_number,
        "Removed From": removed_from,
        "Condition": condition,
        "Condition Grade": grade,
        "Color": color,
        "Material": material,
        "Fitment": fitment,
        "Description": parsed.get("Description"),
        "Features": parsed.get("Features"),
        "Condition Notes": notes,
    }

    # ── Generate initial metafields strictly from parser data ────────
    manufacturer_type = (
        "OEM" if brand and "OEM" in brand.upper() else None
    )
    manufacturer_name = (
        re.sub(r"\s+OEM\b", "", brand, flags=re.IGNORECASE).strip()
        if brand
        else None
    )

    base_metafields: dict[str, str | None] = {
        "custom.spec_material": material,
        "custom.spec_color": color,
        "custom.condition_notes": notes,
        "custom.condition_grade": grade,
        "custom.condition_status": condition,
        "custom.manufacturer_type": manufacturer_type,
        "custom.manufacturer_name": manufacturer_name,
        "custom.part_part_number": part_number,
        "custom.part_part_type": detect_part_type(title, product_type),
        "custom.part_sub_category": parsed.get("Product Type"),
        "custom.part_category": product_type,
        "custom.vehicle_removed_from_year": detect_removed_year(removed_from),
        "custom.vehicle_year_from": year_from,
        "custom.vehicle_year_to": year_to,
        "custom.vehicle_make": make,
        "custom.vehicle_model": model,
    }

    return {
        "cleaned": cleaned,
        "parsed": parsed,
        "description": normalized_description,
        "metafields": base_metafields,
    }


def build_metafields(
    final_description: dict,
    base_metafields: dict,
    llm_metafields: dict,
) -> dict[str, str | None]:
    """
    Build the definitive metafield dict using strict priority:

        Parser Base  >  Derived from Final Description  >  LLM Metafields

    This ensures the parser's direct extraction always wins, followed by
    values re-derived from the (potentially LLM-merged) description, with
    LLM-only metafields used only as a last resort.
    """
    brand = final_description.get("Brand")
    manufacturer_type = (
        "OEM" if brand and "OEM" in str(brand).upper() else None
    )
    manufacturer_name = (
        re.sub(r"\s+OEM\b", "", str(brand), flags=re.IGNORECASE).strip()
        if brand
        else None
    )

    removed_from = final_description.get("Removed From")
    title = final_description.get("Product Name", "")
    prod_type = final_description.get("Product Type", "")

    fitment_text = (
        f"{title} {final_description.get('Fitment', '')} {removed_from or ''}"
    )
    make = detect_make(fitment_text)
    model = detect_model(fitment_text)
    year_from, year_to = detect_years(fitment_text)

    derived: dict[str, str | None] = {
        "custom.spec_material": final_description.get("Material"),
        "custom.spec_color": final_description.get("Color"),
        "custom.condition_notes": final_description.get("Condition Notes"),
        "custom.condition_grade": final_description.get("Condition Grade"),
        "custom.condition_status": final_description.get("Condition"),
        "custom.manufacturer_type": manufacturer_type,
        "custom.manufacturer_name": manufacturer_name,
        "custom.part_part_number": final_description.get("Part Number"),
        "custom.part_part_type": detect_part_type(title, prod_type),
        "custom.part_sub_category": prod_type,
        "custom.part_category": prod_type,
        "custom.vehicle_removed_from_year": detect_removed_year(removed_from),
        "custom.vehicle_year_from": year_from,
        "custom.vehicle_year_to": year_to,
        "custom.vehicle_make": make,
        "custom.vehicle_model": model,
    }

    final: dict[str, str | None] = {}
    for key in METAFIELD_TYPES:
        parser_val = base_metafields.get(key)
        derived_val = derived.get(key)
        llm_val = llm_metafields.get(key)

        if parser_val and str(parser_val).strip():
            final[key] = str(parser_val).strip()
        elif derived_val and str(derived_val).strip():
            final[key] = str(derived_val).strip()
        elif llm_val and str(llm_val).strip():
            final[key] = str(llm_val).strip()
        else:
            final[key] = None

    return final
