"""
Application configuration via environment variables.

Uses Pydantic BaseSettings to load and validate all secrets and
configuration from a `.env` file or the process environment.
"""

from typing import Optional
from pydantic_settings import BaseSettings
from pydantic import Field


class Settings(BaseSettings):
    """Central configuration loaded from environment variables."""

    # ── Shopify ──────────────────────────────────────────────────────────
    shopify_store: str = Field(
        default="",
        description="Shopify store domain, e.g. your-store.myshopify.com",
    )
    shopify_access_token: str = Field(
        default="",
        description="Shopify Admin API access token",
    )
    shopify_api_version: str = Field(
        default="2025-10",
        description="Shopify Admin API version",
    )

    # ── OpenAI ───────────────────────────────────────────────────────────
    openai_api_key: str = Field(
        default="",
        description="OpenAI API key",
    )
    openai_model: str = Field(
        default="gpt-4o-mini",
        description="OpenAI model to use for catalog enrichment",
    )

    # ── Processing ───────────────────────────────────────────────────────
    batch_size: int = Field(
        default=5,
        description="Number of products to process per run",
    )
    dry_run: bool = Field(
        default=False,
        description="When True, skip all Shopify write operations",
    )
    log_file: str = Field(
        default="process_log.txt",
        description="Path to the append-only execution log",
    )
    progress_file: str = Field(
        default="progress.json",
        description="Path to the JSON progress state file",
    )
    openai_timeout: int = Field(
        default=30,
        description="Timeout in seconds for OpenAI API calls",
    )
    shopify_timeout: int = Field(
        default=30,
        description="Timeout in seconds for Shopify API calls",
    )

    # ── Derived ──────────────────────────────────────────────────────────
    @property
    def graphql_url(self) -> str:
        return (
            f"https://{self.shopify_store}/admin/api/"
            f"{self.shopify_api_version}/graphql.json"
        )

    def validate_credentials(self) -> None:
        """Ensure all required environment variables are present before execution."""
        missing = []
        if not self.shopify_store:
            missing.append("SHOPIFY_STORE")
        if not self.shopify_access_token:
            missing.append("SHOPIFY_ACCESS_TOKEN")
        if not self.openai_api_key:
            missing.append("OPENAI_API_KEY")
        if missing:
            raise ValueError(
                f"Missing required environment variable(s): {', '.join(missing)}. "
                "Please check your .env file or environment configuration."
            )

    model_config = {"env_file": ".env", "env_file_encoding": "utf-8", "extra": "ignore"}


# Singleton instance – import this everywhere
settings = Settings()
