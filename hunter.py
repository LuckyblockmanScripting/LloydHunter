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
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        print("Telegram secrets are missing.")
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
            timeout=20,
        )

        if response.ok:
            print("Telegram alert sent.")
        else:
            print("Telegram error:", response.text)

    except Exception as e:
        print("Telegram error:", e)


# =========================
# PRICE PARSING
# =========================

def parse_price(text):
    if not text:
        return None

    text = text.replace("\xa0", " ")

    patterns = [
        (r"(\d[\d\s.,]*)\s*(PLN|zł|zl)\b", "PLN"),
        (r"€\s*(\d[\d\s.,]*)", "EUR"),
        (r"(\d[\d\s.,]*)\s*EUR\b", "EUR"),
        (r"\$\s*(\d[\d\s.,]*)", "USD"),
        (r"(\d[\d\s.,]*)\s*USD\b", "USD"),
        (r"£\s*(\d[\d\s.,]*)", "GBP"),
        (r"(\d[\d\s.,]*)\s*GBP\b", "GBP"),
        (r"C\$\s*(\d[\d\s.,]*)", "CAD"),
        (r"(\d[\d\s.,]*)\s*CAD\b", "CAD"),
    ]

    for pattern, currency in patterns:
        match = re.search(
            pattern,
            text,
            re.IGNORECASE,
        )

        if not match:
            continue

        raw = match.group(1)
        raw = raw.replace(" ", "")

        if "," in raw and "." in raw:
            raw = raw.replace(",", "")
        elif "," in raw:
            raw = raw.replace(",", ".")

        try:
            return float(raw), currency
        except ValueError:
            continue

    return None


def convert_to_pln(price, currency):
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

    soup = BeautifulSoup(
        response.text,
        "html.parser",
    )

    results = []

    for result in soup.select(".result"):
        title_element = result.select_one(".result__a")
        snippet_element = result.select_one(
            ".result__snippet"
        )

        if not title_element:
            continue

        title = title_element.get_text(
            " ",
            strip=True,
        )

        link = title_element.get(
            "href",
            "",
        )

        snippet = ""

        if snippet_element:
            snippet = snippet_element.get_text(
                " ",
                strip=True,
            )

        combined_text = f"{title} {snippet}"

        results.append({
            "title": title,
            "link": link,
            "snippet": snippet,
            "text": combined_text,
            "score": calculate_score(
                combined_text
            ),
        })

    return results


# =========================
# MAIN
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
                    currency,
                )

                if converted is not None:
                    price_pln = round(
                        converted,
                        2,
                    )

            result["price"] = price
            result["currency"] = currency
            result["price_pln"] = price_pln

            all_results.append(result)

        time.sleep(2)

    all_results.sort(
        key=lambda x: (
            x["price_pln"]
            if isinstance(
                x["price_pln"],
                (int, float),
            )
            else 999999,
            -x["score"],
        )
    )

    # =========================
    # SAVE RESULTS
    # =========================

    with open(
        RESULTS_FILE,
        "w",
        newline="",
        encoding="utf-8",
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
        ).strftime(
            "%Y-%m-%d %H:%M:%S UTC"
        )

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
    print(
        f"Found {len(all_results)} unique results."
    )

    print(
        f"Saved results to {RESULTS_FILE}"
    )

    # =========================
    # FIND DEALS
    # =========================

    deals = []

    for result in all_results:
        price_pln = result["price_pln"]

        if not isinstance(
            price_pln,
            (int, float),
        ):
            continue

        if price_pln > MAX_PRICE_PLN:
            continue

        if result["score"] < 20:
            continue

        deals.append(result)

    # =========================
    # PRINT DEALS
    # =========================

    if not deals:
        print()
        print(
            f"No possible deals under "
            f"{MAX_PRICE_PLN} PLN found."
        )

    else:
        print()
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
    # TELEGRAM
    # =========================

    if deals:
        message_lines = [
            "🔥 LLOYD DX DEAL FOUND!",
            "",
        ]

        for deal in deals[:5]:
            message_lines.append(
                f"💰 {deal['price']} "
                f"{deal['currency']} "
                f"(≈ {deal['price_pln']} PLN)"
            )

            message_lines.append(
                f"⭐ Score: {deal['score']}"
            )

            message_lines.append(
                f"🧱 {deal['title'][:180]}"
            )

            message_lines.append(
                f"🔗 {deal['link']}"
            )

            message_lines.append("")

        send_telegram(
            "\n".join(message_lines)
        )

    else:
        print()
        print(
            "No Telegram alert sent because "
            "no qualifying deal was found."
        )


if __name__ == "__main__":
    main()
