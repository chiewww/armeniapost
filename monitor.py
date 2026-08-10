#!/usr/bin/env python3

import sys
from datetime import datetime, timezone
from pathlib import Path

import requests

BASE_URL = "https://api.haypost.am"

PAGE_URL = f"{BASE_URL}/page/91"
POSTAL_CALCULATOR_URL = f"{BASE_URL}/postalCalculator"
ADDITIONAL_TARIFFS_URL = f"{BASE_URL}/postalAdditionalTariffs"

# ============================================================

# ArmeniaPost configuration

# ============================================================

# International

LOCAL = False

# Postcard

POSTAL_ID = 12

# Ordinary / Հասարակ

# postal_simple = category 1

POSTAL_CATEGORY = 1

# Requested postcard weight

WEIGHT_GRAMS = 10

# Russia

RUSSIA_ID = 86

# Moscow

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

```
response = SESSION.get(
    url,
    params=params,
    timeout=30,
)

response.raise_for_status()

return response.json()
```

def clean_name(value):
"""Clean country names without translating them."""

```
if value is None:
    return ""

return str(value).strip()
```

# ============================================================

# Countries

# ============================================================

def get_countries():
"""
Fetch page 91 and return the countries supplied
by ArmeniaPost.
"""

```
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
```

# ============================================================

# Regions

# ============================================================

def get_region_id(country):
"""
ArmeniaPost currently supplies regions for only some
countries.

```
For Russia we explicitly select Moscow.

Other countries are not automatically assigned a region.
"""

country_id = country.get("id")

if country_id == RUSSIA_ID:
    return MOSCOW_REGION_ID

return None
```

# ============================================================

# Postal calculator

# ============================================================

def get_postal_calculator(country):
"""
Request the Postcard tariff for a country.

```
postal_id=12
    Postcard

local=false
    International
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
```

# ============================================================

# Tariff calculation

# ============================================================

def calculate_from_tariff_list(tariffs):
"""
Calculate the tariff for WEIGHT_GRAMS.

```
This follows the weight-selection logic visible in
ArmeniaPost's FinalInfo.js.
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

        price = item.get("price")

        if price is None:
            return None

        return price

# Open-ended tariff.
#
# This corresponds to the FinalInfo.js logic:
#
# if (i >= l.min_weight && -1 === l.max_weight) {
#
#     const a = e.find(
#         e => e.max_weight === l.min_weight
#     );
#
#     ...
#
#     const s =
#         Math.ceil(
#             (Number(i) - l.min_weight) / 1e3
#         ) * l.price;
#
#     t += s
# }

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
```

def calculate_tariff(calculator):
"""
Return ONLY the Ordinary Postcard tariff.

```
postal_type 12 = Postcard

postal_simple = Ordinary / Հասարակ

We intentionally do NOT fall back to:

    postal_standard
    postal_ordered
    postal_trajectory
    postal_ems

because the requested service is specifically:

    Postcard + Ordinary
"""

tariffs = calculator.get("postal_simple") or []

price = calculate_from_tariff_list(tariffs)

return {
    "price": price,
    "tariff_type": "postal_simple",
    "tariffs": tariffs,
}
```

# ============================================================

# Additional tariffs

# ============================================================

def get_additional_tariffs():
"""
Request additional tariff data.

```
postal_type=12
    Postcard

postal_category=1
    postal_simple / Ordinary
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
```

def find_zero_insert_value(data):
"""
Find an additional-service entry corresponding to:

```
    Առաքանու ներդիրի արժեք

The frontend displays the service using:

    e.price || 0 === e.price ? e.price : e.value

This function handles the possible API response shapes.
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
                label_values.append(
                    str(value[key])
                )

        label = " ".join(
            label_values
        ).strip()

        if any(
            phrase in label
            for phrase in target_phrases
        ):

            raw_value = None

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
```

def is_zero(value):
"""Safely determine whether a value represents 0."""

```
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
```

# ============================================================

# Process countries

# ============================================================

def process():

```
countries = get_countries()

if not countries:
    raise RuntimeError(
        "ArmeniaPost returned no countries"
    )

# Fetch additional tariff information once.
additional_tariffs = get_additional_tariffs()

additional_service = find_zero_insert_value(
    additional_tariffs
)

if additional_service is None:

    print(
        'WARNING: Could not find '
        '"Առաքանու ներդիրի արժեք" '
        'in postalAdditionalTariffs response.',
        file=sys.stderr,
    )

country_names = []
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

        result = {
            "country_id": country_id,
            "country": name,
            "region_id": region_id,
            "tariff_type": tariff["tariff_type"],
            "price": tariff["price"],
            "tariffs": tariff["tariffs"],
        }

        results.append(result)

        country_names.append(name)

        price_text = (
            f"{tariff['price']} AMD"
            if tariff["price"] is not None
            else "N/A"
        )

        print(
            f"{name}: {price_text}"
        )

    except Exception as exc:

        print(
            f"WARNING: Failed for "
            f"{name} ({country_id}): {exc}",
            file=sys.stderr,
        )

return (
    country_names,
    results,
    additional_service,
)
```

# ============================================================

# Output

# ============================================================

def write_output(
country_names,
results,
additional_service,
):

```
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
    "International / Postcard / "
    "Ordinary / 10 g"
)

lines.append(
    f"Checked: {now}"
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

    region_text = ""

    if region_id == MOSCOW_REGION_ID:
        region_text = " (Moscow)"

    lines.append(
        f"{country}{region_text}: "
        f"{price_text}"
    )

lines.append("")

lines.append(
    f"Total countries: {len(results)}"
)

lines.append("")

lines.append(
    "ADDITIONAL TARIFF"
)

lines.append(
    "================="
)

if additional_service is not None:

    lines.append(
        f"Label: "
        f"{additional_service['label']}"
    )

    lines.append(
        f"Value: "
        f"{additional_service['value']}"
    )

    lines.append(
        f"Zero: "
        f"{is_zero(additional_service['value'])}"
    )

else:

    lines.append(
        'WARNING: '
        '"Առաքանու ներդիրի արժեք" '
        "was not found."
    )

lines.append("")

lines.append(
    "RUSSIA"
)

lines.append(
    "======"
)

lines.append(
    "Russia → Moscow "
    "(region_id=14)"
)

lines.append("")

lines.append(
    "POSTCARD TARIF DATA"
)

lines.append(
    "==================="
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

OUTPUT_FILE.write_text(
    "\n".join(lines) + "\n",
    encoding="utf-8",
)
```

# ============================================================

# Main

# ============================================================

def main():

```
print(
    "Starting ArmeniaPost monitor..."
)

(
    country_names,
    results,
    additional_service,
) = process()

write_output(
    country_names,
    results,
    additional_service,
)

print(
    f"Found {len(results)} countries."
)

if additional_service:

    print(
        "Additional service:",
        additional_service["label"],
        "=",
        additional_service["value"],
    )

print(
    f"Wrote {OUTPUT_FILE}"
)
```

if **name** == "**main**":
main()
