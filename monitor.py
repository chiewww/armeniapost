#!/usr/bin/env python3

import sys
from datetime import datetime, timezone
from pathlib import Path

import requests


# ============================================================
# ArmeniaPost API
# ============================================================

BASE_URL = "https://api.haypost.am"

PAGE_URL = f"{BASE_URL}/page/91"
POSTAL_CALCULATOR_URL = f"{BASE_URL}/postalCalculator"


# ============================================================
# Configuration
# ============================================================

# International
LOCAL = False

# Postcard
POSTAL_ID = 12

# Ordinary
# postal_simple = category 1
POSTAL_CATEGORY = 1

# Postcard weight
WEIGHT_GRAMS = 10

# Russia / Moscow
RUSSIA_ID = 86
MOSCOW_REGION_ID = 14

# Output
OUTPUT_FILE = Path("output.txt")


# ============================================================
# HTTP session
# ============================================================

SESSION = requests.Session()

SESSION.headers.update(
    {
        "User-Agent": "armeniapost-monitor/1.0",
        "Accept": "application/json",
    }
)


# ============================================================
# Helpers
# ============================================================

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
    """Clean a country name without changing its spelling."""

    if value is None:
        return ""

    return str(value).strip()


def is_zero_price(price):
    """Return True when the tariff is exactly 0 AMD."""

    if price is None:
        return False

    try:
        return float(price) == 0
    except (TypeError, ValueError):
        return False


# ============================================================
# Countries
# ============================================================

def get_countries():
    """
    Fetch the ArmeniaPost Postal Calculator page.

    Country names are kept in Armenian because the API
    currently provides the names in Armenian.
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


# ============================================================
# Regions
# ============================================================

def get_region_id(country):
    """
    Select the required region.

    Russia is explicitly set to Moscow.

    Other countries are requested without a region unless
    specifically configured here.
    """

    country_id = country.get("id")

    if country_id == RUSSIA_ID:
        return MOSCOW_REGION_ID

    return None


# ============================================================
# Postal calculator
# ============================================================

def get_postal_calculator(country):
    """
    Request the Postcard tariff for a country.

    postal_id=12 -> Postcard
    local=false  -> International
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


# ============================================================
# Tariff calculation
# ============================================================

def calculate_from_tariff_list(tariffs):
    """
    Calculate the tariff for WEIGHT_GRAMS.

    This follows the weight logic visible in the ArmeniaPost
    frontend.
    """

    if not tariffs:
        return None

    weight = WEIGHT_GRAMS

    # Normal weight ranges.
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

        if min_weight is None:
            continue

        if max_weight != -1:
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
                (
                    (weight - min_weight + 999)
                    // 1000
                )
                * (item.get("price") or 0)
            )

            price += multiplier

            return price

    return None


def calculate_tariff(calculator):
    """
    Select the appropriate Postcard tariff.

    For the requested Postcard + Ordinary configuration,
    postal_simple is the primary tariff category.

    Fallbacks are retained in case the API does not return
    postal_simple for a particular destination.
    """

    simple = calculator.get("postal_simple") or []
    standard = calculator.get("postal_standard") or []
    trajectory = calculator.get("postal_trajectory") or []
    ordered = calculator.get("postal_ordered") or []

    if simple:
        tariff_list = simple
        tariff_type = "postal_simple"

    elif standard:
        tariff_list = standard
        tariff_type = "postal_standard"

    elif trajectory:
        tariff_list = trajectory
        tariff_type = "postal_trajectory"

    elif ordered:
        tariff_list = ordered
        tariff_type = "postal_ordered"

    else:
        return {
            "price": None,
            "tariff_type": "none",
            "tariffs": [],
        }

    price = calculate_from_tariff_list(
        tariff_list
    )

    return {
        "price": price,
        "tariff_type": tariff_type,
        "tariffs": tariff_list,
    }


# ============================================================
# Process all countries
# ============================================================

def process():
    """
    Fetch every country and determine its Postcard + Ordinary
    tariff.
    """

    countries = get_countries()

    if not countries:
        raise RuntimeError(
            "ArmeniaPost returned no countries"
        )

    results = []

    for country in countries:

        country_id = country.get("id")
        name = clean_name(
            country.get("name")
        )

        if not country_id or not name:
            continue

        region_id = get_region_id(country)

        try:

            calculator = get_postal_calculator(
                country
            )

            tariff = calculate_tariff(
                calculator
            )

            results.append(
                {
                    "country_id": country_id,
                    "country": name,
                    "region_id": region_id,
                    "tariff_type": tariff[
                        "tariff_type"
                    ],
                    "price": tariff[
                        "price"
                    ],
                }
            )

            print(
                f"{name}: "
                f"{tariff['price']} AMD "
                f"({tariff['tariff_type']})"
            )

        except Exception as exc:

            print(
                f"WARNING: Failed for "
                f"{name} ({country_id}): {exc}",
                file=sys.stderr,
            )

            # Keep the country in output even if the API
            # request fails, so monitoring does not silently
            # remove it.
            results.append(
                {
                    "country_id": country_id,
                    "country": name,
                    "region_id": region_id,
                    "tariff_type": "error",
                    "price": None,
                }
            )

    return results


# ============================================================
# Output
# ============================================================

def write_output(results):
    """
    Write output.txt.

    IMPORTANT:
    The 0 AMD COUNTRIES section is ALWAYS written.

    If there are currently no zero-price countries, it contains
    the word NONE.
    """

    now = datetime.now(
        timezone.utc
    ).strftime(
        "%Y-%m-%d %H:%M:%S UTC"
    )

    zero_countries = []

    for result in results:

        if is_zero_price(
            result.get("price")
        ):
            zero_countries.append(
                result
            )

    lines = []

    # --------------------------------------------------------
    # Header
    # --------------------------------------------------------

    lines.append(
        "ARMENIAPOST POSTCARD TARIFF MONITOR"
    )

    lines.append("")

    lines.append(
        "Configuration: "
        "International / Postcard / Ordinary"
    )

    lines.append(
        f"Weight: {WEIGHT_GRAMS} g"
    )

    lines.append(
        f"Checked: {now}"
    )

    lines.append("")

    # --------------------------------------------------------
    # 0 AMD section
    # --------------------------------------------------------

    lines.append(
        "0 AMD COUNTRIES"
    )

    lines.append(
        "==============="
    )

    if zero_countries:

        for result in zero_countries:

            lines.append(
                f"{result['country']} — 0 AMD"
            )

    else:

        # THIS LINE IS ALWAYS PRESENT.
        lines.append(
            "NONE"
        )

    lines.append("")

    # --------------------------------------------------------
    # All tariffs
    # --------------------------------------------------------

    lines.append(
        "ALL POSTCARD TARIFFS"
    )

    lines.append(
        "===================="
    )

    for result in results:

        country = result.get(
            "country",
            "Unknown",
        )

        price = result.get(
            "price"
        )

        if price is None:

            price_text = "N/A"

        else:

            try:

                number = float(price)

                if number.is_integer():
                    price_text = (
                        f"{int(number)} AMD"
                    )
                else:
                    price_text = (
                        f"{number:g} AMD"
                    )

            except (
                TypeError,
                ValueError,
            ):

                price_text = (
                    f"{price} AMD"
                )

        lines.append(
            f"{country} — {price_text}"
        )

    lines.append("")

    # --------------------------------------------------------
    # Summary
    # --------------------------------------------------------

    lines.append(
        "SUMMARY"
    )

    lines.append(
        "======="
    )

    lines.append(
        f"Countries checked: "
        f"{len(results)}"
    )

    lines.append(
        f"0 AMD countries: "
        f"{len(zero_countries)}"
    )

    lines.append("")

    # --------------------------------------------------------
    # Write file
    # --------------------------------------------------------

    OUTPUT_FILE.write_text(
        "\n".join(lines) + "\n",
        encoding="utf-8",
    )

    print(
        f"Wrote {OUTPUT_FILE}"
    )

    print(
        f"Countries checked: "
        f"{len(results)}"
    )

    print(
        f"0 AMD countries: "
        f"{len(zero_countries)}"
    )


# ============================================================
# Main
# ============================================================

def main():

    print(
        "Starting ArmeniaPost monitor..."
    )

    try:

        results = process()

        write_output(
            results
        )

    except Exception as exc:

        print(
            f"ERROR: {exc}",
            file=sys.stderr,
        )

        raise


if __name__ == "__main__":
    main()
