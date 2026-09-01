import csv
import os
import re
import time
from datetime import datetime, timezone
from urllib.parse import quote_plus

import requests
from bs4 import BeautifulSoup


# =========================
# SETTINGS
# =========================

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
    '"Ninjago" figures lot',
]

RESULTS_FILE = "results.csv"

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/139.0 Safari/537.36"
    )
}

# Approximate exchange rates.
# These are only used to compare prices against the PLN limit.
RATES = {
    "PLN": 1.0,
    "EUR": 4.25,
    "USD": 3.65,
    "GBP": 4.95,
    "CAD": 2.65,
}


# =========================
# TELEGRAM
# =========================

TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")


def send_telegram(message):
    """Send a message to Telegram."""

    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        print("Telegram secrets are missing. Skipping Telegram alert.")
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
        response = requests.post(url, data=data, timeout=20)

        if response.ok:
            print("Telegram alert sent.")
        else:
            print("Telegram error:", response.text)

    except Exception as e:
        print("Could not send Telegram message:", e)


# =========================
# PRICE PARSING
# =========================

def parse_price(text):
    """
    Try to find a price and currency in text.

    Examples:
    999 PLN
    250 zł
    €150
    $300
    £200
    C$250
    """

    if not text:
        return None

    text = text.replace("\xa0", " ")

    patterns = [
        # PLN / zł
        (r"(\d[\d\s.,]*)\s*(PLN|zł|zl)\b", "PLN"),

        # EUR
        (r"€\s*(\d[\d\s.,]*)", "EUR"),
        (r"(\d[\d\s.,]*)\s*EUR\b", "EUR"),

        # USD
        (r"\$\s*(\d[\d\s.,]*)", "USD"),
        (r"(\d[\d\s.,]*)\s*USD\b", "USD"),

        # GBP
        (r"£\s*(\d[\d\s.,]*)", "GBP"),
        (r"(\d[\d\s.,]*)\s*GBP\b", "GBP"),

        # CAD
        (r"C\$\s*(\d[\d\s.,]*)", "CAD"),
        (r"(\d[\d\s.,]*)\s*CAD\b", "CAD"),
    ]

    for pattern, currency in patterns:
        match = re.search(pattern, text, re.IGNORECASE)

        if not match:
            continue

        raw = match.group(1)

        # Remove spaces.
        raw = raw.replace(" ", "")

        # Handle common decimal formats.
        if "," in raw and "." in raw:
            # Example: 1,234.56
            raw = raw.replace(",", "")
        elif "," in raw:
            # Example: 999,99
            raw = raw.replace(",", ".")

        try:
            value = float(raw)
            return value, currency

        except ValueError:
            continue

    return None


def convert_to_pln(price, currency):
    """Convert a price to approximate PLN."""

    rate = RATES.get(currency)

    if not rate:
        return None

    return price * rate


# =========================
# RELEVANCE SCORING
# =========================

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


# =========================
# SEARCH
# =========================

def search_duckduckgo(query):
    """Search DuckDuckGo and return results."""

    url = (
        "https://html.duckduckgo.com/html/?q="
        + quote_plus(query)
    )

    try:
        response = requests.get(
            url,
            headers=HEADERS,
            timeout=30,
        )

        response.raise_for_status()

    except Exception as e:
        print(f"Search failed for {query}: {e}")
        return []

    soup = BeautifulSoup(response.text, "html.parser")

    results = []

    for result in soup.select(".result"):

        title_element = result.select_one(".result__a")
        snippet_element = result.select_one(".result__snippet")

        if not title_element:
            continue

        title = title_element.get_text(" ", strip=True)

        link = title_element.get("href", "")

        snippet = ""

        if snippet_element:
            snippet = snippet_element.get_text(
                " ",
                strip=True
            )

        combined_text = f"{title} {snippet}"

        results.append({
            "title": title,
            "link": link,
            "snippet": snippet,
            "text": combined_text,
            "score": calculate_score(combined_text),
        })

    return results


# =========================
# MAIN HUNT
# =========================

def main():

    print("===================================")
    print("        LLOYD DX HUNTER")
    print("===================================")
    print()

    all_results = []
    seen_links = set()

    for phrase in SEARCH_PHRASES:

        print(f"Searching: {phrase}")

        results = search_duckduckgo(phrase)

        for result in results:

            link = result["link"]

            if not link:
                continue

            if link in seen_links:
                continue

            seen_links.add(link)

            # Try to find a price.
            price_info = parse_price(
                result["text"]
            )

            price = ""
            currency = ""
            price_pln = ""

            if price_info:

                price, currency = price_info

                converted = convert_to_pln(
                    price,
                    currency
                )

                if converted is not None:
                    price_pln = round(converted, 2)

            result["price"] = price
            result["currency"] = currency
            result["price_pln"] = price_pln

            all_results.append(result)

        # Small delay between searches.
        time.sleep(2)

    # Sort best matches first.
    all_results.sort(
        key=lambda x: (
            x["price_pln"]
            if isinstance(x["price_pln"], (int, float))
            else 999999,
            -x["score"],
        )
    )

    # =========================
    # SAVE CSV
    # =========================

    with open(
        RESULTS_FILE,
        "w",
        newline="",
        encoding="utf-8"
    ) as file:

        writer = csv.writer(file)

        writer.writerow([
            "Time",
            "Title",
            "Price",
            "Currency",
            "Approx PLN",
            "Score",
            "Link",
            "Snippet",
        ])

        timestamp = datetime.now(
            timezone.utc
        ).strftime("%Y-%m-%d %H:%M:%S UTC")

        for result in all_results:

            writer.writerow([
                timestamp,
                result["title"],
                result["price"],
                result["currency"],
                result["price_pln"],
                result["score"],
                result["link"],
                result["snippet"],
            ])

    print()
    print(f"Found {len(all_results)} unique results.")
    print(f"Saved results to {RESULTS_FILE}")
    print()

    # =========================
    # FIND DEALS
    # =========================

    deals = []

    for result in all_results:

        price_pln = result["price_pln"]

        if not isinstance(price_pln, (int, float)):
            continue

        if price_pln > MAX_PRICE_PLN:
            continue

        # Require some relevance.
        if result["score"] < 20:
            continue

        deals.append(result)

    # =========================
    # PRINT DEALS
    # =========================

    if not deals:

        print("No possible deals under")
        print(f"{MAX_PRICE_PLN} PLN found.")

    else:

        print("🔥 POSSIBLE DEALS")
        print("=================")

        for deal in deals:

            print()
            print(deal["title"])
            print(
                f"Price: {deal['price']} "
                f"{deal['currency']} "
                f"(≈ {deal['price_pln']} PLN)"
            )
            print(
                f"Score: {deal['score']}"
            )
            print(deal["link"])

    # =========================
    # TELEGRAM ALERT
    # =========================

    if deals:

        message_lines = [
            "🔥 LLOYD DX DEAL FOUND!",
            "",
        ]

        # Send at most 5 deals per run.
        for deal in deals[:5]:

            message_lines.append(
                f"💰 {deal['price']} {deal['currency']} "
                f"(≈ {deal['price_pln']} PLN)"
            )

            message_lines.append(
                f"⭐ Score: {deal['score']}"
            )

            message_lines.append(
                deal["title"][:180]
            )

            message_lines.append(
                deal["link"]
            )

            message_lines.append("")

        send_telegram(
            "\n".join(message_lines)
        )

    else:

        print()
        print("No Telegram alert sent because")
        print("no qualifying deal was found.")


if __name__ == "__main__":
    main()    "GBP": 4.95,
}


def extract_price(text):
    patterns = [
        (r"(\d+(?:[.,]\d{1,2})?)\s*(?:PLN|zł|zl)", "PLN"),
        (r"(?:€)\s*(\d+(?:[.,]\d{1,2})?)", "EUR"),
        (r"(\d+(?:[.,]\d{1,2})?)\s*€", "EUR"),
        (r"(?:US\$|\$)\s*(\d+(?:[.,]\d{1,2})?)", "USD"),
        (r"(?:£)\s*(\d+(?:[.,]\d{1,2})?)", "GBP"),
    ]

    for pattern, currency in patterns:
        match = re.search(pattern, text, re.IGNORECASE)
        if match:
            number = match.group(1).replace(",", ".")
            try:
                value = float(number)
                return value, currency
            except ValueError:
                pass

    return None, None


def score_listing(title, description):
    text = f"{title} {description}".lower()

    score = 0

    positive = {
        "njo0108": 50,
        "5004076": 45,
        "lloyd dx": 30,
        "lloyd": 10,
        "ninjago": 10,
        "complete": 20,
        "authentic": 15,
        "genuine": 15,
        "original": 5,
        "target exclusive": 15,
    }

    negative = {
        "custom": -40,
        "fake": -50,
        "replica": -50,
        "missing legs": -30,
        "without legs": -30,
        "legs only": -40,
        "torso only": -40,
        "head only": -40,
        "instructions": -20,
    }

    for word, points in positive.items():
        if word in text:
            score += points

    for word, points in negative.items():
        if word in text:
            score += points

    return max(0, min(score, 100))


def search_duckduckgo(query):
    url = "https://html.duckduckgo.com/html/?q=" + quote_plus(query)

    response = requests.get(
        url,
        headers=HEADERS,
        timeout=20
    )

    response.raise_for_status()

    soup = BeautifulSoup(response.text, "html.parser")

    results = []

    for result in soup.select(".result"):
        link = result.select_one(".result__a")
        snippet = result.select_one(".result__snippet")

        if not link:
            continue

        title = link.get_text(" ", strip=True)
        url = link.get("href", "")

        description = (
            snippet.get_text(" ", strip=True)
            if snippet
            else ""
        )

        price, currency = extract_price(
            f"{title} {description}"
        )

        price_pln = None

        if price is not None:
            price_pln = round(
                price * RATES[currency],
                2
            )

        results.append({
            "search": query,
            "title": title,
            "price": price or "",
            "currency": currency or "",
            "price_pln": price_pln or "",
            "score": score_listing(
                title,
                description
            ),
            "url": url,
            "description": description,
            "found": datetime.now(
                timezone.utc
            ).isoformat(),
        })

    return results


def main():
    print("LLOYD HUNTER STARTING")
    print("=" * 50)

    all_results = []

    for query in SEARCHES:
        print("Searching:", query)

        try:
            results = search_duckduckgo(query)
            all_results.extend(results)

        except Exception as error:
            print("Search failed:", error)

        time.sleep(2)

    filename = "results.csv"

    fields = [
        "search",
        "title",
        "price",
        "currency",
        "price_pln",
        "score",
        "url",
        "description",
        "found",
    ]

    with open(
        filename,
        "w",
        newline="",
        encoding="utf-8"
    ) as file:

        writer = csv.DictWriter(
            file,
            fieldnames=fields
        )

        writer.writeheader()
        writer.writerows(all_results)

    bargains = [
        result
        for result in all_results
        if result["price_pln"] != ""
        and float(result["price_pln"]) <= MAX_PRICE_PLN
    ]

    bargains.sort(
        key=lambda x: (
            -int(x["score"]),
            float(x["price_pln"])
        )
    )

    print()
    print("=" * 50)
    print("POSSIBLE DEALS")
    print("=" * 50)

    for result in bargains[:20]:
        print()
        print(result["title"])
        print(
            f'{result["price"]} '
            f'{result["currency"]} '
            f'(~{result["price_pln"]} PLN)'
        )
        print(
            f'Score: {result["score"]}/100'
        )
        print(result["url"])

    print()
    print(
        f"Found {len(all_results)} results."
    )

    print(
        f"{len(bargains)} appear under "
        f"{MAX_PRICE_PLN} PLN."
    )


if __name__ == "__main__":
    main()
