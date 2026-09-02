import csv
import os
import re
import time
from datetime import datetime
from urllib.parse import quote_plus

import requests
from bs4 import BeautifulSoup


MAX_PRICE_PLN = 1000
TIMEOUT = 20
DELAY = 2

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
    "AUD": 2.40,
}

SEARCHES = {
    "eBay": [
        "njo0108",
        "5004076",
        "Lloyd DX",
        "Lloyd Ninjago minifigure",
    ],
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

POSITIVE = {
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

NEGATIVE = {
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
    "not lego": -50,
}

DEAD_WORDS = [
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

OFFER_WORDS = [
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


def send_telegram(message):
    token = os.getenv("TELEGRAM_BOT_TOKEN")
    chat_id = os.getenv("TELEGRAM_CHAT_ID")

    if not token or not chat_id:
        print("Telegram secrets missing.")
        return False

    url = f"https://api.telegram.org/bot{token}/sendMessage"

    data = {
        "chat_id": chat_id,
        "text": message,
        "disable_web_page_preview": False,
    }

    try:
        response = requests.post(
            url,
            data=data,
            timeout=TIMEOUT,
        )

        if response.status_code == 200:
            return True

        print("Telegram error:", response.status_code)
        return False

    except requests.RequestException as exc:
        print("Telegram error:", exc)
        return False


def clean_url(url):
    if not url:
        return None

    url = url.strip()

    if url.startswith("//"):
        url = "https:" + url

    if not url.startswith("http://") and not url.startswith("https://"):
        return None

    return url


def get_price(text):
    if not text:
        return None

    patterns = [
        ("PLN", r"([0-9][0-9\s.,]*)\s*(?:PLN|zł)"),
        ("EUR", r"(?:€|EUR)\s*([0-9][0-9\s.,]*)"),
        ("EUR", r"([0-9][0-9\s.,]*)\s*(?:€|EUR)"),
        ("USD", r"(?:\$|USD)\s*([0-9][0-9\s.,]*)"),
        ("GBP", r"(?:£|GBP)\s*([0-9][0-9\s.,]*)"),
        ("CAD", r"(?:CAD)\s*([0-9][0-9\s.,]*)"),
        ("AUD", r"(?:AUD)\s*([0-9][0-9\s.,]*)"),
    ]

    for currency, pattern in patterns:
        matches = re.findall(pattern, text)

        for match in matches:
            value = match.replace(" ", "")
            value = value.replace("\xa0", "")

            if "," in value and "." in value:
                if value.rfind(",") > value.rfind("."):
                    value = value.replace(".", "")
                    value = value.replace(",", ".")
                else:
                    value = value.replace(",", "")

            elif "," in value:
                parts = value.split(",")

                if len(parts[-1]) == 2:
                    value = value.replace(",", ".")
                else:
                    value = value.replace(",", "")

            try:
                number = float(value)
            except ValueError:
                continue

            if number < 5 or number > 100000:
                continue

            return {
                "currency": currency,
                "price": number,
                "pln": number * RATES[currency],
            }

    return None


def score_listing(title):
    text = title.lower()
    score = 0

    for word, points in POSITIVE.items():
        if word in text:
            score += points

    for word, points in NEGATIVE.items():
        if word in text:
            score += points

    return score


def search_ebay(query):
    print("[eBay]", query)

    url = (
        "https://www.ebay.com/sch/i.html"
        f"?_nkw={quote_plus(query)}"
    )

    try:
        response = requests.get(
            url,
            headers=HEADERS,
            timeout=TIMEOUT,
        )

        if response.status_code >= 400:
            print("eBay HTTP", response.status_code)
            return []

        soup = BeautifulSoup(
            response.text,
            "html.parser",
        )

        results = []

        for item in soup.select("li.s-item"):
            link = item.select_one("a.s-item__link")
            title = item.select_one(".s-item__title")
            price = item.select_one(".s-item__price")

            if not link or not title:
                continue

            href = clean_url(link.get("href"))

            if not href:
                continue

            title_text = title.get_text(
                " ",
                strip=True,
            )

            price_text = ""

            if price:
                price_text = price.get_text(
                    " ",
                    strip=True,
                )

            results.append(
                {
                    "marketplace": "eBay",
                    "title": title_text,
                    "url": href,
                    "price_text": price_text,
                }
            )

        return results

    except requests.RequestException as exc:
        print("eBay error:", exc)
        return []


def search_olx(query):
    print("[OLX]", query)

    url = (
        "https://www.olx.pl/oferty/q-"
        f"{quote_plus(query)}/"
    )

    try:
        response = requests.get(
            url,
            headers=HEADERS,
            timeout=TIMEOUT,
        )

        if response.status_code >= 400:
            print("OLX HTTP", response.status_code)
            return []

        soup = BeautifulSoup(
            response.text,
            "html.parser",
        )

        results = []

        for link in soup.find_all("a", href=True):
            href = link.get("href")

            if not href:
                continue

            if not href.startswith("http"):
                href = "https://www.olx.pl" + href

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
                    "price_text": "",
                }
            )

        return results

    except requests.RequestException as exc:
        print("OLX error:", exc)
        return []


def search_vinted(query):
    print("[Vinted]", query)

    url = (
        "https://www.vinted.pl/catalog"
        f"?search_text={quote_plus(query)}"
    )

    try:
        response = requests.get(
            url,
            headers=HEADERS,
            timeout=TIMEOUT,
        )

        if response.status_code >= 400:
            print("Vinted HTTP", response.status_code)
            return []

        soup = BeautifulSoup(
            response.text,
            "html.parser",
        )

        results = []

        for link in soup.find_all("a", href=True):
            href = link.get("href")

            if not href:
                continue

            if not href.startswith("http"):
                href = "https://www.vinted.pl" + href

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
                    "price_text": "",
                }
            )

        return results

    except requests.RequestException as exc:
        print("Vinted error:", exc)
        return []


def search_bricklink(query):
    print("[BrickLink]", query)

    if query == "njo0108":
        url = (
            "https://www.bricklink.com/v2/catalog/"
            "catalogitem.page?M=njo0108"
        )
    elif query == "5004076":
        url = (
            "https://www.bricklink.com/v2/catalog/"
            "catalogitem.page?S=5004076-1"
        )
    else:
        return []

    return [
        {
            "marketplace": "BrickLink",
            "title": query,
            "url": url,
            "price_text": "",
            "catalog_only": True,
        }
    ]


def search_duckduckgo(query):
    print("[DuckDuckGo]", query)

    url = (
        "https://html.duckduckgo.com/html/"
        f"?q={quote_plus(query)}"
    )

    try:
        response = requests.get(
            url,
            headers=HEADERS,
            timeout=TIMEOUT,
        )

        if response.status_code >= 400:
            print(
                "DuckDuckGo HTTP",
                response.status_code,
            )
            return []

        soup = BeautifulSoup(
            response.text,
            "html.parser",
        )

        results = []

        for item in soup.select(".result"):
            link = item.select_one(".result__a")

            if not link:
                continue

            href = link.get("href")

            if not href:
                continue

            if href.startswith("//"):
                href = "https:" + href

            title = link.get_text(
                " ",
                strip=True,
            )

            snippet = item.select_one(
                ".result__snippet"
            )

            description = ""

            if snippet:
                description = snippet.get_text(
                    " ",
                    strip=True,
                )

            results.append(
                {
                    "marketplace": "Search",
                    "title": title,
                    "url": href,
                    "price_text": description,
                }
            )

        return results

    except requests.RequestException as exc:
        print(
            "DuckDuckGo error:",
            exc,
        )
        return []


def verify(url):
    try:
        response = requests.get(
            url,
            headers=HEADERS,
            timeout=TIMEOUT,
            allow_redirects=True,
        )

        if response.status_code >= 400:
            return False, response.url, "HTTP error"

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

        for word in DEAD_WORDS:
            if word in text:
                return False, response.url, word

        signals = 0

        for word in OFFER_WORDS:
            if word in text:
                signals += 1

        if signals < 2:
            return (
                False,
                response.url,
                "Not enough listing signals",
            )

        return True, response.url, "Verified"

    except requests.RequestException as exc:
        return False, url, str(exc)


def save_csv(results):
    fields = [
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

    existing = []

    if os.path.exists("results.csv"):
        try:
            with open(
                "results.csv",
                "r",
                encoding="utf-8",
                newline="",
            ) as file:
                existing = list(
                    csv.DictReader(file)
                )
        except Exception:
            existing = []

    timestamp = datetime.utcnow().isoformat()

    rows = []

    for result in results:
        rows.append(
            {
                "timestamp": timestamp,
                "marketplace": result.get(
                    "marketplace",
                    "",
                ),
                "title": result.get(
                    "title",
                    "",
                ),
                "url": result.get(
                    "url",
                    "",
                ),
                "final_url": result.get(
                    "final_url",
                    "",
                ),
                "currency": result.get(
                    "currency",
                    "",
                ),
                "price": result.get(
                    "price",
                    "",
                ),
                "price_pln": result.get(
                    "price_pln",
                    "",
                ),
                "score": result.get(
                    "score",
                    "",
                ),
                "deal": result.get(
                    "deal",
                    "",
                ),
                "verified": result.get(
                    "verified",
                    "",
                ),
                "verification_reason": result.get(
                    "verification_reason",
                    "",
                ),
            }
        )

    rows = existing + rows
    rows = rows[-5000:]

    with open(
        "results.csv",
        "w",
        encoding="utf-8",
        newline="",
    ) as file:
        writer = csv.DictWriter(
            file,
            fieldnames=fields,
        )

        writer.writeheader()
        writer.writerows(rows)


def main():
    print("=" * 60)
    print("LLOYD HUNTER")
    print("=" * 60)

    raw_results = []

    for query in SEARCHES["eBay"]:
        raw_results.extend(
            search_ebay(query)
        )
        time.sleep(DELAY)

    for query in SEARCHES["OLX"]:
        raw_results.extend(
            search_olx(query)
        )
        time.sleep(DELAY)

    for query in SEARCHES["Vinted"]:
        raw_results.extend(
            search_vinted(query)
        )
        time.sleep(DELAY)

    for query in SEARCHES["BrickLink"]:
        raw_results.extend(
            search_bricklink(query)
        )
        time.sleep(DELAY)

    for query in SEARCHES["DuckDuckGo"]:
        raw_results.extend(
            search_duckduckgo(query)
        )
        time.sleep(DELAY)

    print()
    print(
        "Raw results:",
        len(raw_results),
    )

    results = []
    seen = set()

    for raw in raw_results:
        url = clean_url(
            raw.get("url")
        )

        if not url:
            continue

        if url in seen:
            continue

        seen.add(url)

        title = raw.get(
            "title",
            "",
        )

        price_text = raw.get(
            "price_text",
            "",
        )

        price = get_price(
            f"{title} {price_text}"
        )

        score = score_listing(title)

        if price:
            price_pln = price["pln"]

            if price_pln <= 400 and score >= 60:
                deal = "INSANE DEAL"
            elif price_pln <= 600 and score >= 50:
                deal = "GREAT DEAL"
            elif price_pln <= 800 and score >= 45:
                deal = "GOOD DEAL"
            elif price_pln <= MAX_PRICE_PLN and score >= 35:
                deal = "POSSIBLE DEAL"
            else:
                deal = "CHECK"
        else:
            price_pln = ""
            deal = "NO PRICE"

        result = {
            "marketplace": raw.get(
                "marketplace",
                "Unknown",
            ),
            "title": title,
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
                if price
                else ""
            ),
            "score": score,
            "deal": deal,
            "verified": False,
            "verification_reason": "",
        }

        if raw.get("catalog_only"):
            result["verification_reason"] = (
                "BrickLink catalog page"
            )
        else:
            print()
            print(
                "Checking:",
                title[:80],
            )

            ok, final_url, reason = verify(url)

            result["verified"] = ok
            result["final_url"] = final_url
            result["verification_reason"] = reason

            if ok:
                print("VERIFIED")
            else:
                print(
                    "Rejected:",
                    reason,
                )

        results.append(result)
        time.sleep(DELAY)

    save_csv(results)

    alerts = 0

    for result in results:
        if not result["verified"]:
            continue

        if not result["price_pln"]:
            continue

        if float(result["price_pln"]) > MAX_PRICE_PLN:
            continue

        if result["score"] < 30:
            continue

        price_pln = float(
            result["price_pln"]
        )

        if result["deal"] == "INSANE DEAL":
            emoji = "🚨"
        elif result["deal"] == "GREAT DEAL":
            emoji = "🔥"
        elif result["deal"] == "GOOD DEAL":
            emoji = "🟢"
        else:
            emoji = "🟡"

        message = (
            f"{emoji} {price_pln:.2f} PLN — "
            f"{result['deal']}\n\n"
            f"📦 {result['title']}\n"
            f"🌐 {result['marketplace']}\n"
            f"⭐ Score: {result['score']}\n"
            f"💰 Original price: "
            f"{result['price']} "
            f"{result['currency']}\n\n"
            f"🔗 {result['final_url']}"
        )

        if send_telegram(message):
            alerts += 1

        time.sleep(1)

    verified = sum(
        1
        for result in results
        if result["verified"]
    )

    print()
    print("=" * 60)
    print("HUNT COMPLETE")
    print("=" * 60)
    print(
        "Unique results:",
        len(results),
    )
    print(
        "Verified listings:",
        verified,
    )
    print(
        "Telegram alerts:",
        alerts,
    )
    print(
        "Saved to results.csv"
    )


if __name__ == "__main__":
    main()
