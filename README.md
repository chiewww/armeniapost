# armeniapost

Daily monitoring of the Haypost international postal calculator.

## Monitored configuration

- International (`local=false`)
- Postcard (`postal_id=12`)
- Weight: 10 g
- Standard
- Ordinary (`postal_simple`)
- Armenian country names

Russia is checked using:

- Country: Russia (`country_id=86`)
- Region: Moscow (`region_id=14`)

## APIs

The monitor uses the Haypost API directly:

### Country list

`GET https://api.haypost.am/page/91?lng=am`

### Postal calculator

`GET https://api.haypost.am/postalCalculator`

Parameters:

```text
postal_id=12
local=false
country_id=<country id>
region_id=<region id when applicable>
