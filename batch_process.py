import json
import os
import re
from html import escape
from datetime import datetime
import requests
from bs4 import BeautifulSoup
from dotenv import load_dotenv

# ======================================================
# Safety Settings & File Setup
# ======================================================

DRY_RUN = False
#PRODUCT_LIMIT = 1 # batch size
#SKIP_PRODUCTS = 10
LOG_FILE = "process_log.txt"
PROGRESS_FILE = "progress.json"

load_dotenv()


def load_progress(default_batch_size=1, default_processed_count=0):
    """Loads current batch size and total processed count state."""
    if os.path.exists(PROGRESS_FILE):
        try:
            with open(PROGRESS_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
                return data.get("batch_size", default_batch_size), data.get(
                    "processed_count", default_processed_count
                )
        except Exception as e:
            print(f"Error reading {PROGRESS_FILE}, using defaults. Error: {e}")

    # Default fallback state if file doesn't exist yet
    return default_batch_size, default_processed_count


def save_progress(batch_size, processed_count):
    """Overwrites progress.json with the single updated values at the end of a run."""
    state = {"batch_size": batch_size, "processed_count": processed_count}
    with open(PROGRESS_FILE, "w", encoding="utf-8") as f:
        json.dump(state, f, indent=4)
    print(
        f"[PROGRESS UPDATED] State file '{PROGRESS_FILE}' updated -> Batch Size: {batch_size}, Total Processed: {processed_count}"
    )

def append_run_log(processed_items, total_processed_count):
    """Appends detailed execution logs separated by Success/Error status."""
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    # Filter into groups
    successes = [item for item in processed_items if item.get("status") in ("SUCCESS", "DRY-RUN")]
    failures = [item for item in processed_items if item.get("status") == "FAILED"]

    log_entry = []
    log_entry.append("=" * 70)
    log_entry.append(f"EXECUTION LOG - {timestamp}")
    log_entry.append("=" * 70)

    # 1. Successful Updates Section
    log_entry.append(f"SUCCESSFUL UPDATES ({len(successes)}):")
    if successes:
        for item in successes:
            status_tag = f"[{item['status']}]"
            meta_info = f" | Metafields Set: {item.get('metafields_count', 0)}" if "metafields_count" in item else ""
            log_entry.append(f"  ✓ {status_tag} ID: {item['id']} | Title: {item['title']}{meta_info}")
    else:
        log_entry.append("  None")

    log_entry.append("-" * 70)

    # 2. Failed Updates Section
    log_entry.append(f"FAILED UPDATES ({len(failures)}):")
    if failures:
        for item in failures:
            log_entry.append(f"  ✗ [FAILED] ID: {item['id']} | Title: {item['title']}")
            log_entry.append(f"    Reason: {item['error']}")
    else:
        log_entry.append("  None")

    log_entry.append("-" * 70)
    log_entry.append(f"TOTAL PROCESSED PRODUCTS TO DATE: {total_processed_count}")
    log_entry.append("=" * 70 + "\n\n")

    # Write to log file
    with open(LOG_FILE, "a", encoding="utf-8") as f:
        f.write("\n".join(log_entry))

    print(f"\n[LOG UPDATED] Detailed run summary appended to '{LOG_FILE}'.")


# --- Load initial state from progress.json (or fallback defaults) ---
PRODUCT_LIMIT, SKIP_PRODUCTS = load_progress(
    default_batch_size=1, default_processed_count=8
)


# ======================================================
# Environment Setup


SHOP = "cheap-thrills-motorsports.myshopify.com"  # os.getenv("SHOPIFY_STORE")
ACCESS_TOKEN = "123"  # os.getenv("SHOPIFY_ACCESS_TOKEN")
API_VERSION = "2025-10"  # os.getenv("SHOPIFY_API_VERSION", "2025-10")
OPENAI_API_KEY = "xyz"  # os.getenv("OPENAI_API_KEY")

GRAPHQL_URL = f"https://{SHOP}/admin/api/{API_VERSION}/graphql.json"
HEADERS = {
    "X-Shopify-Access-Token": ACCESS_TOKEN,
    "Content-Type": "application/json",
}

LABELS = sorted(
    [
        "Product Name", "Product Type", "Brand", "MFG Part Number",
        "Part Number", "Removed From", "Condition Grade", "Condition Notes",
        "Condition", "Color", "Material", "Fitment", "Vehicle",
        "Features", "Description", "Notes",
    ],
    key=len,
    reverse=True,
)

METAFIELD_TYPES = {
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





# ======================================================
# Description & Parser Helpers
# ======================================================

def clean_html(html):
    soup = BeautifulSoup(html or "", "html.parser")
    text = soup.get_text("\n")
    text = text.replace("\r", "")
    text = re.sub(r"\n+", "\n", text)
    text = re.sub(r"[ \t]+", " ", text)
    text = text.replace("MFG Part\nNumber", "MFG Part Number")
    return text.strip()

def parse_description(text):
    fields = {}
    current_label = None
    for raw_line in text.split("\n"):
        line = raw_line.strip()
        if not line:
            continue
        matched_label = None
        for label in LABELS:
            if line.lower().startswith(label.lower()):
                matched_label = label
                value = line[len(label):].strip(" :")
                fields[label] = value
                current_label = label
                break
        if matched_label:
            continue
        if current_label:
            existing_value = fields.get(current_label, "")
            separator = "\n" if current_label in ["Features", "Description", "Condition Notes", "Notes"] else " "
            fields[current_label] = (existing_value + separator + line) if existing_value else line
    return fields

def tag_lookup(tags, prefix):
    for tag in tags:
        cleaned_tag = tag.strip()
        if cleaned_tag.lower().startswith(prefix.lower()):
            return cleaned_tag[len(prefix):].strip()
    return None

def detect_make(text):
    makes = ["Yamaha", "Honda", "Suzuki", "Kawasaki", "KTM", "BMW", "Ducati", "Triumph", "Harley-Davidson", "Harley", "Aprilia", "Husqvarna", "Indian", "Polaris", "Can-Am"]
    for make in makes:
        if re.search(rf"\b{re.escape(make)}\b", text, flags=re.IGNORECASE):
            return make
    return None

def detect_model(text):
    models = ["YZF-R6", "YZF-R1", "GSX-R1000", "GSX-R750", "GSX-R600", "CBR1000RR", "CBR600RR", "ZX-10R", "ZX10R", "ZX-6R", "ZX6R", "MT-09", "MT09", "MT-07", "MT07", "GSXR", "R6", "R1"]
    models.sort(key=len, reverse=True)
    for model in models:
        if re.search(rf"\b{re.escape(model)}\b", text, flags=re.IGNORECASE):
            return model
    return None

def detect_years(text):
    range_match = re.search(r"\b((?:19|20)\d{2})\s*[-–—/]\s*((?:19|20)\d{2})\b", text)
    if range_match:
        return range_match.group(1), range_match.group(2)
    single_match = re.search(r"\b((?:19|20)\d{2})\b", text)
    if single_match:
        year = single_match.group(1)
        return year, year
    return None, None

def detect_removed_year(text):
    if not text:
        return None
    match = re.search(r"\b(?:19|20)\d{2}\b", text)
    return match.group(0) if match else None

def detect_part_type(title, product_type):
    text = f"{title} {product_type or ''}".lower()
    keywords = ["crankcase", "transmission", "clutch", "wheel", "brake", "fairing", "tire", "tyre", "bolt", "stator", "fork", "shock", "engine", "radiator", "caliper", "swingarm", "exhaust", "fuel tank", "seat", "handlebar", "light"]
    for keyword in keywords:
        if keyword in text:
            return keyword.title()
    return product_type

# ======================================================
# Step 1: Base Extraction
# ======================================================

def normalize_product(product):
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
    part_number = parsed.get("Part Number") or parsed.get("MFG Part Number") or sku
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
        fitment = f"{make} {model} {year_from}" if year_from == year_to else f"{make} {model} {year_from}-{year_to}"

    normalized_description = {
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

    # Generate initial fallback metafields based strictly on parser data
    manufacturer_type = "OEM" if brand and "OEM" in brand.upper() else None
    manufacturer_name = re.sub(r"\s+OEM\b", "", brand, flags=re.IGNORECASE).strip() if brand else None

    base_metafields = {
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

# ======================================================
# Step 2: LLM Integration & Merging
# ======================================================

def enhance_with_llm(base_data, raw_title, raw_description):
    """
    Passes extracted data and raw description to LLM for cleanup, SEO creation,
    and returns missing data while handling heavy descriptions safely.
    """
    prompt = f"""
    You are an expert product catalog technician. Refine and format the motorcycle part details below into JSON.

    CRITICAL RULES FOR HEAVY DESCRIPTIONS, SEO, AND METAFIELDS:
    1. SUMMARY FIRST: Distill long descriptions down to core technical facts, condition details, and key specs without fluff.
    2. OPTIMIZED TITLE: Generate a clean, high-converting, SEO-optimized product title (under 70 chars) formatted as: [Brand] [Product Name] [Part Number / Fitment].
    3. META DESCRIPTION: Write a compelling search engine meta description (under 160 chars) highlighting the product, key specs, and fitment.
    4. TYPE & TAGS: Determine the standardized Product Type and generate relevant comma-separated tags (e.g., brand, fitment, condition, category).
    5. HTML TABLE IS SOURCE OF TRUTH: If a field value is already present or derivable from the Description Table/Extracted Data, do NOT populate it in the 'metafields' object—leave it NULL in 'metafields'.

    Return ONLY valid JSON matching this exact key structure:
    {{
      "seo": {{
        "title": "...",
        "meta_description": "...",
        "product_type": "...",
        "tags": ["tag1", "tag2", "tag3"]
      }},
      "description": {{
        "Product Name": "...",
        "Product Type": "...",
        "Brand": "...",
        "Part Number": "...",
        "Removed From": "...",
        "Condition": "...",
        "Condition Grade": "...",
        "Color": "...",
        "Material": "...",
        "Fitment": "...",
        "Description": "...",
        "Features": "...",
        "Condition Notes": "..."
      }},
      "metafields": {{
        "custom.spec_material": null,
        "custom.spec_color": null,
        "custom.condition_notes": null,
        "custom.condition_grade": null,
        "custom.condition_status": null,
        "custom.manufacturer_type": null,
        "custom.manufacturer_name": null,
        "custom.part_part_number": null,
        "custom.part_part_type": null,
        "custom.part_sub_category": null,
        "custom.part_category": null,
        "custom.vehicle_removed_from_year": null,
        "custom.vehicle_year_from": null,
        "custom.vehicle_year_to": null,
        "custom.vehicle_make": null,
        "custom.vehicle_model": null
      }}
    }}

    STRICT INSTRUCTIONS:
    - Do not invent values.
    - Return null/empty for any field that cannot be determined or is already covered by the description table.

    Raw Title: {raw_title}
    Extracted Text: {raw_description[:3000]}
    Base Extracted Description: {json.dumps(base_data['description'])}
    Base Extracted Metafields: {json.dumps(base_data['metafields'])}
    """

    try:
        response = requests.post(
            "https://api.openai.com/v1/chat/completions",
            headers={"Authorization": f"Bearer {OPENAI_API_KEY}"},
            json={
                "model": "gpt-4o-mini",
                "messages": [{"role": "user", "content": prompt}],
                "temperature": 0.0,
                "response_format": {"type": "json_object"}
            },
            timeout=15
        )
        res_json = response.json()
        llm_parsed = json.loads(res_json["choices"][0]["message"]["content"])

        # Merge Description (Parser First, LLM Second as fallback)
        llm_desc = llm_parsed.get("description", {}) or {}
        merged_description = dict(base_data["description"])
        for key, val in llm_desc.items():
            current_val = merged_description.get(key)
            if not current_val and val and str(val).strip():
                merged_description[key] = str(val).strip()

        base_data["description"] = merged_description
        base_data["llm_metafields"] = llm_parsed.get("metafields", {}) or {}
        base_data["seo"] = llm_parsed.get("seo", {}) or {}

    except Exception as e:
        print(f"LLM processing skipped or failed ({e}). Proceeding with base parsed data.")
        base_data["llm_metafields"] = {}
        base_data["seo"] = {}

    return base_data

# ======================================================
# Step 3: Single Source Metafields Generation
# ======================================================

def build_metafields(final_description, base_metafields, llm_metafields):
    """
    Constructs final metafield payload using Final Description as single source of truth,
    applying strict priority: Parser Base > Final Description > LLM Metafields.
    """
    brand = final_description.get("Brand")
    manufacturer_type = "OEM" if brand and "OEM" in str(brand).upper() else None
    manufacturer_name = re.sub(r"\s+OEM\b", "", str(brand), flags=re.IGNORECASE).strip() if brand else None

    removed_from = final_description.get("Removed From")
    title = final_description.get("Product Name", "")
    prod_type = final_description.get("Product Type", "")

    # Re-detect vehicle fields from finalized fitment/text if available
    fitment_text = f"{title} {final_description.get('Fitment', '')} {removed_from or ''}"
    make = detect_make(fitment_text)
    model = detect_model(fitment_text)
    year_from, year_to = detect_years(fitment_text)

    derived_metafields = {
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

    final_metafields = {}

    # Priority Resolution per key
    for key in METAFIELD_TYPES.keys():
        parser_val = base_metafields.get(key)
        derived_val = derived_metafields.get(key)
        llm_val = llm_metafields.get(key)

        if parser_val and str(parser_val).strip():
            final_metafields[key] = str(parser_val).strip()
        elif derived_val and str(derived_val).strip():
            final_metafields[key] = str(derived_val).strip()
        elif llm_val and str(llm_val).strip():
            final_metafields[key] = str(llm_val).strip()
        else:
            final_metafields[key] = None

    return final_metafields

# ======================================================
# Step 4: Build HTML & GraphQL Updates
# ======================================================

def build_description_html(normalized_description):
    specification_labels = [
        "Product Name", "Product Type", "Brand", "Part Number",
        "Removed From", "Condition", "Condition Grade", "Color",
        "Material", "Fitment",
    ]

    rows = []
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

    html = f'<div class="normalized-product-description">\n<table>\n<tbody>\n' + "\n".join(rows) + '\n</tbody>\n</table>'

    description = normalized_description.get("Description")
    if description:
        paragraphs = [p.strip() for p in description.split("\n") if p.strip()]
        if paragraphs:
            html += "\n<h3>Description</h3>" + "".join([f"\n<p>{escape(p)}</p>" for p in paragraphs])

    features = normalized_description.get("Features")
    if features:
        feature_lines = [l.strip(" •-*") for l in features.split("\n") if l.strip(" •-*")]
        if feature_lines:
            html += "\n<h3>Features</h3>\n<ul>" + "".join([f"\n<li>{escape(f)}</li>" for f in feature_lines]) + "\n</ul>"

    notes = normalized_description.get("Condition Notes")
    if notes:
        html += f"\n<h3>Condition Notes</h3>\n<p>{escape(notes)}</p>"

    html += "\n</div>"
    return html

def prepare_metafields(product_id, metafields):
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
        prepared.append({
            "ownerId": product_id,
            "namespace": namespace,
            "key": key,
            "type": metafield_type,
            "value": value,
        })
    return prepared

def shopify_graphql(query, variables=None):
    response = requests.post(
        GRAPHQL_URL,
        headers=HEADERS,
        json={"query": query, "variables": variables or {}},
        timeout=30,
    )
    response.raise_for_status()
    result = response.json()
    if result.get("errors"):
        raise RuntimeError(f"Shopify GraphQL error: {result['errors']}")
    return result["data"]

PRODUCTS_QUERY = """
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

def fetch_products_after_skipping(skip_count, product_limit):
    cursor = None
    remaining_to_skip = skip_count
    while remaining_to_skip > 0:
        batch_size = min(remaining_to_skip, 250)
        page = shopify_graphql(PRODUCTS_QUERY, {"first": batch_size, "after": cursor})["products"]
        skipped = page["nodes"]
        if not skipped:
            return []
        remaining_to_skip -= len(skipped)
        cursor = page["pageInfo"]["endCursor"]
        if remaining_to_skip > 0 and not page["pageInfo"]["hasNextPage"]:
            return []
    page = shopify_graphql(PRODUCTS_QUERY, {"first": product_limit, "after": cursor})["products"]
    return page["nodes"]

def update_product_details(product_id, description_html, seo_data, fallback_title, fallback_type, existing_tags):
    """
    Updates Product Title, Type, Tags, Description HTML, and Search Engine Listing (Meta Description) via GraphQL.
    """
    mutation = """
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

    title = seo_data.get("title") or fallback_title
    product_type = seo_data.get("product_type") or fallback_type
    meta_description = seo_data.get("meta_description") or ""

    new_tags = seo_data.get("tags") or []
    combined_tags = list(set([t.strip() for t in (existing_tags + new_tags) if t and t.strip()]))

    product_input = {
        "id": product_id,
        "title": title,
        "productType": product_type,
        "tags": combined_tags,
        "descriptionHtml": description_html,
        "seo": {
            "title": title[:70],
            "description": meta_description[:160]
        }
    }

    data = shopify_graphql(mutation, {"product": product_input})
    res = data["productUpdate"]
    if res["userErrors"]:
        raise RuntimeError(f"Product update errors: {res['userErrors']}")
    return res["product"]

def update_product_metafields(product_id, metafields):
    prepared = prepare_metafields(product_id, metafields)
    if not prepared:
        return []
    mutation = """
    mutation SetMetafields($metafields: [MetafieldsSetInput!]!) {
      metafieldsSet(metafields: $metafields) {
        metafields { id namespace key type value }
        userErrors { field message code }
      }
    }
    """
    data = shopify_graphql(mutation, {"metafields": prepared})
    res = data["metafieldsSet"]
    if res["userErrors"]:
        raise RuntimeError(f"Metafield update errors: {res['userErrors']}")
    return res["metafields"]

# ======================================================
# Main Processing Loop
# ======================================================
processed_in_this_run = []
products = fetch_products_after_skipping(SKIP_PRODUCTS, PRODUCT_LIMIT)

for product in products:
    product_id = product["id"]
    title = product["title"]
    existing_tags = product.get("tags", [])

    # 1. Base extraction
    normalized = normalize_product(product)

    # 2. LLM Enhancement (Extracts SEO, Title, Type, Tags, Description)
    normalized = enhance_with_llm(normalized, title, product.get("descriptionHtml", ""))

    # 3. Generate Final Metafields after LLM Merge using single source of truth
    final_metafields = build_metafields(
        normalized["description"],
        normalized["metafields"],
        normalized.get("llm_metafields", {})
    )
    normalized["metafields"] = final_metafields

    # 4. HTML formatting from finalized result
    description_html = build_description_html(normalized["description"])
    seo_info = normalized.get("seo", {})

    print("\n" + "=" * 90)
    print("PRODUCT TITLE    :", seo_info.get("title") or title)
    print("PRODUCT ID    :", product_id)
    print("=" * 90)
    print("META DESCRIPTION :", seo_info.get("meta_description"))
    print("PRODUCT TYPE     :", seo_info.get("product_type") or normalized["description"].get("Product Type"))
    print("TAGS             :", seo_info.get("tags"))

    print("\n[FINAL DESCRIPTION TABLE]")
    for key, value in normalized["description"].items():
        print(f"{key:24}: {value}")

    print("\n[FINAL METAFIELDS]")
    for key, value in normalized["metafields"].items():
        print(f"{key:32}: {value}")

    if DRY_RUN:
        print("\nDRY RUN ENABLED: Skipping Shopify API write.")
        SKIP_PRODUCTS += 1
        processed_in_this_run.append({
            "id": product_id,
            "title": title,
            "status": "DRY-RUN",
            "details": "Dry run enabled - no changes applied to Shopify."
        })
        
        continue

    try:
        updated_product = update_product_details(
            product_id=product_id,
            description_html=description_html,
            seo_data=seo_info,
            fallback_title=title,
            fallback_type=normalized["description"].get("Product Type", ""),
            existing_tags=existing_tags
        )
        updated_metafields = update_product_metafields(product_id, normalized["metafields"])

        print("\nSUCCESSFULLY UPDATED:", updated_product["title"])
        print("Metafields updated:", len(updated_metafields))
        # --- Increment total count and append processed product details ---
        SKIP_PRODUCTS += 1
        processed_in_this_run.append({"id": product_id, "title": title, "status": "SUCCESS","details": {"metafields_count": len(updated_metafields), "seo_title": seo_info.get("title")} })

    except Exception as error:
        print("\nUPDATE FAILED:", title)
        print("Error:", error)
        processed_in_this_run.append({"id": product_id, "title": title, "status": "FAILED","details": error})


# ======================================================
# Post-Run File Updates
# ======================================================

# 1. APPEND batch results into process_log.txt history
append_run_log(processed_in_this_run, SKIP_PRODUCTS)

# 2. OVERWRITE progress.json with latest active state for the next execution
save_progress(batch_size=PRODUCT_LIMIT, processed_count=SKIP_PRODUCTS)