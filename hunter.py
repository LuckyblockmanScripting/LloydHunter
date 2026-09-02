import csv
import html
import os
import re
import time
import base64
from datetime import datetime, timezone
from urllib.parse import urljoin, urlparse, parse_qs

import requests
from bs4 import BeautifulSoup


SITE_URL = "https://luckyblockmanscripting.github.io/LloydHunter/"
RESULTS_FILE = "results.csv"
TELEGRAM_OFFSET_FILE = "telegram_offset.txt"
BUDGET_PLN = 1000.0


RATES = {
    "PLN": 1.0,
    "EUR": 4.25,
    "USD": 3.65,
    "GBP": 4.95,
    "CAD": 2.65,
    "AUD": 2.40,
}


SEARCHES = {
    "OLX": [
        "njo0108",
        "5004076",
        "Lloyd DX",
        "Lloyd Ninjago",
    ],
    "Vinted": [
        "njo0108",
        "5004076",
        "Lloyd DX",
        "Lloyd Ninjago",
    ],
    "BrickLink": [
        "njo0108",
        "5004076",
    ],
    "DuckDuckGo": [
        "njo0108",
        "5004076",
        '"Lloyd DX" Ninjago',
        '"Lloyd DX" LEGO',
        '"Lloyd Ninjago" minifigure',
        '"Lloyd" "DX" minifigure',
        '"Loyd" Ninjago minifigure',
        '"Lloid" Ninjago minifigure',
        '"Ninjago" minifigure lot Lloyd',
        '"Ninjago" figures lot',
    ],
}


EBAY_SEARCHES = [
    "njo0108",
    "5004076",
    '"Lloyd DX" Ninjago',
    '"Lloyd Ninjago" minifigure',
    '"Lloyd" "DX" LEGO minifigure',
]


# eBay marketplace IDs.
EBAY_MARKETPLACES = [
    ("EBAY_US", "USD"),
    ("EBAY_GB", "GBP"),
    ("EBAY_DE", "EUR"),
    ("EBAY_CA", "CAD"),
    ("EBAY_AU", "AUD"),
]


HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/139.0 Safari/537.36"
    ),
    "Accept-Language": "en-US,en;q=0.9",
}


POSITIVE_SCORE = {
    "njo0108": 50,
    "5004076": 45,
    "lloyd dx": 30,
    "lloyd": 10,
    "ninjago": 10,
    "complete": 20,
    "100% complete": 25,
    "authentic": 15,
    "genuine": 15,
    "original": 5,
    "target exclusive": 15,
    "target": 5,
    "rare": 5,
}


NEGATIVE_SCORE = {
    "custom": -40,
    "fake": -50,
    "replica": -50,
    "reproduction": -50,
    "UV": -50,
    "missing legs": -30,
    "without legs": -30,
    "no legs": -30,
    "legs only": -40,
    "torso only": -40,
    "head only": -40,
    "instructions": -20,
    "sticker": -20,
    "stickers": -15,
    "compatible": -30,
    "not lego": -50,
}


DEAD_TERMS = [
    "page not found",
    "listing has ended",
    "item has ended",
    "no longer available",
    "listing ended",
    "this item has been removed",
    "item has been removed",
    "listing removed",
    "sold out",
    "out of stock",
    "unavailable",
]


OFFER_SIGNALS = [
    "add to cart",
    "buy now",
    "buy it now",
    "make offer",
    "add to bag",
    "add to basket",
    "quantity",
    "condition",
    "seller",
    "item number",
    "listing",
]


def clean_text(value):
    return re.sub(
        r"\s+",
        " ",
        html.unescape(str(value or "")),
    ).strip()


def normalize_url(url):
    url = clean_text(url)

    if not url:
        return ""

    if url.startswith("//"):
        url = "https:" + url

    if url.startswith("/"):
        url = urljoin(
            "https://duckduckgo.com",
            url,
        )

    parsed = urlparse(url)

    if parsed.netloc and "duckduckgo.com" in parsed.netloc.lower():
        params = parse_qs(parsed.query)
        destination = params.get("uddg", [None])[0]

        if destination:
            return destination

    return url


def parse_price(text):
    text = clean_text(text)

    if not text:
        return None, None

    patterns = [
        (r"(?:PLN|zł)\s*([0-9][0-9\s.,]*)", "PLN"),
        (r"([0-9][0-9\s.,]*)\s*(?:PLN|zł)", "PLN"),
        (r"€\s*([0-9][0-9\s.,]*)", "EUR"),
        (r"([0-9][0-9\s.,]*)\s*€", "EUR"),
        (r"\$\s*([0-9][0-9\s.,]*)", "USD"),
        (r"USD\s*([0-9][0-9\s.,]*)", "USD"),
        (r"£\s*([0-9][0-9\s.,]*)", "GBP"),
        (r"GBP\s*([0-9][0-9\s.,]*)", "GBP"),
        (r"CAD\s*\$?\s*([0-9][0-9\s.,]*)", "CAD"),
        (r"AUD\s*\$?\s*([0-9][0-9\s.,]*)", "AUD"),
    ]

    for pattern, currency in patterns:
        match = re.search(
            pattern,
            text,
            re.IGNORECASE,
        )

        if not match:
            continue

        raw = match.group(1).replace(" ", "")

        if "," in raw and "." in raw:
            if raw.rfind(",") > raw.rfind("."):
                raw = raw.replace(".", "")
                raw = raw.replace(",", ".")
            else:
                raw = raw.replace(",", "")

        elif "," in raw:
            parts = raw.split(",")

            if len(parts[-1]) in (1, 2):
                raw = raw.replace(",", ".")
            else:
                raw = raw.replace(",", "")

        elif "." in raw:
            parts = raw.split(".")

            if len(parts[-1]) == 3:
                raw = raw.replace(".", "")

        try:
            return float(raw), currency
        except ValueError:
            continue

    return None, None


def to_pln(amount, currency):
    if amount is None:
        return None

    if currency not in RATES:
        return None

    return amount * RATES[currency]


def score_listing(title, description=""):
    text = clean_text(
        f"{title} {description}"
    ).lower()

    score = 0

    for term, points in POSITIVE_SCORE.items():
        if term in text:
            score += points

    for term, points in NEGATIVE_SCORE.items():
        if term in text:
            score += points

    return score


def deal_status(price_pln, score):
    if price_pln is None:
        return "NO PRICE"

    if price_pln <= 400 and score >= 60:
        return "INSANE DEAL"

    if price_pln <= 600 and score >= 50:
        return "GREAT DEAL"

    if price_pln <= 800 and score >= 45:
        return "GOOD DEAL"

    if price_pln <= 1000 and score >= 35:
        return "POSSIBLE DEAL"

    return "CHECK"


def is_alert_worthy(price_pln, score, verified):
    return (
        verified
        and price_pln is not None
        and price_pln <= BUDGET_PLN
        and score >= 30
    )


def verify(url):
    url = normalize_url(url)

    if not url:
        return False, "No URL"

    try:
        response = requests.get(
            url,
            headers=HEADERS,
            timeout=15,
            allow_redirects=True,
        )

    except requests.RequestException as exc:
        return False, f"Request error: {exc}"

    if response.status_code >= 400:
        return False, f"HTTP {response.status_code}"

    body = clean_text(
        BeautifulSoup(
            response.text,
            "html.parser",
        ).get_text(" ")
    )

    lower_body = body.lower()

    for term in DEAD_TERMS:
        if term in lower_body:
            return False, f"Dead page: {term}"

    signal_count = sum(
        1
        for signal in OFFER_SIGNALS
        if signal in lower_body
    )

    if signal_count < 2:
        return False, "Not enough listing signals"

    return True, response.url


def get_ebay_token():
    client_id = os.getenv("EBAY_CLIENT_ID")
    client_secret = os.getenv("EBAY_CLIENT_SECRET")

    if not client_id or not client_secret:
        print(
            "eBay API secrets are missing. "
            "Skipping eBay API."
        )
        return None

    credentials = (
        f"{client_id}:{client_secret}"
    ).encode("utf-8")

    encoded_credentials = base64.b64encode(
        credentials
    ).decode("ascii")

    headers = {
        "Authorization": (
            f"Basic {encoded_credentials}"
        ),
        "Content-Type": (
            "application/x-www-form-urlencoded"
        ),
    }

    data = {
        "grant_type": "client_credentials",
        "scope": (
            "https://api.ebay.com/oauth/api_scope"
        ),
    }

    try:
        response = requests.post(
            "https://api.ebay.com/identity/v1/oauth2/token",
            headers=headers,
            data=data,
            timeout=20,
        )

    except requests.RequestException as exc:
        print(
            f"eBay OAuth request failed: {exc}"
        )
        return None

    if response.status_code != 200:
        print(
            f"eBay OAuth failed: "
            f"HTTP {response.status_code}"
        )
        print(response.text[:500])
        return None

    try:
        payload = response.json()
    except ValueError:
        print(
            "eBay OAuth returned invalid JSON."
        )
        return None

    token = payload.get("access_token")

    if not token:
        print(
            "eBay OAuth response did not contain "
            "an access token."
        )
        return None

    print("eBay API authentication successful.")

    return token


def ebay_search(
    token,
    query,
    marketplace_id,
    currency,
):
    url = (
        "https://api.ebay.com/"
        "buy/browse/v1/item_summary/search"
    )

    headers = {
        "Authorization": f"Bearer {token}",
        "Accept": "application/json",
        "X-EBAY-C-MARKETPLACE-ID": marketplace_id,
    }

    params = {
        "q": query,
        "limit": 50,
        "sort": "price",
    }

    try:
        response = requests.get(
            url,
            headers=headers,
            params=params,
            timeout=20,
        )

    except requests.RequestException as exc:
        print(
            f"eBay search failed for "
            f"{marketplace_id} / {query}: {exc}"
        )
        return []

    if response.status_code != 200:
        print(
            f"eBay search failed for "
            f"{marketplace_id} / {query}: "
            f"HTTP {response.status_code}"
        )
        print(response.text[:500])
        return []

    try:
        payload = response.json()
    except ValueError:
        print("eBay returned invalid JSON.")
        return []

    results = []

    for item in payload.get(
        "itemSummaries",
        [],
    ):
        title = clean_text(
            item.get("title")
        )

        item_url = normalize_url(
            item.get("itemWebUrl")
            or item.get("itemAffiliateWebUrl")
        )

        item_id = clean_text(
            item.get("itemId")
        )

        price_data = item.get("price") or {}

        value = price_data.get("value")

        item_currency = clean_text(
            price_data.get("currency")
        ) or currency

        try:
            amount = (
                float(value)
                if value is not None
                else None
            )
        except (TypeError, ValueError):
            amount = None

        condition = clean_text(
            item.get("condition")
        )

        buying_options = ", ".join(
            clean_text(option)
            for option in item.get(
                "buyingOptions",
                [],
            )
        )

        seller = item.get("seller") or {}

        seller_name = clean_text(
            seller.get("username")
        )

        localized_aspects = (
            item.get("localizedAspects")
            or []
        )

        aspect_text = " ".join(
            (
                f"{clean_text(a.get('name'))} "
                f"{clean_text(a.get('value'))}"
            )
            for a in localized_aspects
            if isinstance(a, dict)
        )

        description = clean_text(
            f"{condition} "
            f"{buying_options} "
            f"{seller_name} "
            f"{aspect_text}"
        )

        price_pln = to_pln(
            amount,
            item_currency,
        )

        score = score_listing(
            title,
            description,
        )

        results.append(
            {
                "marketplace": (
                    f"eBay "
                    f"{marketplace_id.replace('EBAY_', '')}"
                ),
                "title": title,
                "url": item_url,
                "price": amount,
                "currency": item_currency,
                "price_pln": price_pln,
                "score": score,
                "status": deal_status(
                    price_pln,
                    score,
                ),
                "verified": True,
                "verification": (
                    "Verified by eBay Browse API"
                ),
                "item_id": item_id,
            }
        )

    return results


def search_ebay():
    token = get_ebay_token()

    if not token:
        return []

    all_results = []
    seen_ids = set()

    for marketplace_id, currency in (
        EBAY_MARKETPLACES
    ):
        for query in EBAY_SEARCHES:
            print(
                f"eBay API: "
                f"{marketplace_id} -> {query}"
            )

            results = ebay_search(
                token,
                query,
                marketplace_id,
                currency,
            )

            for result in results:
                key = (
                    result["item_id"]
                    or result["url"]
                )

                if not key:
                    continue

                if key in seen_ids:
                    continue

                seen_ids.add(key)
                all_results.append(result)

    return all_results


def search_duckduckgo(query):
    url = (
        "https://html.duckduckgo.com/html/"
    )

    params = {
        "q": query,
    }

    try:
        response = requests.get(
            url,
            params=params,
            headers=HEADERS,
            timeout=15,
        )

        response.raise_for_status()

    except requests.RequestException as exc:
        print(
            f"DuckDuckGo error for "
            f"{query}: {exc}"
        )
        return []

    soup = BeautifulSoup(
        response.text,
        "html.parser",
    )

    results = []

    for result in soup.select(".result"):
        link = result.select_one(
            ".result__a"
        )

        if not link:
            continue

        title = clean_text(
            link.get_text(
                " ",
                strip=True,
            )
        )

        href = normalize_url(
            link.get("href", "")
        )

        snippet_node = result.select_one(
            ".result__snippet"
        )

        snippet = (
            clean_text(
                snippet_node.get_text(
                    " ",
                    strip=True,
                )
            )
            if snippet_node
            else ""
        )

        price, currency = parse_price(
            f"{title} {snippet}"
        )

        price_pln = to_pln(
            price,
            currency,
        )

        score = score_listing(
            title,
            snippet,
        )

        results.append(
            {
                "marketplace": "DuckDuckGo",
                "title": title,
                "url": href,
                "price": price,
                "currency": currency or "",
                "price_pln": price_pln,
                "score": score,
                "status": deal_status(
                    price_pln,
                    score,
                ),
                "verified": False,
                "verification": "Not checked yet",
                "item_id": "",
            }
        )

    return results


def generic_marketplace_search(
    marketplace,
    query,
):
    site_map = {
        "OLX": "site:olx.pl",
        "Vinted": "site:vinted.pl",
        "BrickLink": "site:bricklink.com",
    }

    site = site_map[marketplace]

    ddg_query = (
        f"{site} {query}"
    )

    results = search_duckduckgo(
        ddg_query
    )

    for result in results:
        result["marketplace"] = marketplace

    return results


def verify_and_score(results):
    checked = []

    for result in results:
        url = normalize_url(
            result.get("url", "")
        )

        result["url"] = url

        if not url:
            result["verified"] = False
            result["verification"] = "No URL"
            checked.append(result)
            continue

        if result.get(
            "marketplace",
            "",
        ).startswith("eBay"):
            result["verified"] = True
            result["verification"] = (
                "Verified by eBay Browse API"
            )
            checked.append(result)
            continue

        verified, verification = verify(
            url
        )

        result["verified"] = verified
        result["verification"] = verification

        if verified:
            result["score"] = score_listing(
                result.get("title", ""),
                verification,
            )

            if result.get(
                "price_pln"
            ) is not None:
                result["status"] = deal_status(
                    result["price_pln"],
                    result["score"],
                )

        checked.append(result)

    return checked


def deduplicate(results):
    unique = {}

    for result in results:
        url = normalize_url(
            result.get("url", "")
        )

        title = clean_text(
            result.get("title", "")
        ).lower()

        key = (
            url.lower()
            if url
            else title
        )

        if not key:
            continue

        existing = unique.get(key)

        if (
            existing is None
            or result.get("score", 0)
            > existing.get("score", 0)
        ):
            unique[key] = result

    return list(unique.values())


def send_telegram_message(text):
    token = os.getenv(
        "TELEGRAM_BOT_TOKEN"
    )

    chat_id = os.getenv(
        "TELEGRAM_CHAT_ID"
    )

    if not token or not chat_id:
        print(
            "Telegram secrets are missing."
        )
        return False

    url = (
        f"https://api.telegram.org/"
        f"bot{token}/sendMessage"
    )

    try:
        response = requests.post(
            url,
            data={
                "chat_id": chat_id,
                "text": text,
                "disable_web_page_preview": False,
            },
            timeout=15,
        )

    except requests.RequestException as exc:
        print(
            f"Telegram error: {exc}"
        )
        return False

    if response.status_code != 200:
        print(
            f"Telegram failed: "
            f"HTTP {response.status_code}"
        )
        print(response.text[:500])
        return False

    return True


def process_telegram_commands():
    token = os.getenv(
        "TELEGRAM_BOT_TOKEN"
    )

    chat_id = os.getenv(
        "TELEGRAM_CHAT_ID"
    )

    if not token or not chat_id:
        return

    offset = 0

    if os.path.exists(
        TELEGRAM_OFFSET_FILE
    ):
        try:
            with open(
                TELEGRAM_OFFSET_FILE,
                "r",
                encoding="utf-8",
            ) as file:
                offset = int(
                    file.read().strip() or "0"
                )

        except (ValueError, OSError):
            offset = 0

    url = (
        f"https://api.telegram.org/"
        f"bot{token}/getUpdates"
    )

    try:
        response = requests.get(
            url,
            params={
                "offset": offset,
                "timeout": 1,
                "allowed_updates": (
                    '["message"]'
                ),
            },
            timeout=10,
        )

        response.raise_for_status()

        payload = response.json()

    except (
        requests.RequestException,
        ValueError,
    ) as exc:
        print(
            f"Telegram command check failed: "
            f"{exc}"
        )
        return

    updates = payload.get(
        "result",
        [],
    )

    highest_update_id = offset - 1

    for update in updates:
        update_id = update.get(
            "update_id",
            0,
        )

        highest_update_id = max(
            highest_update_id,
