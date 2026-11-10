# Shopify Product Catalog Enrichment Pipeline

> Automated product data enrichment for Shopify stores — parses HTML descriptions, enriches them with AI, and writes structured metafields & SEO data back to your catalog via the Shopify Admin GraphQL API.

[![Python 3.11+](https://img.shields.io/badge/python-3.11%2B-blue.svg)](https://www.python.org/downloads/)
[![License: MIT](https://img.shields.io/badge/License-MIT-green.svg)](LICENSE)

---

## Table of Contents

- [Overview](#overview)
- [Architecture](#architecture)
- [Project Structure](#project-structure)
- [Prerequisites](#prerequisites)
- [Setup](#setup)
- [Configuration](#configuration)
- [Usage](#usage)
- [How It Works](#how-it-works)
- [Contributing](#contributing)
- [Author](#author)
- [License](#license)

---

## Overview

Many Shopify stores accumulate product listings with inconsistent, unstructured HTML descriptions. This pipeline:

1. **Fetches** products in resumable batches from the Shopify Admin GraphQL API.
2. **Parses** raw HTML descriptions into structured fields (brand, fitment, condition, etc.) using BeautifulSoup and regex.
3. **Enriches** extracted data with an OpenAI LLM call — generating SEO titles, meta descriptions, tags, and filling missing fields.
4. **Merges** results with strict priority (parser wins over LLM) to avoid hallucinated overwrites.
5. **Writes** the enriched product data, HTML description table, and Shopify metafields back to the store.
6. **Tracks** progress across runs so processing can be stopped and resumed at any time.

---

## Architecture

```
┌─────────────┐     ┌──────────────┐     ┌──────────────┐
│  Shopify     │────▶│  Text Parser │────▶│  LLM Service │
│  GraphQL API │     │  (BS4+Regex) │     │  (OpenAI SDK)│
└──────┬───────┘     └──────────────┘     └──────┬───────┘
       │                                          │
       │              ┌──────────────┐            │
       │◀─────────────│   Merger &   │◀───────────┘
       │              │  Metafield   │
       │              │  Builder     │
       │              └──────────────┘
       │
       ▼
┌─────────────┐     ┌──────────────┐
│  Product     │     │  State       │
│  Update +    │     │  Manager     │
│  Metafields  │     │  (JSON)      │
└─────────────┘     └──────────────┘
```

---

## Project Structure

```
.
├── config.py                  # Pydantic BaseSettings (env var loading)
├── models.py                  # Pydantic schemas (LLM Structured Outputs, metafields)
├── main.py                    # Async pipeline orchestrator (entry point)
├── services/
│   ├── shopify_client.py      # Shopify GraphQL client (tenacity retry)
│   ├── llm_service.py         # OpenAI SDK with Structured Outputs
│   └── text_parser.py         # BeautifulSoup & regex parsers
├── utils/
│   ├── logger.py              # Structured logging setup
│   └── state_manager.py       # Progress tracker (progress.json)
├── requirements.txt           # Python dependencies
├── .env.example               # Environment variable template
├── .gitignore                 # Git ignore rules
└── README.md                  # Project documentation
```

---

## Prerequisites

- **Python 3.11+**
- A **Shopify** store with Admin API access (custom app with `write_products` scope)
- An **OpenAI** API key

---

## Setup

1. **Clone the repository**

   ```bash
   git clone https://github.com/Faizan-Aziz/shopify-product-cleaning-script.git
   cd shopify-product-cleaning-script
   ```

2. **Create a virtual environment**

   ```bash
   python -m venv .venv
   source .venv/bin/activate   # Linux / macOS
   .venv\Scripts\activate      # Windows
   ```

3. **Install dependencies**

   ```bash
   pip install -r requirements.txt
   ```

4. **Configure environment variables**

   ```bash
   cp .env.example .env
   ```

   Open `.env` and fill in your real credentials (see [Configuration](#configuration)).

---

## Configuration

All settings are loaded from environment variables (or a `.env` file) using [Pydantic Settings](https://docs.pydantic.dev/latest/concepts/pydantic_settings/).

| Variable | Required | Default | Description |
|---|---|---|---|
| `SHOPIFY_STORE` | ✅ | — | Store domain (`your-store.myshopify.com`) |
| `SHOPIFY_ACCESS_TOKEN` | ✅ | — | Admin API access token |
| `SHOPIFY_API_VERSION` | — | `2025-10` | API version string |
| `OPENAI_API_KEY` | ✅ | — | OpenAI API key |
| `OPENAI_MODEL` | — | `gpt-4o-mini` | Model for enrichment |
| `BATCH_SIZE` | — | `5` | Products per run |
| `DRY_RUN` | — | `false` | Skip Shopify writes when `true` |
| `LOG_FILE` | — | `process_log.txt` | Execution log path |
| `PROGRESS_FILE` | — | `progress.json` | Progress state path |

> **⚠️ Security:** Never commit your `.env` file. The `.gitignore` is pre-configured to exclude it.

---

## Usage

### Process the next batch

```bash
python main.py
```

### Dry-run mode (preview without writing to Shopify)

```bash
DRY_RUN=true python main.py
```

Or set `DRY_RUN=true` in your `.env` file.

### Resume after interruption

The pipeline automatically resumes from where it left off — progress is tracked in `progress.json`.

---

## How It Works

### 1. Text Parsing (`services/text_parser.py`)

- Strips HTML with BeautifulSoup.
- Extracts labelled fields (Brand, Part Number, Fitment, etc.) using longest-prefix matching.
- Detects motorcycle make, model, and year ranges via regex.

### 2. LLM Enrichment (`services/llm_service.py`)

- Sends extracted data + raw description to OpenAI using **Structured Outputs** (`client.beta.chat.completions.parse`).
- Returns a validated Pydantic model with SEO metadata and gap-filled fields.

### 3. Priority Merge

Fields are resolved with strict priority:

```
Parser Base  →  Derived from Final Description  →  LLM (fallback only)
```

This ensures deterministic, parser-first results — the LLM can only fill gaps, never overwrite existing data.

### 4. Shopify Write-Back (`services/shopify_client.py`)

- Updates product title, type, tags, HTML description, and SEO metadata via `productUpdate`.
- Sets Shopify metafields via `metafieldsSet`.
- Automatic retry with exponential back-off on rate limits (HTTP 429) and transient failures.

---

## Contributing

1. Fork the repository
2. Create a feature branch (`git checkout -b feature/my-feature`)
3. Commit your changes (`git commit -m 'feat: add my feature'`)
4. Push to the branch (`git push origin feature/my-feature`)
5. Open a Pull Request

---

## Author

**Muhammad Faizan Aziz**  
Full-Stack & AI Backend Developer  
GitHub: [@Faizan-Aziz](https://github.com/Faizan-Aziz)

---

## License

This project is licensed under the [MIT License](LICENSE).
