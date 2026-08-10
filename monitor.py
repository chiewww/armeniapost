from datetime import datetime, timezone


def is_zero_price(price):
    """Return True when the tariff is exactly 0 AMD."""
    if price is None:
        return False

    try:
        return float(price) == 0
    except (TypeError, ValueError):
        return False


def write_output(results):
    now = datetime.now(timezone.utc).strftime(
        "%Y-%m-%d %H:%M:%S UTC"
    )

    # Countries with an actual 0 AMD postcard tariff.
    zero_countries = [
        result
        for result in results
        if is_zero_price(result.get("price"))
    ]

    # Countries with a non-zero postcard tariff.
    priced_countries = [
        result
        for result in results
        if not is_zero_price(result.get("price"))
    ]

    lines = []

    lines.append("ARMENIAPOST POSTCARD TARIFF MONITOR")
    lines.append("")
    lines.append("Configuration: International / Postcard / Ordinary")
    lines.append(f"Checked: {now}")
    lines.append("")

    # ---------------------------------------------------------
    # 0 AMD SECTION
    # ---------------------------------------------------------

    lines.append("0 AMD")
    lines.append("=====")

    if zero_countries:
        for result in zero_countries:
            lines.append(
                f"{result['country']} — 0 AMD"
            )
    else:
        lines.append("(none)")

    lines.append("")

    # ---------------------------------------------------------
    # PRICED COUNTRIES
    # ---------------------------------------------------------

    lines.append("POSTCARD TARIFFS")
    lines.append("================")

    for result in priced_countries:
        country = result["country"]
        price = result.get("price")

        if price is None:
            price_text = "N/A"
        else:
            price_text = f"{price:g} AMD"

        lines.append(
            f"{country} — {price_text}"
        )

    lines.append("")

    # ---------------------------------------------------------
    # SUMMARY
    # ---------------------------------------------------------

    lines.append("SUMMARY")
    lines.append("=======")
    lines.append(f"Countries checked: {len(results)}")
    lines.append(f"Countries with 0 AMD: {len(zero_countries)}")
    lines.append(f"Countries with a price: {len(priced_countries)}")

    OUTPUT_FILE.write_text(
        "\n".join(lines) + "\n",
        encoding="utf-8",
    )

    print(
        f"Wrote {OUTPUT_FILE} "
        f"({len(zero_countries)} countries at 0 AMD)"
    )
