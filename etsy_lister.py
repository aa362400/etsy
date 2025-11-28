"""Command-line helper to create Etsy listings from a structured product file.

The script posts directly to the Etsy V3 Open API. Provide credentials via
`ETSY_API_KEY` and `ETSY_ACCESS_TOKEN` environment variables and optionally
`ETSY_SHOP_ID` for the default shop.
"""
from __future__ import annotations

import argparse
import json
import logging
import os
from pathlib import Path
from typing import Any, Dict, Iterable, Mapping, MutableMapping

import requests
import yaml

API_BASE = "https://openapi.etsy.com/v3/application"
REQUIRED_FIELDS = {
    "title",
    "description",
    "price",
    "quantity",
    "taxonomy_id",
    "who_made",
    "when_made",
    "is_supply",
    "shipping_profile_id",
}


class EtsyListingError(RuntimeError):
    """Raised when the Etsy API returns an unexpected response."""


def load_product(path: Path) -> MutableMapping[str, Any]:
    """Load product data from a YAML or JSON file."""
    if not path.exists():
        raise FileNotFoundError(f"Product file not found: {path}")

    with path.open("r", encoding="utf-8") as handle:
        if path.suffix.lower() in {".yaml", ".yml"}:
            return yaml.safe_load(handle) or {}
        if path.suffix.lower() == ".json":
            return json.load(handle)
        raise ValueError("Unsupported product file type. Use YAML or JSON.")


def validate_product(data: Mapping[str, Any]) -> None:
    """Ensure the product definition has the minimum required attributes."""
    missing = [field for field in REQUIRED_FIELDS if field not in data]
    if missing:
        raise ValueError(
            f"Product file missing required fields: {', '.join(sorted(missing))}"
        )


def build_listing_payload(product: Mapping[str, Any]) -> Dict[str, Any]:
    """Extract listing fields from the loaded product mapping."""
    payload: Dict[str, Any] = {
        "title": product["title"],
        "description": product["description"],
        "price": str(product["price"]),
        "quantity": int(product["quantity"]),
        "taxonomy_id": int(product["taxonomy_id"]),
        "who_made": product["who_made"],
        "when_made": product["when_made"],
        "is_supply": bool(product["is_supply"]),
        "type": product.get("type", "physical"),
        "shipping_profile_id": int(product["shipping_profile_id"]),
    }

    optional_fields = [
        "return_policy_id",
        "shop_section_id",
        "tags",
        "materials",
        "style",
        "should_auto_renew",
        "production_partner_ids",
        "sku",
        "item_weight",
        "item_weight_unit",
        "item_length",
        "item_width",
        "item_height",
        "item_dimensions_unit",
    ]

    for field in optional_fields:
        if field in product and product[field] is not None:
            payload[field] = product[field]

    return payload


def create_session(api_key: str, access_token: str) -> requests.Session:
    session = requests.Session()
    session.headers.update(
        {
            "x-api-key": api_key,
            "Authorization": f"Bearer {access_token}",
            "Accept": "application/json",
        }
    )
    return session


def create_listing(
    session: requests.Session, shop_id: str, payload: Mapping[str, Any]
) -> int:
    url = f"{API_BASE}/shops/{shop_id}/listings"
    logging.info("Creating draft listing for shop %s", shop_id)
    response = session.post(url, json=payload, timeout=30)
    response.raise_for_status()
    data = response.json() if response.content else {}
    listing_id = data.get("listing_id") or data.get("data", {}).get("listing_id")
    if not listing_id:
        raise EtsyListingError(
            "Etsy API did not return listing_id. Full response: " + json.dumps(data)
        )
    logging.info("Draft listing created: %s", listing_id)
    return int(listing_id)


def upload_images(
    session: requests.Session, listing_id: int, images: Iterable[Mapping[str, Any]]
) -> None:
    url = f"{API_BASE}/listings/{listing_id}/images"
    for image in images:
        image_path = Path(image["path"]).expanduser()
        alt_text = image.get("alt_text") or image.get("alt")
        if not image_path.exists():
            raise FileNotFoundError(f"Image not found: {image_path}")

        logging.info("Uploading image %s for listing %s", image_path.name, listing_id)
        with image_path.open("rb") as img_handle:
            files = {"image": (image_path.name, img_handle, "application/octet-stream")}
            data = {"alt_text": alt_text} if alt_text else None
            response = session.post(url, files=files, data=data, timeout=30)
            response.raise_for_status()


def publish_listing(session: requests.Session, listing_id: int) -> None:
    url = f"{API_BASE}/listings/{listing_id}/publish"
    logging.info("Publishing listing %s", listing_id)
    response = session.post(url, timeout=30)
    response.raise_for_status()


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Create Etsy listings from YAML/JSON definitions. Provide Etsy API "
            "credentials via environment variables or explicit arguments."
        )
    )
    parser.add_argument(
        "--product-file",
        required=True,
        help="Path to YAML/JSON file describing the product listing.",
    )
    parser.add_argument(
        "--shop-id",
        default=os.getenv("ETSY_SHOP_ID"),
        help="Numeric shop ID. Defaults to ETSY_SHOP_ID env variable.",
    )
    parser.add_argument(
        "--api-key",
        default=os.getenv("ETSY_API_KEY"),
        help="Etsy API key (x-api-key). Defaults to ETSY_API_KEY env variable.",
    )
    parser.add_argument(
        "--access-token",
        default=os.getenv("ETSY_ACCESS_TOKEN"),
        help="OAuth access token. Defaults to ETSY_ACCESS_TOKEN env variable.",
    )
    parser.add_argument(
        "--publish",
        action="store_true",
        help="Publish the listing after uploading images. Default creates a draft.",
    )
    parser.add_argument(
        "--skip-images",
        action="store_true",
        help="Create the listing without uploading images.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print payloads without calling the Etsy API.",
    )
    parser.add_argument(
        "--verbose",
        action="store_true",
        help="Enable verbose logging.",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()

    logging.basicConfig(level=logging.INFO if args.verbose else logging.WARNING)
    if not args.api_key or not args.access_token:
        raise SystemExit("ETSY_API_KEY and ETSY_ACCESS_TOKEN are required")
    if not args.shop_id:
        raise SystemExit("Shop ID is required (set --shop-id or ETSY_SHOP_ID)")

    product = load_product(Path(args.product_file))
    validate_product(product)

    images = product.pop("images", [])
    payload = build_listing_payload(product)

    if args.dry_run:
        print("=== Listing payload ===")
        print(json.dumps(payload, indent=2, ensure_ascii=False))
        if images:
            print("\n=== Images ===")
            print(json.dumps(images, indent=2, ensure_ascii=False))
        return

    session = create_session(args.api_key, args.access_token)
    listing_id = create_listing(session, args.shop_id, payload)

    if images and not args.skip_images:
        upload_images(session, listing_id, images)

    if args.publish:
        publish_listing(session, listing_id)

    print(f"Listing ready: {listing_id}")


if __name__ == "__main__":
    main()
