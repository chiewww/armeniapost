# armeniapost

Daily monitoring of HayPost international postcard prices.

## Configuration

The monitor checks:

- International
- Postcard
- 10 grams
- HayPost's standard/simple/trajectory/ordered tariff logic

Russia uses:

- Russia: country ID 86
- Moscow: region ID 14

Other countries use no region.

## Output

The GitHub Action generates:

### output/countries.txt

All countries currently returned by HayPost:

    Armenian name — English name

### output/zero_amd.txt

Countries whose calculated 10g postcard price is:

    0 AMD

## HayPost API

Country information:

https://api.haypost.am/page/91?lng=am

Calculator:

https://api.haypost.am/postalCalculator

Postcard:

    postal_id=12

International:

    local=false

## Translation

HayPost provides the country names in Armenian.

English names are maintained locally in:

    country_translations.json

Translations are keyed by HayPost country ID.

If HayPost adds a new country, the monitor stops and reports the missing ID rather than silently producing an incorrect translation.

## GitHub Actions

The monitor runs automatically once per day.

It can also be run manually from:

GitHub → Actions → HayPost daily monitor → Run workflow

## changedetection.io

After the first successful GitHub Action run, configure changedetection.io to monitor the raw versions of:

    output/countries.txt

and:

    output/zero_amd.txt
