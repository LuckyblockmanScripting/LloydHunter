import csv
import os
import re
import time
from datetime import datetime, timezone
from urllib.parse import parse_qs, unquote, urljoin, urlsplit

import requests
from bs4 import BeautifulSoup


# ============================================================
# CONFIG
# ============================================================

MAX_PRICE_PLN = 1000

SEARCH_PHRASES = [
    '"njo0108"',
    '"5004076"',
    '"Lloyd DX" Ninjago',
    '"Lloyd DX" LEGO',
    '"Lloyd Ninjago" minifigure',
    '"Lloyd" "DX" minifigure',
    '"Loyd" Ninjago minifigure',
    '"Lloid" Ninjago minifigure',
    '"Ninjago" minifigure lot Lloyd',
    '"Ninjago" figures lot",
]

CURRENCY_TO_PLN = {
    "PLN": 1.00,
    "EUR": 4.25,
    "USD": 3.65,
    "GBP": 4.95,
    "CAD": 2.65,
}

POSITIVE_TERMS = {
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
}

DEAD_PAGE_TERMS = [
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
    "item removed",
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
    "category",
    "categories",
    "filter by",
]

OFFER_TERMS = [
    "add to cart",
    "buy now",
    "buy it now",
    "make offer",
    "add to bag",
    "add to basket",
    "quantity",
    "price",
    "condition",
    "seller",
    "item number",
    "listing",
]

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/139.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "en-US,en;q=0.9",
}


# ============================================================
# URL HANDLING
# ============================================================

def normalize_url(url):
    """
    Convert DuckDuckGo redirect URLs and protocol-relative URLs
    into normal absolute URLs.
    """

    if not url:
        return None

    url = url.strip()
    url = url.replace("&amp;", "&")

    # DuckDuckGo sometimes returns URLs beginning with //.
    if url.startswith("//"):
        url = "https:" + url

    # Relative URLs.
    elif url.startswith("/"):
        url = urljoin("https://duckduckgo.com", url)

    try:
        parsed = urlsplit(url)
        query = parse_qs(parsed.query)

        # DuckDuckGo uses "uddg" for the real destination.
        if "uddg" in query and query["uddg"]:
            destination = unquote(query["uddg"][0]).strip()

            if destination.startswith("//"):
                destination = "https:" + destination

            if destination.startswith("http://") or destination.startswith(
                "https://"
            ):
                return destination

    except Exception:
        return None

    if url.startswith("http://") or url.startswith("https://"):
        return url

    return None


# ============================================================
# DUCKDUCKGO SEARCH
# ============================================================

def search_duckduckgo(query):
    search_url = "https://html.duckduckgo.com/html/"

    try:
        response = requests.get(
            search_url,
            params={"q": query},
            headers=HEADERS,
            timeout=20,
        )

        response.raise_for_status()

    except requests.RequestException as exc:
        print(f"Search request failed for '{query}': {exc}")
        return []

    soup = BeautifulSoup(response.text, "html.parser")

    results = []

    for result in soup.select(".result"):
        link = result.select_one("a.result__a")

        if not link:
            continue

        raw_url = link.get("href", "")
        title = link.get_text(" ", strip=True)

        snippet_element = result.select_one(".result__snippet")

        snippet = (
            snippet_element.get_text(" ", strip=True)
            if snippet_element
            else ""
        )

        clean_url = normalize_url(raw_url)

        if not clean_url:
            continue

        results.append(
            {
                "title": title,
                "url": clean_url,
                "snippet": snippet,
                "query": query,
            }
        )

    return results


# ============================================================
# PRICE EXTRACTION
# ============================================================

def extract_price(text):
    if not text:
        return None, None

    text = text.replace("\xa0", " ")

    patterns = [
        (r"(?<!\w)(\d{1,6}(?:[.,]\d{1,2})?)\s*(?:PLN|zł|zl)\b", "PLN"),

        (r"(?<!\w)(\d{1,6}(?:[.,]\d{1,2})?)\s*(?:EUR|€)\b", "EUR"),
        (r"€\s*(\d{1,6}(?:[.,]\d{1,2})?)", "EUR"),

        (r"(?<!\w)(\d{1,6}(?:[.,]\d{1,2})?)\s*(?:USD)\b", "USD"),
        (r"\$\s*(\d{1,6}(?:[.,]\d{1,2})?)", "USD"),

        (r"(?<!\w)(\d{1,6}(?:[.,]\d{1,2})?)\s*(?:GBP|£)\b", "GBP"),
        (r"£\s*(\d{1,6}(?:[.,]\d{1,2})?)", "GBP"),

        (r"(?<!\w)(\d{1,6}(?:[.,]\d{1,2})?)\s*(?:CAD)\b", "CAD"),
        (r"C\$\s*(\d{1,6}(?:[.,]\d{1,2})?)", "CAD"),
    ]

    for pattern, currency in patterns:
        match = re.search(
            pattern,
            text,
            flags=re.IGNORECASE,
        )

        if not match:
            continue

        raw_amount = match.group(1).replace(",", ".")

        try:
            amount = float(raw_amount)
        except ValueError:
            continue

        return amount, currency

    return None, None


def convert_to_pln(amount, currency):
    rate = CURRENCY_TO_PLN.get(currency)

    if rate is None:
        return None

    return amount * rate


# ============================================================
# RELEVANCE SCORING
# ============================================================

def calculate_score(text):
    text_lower = text.lower()

    score = 0

    for term, points in POSITIVE_TERMS.items():
        if term in text_lower:
            score += points

    for term, points in NEGATIVE_TERMS.items():
        if term in text_lower:
            score += points

    return score


# ============================================================
# MARKETPLACE DETECTION
# ============================================================

def detect_marketplace(url):
    if not url:
        return "Unknown"

    hostname = urlsplit(url).netloc.lower()

    if "ebay." in hostname:
        return "eBay"

    if "olx." in hostname:
        return "OLX"

    if "vinted." in hostname:
        return "Vinted"

    if "bricklink." in hostname:
        return "BrickLink"

    if "brickowl." in hostname:
        return "BrickOwl"

    return hostname


# ============================================================
# OFFER VERIFICATION
# ============================================================

def verify_offer(url):
    clean_url = normalize_url(url)

    if not clean_url:
        return {
            "valid": False,
            "final_url": "",
            "reason": "Invalid or unsupported URL",
            "page_text": "",
            "title": "",
        }

    try:
        response = requests.get(
            clean_url,
            headers=HEADERS,
            timeout=25,
            allow_redirects=True,
        )

        final_url = normalize_url(response.url) or response.url

        if response.status_code >= 400:
            return {
                "valid": False,
                "final_url": final_url,
                "reason": f"HTTP {response.status_code}",
                "page_text": "",
                "title": "",
            }

    except requests.RequestException as exc:
        return {
            "valid": False,
            "final_url": clean_url,
            "reason": f"Request error: {exc}",
            "page_text": "",
            "title": "",
        }

    soup = BeautifulSoup(response.text, "html.parser")

    title = (
        soup.title.get_text(" ", strip=True)
        if soup.title
        else ""
    )

    page_text = soup.get_text(" ", strip=True)
    page_text_lower = page_text.lower()

    # --------------------------------------------------------
    # Dead listing check
    # --------------------------------------------------------

    for term in DEAD_PAGE_TERMS:
        if term in page_text_lower:
            return {
                "valid": False,
                "final_url": final_url,
                "reason": f"Dead/unavailable page: {term}",
                "page_text": page_text,
                "title": title,
            }

    # --------------------------------------------------------
    # Search/category page check
    # --------------------------------------------------------

    search_indicator_count = 0

    for term in SEARCH_PAGE_TERMS:
        if term in page_text_lower:
            search_indicator_count += 1

    if search_indicator_count >= 2:
        return {
            "valid": False,
            "final_url": final_url,
            "reason": "Looks like a search/category page",
            "page_text": page_text,
            "title": title,
        }

    # --------------------------------------------------------
    # Offer signal check
    # --------------------------------------------------------

    offer_signal_count = 0

    for term in OFFER_TERMS:
        if term in page_text_lower:
            offer_signal_count += 1

    if offer_signal_count < 2:
        return {
            "valid": False,
            "final_url": final_url,
            "reason": "Not enough signs of an individual listing",
            "page_text": page_text,
            "title": title,
        }

    return {
        "valid": True,
        "final_url": final_url,
        "reason": "Live listing detected",
        "page_text": page_text,
        "title": title,
    }


# ============================================================
# TELEGRAM
# ============================================================

def send_telegram(message):
    token = os.getenv("TELEGRAM_BOT_TOKEN")
    chat_id = os.getenv("TELEGRAM_CHAT_ID")

    if not token or not chat_id:
        print("Telegram secrets are missing. Skipping Telegram alert.")
        return False

    url = f"https://api.telegram.org/bot{token}/sendMessage"

    try:
        response = requests.post(
            url,
            data={
                "chat_id": chat_id,
                "text": message,
                "disable_web_page_preview": False,
            },
            timeout=20,
        )

        response.raise_for_status()

        return True

    except requests.RequestException as exc:
        print(f"Telegram request failed: {exc}")
        return False


# ============================================================
# CSV
# ============================================================

def save_results(results):
    filename = "results.csv"

    fieldnames = [
        "timestamp",
        "marketplace",
        "query",
        "title",
        "price",
        "currency",
        "price_pln",
        "score",
        "verified",
        "verification_reason",
        "url",
    ]

    try:
        with open(
            filename,
            "w",
            newline="",
            encoding="utf-8",
        ) as csv_file:

            writer = csv.DictWriter(
                csv_file,
                fieldnames=fieldnames,
            )

            writer.writeheader()

            for result in results:
                writer.writerow(result)

    except OSError as exc:
        print(f"Could not save results.csv: {exc}")


# ============================================================
# MAIN HUNTER
# ============================================================

def main():
    print("=" * 60)
    print("LLOYD DX HUNTER STARTING")
    print("=" * 60)

    all_results = []
    seen_urls = set()

    for query in SEARCH_PHRASES:

        print()
        print(f"Searching: {query}")

        search_results = search_duckduckgo(query)

        print(f"Found {len(search_results)} search results.")

        for item in search_results:

            url = normalize_url(item["url"])

            if not url:
                continue

            # Prevent the same listing appearing multiple times.
            if url in seen_urls:
                continue

            seen_urls.add(url)

            title = item["title"]
            snippet = item["snippet"]

            combined_text = f"{title} {snippet}"

            # ------------------------------------------------
            # Basic relevance check
            # ------------------------------------------------

            score = calculate_score(combined_text)

            if score <= 0:
                continue

            # ------------------------------------------------
            # Price extraction
            # ------------------------------------------------

            amount, currency = extract_price(combined_text)

            if amount is None:
                print(f"Skipped — no recognizable price: {title}")
                continue

            price_pln = convert_to_pln(amount, currency)

            if price_pln is None:
                continue

            # Don't waste verification requests on obviously
            # over-budget results.
            if price_pln > MAX_PRICE_PLN:
                continue

            marketplace = detect_marketplace(url)

            print()
            print(f"Candidate: {title}")
            print(f"Marketplace: {marketplace}")
            print(
                f"Price: {amount:.2f} {currency} "
                f"(~{price_pln:.2f} PLN)"
            )
            print(f"Score: {score}")
            print(f"URL: {url}")

            # ------------------------------------------------
            # Verify actual listing
            # ------------------------------------------------

            verification = verify_offer(url)

            if not verification["valid"]:
                print(
                    "Rejected: "
                    + verification["reason"]
                )
                continue

            final_url = verification["final_url"]

            # ------------------------------------------------
            # Re-score using actual page
            # ------------------------------------------------

            page_text = verification["page_text"]

            page_score = calculate_score(
                f"{title} {snippet} {page_text[:20000]}"
            )

            if page_score > score:
                score = page_score

            # ------------------------------------------------
            # Try to find a better price on actual page
            # ------------------------------------------------

            page_amount, page_currency = extract_price(
                page_text[:50000]
            )

            if page_amount is not None:
                page_price_pln = convert_to_pln(
                    page_amount,
                    page_currency,
                )

                if page_price_pln is not None:
                    amount = page_amount
                    currency = page_currency
                    price_pln = page_price_pln

            # ------------------------------------------------
            # Final budget check
            # ------------------------------------------------

            if price_pln > MAX_PRICE_PLN:
                print(
                    "Rejected after page check: "
                    f"{price_pln:.2f} PLN is over budget."
                )
                continue

            # ------------------------------------------------
            # Save verified result
            # ------------------------------------------------

            result = {
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "marketplace": marketplace,
                "query": query,
                "title": title,
                "price": f"{amount:.2f}",
                "currency": currency,
                "price_pln": f"{price_pln:.2f}",
                "score": score,
                "verified": True,
                "verification_reason": verification["reason"],
                "url": final_url,
            }

            all_results.append(result)

            # ------------------------------------------------
            # Telegram alert
            # ------------------------------------------------

            message = (
                "🔥 VERIFIED LLOYD DX DEAL!\n\n"
                f"💰 {amount:.2f} {currency} "
                f"(≈ {price_pln:.0f} PLN)\n"
                f"⭐ Score: {score}\n"
                f"🛒 Marketplace: {marketplace}\n\n"
                f"🧱 {title}\n\n"
                f"🔗 {final_url}"
            )

            send_telegram(message)

            print("✅ VERIFIED DEAL FOUND!")

            time.sleep(1)

    # --------------------------------------------------------
    # Save results
    # --------------------------------------------------------

    save_results(all_results)

    print()
    print("=" * 60)
    print("HUNT COMPLETE")
    print(f"Verified deals found: {len(all_results)}")
    print(f"Unique URLs checked: {len(seen_urls)}")
    print("=" * 60)


if __name__ == "__main__":
    main()
