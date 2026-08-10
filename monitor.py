#!/usr/bin/env python3

import sys
from datetime import datetime, timezone
from pathlib import Path

import requests


BASE_URL = "https://api.haypost.am"

PAGE_URL = f"{BASE_URL}/page/91"
POSTAL_CALCULATOR_URL = f"{BASE_URL}/postalCalculator"
ADDITIONAL_TARIFFS_URL = f"{BASE_URL}/postalAdditionalTariffs"


# Haypost:
# International = local=false
# Postcard = postal_id 12
# Ordinary = postal_simple = category 1

LOCAL = False
POSTAL_ID = 12
POSTAL_CATEGORY = 1

# Requested weight.
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
    """
    Keep Haypost's Armenian country spelling exactly as supplied,
    while removing accidental leading/trailing whitespace.
    """
    if value is None:
        return ""

    return str(value).strip()


def get_countries():
    """
    Fetch page 91 and return the countries supplied by Haypost.
    """
    data = get_json(PAGE_URL, params={"lng": "am"})

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
    Haypost currently has regions for only a small number of countries.

    For Russia we explicitly select Moscow because the calculator
    requires a region for the Moscow tariff.

    For other countries, do not automatically select a region.
    """
    country_id = country.get("id")

    if country_id == RUSSIA_ID:
        return MOSCOW_REGION_ID

    return None


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


def calculate_tariff(calculator):
    """
    Reproduce the relevant part of Haypost's FinalInfo logic.

    Priority:

    1. postal_standard
    2. postal_trajectory
    3. postal_simple
    4. postal_ordered
    """
    standard = calculator.get("postal_standard") or []
    trajectory = calculator.get("postal_trajectory") or []
    simple = calculator.get("postal_simple") or []
    ordered = calculator.get("postal_ordered") or []

    if standard:
        tariff_list = standard
        tariff_type = "postal_standard"

    elif trajectory:
        tariff_list = trajectory
        tariff_type = "postal_trajectory"

    elif simple:
        tariff_list = simple
        tariff_type = "postal_simple"

    else:
        tariff_list = ordered
        tariff_type = "postal_ordered"

    price = calculate_from_tariff_list(tariff_list)

    return {
        "price": price,
        "tariff_type": tariff_type,
        "tariffs": tariff_list,
    }


def calculate_from_tariff_list(tariffs):
    """
    Calculate the Haypost tariff for the requested weight.

    This follows the weight logic visible in FinalInfo.js.
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

        # Unlimited / special tariff.
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
                ((weight - min_weight + 999) // 1000)
                * (item.get("price") or 0)
            )

            price += multiplier

            return price

    return None


def get_additional_tariffs():
    """
    Request the additional-tariff data.

    postal_type=12      -> Postcard
    postal_category=1   -> postal_simple / Ordinary
    """
    params = {
        "local": str(LOCAL).lower(),
        "postal_type": POSTAL_ID,
        "postal_category": POSTAL_CATEGORY,
    }

    return get_json(
        ADDITIONAL_TARIFFS_URL,
        params=params,
    )


def find_zero_insert_value(data):
    """
    Find an additional-service entry corresponding to:

        "Առաքանու ներդիրի արժեք"

    Haypost's frontend displays an additional service using:

        e.short_title
        e.price || 0 === e.price ? e.price : e.value
        e.percent ? "%" : "AMD"

    The API response is therefore handled flexibly.
    """
    target_phrases = [
        "Առաքանու ներդիրի արժեք",
        "Առաքանու ներդիրի",
    ]

    matches = []

    def walk(value):
        if isinstance(value, dict):
            label_values = []

            for key in (
                "short_title",
                "title",
                "name",
                "label",
                "description",
            ):
                if key in value and value[key] is not None:
                    label_values.append(str(value[key]))

            label = " ".join(label_values).strip()

            if any(
                phrase in label
                for phrase in target_phrases
            ):
                raw_value = None

                # Mirrors the frontend's selection of price/value.
                if "price" in value:
                    raw_value = value["price"]
                elif "value" in value:
                    raw_value = value["value"]

                matches.append(
                    {
                        "label": label,
                        "value": raw_value,
                        "object": value,
                    }
                )

            for child in value.values():
                walk(child)

        elif isinstance(value, list):
            for child in value:
                walk(child)

    walk(data)

    if not matches:
        return None

    exact = [
        item
        for item in matches
        if item["label"] == "Առաքանու ներդիրի արժեք"
    ]

    return exact[0] if exact else matches[0]


def is_zero(value):
    """
    Safely determine whether a value represents 0 AMD.
    """
    if value is None:
        return False

    if isinstance(value, bool):
        return False

    if isinstance(value, (int, float)):
        return value == 0

    text = str(value).strip()

    if not text:
        return False

    text = text.replace(",", "")
    text = text.replace("AMD", "")
    text = text.strip()

    try:
        return float(text) == 0
    except ValueError:
        return False


def process():
    countries = get_countries()

    if not countries:
        raise RuntimeError("Haypost returned no countries")

    additional_tariffs = get_additional_tariffs()
    additional_service = find_zero_insert_value(
        additional_tariffs
    )

    if additional_service is None:
        print(
            "WARNING: Could not find "
            "'Առաքանու ներդիրի արժեք' "
            "in postalAdditionalTariffs response.",
            file=sys.stderr,
        )

    country_names = []
    zero_countries = []
    results = []

    for country in countries:
        country_id = country.get("id")
        name = clean_name(country.get("name"))

        if not country_id or not name:
            continue

        region_id = get_region_id(country)

        try:
            calculator = get_postal_calculator(country)
            tariff = calculate_tariff(calculator)

            results.append(
                {
                    "country_id": country_id,
                    "country": name,
                    "region_id": region_id,
                    "tariff_type": tariff["tariff_type"],
                    "price": tariff["price"],
                }
            )

            # Keep the Armenian name exactly as Haypost provides it.
            country_names.append(name)

        except Exception as exc:
            print(
                f"WARNING: Failed for {name} "
                f"({country_id}): {exc}",
                file=sys.stderr,
            )

    # The additional-tariff endpoint is not country-specific
    # according to the frontend code.
    #
    # Therefore, if the returned service is 0 AMD, we record
    # that separately rather than pretending the API returned
    # a country-specific zero tariff.
    if additional_service is not None:
        additional_zero = is_zero(
            additional_service["value"]
        )
    else:
        additional_zero = False

    if additional_zero:
        zero_countries = country_names.copy()

    return (
        country_names,
        zero_countries,
        results,
        additional_service,
    )


def write_output(
    country_names,
    zero_countries,
    results,
    additional_service,
):
    now = datetime.now(timezone.utc).strftime(
        "%Y-%m-%d %H:%M:%S UTC"
    )

    lines = []

    lines.append(
        "HAYPOST POSTAL CALCULATOR MONITOR"
    )
    lines.append("")
    lines.append(
        "Configuration: "
        "International / Postcard / 10 g / "
        "Standard / Ordinary"
    )
    lines.append(f"Checked: {now}")
    lines.append("")

    lines.append("COUNTRIES")
    lines.append("=========")

    for name in country_names:
        lines.append(name)

    lines.append("")
    lines.append(
        '0 AMD — "Առաքանու ներդիրի արժեք"'
    )
    lines.append(
        "================================"
    )

    if zero_countries:
        for name in zero_countries:
            lines.append(name)
    else:
        lines.append("(none)")

    lines.append("")

    if additional_service is not None:
        lines.append(
            "Additional tariff detected:"
        )
        lines.append(
            f"Label: {additional_service['label']}"
        )
        lines.append(
            f"Value: {additional_service['value']}"
        )
    else:
        lines.append(
            'WARNING: "Առաքանու ներդիրի արժեք" '
            "was not found in the "
            "additional-tariff response."
        )

    lines.append("")
    lines.append("Russia region:")
    lines.append(
        "Ռուսաստան → Մոսկվա (region_id=14)"
    )
    lines.append("")

    OUTPUT_FILE.write_text(
        "\n".join(lines) + "\n",
        encoding="utf-8",
    )


def main():
    print("Starting Haypost monitor...")

    (
        country_names,
        zero_countries,
        results,
        additional_service,
    ) = process()

    write_output(
        country_names,
        zero_countries,
        results,
        additional_service,
    )

    print(
        f"Found {len(country_names)} countries."
    )

    if additional_service:
        print(
            "Additional service:",
            additional_service["label"],
            "=",
            additional_service["value"],
        )

    print(f"Wrote {OUTPUT_FILE}")

if __name__ == "__main__":
    main()
