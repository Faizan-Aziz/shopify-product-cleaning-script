# AI-Powered Shopify Catalog & SEO Optimization Engine

## 📌 Overview
An automated Python backend application designed to overhaul massive e-commerce catalogs. It leverages the OpenAI API (`gpt-4o-mini`) to read, clean, and standardize product listings at scale. The system intelligently extracts specifications, determines fitment, writes high-converting SEO meta-descriptions, and safely injects structured Metafields back into Shopify.

## 🚀 Core Features
* **GraphQL API Architecture:** High-speed data retrieval and product mutations using Shopify's GraphQL API with robust paginated query loops.
* **Data Extraction & HTML Sanitization:** Uses `BeautifulSoup` and Regex to strip heavy, legacy HTML and extract base attributes (Brand, Part Number, Fitment, Materials).
* **LLM Integration:** Prompts an AI agent to distill messy descriptions into core facts, generating 70-character SEO titles and 160-character meta descriptions in strict JSON format.
* **Automated Metafield Mapping:** Populates up to 16 distinct Shopify Metafields (e.g., `custom.vehicle_make`, `custom.part_category`) to enable advanced storefront filtering.
* **Fault-Tolerant Batch Processing:** Engineered with a "Dry Run" safety mode, automatic cursor tracking (`progress.json`), and comprehensive batch execution logging (`process_log.txt`). It can pause, resume, and track errors without duplicating updates.

## 🛠️ Technology Stack
* **Backend:** Python
* **APIs:** Shopify GraphQL API, OpenAI API (GPT-4o-mini)
* **Data Processing:** BeautifulSoup 4, Regex, JSON

## ⚙️ Installation & Setup

1. **Clone the repository**
   ```bash
   git clone [https://github.com/yourusername/shopify-ai-catalog-optimizer.git](https://github.com/yourusername/shopify-ai-catalog-optimizer.git)
   cd shopify-ai-catalog-optimizer
   ```

2. **Set up a virtual environment**
   ```bash
   python -m venv venv
   source venv/bin/activate  # On Windows: venv\Scripts\activate
   ```

3. **Install dependencies**
   ```bash
   pip install -r requirements.txt
   ```

4. **Configure Environment Variables**
   Create a `.env` file in the root directory:
   ```env
   SHOPIFY_STORE_URL="your-store.myshopify.com"
   SHOPIFY_ACCESS_TOKEN="shpat_your_access_token_here"
   OPENAI_API_KEY="sk-your_openai_api_key_here"
   ```

## 💻 Usage

**Test Mode (Dry Run)**
Safely process products and view the AI's output without making any changes to your live Shopify store:
```bash
python run_optimizer.py --dry-run
```

**Production Mode**
Execute the script to update live Shopify products and metafields:
```bash
python run_optimizer.py --production
```

## 📊 Logging & State Management
* **`progress.json`**: Automatically saves the last processed GraphQL cursor. If the script drops connection, it resumes exactly where it left off.
* **`process_log.txt`**: Appends detailed logs of updated items, skipped items, and API rate limit events.

## 👨‍💻 Author
**Muhammad Faizan Aziz**  
Full-Stack & AI Backend Developer
