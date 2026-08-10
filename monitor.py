#!/usr/bin/env python3

import json
import sys
from pathlib import Path
from typing import Any

import requests


BASE_URL = "https://api.haypost.am"

PAGE_URL = f"{BASE_URL}/page/91?lng=am"
CALCULATOR_URL = f"{BASE_URL}/postalCalculator"

# HayPost International -> Postcard
POSTCARD_ID = 12

# 10 grams
WEIGHT_GRAMS = 10

# Russia -> Moscow
RUSSIA_ID = 86
MOSCOW_ID = 14

ROOT = Path(__file__).resolve().parent
TRANSLATIONS_FILE = ROOT / "country_translations.json"
OUTPUT_DIR = ROOT / "output"


SESSION = requests.Session()
SESSION.headers.update(
    {
        "User-Agent": "armeniapost-monitor/1.0",
        "Accept": "application/json",
    }
)


def get_json(url: str, params=None):
    response = SESSION.get(
        url,
        params=params,
        timeout=30,
    )

    response.raise_for_status()
    return response.json()


def find_countries(data: Any):
    """
    Find international country records in the /page/91 response.

    Country objects have:
        id
        name
        clearance_fee
        regions
    """

    countries = []

    def walk(value):
        if isinstance(value, dict):

            if (
                isinstance(value.get("id"), int)
                and isinstance(value.get("name"), str)
                and "clearance_fee" in value
                and isinstance(value.get("regions"), list)
            ):
                countries.append(value)

            for child in value.values():
                walk(child)

        elif isinstance(value, list):

            for child in value:
                walk(child)

    walk(data)

    # Remove duplicates while preserving order.
    result = {}
    for country in countries:
        result[country["id"]] = country

    return list(result.values())


def load_translations():

    with open(
        TRANSLATIONS_FILE,
        "r",
        encoding="utf-8",
    ) as f:
        return json.load(f)


def get_region_id(country):

    """
    Russia is the only country for which we currently need
    to select a region.

    Russia:
        country_id = 86
        Moscow = 14

    All other countries:
        region_id = null
    """

    if country["id"] == RUSSIA_ID:
        return MOSCOW_ID

    return None


def get_region_sub_price_flag(country, region_id):

    if region_id is None:
        return False

    for region in country.get("regions", []):

        if region.get("id") == region_id:
            return bool(
                region.get(
                    "postal_tariff_sub_price",
                    False,
                )
            )

    return False


def get_tariff_table(calculator_data):

    """
    Reproduce the effective tariff selection used by FinalInfo.js.

    Frontend logic:

        postal_standard
        postal_trajectory
        postal_simple
        postal_ordered

    The frontend uses the first applicable non-empty table.
    """

    standard = calculator_data.get("postal_standard") or []

    if standard:
        return "postal_standard", standard

    trajectory = calculator_data.get("postal_trajectory") or []

    if trajectory:
        return "postal_trajectory", trajectory

    simple = calculator_data.get("postal_simple") or []

    if simple:
        return "postal_simple", simple

    ordered = calculator_data.get("postal_ordered") or []

    if ordered:
        return "postal_ordered", ordered

    return "none", []


def calculate_price(
    tariff_rows,
    weight,
    use_sub_price=False,
):

    """
    Reproduce the weight calculation from HayPost's
    FinalInfo.js.

    For normal tariff rows:

        min_weight <= weight <= max_weight

    use price unless the selected region has
    postal_tariff_sub_price=true.
    """

    for item in tariff_rows:

        min_weight = item.get("min_weight")
        max_weight = item.get("max_weight")

        if min_weight is None or max_weight is None:
            continue

        # Normal range
        if min_weight <= weight <= max_weight:

            if use_sub_price:
                return item.get("sub_price")

            return item.get("price")

        # Special -1/-1 tariff
        if min_weight == -1 and max_weight == -1:

            return item.get("price")

        # Open-ended tariff
        if weight >= min_weight and max_weight == -1:

            previous = None

            for candidate in tariff_rows:

                if candidate.get("max_weight") == min_weight:
                    previous = candidate
                    break

            base_price = (
                previous.get("price", 0)
                if previous
                else 0
            )

            price = item.get("price") or 0

            multiplier = (
                (weight - min_weight + 999) // 1000
            )

            return base_price + multiplier * price

    return None


def calculate_country(country):

    country_id = country["id"]

    region_id = get_region_id(country)

    params = {
        "postal_id": POSTCARD_ID,
        "local": "false",
        "country_id": country_id,
    }

    if region_id is not None:
        params["region_id"] = region_id

    calculator = get_json(
        CALCULATOR_URL,
        params=params,
    )

    tariff_name, tariff_rows = get_tariff_table(
        calculator
    )

    use_sub_price = get_region_sub_price_flag(
        country,
        region_id,
    )

    price = calculate_price(
        tariff_rows,
        WEIGHT_GRAMS,
        use_sub_price,
    )

    return {
        "id": country_id,
        "name_hy": country["name"],
        "region_id": region_id,
        "tariff": tariff_name,
        "price": price,
    }


def main():

    print("Downloading HayPost country list...")

    page = get_json(PAGE_URL)

    countries = find_countries(page)

    if not countries:

        raise RuntimeError(
            "No countries found in HayPost /page/91 response."
        )

    print(
        f"Found {len(countries)} countries."
    )

    translations = load_translations()

    # Do not silently create bad English names.
    missing = []

    for country in countries:

        if str(country["id"]) not in translations:

            missing.append(country)

    if missing:

        print(
            "\nERROR: Missing English translations:\n",
            file=sys.stderr,
        )

        for country in missing:

            print(
                f'  {country["id"]}: '
                f'{country["name"]}',
                file=sys.stderr,
            )

        print(
            "\nAdd these IDs to "
            "country_translations.json.",
            file=sys.stderr,
        )

        return 2

    results = []

    for index, country in enumerate(
        countries,
        start=1,
    ):

        print(
            f"[{index}/{len(countries)}] "
            f'{country["name"]}'
        )

        result = calculate_country(
            country
        )

        result["name_en"] = translations[
            str(country["id"])
        ]

        results.append(result)

        print(
            f'    {result["name_en"]}: '
            f'{result["price"]} AMD '
            f'[{result["tariff"]}]'
        )

    # Alphabetical English order.
    results.sort(
        key=lambda item: item["name_en"].casefold()
    )

    OUTPUT_DIR.mkdir(
        parents=True,
        exist_ok=True,
    )

    # --------------------------------
    # ALL COUNTRIES
    # --------------------------------

    country_lines = []

    for result in results:

        line = (
            f'{result["name_hy"]} — '
            f'{result["name_en"]}'
        )

        country_lines.append(line)

    countries_file = (
        OUTPUT_DIR / "countries.txt"
    )

    countries_file.write_text(
        "\n".join(country_lines) + "\n",
        encoding="utf-8",
    )

    # --------------------------------
    # ZERO AMD
    # --------------------------------

    zero_lines = []

    for result in results:

        if result["price"] == 0:

            line = (
                f'{result["name_hy"]} — '
                f'{result["name_en"]}'
            )

            zero_lines.append(line)

    zero_file = (
        OUTPUT_DIR / "zero_amd.txt"
    )

    if zero_lines:

        zero_file.write_text(
            "\n".join(zero_lines) + "\n",
            encoding="utf-8",
        )

    else:

        zero_file.write_text(
            "",
            encoding="utf-8",
        )

    print()
    print("================================")
    print("Monitoring complete")
    print("================================")
    print(
        f"Countries: {len(results)}"
    )
    print(
        f"Zero AMD:  {len(zero_lines)}"
    )
    print(
        f"Written:   {countries_file}"
    )
    print(
        f"Written:   {zero_file}"
    )

    return 0


if __name__ == "__main__":
    sys.exit(main())
