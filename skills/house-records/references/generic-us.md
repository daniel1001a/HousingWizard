# Public records outside New York City (generic US)

There is no national property-record API. These are the kinds of sources that exist almost everywhere; names and access differ by county and city. Ask the buyer which county and municipality the property is in, then find the local version of each.

| Source | Usually called | What it answers |
|---|---|---|
| County assessor or appraiser | Property search, parcel viewer | Owner of record, parcel ID, assessed value, recorded building area, year built, exemptions (homestead, senior, veteran) |
| County recorder, clerk or register of deeds | Official records search | Deeds, mortgages, releases, liens, life estates, easements. Often searchable by name or parcel; images may cost a few dollars |
| County or city tax collector | Tax bill lookup | Current tax bill, delinquencies, special assessments |
| Building or permits department | Permit search, citizen portal | Permits, final inspections, open or expired permits, certificates of occupancy where they exist |
| Code enforcement | Code cases | Open and closed violations |
| Planning or zoning | Zoning map, GIS | Zoning district, overlays, historic district, setbacks |
| FEMA | National Flood Hazard Layer, Flood Map Service Center | Flood zone (use `scripts/us_flood.py`) |
| Utility and sewer authorities | Customer service or GIS | Public sewer or septic, public water or well, gas service on the street |
| State environmental agency | Tank registry, contamination sites | Registered underground storage tanks, nearby contamination |
| Courts | Probate or surrogate court search | Estate cases for the owner of record |
| School district | Attendance zone lookup | Actual zoned schools, which can differ from the listing |
| Street-level imagery history | Map apps with historical views | Changes to the house and neighbors over the years |

## How to use them

- Start with the assessor: it gives the parcel ID used everywhere else, and the recorded area to compare with the listing.
- Search permits by address and by parcel; some portals only index one.
- Pull the full deed chain back to the last arm's-length sale. A transfer for nominal consideration, a life-estate deed, or a trustee or executor deed changes who can sign and what they can promise.
- For sites with a CAPTCHA or login, stop and give the buyer the exact steps.

## Limits

Many counties only digitized records from a certain year. Older permits may exist only on paper; ask the building department how to request them. An empty online search is not evidence that nothing was filed.
