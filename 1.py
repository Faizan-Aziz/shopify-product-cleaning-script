import requests

SHOP = "cheap-thrills-motorsports.myshopify.com"  # os.getenv("SHOPIFY_STORE")
ACCESS_TOKEN = "123"  # os.getenv("SHOPIFY_ACCESS_TOKEN")
API_VERSION = "2025-10"  # os.getenv("SHOPIFY_API_VERSION", "2025-10")

GRAPHQL_URL = f"https://{SHOP}/admin/api/2026-07/graphql.json"

HEADERS = {
    "X-Shopify-Access-Token": ACCESS_TOKEN,
    "Content-Type": "application/json",
}


def graphql_request(query, variables=None):
    response = requests.post(
        GRAPHQL_URL,
        headers=HEADERS,
        json={
            "query": query,
            "variables": variables or {}
        }
    )

    response.raise_for_status()

    result = response.json()

    if "errors" in result:
        raise Exception(result["errors"])

    return result["data"]


def find_product_position(target_title):

    query = """
    query GetProducts($cursor: String) {
      products(
        first: 250
        after: $cursor
        sortKey: ID
      ) {
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

    cursor = None
    position = 0

    while True:

        data = graphql_request(
            query,
            {
                "cursor": cursor
            }
        )

        products = data["products"]["nodes"]

        for product in products:

            position += 1

            if product["title"].strip().lower() == target_title.strip().lower():

                return {
                    "position": position,
                    "title": product["title"],
                    "id": product["id"],
                    "handle": product["handle"]
                }

        page_info = data["products"]["pageInfo"]

        if not page_info["hasNextPage"]:
            break

        cursor = page_info["endCursor"]

    return None


# ---------------------------
# SEARCH PRODUCT
# ---------------------------

title = "Suzuki 1999-2002 SV650/S Tail Light OEM"

result = find_product_position(title)

if result:

    print(f"Product found!")
    print(f"Position: {result['position']}")
    print(f"Title: {result['title']}")
    print(f"ID: {result['id']}")
    print(f"Handle: {result['handle']}")

else:

    print("Product not found")