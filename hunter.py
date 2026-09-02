import csv
import html
import os
import re
import time
from datetime import datetime
from urllib.parse import parse_qs, quote_plus, unquote, urljoin, urlparse

import requests
from bs4 import BeautifulSoup


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
    "instructions": -20,
    "sticker": -20,
    "stickers": -15,
    "compatible": -30,
    "compatible with lego": -30,
    "not lego": -50,
}


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


CSV_FILE = "results.csv"

CSV_FIELDS = [
    "timestamp",
    "marketplace",
    "title",
    "url",
    "final_url",
    "currency",
    "price",
    "price_pln",
    "score",
    "deal",
    "verified",
    "verification_reason",
]


TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")


def send_telegram(message):
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        print("Telegram secrets are not configured.")
        return False

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
            print("Telegram error:", response.status_code)
            return False

        return True

    except requests.RequestException as exc:
        print("Telegram request error:", exc)
        return False


def normalize_url(url, base_url=None):
    if not url:
        return None

    url = html.unescape(url).strip()

    if url.startswith("//"):
        url = "https:" + url

    if base_url:
        url = urljoin(base_url, url)

    parsed = urlparse(url)

    if "duckduckgo.com" in parsed.netloc.lower():
        query = parse_qs(parsed.query)

        if "uddg" in query and query["uddg"]:
            destination = unquote(query["uddg"][0])

            if destination.startswith("http://"):
                url = destination
            elif destination.startswith("https://"):
                url = destination

    parsed = urlparse(url)

    if parsed.scheme not in ("http", "https"):
        return None

    if not parsed.netloc:
        return None

    return url


def canonical_url(url):
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

    query = parse_qs(
        parsed.query,
        keep_blank_values=True,
    )

    cleaned = []

    for key, values in query.items():
        if key.lower() in tracking_parameters:
            continue

        for value in values:
            cleaned.append(
                f"{quote_plus(key)}={quote_plus(value)}"
            )

    query_string = "&".join(cleaned)

    cleaned_url = parsed._replace(
        query=query_string,
        fragment="",
    )

    return cleaned_url.geturl()


def clean_number(value):
    value = value.strip()
    value = value.replace("\xa0", "")
    value = value.replace(" ", "")

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
    if not text:
        return []

    patterns = [
        ("PLN", r"(?i)(?:PLN|zł)\s*([0-9][0-9\s.,]*)"),
        ("PLN", r"([0-9][0-9\s.,]*)\s*(?:PLN|zł)"),
        ("EUR", r"(?i)(?:EUR|€)\s*([0-9][0-9\s.,]*)"),
        ("EUR", r"([0-9][0-9\s.,]*)\s*(?:EUR|€)"),
        ("USD", r"(?i)(?:USD|\$)\s*([0-9][0-9\s.,]*)"),
        ("USD", r"([0-9][0-9\s.,]*)\s*(?:USD)"),
        ("GBP", r"(?i)(?:GBP|£)\s*([0-9][0-9\s.,]*)"),
        ("CAD", r"(?i)(?:CAD)\s*([0-9][0-9\s.,]*)"),
        ("AUD", r"(?i)(?:AUD)\s*([0-9][0-9\s.,]*)"),
        ("CZK", r"([0-9][0-9\s.,]*)\s*(?:Kč|CZK)"),
    ]

    results = []

    for currency, pattern in patterns:
        matches = re.findall(pattern, text)

        for match in matches:
            number = clean_number(match)

            if number is None:
                continue

            if number < 5:
                continue

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

    return min(
        prices,
        key=lambda item: item["price_pln"],
    )


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
    if price_pln is None:
        return "NO PRICE"

    if price_pln <= 400 and score >= 60:
        return "INSANE DEAL"

    if price_pln <= 600 and score >= 50:
        return "GREAT DEAL"

    if price_pln <= 800 and score >= 45:
        return "GOOD DEAL"

    if price_pln <= MAX_PRICE_PLN and score >= 35:
        return "POSSIBLE DEAL"

    return "CHECK"


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


def verify_offer(url):
    try:
        response = requests.get(
            url,
            headers=HEADERS,
            timeout=REQUEST_TIMEOUT,
            allow_redirects=True,
        )

        if response.status_code >= 400:
            return False, response.url, f"HTTP {response.status_code}"

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

        title = ""

        if soup.title:
            title = soup.title.get_text(
                " ",
                strip=True,
            )

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


def search_ebay(phrase):
    print(f"[eBay] Searching: {phrase}")

    url = (
        "https://www.ebay.com/sch/i.html"
        f"?_nkw={quote_plus(phrase)}"
    )

    try:
        response = requests.get(
            url,
            headers=HEADERS,
            timeout=REQUEST_TIMEOUT,
        )

        if response.status_code >= 400:
            print(f"[eBay] HTTP {response.status_code}")
            return []

        soup = BeautifulSoup(
            response.text,
            "html.parser",
        )

        results = []

        for item in soup.select("li.s-item"):
            link = item.select_one("a.s-item__link")
            title_element = item.select_one(".s-item__title")
            price_element = item.select_one(".s-item__price")

            if not link:
                continue

            href = normalize_url(link.get("href"))

            if not href:
                continue

            title = ""

            if title_element:
                title = title_element.get_text(
                    " ",
                    strip=True,
                )

            if not title:
                continue

            price_text = ""

            if price_element:
                price_text = price_element.get_text(
                    " ",
                    strip=True,
                )

            results.append(
                {
                    "marketplace": "eBay",
                    "title": title,
                    "url": href,
                    "price_text": price_text,
                }
            )

        return results

    except requests.RequestException as exc:
        print(f"[eBay] Request error: {exc}")
        return []


def search_olx(phrase):
    print(f"[OLX] Searching: {phrase}")

    url = (
        "https://www.olx.pl/oferty/q-"
        f"{quote_plus(phrase)}/"
    )

    try:
        response = requests.get(
            url,
            headers=HEADERS,
            timeout=REQUEST_TIMEOUT,
        )

        if response.status_code >= 400:
            print(f"[OLX] HTTP {response.status_code}")
            return []

        soup = BeautifulSoup(
            response.text,
            "html.parser",
        )

        results = []

        for link in soup.find_all("a", href=True):
            href = normalize_url(
                link.get("href"),
                "https://www.olx.pl/",
            )

            if not href:
                continue

            if "olx.pl" not in urlparse(href).netloc.lower():
                continue

            if "/d/oferta/" not in href:
                continue

            title = link.get_text(
                " ",
                strip=True,
            )

            if len(title) < 5:
                continue

            results.append(
                {
                    "marketplace": "OLX",
                    "title": title,
                    "url": href,
                }
            )

        return results

    except requests.RequestException as exc:
        print(f"[OLX] Request error: {exc}")
        return []


def search_vinted(phrase):
    print(f"[Vinted] Searching: {phrase}")

    url = (
        "https://www.vinted.pl/catalog"
        f"?search_text={quote_plus(phrase)}"
    )

    try:
        response = requests.get(
            url,
            headers=HEADERS,
            timeout=REQUEST_TIMEOUT,
        )

        if response.status_code >= 400:
            print(f"[Vinted] HTTP {response.status_code}")
            return []

        soup = BeautifulSoup(
            response.text,
            "html.parser",
        )

        results = []

        for link in soup.find_all("a", href=True):
            href = normalize_url(
                link.get("href"),
                "https://www.vinted.pl/",
            )

            if not href:
                continue

            host = urlparse(href).netloc.lower()

            if "vinted." not in host:
                continue

            if "/items/" not in href:
                continue

            title = link.get_text(
                " ",
                strip=True,
            )

            if len(title) < 5:
                continue

            results.append(
                {
                    "marketplace": "Vinted",
                    "title": title,
                    "url": href,
                }
            )

        return results

    except requests.RequestException as exc:
        print(f"[Vinted] Request error: {exc}")
        return []


def search_bricklink(phrase):
    print(f"[BrickLink] Searching: {phrase}")

    normalized = phrase.lower().strip()

    if normalized == "njo0108":
        url = (
            "https://www.bricklink.com/v2/catalog/"
            "catalogitem.page?M=njo0108"
        )
    elif normalized == "5004076":
        url = (
            "https://www.bricklink.com/v2/catalog/"
            "catalogitem.page?S=5004076-1"
        )
    else:
        url = (
            "https://www.bricklink.com/catalogList.asp"
            f"?catType=M&catString={quote_plus(phrase)}"
        )

    try:
        response = requests.get(
            url,
            headers=HEADERS,
            timeout=REQUEST_TIMEOUT,
        )

        if response.status_code >= 400:
            print(f"[BrickLink] HTTP {response.status_code}")
            return []

        soup = BeautifulSoup(
            response.text,
            "html.parser",
        )

        title = ""

        if soup.title:
            title = soup.title.get_text(
                " ",
                strip=True,
            )

        return [
            {
                "marketplace": "BrickLink",
                "title": title or phrase,
                "url": response.url,
                "price_text": "",
                "catalog_only": True,
            }
        ]

    except requests.RequestException as exc:
        print(f"[BrickLink] Request error: {exc}")
        return []


def search_duckduckgo(phrase):
    print(f"[DuckDuckGo] Searching: {phrase}")

    url = (
        "https://html.duckduckgo.com/html/"
        f"?q={quote_plus(phrase)}"
    )

    try:
        response = requests.get(
            url,
            headers=HEADERS,
            timeout=REQUEST_TIMEOUT,
        )

        if response.status_code >= 400:
            print(
                f"[DuckDuckGo] HTTP {response.status_code}"
            )
            return []

        soup = BeautifulSoup(
            response.text,
            "html.parser",
        )

        results = []

        for result in soup.select(".result"):
            link = result.select_one(".result__a")

            if not link:
                continue

            href = normalize_url(
                link.get("href")
            )

            if not href:
                continue

            title = link.get_text(
                " ",
                strip=True,
            )

            snippet_element = result.select_one(
                ".result__snippet"
            )

            description = ""

            if snippet_element:
                description = snippet_element.get_text(
                    " ",
                    strip=True,
                )

            if not title:
                continue

            results.append(
                {
                    "marketplace": detect_marketplace(href),
                    "title": title,
                    "url": href,
                    "description": description,
                }
            )

        return results

    except requests.RequestException as exc:
        print(
            f"[DuckDuckGo] Request error: {exc}"
        )
        return []


def build_result(raw):
    title = raw.get(
        "title",
        "",
    ).strip()

    description = raw.get(
        "description",
        "",
    ).strip()

    url = canonical_url(
        raw.get("url")
    )

    if not url:
        return None

    price_text = raw.get(
        "price_text",
        "",
    )

    combined_text = (
        f"{title} "
        f"{description} "
        f"{price_text}"
    )

    price = best_price_from_text(
        combined_text
    )

    score = calculate_score(
        title,
        description,
    )

    price_pln = None

    if price:
        price_pln = price["price_pln"]

    return {
        "marketplace": raw.get(
            "marketplace",
            detect_marketplace(url),
        ),
        "title": title[:500],
        "url": url,
        "final_url": url,
        "currency": (
            price["currency"]
            if price
            else ""
        ),
        "price": (
            price["price"]
            if price
            else ""
        ),
        "price_pln": (
            round(price_pln, 2)
            if price_pln is not None
            else ""
        ),
        "score": score,
        "deal": deal_label(
            price_pln,
            score,
        ),
        "verified": False,
        "verification_reason": "",
        "catalog_only": raw.get(
            "catalog_only",
            False,
 
