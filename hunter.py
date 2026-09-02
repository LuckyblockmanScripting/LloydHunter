import csv
import html
import os
import re
import time
from datetime import datetime
from urllib.parse import quote_plus, urljoin, urlparse, parse_qs, unquote

import requests
from bs4 import BeautifulSoup


# ============================================================
# SETTINGS
# ============================================================

MAX_PRICE_PLN = 1000

REQUEST_TIMEOUT = 20
DELAY_BETWEEN_REQUESTS = 2

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/139.0 Safari/537.36"
    ),
    "Accept-Language": "pl-PL,pl;q=0.9,en-US;q=0.8,en;q=0.7",
}

# Approximate exchange rates to PLN.
# These are deliberately simple for now.
RATES_TO_PLN = {
    "PLN": 1.0,
    "EUR": 4.25,
    "USD": 3.65,
    "GBP": 4.95,
    "CAD": 2.65,
    "AUD": 2.40,
    "CZK": 0.17,
    "DKK": 0.57,
    "SEK": 0.37,
    "NOK": 0.37,
}

SEARCH_PHRASES = [
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
]

# Extra marketplace-specific searches.
MARKETPLACE_SEARCHES = {
    "eBay": [
        "njo0108",
        "5004076",
        "Lloyd DX",
        "Lloyd Ninjago minifigure",
        "Lloyd Dragon minifigure",
        "Ninjago Lloyd minifigure",
    ],
    "OLX": [
        "njo0108",
        "5004076",
        "Lloyd DX",
        "Lloyd Ninjago",
        "Lloyd minifigurka",
        "Ninjago minifigurki",
    ],
    "Vinted": [
        "njo0108",
        "5004076",
        "Lloyd DX",
        "Lloyd Ninjago",
        "Lloyd minifigure",
        "Ninjago minifigure",
    ],
    "BrickLink": [
        "njo0108",
        "5004076",
    ],
}


# ============================================================
# TELEGRAM
# ============================================================

TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")


def send_telegram(message):
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        print("Telegram secrets are not configured.")
        return

    url = (
        f"https://api.telegram.org/bot"
        f"{TELEGRAM_BOT_TOKEN}/sendMessage"
    )

    data = {
        "chat_id": TELEGRAM_CHAT_ID,
        "text": message,
        "disable_web_page_preview": False,
    }

    try:
        response = requests.post(
            url,
            data=data,
            timeout=REQUEST_TIMEOUT,
        )

        if response.status_code != 200:
            print(
                "Telegram error:",
                response.status_code,
                response.text[:300],
            )

    except requests.RequestException as exc:
        print("Telegram request error:", exc)


# ============================================================
# URL HELPERS
# ============================================================

def normalize_url(url, base_url=None):
    if not url:
        return None

    url = html.unescape(url).strip()

    # DuckDuckGo sometimes returns protocol-relative redirect URLs.
    if url.startswith("//"):
        url = "https:" + url

    if base_url:
        url = urljoin(base_url, url)

    parsed = urlparse(url)

    # Unwrap DuckDuckGo redirect links.
    if "duckduckgo.com" in parsed.netloc:
        query = parse_qs(parsed.query)

        if "uddg" in query and query["uddg"]:
            destination = unquote(query["uddg"][0])

            if destination.startswith("http://") or destination.startswith(
                "https://"
            ):
                url = destination

    # Only accept normal HTTP(S) URLs.
    parsed = urlparse(url)

    if parsed.scheme not in ("http", "https"):
        return None

    if not parsed.netloc:
        return None

    return url


def canonical_url(url):
    """
    Removes common tracking parameters so the same listing
    found by multiple searches becomes one result.
    """

    url = normalize_url(url)

    if not url:
        return None

    parsed = urlparse(url)

    tracking_parameters = {
        "utm_source",
        "utm_medium",
        "utm_campaign",
        "utm_term",
        "utm_content",
        "fbclid",
        "gclid",
        "ref",
        "referrer",
    }

    query = parse_qs(parsed.query, keep_blank_values=True)

    cleaned = []

    for key, values in query.items():
        if key.lower() in tracking_parameters:
            continue

        for value in values:
            cleaned.append(
                f"{quote_plus(key)}={quote_plus(value)}"
            )

    query_string = "&".join(cleaned)

    result = parsed._replace(
        query=query_string,
        fragment="",
    )

    return result.geturl()


# ============================================================
# PRICE PARSING
# ============================================================

PRICE_PATTERNS = [
    (
        "PLN",
        r"(?i)(?:PLN|zł)\s*([0-9][0-9\s.,]*)",
    ),
    (
        "PLN",
        r"([0-9][0-9\s.,]*)\s*(?:PLN|zł)",
    ),
    (
        "EUR",
        r"(?i)(?:EUR|€)\s*([0-9][0-9\s.,]*)",
    ),
    (
        "EUR",
        r"([0-9][0-9\s.,]*)\s*(?:EUR|€)",
    ),
    (
        "USD",
        r"(?i)(?:USD|\$)\s*([0-9][0-9\s.,]*)",
    ),
    (
        "USD",
        r"([0-9][0-9\s.,]*)\s*(?:USD)",
    ),
    (
        "GBP",
        r"(?i)(?:GBP|£)\s*([0-9][0-9\s.,]*)",
    ),
    (
        "CAD",
        r"(?i)(?:CAD)\s*([0-9][0-9\s.,]*)",
    ),
    (
        "AUD",
        r"(?i)(?:AUD)\s*([0-9][0-9\s.,]*)",
    ),
    (
        "CZK",
        r"([0-9][0-9\s.,]*)\s*(?:Kč|CZK)",
    ),
]


def clean_number(number_string):
    value = number_string.strip()
    value = value.replace("\xa0", "")
    value = value.replace(" ", "")

    # Handle Polish / European formatting.
    if "," in value and "." in value:
        if value.rfind(",") > value.rfind("."):
            value = value.replace(".", "")
            value = value.replace(",", ".")
        else:
            value = value.replace(",", "")

    elif "," in value:
        parts = value.split(",")

        if len(parts[-1]) == 2:
            value = value.replace(".", "")
            value = value.replace(",", ".")
        else:
            value = value.replace(",", "")

    elif "." in value:
        parts = value.split(".")

        if len(parts[-1]) != 2:
            value = value.replace(".", "")

    value = re.sub(r"[^0-9.]", "", value)

    try:
        return float(value)
    except ValueError:
        return None


def extract_prices(text):
    results = []

    if not text:
        return results

    for currency, pattern in PRICE_PATTERNS:
        matches = re.findall(pattern, text)

        for match in matches:
            number = clean_number(match)

            if number is None:
                continue

            if number <= 0:
                continue

            # Ignore absurd values.
            if number > 100000:
                continue

            results.append(
                {
                    "currency": currency,
                    "price": number,
                    "price_pln": number * RATES_TO_PLN[currency],
                }
            )

    return results


def best_price_from_text(text):
    prices = extract_prices(text)

    if not prices:
        return None

    # Ignore obviously tiny numbers that are probably years,
    # quantities, item numbers, etc.
    valid = [
        price
        for price in prices
        if price["price_pln"] >= 5
    ]

    if not valid:
        return None

    return min(
        valid,
        key=lambda item: item["price_pln"],
    )


# ============================================================
# SCORING
# ============================================================

POSITIVE_TERMS = {
    "njo0108": 50,
    "5004076": 45,
    "lloyd dx": 30,
    "lloyd": 10,
    "ninjago": 10,
    "complete": 20,
    "100% complete": 25,
    "100%": 10,
    "authentic": 15,
    "genuine": 15,
    "original": 5,
    "target exclusive": 15,
    "target": 5,
    "rare": 5,
}

NEGATIVE_TERMS = {
    "custom": -40,
    "fake": -50,
    "replica": -50,
    "reproduction": -50,
    "missing legs": -30,
    "without legs": -30,
    "no legs": -30,
    "legs only": -40,
    "torso only": -40,
    "head only": -40,
    "head only": -40,
    "instructions": -20,
    "sticker": -20,
    "stickers": -15,
    "compatible": -30,
    "compatible with lego": -30,
    "not lego": -50,
}


def calculate_score(title, description=""):
    text = f"{title} {description}".lower()

    score = 0

    for term, points in POSITIVE_TERMS.items():
        if term in text:
            score += points

    for term, points in NEGATIVE_TERMS.items():
        if term in text:
            score += points

    return score


def deal_label(price_pln, score):
    if price_pln <= 0:
        return "UNKNOWN"

    if price_pln <= 400 and score >= 60:
        return "INSANE DEAL"

    if price_pln <= 600 and score >= 50:
        return "🔥 GREAT DEAL"

    if price_pln <= 800 and score >= 45:
        return "🟢 GOOD DEAL"

    if price_pln <= MAX_PRICE_PLN and score >= 35:
        return "🟡 POSSIBLE DEAL"

    return "⚪ CHECK"


# ============================================================
# MARKETPLACE DETECTION
# ============================================================

def detect_marketplace(url):
    host = urlparse(url).netloc.lower()

    if "ebay." in host:
        return "eBay"

    if "olx." in host:
        return "OLX"

    if "vinted." in host:
        return "Vinted"

    if "bricklink." in host:
        return "BrickLink"

    if "duckduckgo." in host:
        return "DuckDuckGo"

    return "Other"


# ============================================================
# LIVE LISTING VERIFICATION
# ============================================================

DEAD_TERMS = [
    "page not found",
    "404",
    "not found",
    "listing has ended",
    "item has ended",
    "item is no longer available",
    "no longer available",
    "listing ended",
    "this listing ended",
    "this item has been removed",
    "item has been removed",
    "listing removed",
    "sold out",
    "out of stock",
    "unavailable",
]

SEARCH_PAGE_TERMS = [
    "search results",
    "search results for",
    "search products",
    "browse products",
    "filter by",
    "categories",
]

OFFER_TERMS = [
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


def verify_offer(url):
    try:
        response = requests.get(
            url,
            headers=HEADERS,
            timeout=REQUEST_TIMEOUT,
            allow_redirects=True,
        )

        if response.status_code >= 400:
            return False, url, f"HTTP {response.status_code}"

        final_url = canonical_url(response.url) or response.url

        content_type = response.headers.get(
            "content-type",
            "",
        ).lower()

        if "text/html" not in content_type:
            return False, final_url, "Not an HTML page"

        soup = BeautifulSoup(
            response.text,
            "html.parser",
        )

        title = soup.title.get_text(
            " ",
            strip=True,
        ) if soup.title else ""

        body = soup.get_text(
            " ",
            strip=True,
        )

        text = f"{title} {body}".lower()

        for term in DEAD_TERMS:
            if term in text:
                return False, final_url, f"Dead-page term: {term}"

        search_indicators = sum(
            1
            for term in SEARCH_PAGE_TERMS
            if term in text
        )

        if search_indicators >= 2:
            return (
                False,
                final_url,
                "Looks like a search/category page",
            )

        offer_signals = sum(
            1
            for term in OFFER_TERMS
            if term in text
        )

        if offer_signals < 2:
            return (
                False,
                final_url,
                "Not enough listing signals",
            )

        return True, final_url, "Verified listing"

    except requests.RequestException as exc:
        return False, url, f"Request error: {exc}"


# ============================================================
# GENERIC HTML SEARCH EXTRACTION
# ============================================================

def extract_links_from_page(
    page_url,
    response_text,
    marketplace,
):
    soup = BeautifulSoup(
        response_text,
        "html.parser",
    )

    results = []

    for link in soup.find_all("a", href=True):
        href = normalize_url(
            link.get("href"),
            base_url=page_url,
        )

        if not href:
            continue

        text = link.get_text(
            " ",
            strip=True,
        )

        if len(text) < 3:
            continue

        # Skip obvious navigation links.
        lowered = text.lower()

        if lowered in {
            "home",
            "login",
            "log in",
            "sign in",
            "register",
            "menu",
            "categories",
            "help",
            "contact",
        }:
            continue

        results.append(
            {
                "marketplace": marketplace,
                "title": text[:500],
                "url": href,
            }
        )

    return results


# ============================================================
# eBAY PUBLIC SEARCH
# ============================================================

def search_ebay(phrase):
    encoded = quote_plus(phrase)

    url = (
        "https://www.ebay.com/sch/i.html"
        f"?_nkw={encoded}"
        "&LH_ItemCondition=1000%7C1500"
    )

    print(f"[eBay] Searching: {phrase}")

    try:
        response = requests.get(
            url,
            headers=HEADERS,
            timeout=REQUEST_TIMEOUT,
        )

        if response.status_code >= 400:
            print(
                f"[eBay] HTTP {response.status_code}"
            )
            return []

        soup = BeautifulSoup(
            response.text,
            "html.parser",
        )

        results = []

        for item in soup.select(
            "li.s-item"
        ):
            link = item.select_one(
                "a.s-item__link"
            )

            title_element = item.select_one(
                ".s-item__title"
            )

            price_element = item.select_one(
                ".s-item__price"
            )

            if not link:
                continue

            href = normalize_url(
                link.get("href")
            )

            if not href:
                continue

            title = (
                title_element.get_text(
                    " ",
                    strip=True,
                )
                if title_element
                else ""
            )

            price_text = (
                price_element.get_text(
                    " ",
                    strip=True,
                )
                if price_element
                else ""
            )

            if not title:
                continue

            results.append(
                {
                    "marketplace": "eBay",
                    "title": title[:500],
                    "url": href,
                    "price_text": price_text,
                }
            )

        return results

    except requests.RequestException as exc:
        print(f"[eBay] Request error: {exc}")
        return []


# ============================================================
# OLX
# ============================================================

def search_olx(phrase):
    encoded = quote_plus(phrase)

    url = (
        "https://www.olx.pl/oferty/q-"
        f"{encoded}/"
    )

    print(f"[OLX] Searching: {phrase}")

    try:
        response = requests.get(
            url,
            headers=HEADERS,
            timeout=REQUEST_TIMEOUT,
        )

        if response.status_code >= 400:
            print(
                f"[OLX] HTTP {response.status_code}"
            )
            return []

        soup = BeautifulSoup(
            response.text,
            "html.parser",
        )

        results = []

        for link in soup.find_all(
            "a",
            href=True,
        ):
            href = normalize_url(
                link.get("href"),
                base_url="https://www.olx.pl/",
            )

            if not href:
                continue

            if "olx.pl" not in urlparse(
                href
            ).netloc:
                continue

            text = link.get_text(
                " ",
                strip=True,
            )

            if len(text) < 5:
                continue

            # Most actual OLX ads contain /d/oferta/
            # in their URL.
            if "/d/oferta/" not in href:
                continue

            results.append(
                {
                    "marketplace": "OLX",
                    "title": text[:500],
                    "url": href,
                }
            )

        return results

    except requests.RequestException as exc:
        print(f"[OLX] Request error: {exc}")
        return []


# ============================================================
# VINTED
# ============================================================

def search_vinted(phrase):
    encoded = quote_plus(phrase)

    url = (
        "https://www.vinted.pl/catalog"
        f"?search_text={encoded}"
    )

    print(f"[Vinted] Searching: {phrase}")

    try:
        response = requests.get(
            url,
            headers=HEADERS,
            timeout=REQUEST_TIMEOUT,
        )

        if response.status_code >= 400:
            print(
                f"[Vinted] HTTP {response.status_code}"
            )
            return []

        soup = BeautifulSoup(
            response.text,
            "html.parser",
        )

        results = []

        for link in soup.find_all(
            "a",
            href=True,
        ):
            href = normalize_url(
                link.get("href"),
                base_url="https://www.vinted.pl/",
            )

            if not href:
                continue

            host = urlparse(href).netloc.lower()

            if "vinted." not in host:
                continue

            # Vinted item URLs generally contain /items/
            if "/items/" not in href:
                continue

            text = link.get_text(
                " ",
                strip=True,
            )

            if len(text) < 5:
                continue

            results.append(
                {
                    "marketplace": "Vinted",
                    "title": text[:500],
                    "url": href,
                }
            )

        return results

    except requests.RequestException as exc:
        print(
            f"[Vinted] Request error: {exc}"
        )
        return []


# ============================================================
# BRICKLINK
# ============================================================

def search_bricklink(phrase):
    print(f"[BrickLink] Searching: {phrase}")

    # BrickLink's catalog is particularly useful for exact
    # LEGO IDs such as njo0108. We therefore use the catalog
    # directly for exact IDs.
    normalized = phrase.lower().strip()

    if normalized == "njo0108":
        url = (
            "https://www.bricklink.com/v2/catalog/"
            "catalogitem.page?M=njo0108"
        )

    elif normalized == "5004076":
        url = (
            "https://www.bricklink.com/v2/catalog/"
            "
