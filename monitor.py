#!/usr/bin/env python3

import sys
from datetime import datetime, timezone
from pathlib import Path

import requests

BASE_URL = "https://api.haypost.am"

PAGE_URL = f"{BASE_URL}/page/91"
POSTAL_CALCULATOR_URL = f"{BASE_URL}/postalCalculator"
ADDITIONAL_TARIFFS_URL = f"{BASE_URL}/postalAdditionalTariffs"

# International
LOCAL = False

# Postcard
POSTAL_ID = 12

# Ordinary / Հասարակ
# postal_simple = category 1
POSTAL_CATEGORY = 1

# Requested weight
WEIGHT_GRAMS = 10

# Russia
RUSSIA_ID = 86

# Moscow
MOSCOW_REGION_ID = 14

OUTPUT_FILE = Path("output.txt")

SESSION = requests.Session()
SESSION.headers.update({
    "User-Agent": "armeniapost-monitor/1.0",
    "Accept": "application/json",
})


def get_json(url, params=None):
    """GET JSON from the ArmeniaPost API."""
    response = SESSION.get(
        url,
        params=params,
        timeout=30,
    )
    response.raise_for_status()
    return response.json()


def clean_name(value):
    """Clean country names without translating them."""
    if value is None:
        return ""

    return str(value).strip()


def get_countries():
    """Fetch countries from ArmeniaPost page 91."""
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
            "Could not find module.countries"
        )

    return countries


def get_region_id(country):
    """Return the required region ID."""

    if country.get("id") == RUSSIA_ID:
        return MOSCOW_REGION_ID

    return None


def get_postal_calculator(country):
    """
    Request International Postcard pricing.

    postal_id=12 = Postcard
    local=false = International
    """

    params = {
        "postal_id": POSTAL_ID,
        "local": "false",
        "country_id": country["id"],
    }

    region_id = get_region_id(country)

    if region_id is not None:
        params["region_id"] = region_id

    return get_json(
        POSTAL_CALCULATOR_URL,
        params=params,
    )


def calculate_from_tariff_list(tariffs):
    """Find the tariff applicable to WEIGHT_GRAMS."""

    if not tariffs:
        return None

    weight = WEIGHT_GRAMS

    for item in tariffs:
        min_weight = item.get("min_weight")
        max_weight = item.get("max_weight")

        if min_weight is None or max_weight is None:
            continue

        if min_weight == -1 and max_weight == -1:
            return item.get("price")

        if min_weight <= weight <= max_weight:
            return item.get("price")

    for item in tariffs:
        min_weight = item.get("min_weight")
        max_weight = item.get("max_weight")

        if min_weight is None:
            continue

        if max_weight != -1:
            continue

        if weight < min_weight:
            continue

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

        tariff_price = item.get("price") or 0

        multiplier = (
            (weight - min_weight + 999)
            // 1000
        )

        price += multiplier * tariff_price

        return price

    return None


def calculate_tariff(calculator):
    """
    Calculate ONLY the Ordinary Postcard tariff.

    postal_simple = Ordinary / Հասարակ

    No fallback to Standard, Express, Ordered,
    Trajectory, or EMS.
    """

    tariffs = calculator.get("postal_simple") or []

    price = calculate_from_tariff_list(tariffs)

    return {
        "price": price,
        "tariff_type": "postal_simple",
        "tariffs": tariffs,
    }


def get_additional_tariffs():
    """
    Request additional tariffs for:

    Postcard + Ordinary.
    """

    params = {
        "local": "false",
        "postal_type": POSTAL_ID,
        "postal_category": POSTAL_CATEGORY,
    }

    return get_json(
        ADDITIONAL_TARIFFS_URL,
        params=params,
    )


def process():
    """Process every country and retrieve its tariff."""

    countries = get_countries()

    if not countries:
        raise RuntimeError(
            "ArmeniaPost returned no countries"
        )

    results = []

    for country in countries:
        country_id = country.get("id")
        name = clean_name(country.get("name"))

        if not country_id or not name:
            continue

        try:
            calculator = get_postal_calculator(country)
            tariff = calculate_tariff(calculator)

            result = {
                "country_id": country_id,
                "country": name,
                "region_id": get_region_id(country),
                "tariff_type": tariff["tariff_type"],
                "price": tariff["price"],
            }

            results.append(result)

            price = tariff["price"]

            if price is None:
                price_text = "N/A"
            else:
                price_text = f"{price} AMD"

            print(f"{name}: {price_text}")

        except Exception as exc:
            print(
                f"WARNING: Failed for "
                f"{name} ({country_id}): {exc}",
                file=sys.stderr,
            )

    return results


def write_output(results):
    """Write country names and actual tariffs to output.txt."""

    now = datetime.now(
        timezone.utc
    ).strftime(
        "%Y-%m-%d %H:%M:%S UTC"
    )

    lines = []

    lines.append(
        "ARMENIAPOST POSTCARD TARIFF MONITOR"
    )
    lines.append("")
    lines.append(
        "Configuration: "
        "International / Postcard / Ordinary / 10 g"
    )
    lines.append("")
    lines.append(
        "POSTCARD TARIFFS"
    )
    lines.append(
        "================"
    )

    for result in results:
        country = result["country"]
        price = result["price"]
        region_id = result["region_id"]

        if price is None:
            price_text = "N/A"
        else:
            price_text = f"{price} AMD"

        if region_id == MOSCOW_REGION_ID:
            lines.append(
                f"{country} (Moscow): {price_text}"
            )
        else:
            lines.append(
                f"{country}: {price_text}"
            )

    lines.append("")
    lines.append(
        f"Total countries: {len(results)}"
    )
    lines.append("")
    lines.append(
        "API configuration:"
    )
    lines.append(
        "postal_id=12"
    )
    lines.append(
        "postal_category=1"
    )
    lines.append(
        "tariff=postal_simple"
    )
    lines.append(
        "weight=10 g"
    )
    lines.append("")
    lines.append(
        "Russia region: Moscow (region_id=14)"
    )

    OUTPUT_FILE.write_text(
        "\n".join(lines) + "\n",
        encoding="utf-8",
    )


def main():
    print(
        "Starting ArmeniaPost monitor..."
    )

    results = process()

    write_output(results)

    print(
        f"Found {len(results)} countries."
    )

    print(
        f"Wrote {OUTPUT_FILE}"
    )


if __name__ == "__main__":
    main()
