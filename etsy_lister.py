"""Command-line helper to create Etsy listings from a structured product file.

This revision removes the need to manually paste long-lived API tokens. Run the
``auth`` command once to authorize the app against your shop, then the stored
token is reused whenever you call the ``list`` command to create listings.
"""
from __future__ import annotations

import argparse
import base64
import hashlib
import json
import logging
import os
import time
from pathlib import Path
from typing import Any, Dict, Iterable, Mapping, MutableMapping, Optional, Tuple
from urllib.parse import urlencode, urlparse, parse_qs

import requests
import yaml

API_BASE = "https://openapi.etsy.com/v3/application"
AUTH_BASE = "https://www.etsy.com/oauth/connect"
TOKEN_URL = "https://openapi.etsy.com/v3/public/oauth/token"
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


def _generate_pkce_pair() -> Tuple[str, str]:
    verifier = base64.urlsafe_b64encode(os.urandom(64)).rstrip(b"=").decode()
    challenge = base64.urlsafe_b64encode(
        hashlib.sha256(verifier.encode()).digest()
    ).rstrip(b"=").decode()
    return verifier, challenge


def start_local_listener(host: str, port: int, timeout: int = 120) -> str:
    """Start a tiny HTTP server to capture the OAuth redirect code."""

    from http.server import BaseHTTPRequestHandler, HTTPServer

    code_holder: Dict[str, Optional[str]] = {"code": None}

    class Handler(BaseHTTPRequestHandler):  # type: ignore[misc]
        def do_GET(self) -> None:  # noqa: N802  (BaseHTTPRequestHandler naming)
            parsed = urlparse(self.path)
            params = parse_qs(parsed.query)
            code_holder["code"] = params.get("code", [None])[0]
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.end_headers()
            self.wfile.write(
                b"<html><body><h2>Etsy authorization received.</h2>"
                b"You can close this window.</body></html>"
            )

        def log_message(self, format: str, *args: Any) -> None:  # noqa: A003
            return

    server = HTTPServer((host, port), Handler)
    server.timeout = timeout

    start = time.time()
    while time.time() - start < timeout and code_holder["code"] is None:
        server.handle_request()

    if code_holder["code"] is None:
        raise TimeoutError("Did not receive authorization code before timeout")
    return code_holder["code"]


def exchange_code_for_token(
    client_id: str, code: str, redirect_uri: str, verifier: str
) -> Dict[str, Any]:
    data = {
        "grant_type": "authorization_code",
        "client_id": client_id,
        "redirect_uri": redirect_uri,
        "code": code,
        "code_verifier": verifier,
    }
    response = requests.post(TOKEN_URL, data=data, timeout=30)
    response.raise_for_status()
    return response.json()


def refresh_access_token(client_id: str, refresh_token: str) -> Dict[str, Any]:
    data = {
        "grant_type": "refresh_token",
        "client_id": client_id,
        "refresh_token": refresh_token,
    }
    response = requests.post(TOKEN_URL, data=data, timeout=30)
    response.raise_for_status()
    return response.json()


def save_tokens(tokens: Mapping[str, Any], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        json.dump(tokens, handle, ensure_ascii=False, indent=2)


def load_tokens(path: Path) -> Optional[MutableMapping[str, Any]]:
    if not path.exists():
        return None
    with path.open("r", encoding="utf-8") as handle:
        return json.load(handle)


def ensure_access_token(client_id: str, token_path: Path) -> str:
    tokens = load_tokens(token_path)
    if not tokens:
        raise SystemExit(
            f"No token file found at {token_path}. Run 'auth' command first."
        )

    expires_at = tokens.get("expires_at")
    if expires_at and expires_at <= time.time():
        logging.info("Refreshing expired access token")
        refreshed = refresh_access_token(client_id, tokens["refresh_token"])
        refreshed["expires_at"] = time.time() + int(refreshed.get("expires_in", 0))
        save_tokens(refreshed, token_path)
        tokens = refreshed

    return tokens["access_token"]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Authorize once, then create Etsy listings from YAML/JSON definitions "
            "without manually managing tokens."
        )
    )

    parser.add_argument(
        "--client-id",
        default=os.getenv("ETSY_CLIENT_ID"),
        help="Etsy App client_id (formerly API key).",
    )
    parser.add_argument(
        "--token-file",
        default=os.getenv("ETSY_TOKEN_FILE", "~/.etsy_tokens.json"),
        help="Where to cache OAuth tokens after binding the shop.",
    )
    parser.add_argument(
        "--verbose",
        action="store_true",
        help="Enable verbose logging.",
    )

    subparsers = parser.add_subparsers(dest="command", required=True)

    auth_cmd = subparsers.add_parser(
        "auth", help="Bind a shop by completing the Etsy OAuth flow."
    )
    auth_cmd.add_argument(
        "--redirect-host",
        default="localhost",
        help="Host for the temporary callback server (default: localhost).",
    )
    auth_cmd.add_argument(
        "--redirect-port",
        type=int,
        default=8787,
        help="Port for the temporary callback server (default: 8787).",
    )
    auth_cmd.add_argument(
        "--scopes",
        default="listings_r listings_w shops_r transactions_r",
        help="Space-separated scopes to request during authorization.",
    )
    auth_cmd.add_argument(
        "--redirect-path",
        default="/etsy/oauth/callback",
        help="Path Etsy should redirect to after consent.",
    )

    list_cmd = subparsers.add_parser(
        "list", help="Create a listing from a structured product file."
    )
    list_cmd.add_argument(
        "--product-file",
        required=True,
        help="Path to YAML/JSON file describing the product listing.",
    )
    list_cmd.add_argument(
        "--shop-id",
        default=os.getenv("ETSY_SHOP_ID"),
        help="Numeric shop ID. Defaults to ETSY_SHOP_ID env variable.",
    )
    list_cmd.add_argument(
        "--publish",
        action="store_true",
        help="Publish the listing after uploading images. Default creates a draft.",
    )
    list_cmd.add_argument(
        "--skip-images",
        action="store_true",
        help="Create the listing without uploading images.",
    )
    list_cmd.add_argument(
        "--dry-run",
        action="store_true",
        help="Print payloads without calling the Etsy API.",
    )

    return parser.parse_args()


def run_auth(args: argparse.Namespace) -> None:
    if not args.client_id:
        raise SystemExit("Client ID is required. Set --client-id or ETSY_CLIENT_ID")

    redirect_uri = (
        f"http://{args.redirect_host}:{args.redirect_port}{args.redirect_path}"
    )
    verifier, challenge = _generate_pkce_pair()
    params = {
        "response_type": "code",
        "redirect_uri": redirect_uri,
        "scope": args.scopes,
        "client_id": args.client_id,
        "code_challenge": challenge,
        "code_challenge_method": "S256",
    }
    auth_url = f"{AUTH_BASE}?{urlencode(params)}"

    print("1) Open this URL in your browser and approve the app:")
    print(auth_url)
    print("2) Waiting for Etsy to redirect back and capture the code...")

    try:
        code = start_local_listener(args.redirect_host, args.redirect_port)
    except TimeoutError as exc:  # pragma: no cover - interactive flow
        raise SystemExit(f"Authorization timeout: {exc}")

    print("Received authorization code. Exchanging for tokens...")
    tokens = exchange_code_for_token(args.client_id, code, redirect_uri, verifier)
    tokens["expires_at"] = time.time() + int(tokens.get("expires_in", 0))
    token_path = Path(args.token_file).expanduser()
    save_tokens(tokens, token_path)

    print(f"Tokens saved to {token_path}. You can now run the 'list' command.")


def run_list(args: argparse.Namespace) -> None:
    if not args.client_id:
        raise SystemExit("Client ID is required. Set --client-id or ETSY_CLIENT_ID")
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

    token_path = Path(args.token_file).expanduser()
    access_token = ensure_access_token(args.client_id, token_path)
    session = create_session(args.client_id, access_token)
    listing_id = create_listing(session, args.shop_id, payload)

    if images and not args.skip_images:
        upload_images(session, listing_id, images)

    if args.publish:
        publish_listing(session, listing_id)

    print(f"Listing ready: {listing_id}")


def main() -> None:
    args = parse_args()
    logging.basicConfig(level=logging.INFO if args.verbose else logging.WARNING)

    if args.command == "auth":
        run_auth(args)
    elif args.command == "list":
        run_list(args)
    else:  # pragma: no cover - defensive
        raise SystemExit(f"Unknown command: {args.command}")


if __name__ == "__main__":
    main()
