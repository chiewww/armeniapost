#!/usr/bin/env python3

from datetime import datetime, timezone
from pathlib import Path

import requests


BASE_URL = "https://api.haypost.am"

PAGE_URL = f"{BASE_URL}/page/91"
POSTAL_CALCULATOR_URL = f"{BASE_URL}/postalCalculator"

# Haypost configuration:
# International = local=false
# Postcard = postal_id 12
# Ordinary / Հասարակ = postal_simple / category 1
LOCAL = False
POSTAL_ID = 12
POSTAL_CATEGORY = 1

# Requested postcard weight.
WEIGHT_GRAMS = 10

# Russia / Moscow.
RUSSIA_ID = 86
MOSCOW_REGION_ID = 14

OUTPUT_FILE = Path("output.txt")

SESSION = requests.Session()
SESSION.headers.update(
    {
        "User-Agent": "armeniapost-monitor/1.0",
        "Accept": "application/json",
    }
)


def get_json(url, params=None):
    response = SESSION.get(url, params=params, timeout=30)
    response.raise_for_status()
    return response.json()


def clean_name(value):
    if value is None:
        return ""

    return str(value).strip()


def get_countries():
    """
    Fetch Haypost page 91 and return its countries.
    """
    data = get_json(
        PAGE_URL,
        params={"lng": "am"},
    )

    countries = (
        data.get("module", {})
        .get("countries", [])
    )

    if not isinstance(countries, list):
        raise RuntimeError(
            "Could not find module.countries in page/91 response"
        )

    return countries


def get_region_id(country):
    """
    Haypost currently supplies a region for Russia.
    For Russia we explicitly select Moscow.
    """
    if country.get("id") == RUSSIA_ID:
        return MOSCOW_REGION_ID

    return None


def get_postal_calculator(country):
    """
    Request the international Postcard calculator data.
    """
    params = {
        "postal_id": POSTAL_ID,
        "local": str(LOCAL).lower(),
        "country_id": country["id"],
    }

    region_id = get_region_id(country)

    if region_id is not None:
        params["region_id"] = region_id

    return get_json(
        POSTAL_CALCULATOR_URL,
        params=params,
    )


def calculate_simple_tariff(calculator):
    """
    Calculate the Ordinary / Հասարակ Postcard tariff.

    We deliberately use postal_simple only.

    This corresponds to:
        postal_id = 12       -> Postcard
        postal_simple       -> Ordinary / Հասարակ
    """

    tariffs = calculator.get("postal_simple") or []

    if not tariffs:
        return None

    weight = WEIGHT_GRAMS

    # Normal ranges, e.g. 0-20 g.
    for item in tariffs:
        min_weight = item.get("min_weight")
        max_weight = item.get("max_weight")

        if min_weight is None or max_weight is None:
            continue

        # Special unlimited tariff.
        if min_weight == -1 and max_weight == -1:
            return item.get("price")

        if min_weight <= weight <= max_weight:
            return item.get("price")

    # Open-ended tariff.
    for item in tariffs:
        min_weight = item.get("min_weight")
        max_weight = item.get("max_weight")

        if min_weight is None or max_weight != -1:
            continue

        if weight >= min_weight:
            previous = next(
                (
                    x
                    for x in tariffs
                    if x.get("max_weight") == min_weight
                ),
                None,
            )

            price = 0

            if previous:
                price += previous.get("price") or 0

            multiplier = (
                (weight - min_weight + 999) // 1000
            )

            price += multiplier * (item.get("price") or 0)

            return price

    return None


def process():
    countries = get_countries()

    if not countries:
        raise RuntimeError(
            "Haypost returned no countries"
        )

    results = []

    for country in countries:
        country_id = country.get("id")
        name = clean_name(country.get("name"))

        if not country_id or not name:
            continue

        region_id = get_region_id(country)

        try:
            calculator = get_postal_calculator(country)

            price = calculate_simple_tariff(calculator)

            results.append(
                {
                    "country_id": country_id,
                    "country": name,
                    "region_id": region_id,
                    "price": price,
                }
            )

        except Exception as exc:
            print(
                f"WARNING: Failed for "
                f"{name} ({country_id}): {exc}"
            )

            results.append(
                {
                    "country_id": country_id,
                    "country": name,
                    "region_id": region_id,
                    "price": None,
                }
            )

    return results


def write_output(results):
    now = datetime.now(timezone.utc).strftime(
        "%Y-%m-%d %H:%M:%S UTC"
    )

    lines = []

    lines.append("HAYPOST POSTCARD TARIFF MONITOR")
    lines.append("")
    lines.append(
        "Configuration: International / "
        "Postcard / Ordinary (Հասարակ) / 10 g"
    )
    lines.append(f"Checked: {now}")
    lines.append("")
    lines.append(
        "Country — Postcard tariff"
    )
    lines.append(
        "=========================="
    )

    for result in results:
        country = result["country"]
        price = result["price"]

        if price is None:
            lines.append(
                f"{country} — N/A"
            )
        else:
            lines.append(
                f"{country} — {price} AMD"
            )

    lines.append("")
    lines.append(
        f"Total countries checked: {len(results)}"
    )

    OUTPUT_FILE.write_text(
        "\n".join(lines) + "\n",
        encoding="utf-8",
    )


def main():
    print("Starting Haypost postcard tariff monitor...")

    results = process()

    write_output(results)

    print(
        f"Checked {len(results)} countries."
    )

    print(
        f"Wrote {OUTPUT_FILE}"
    )


if __name__ == "__main__":
    main()
