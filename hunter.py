import csv
import re
import time
from datetime import datetime, timezone
from urllib.parse import quote_plus

import requests
from bs4 import BeautifulSoup

MAX_PRICE_PLN = 1000

SEARCHES = [
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
