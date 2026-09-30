# New York City records and rules (one- and two-family homes)

Dataset IDs were checked against the NYC Open Data catalog in September 2026. Code and zoning sections were read in September 2026; **re-read the current text before relying on any section number**, because City of Yes (effective 2024-12-05) renumbered large parts of the Zoning Resolution. Items marked "secondhand" need confirmation by an attorney, architect or expediter.

## Contents

1. Datasets the script queries
2. Reading the results
3. Other sources to check by hand
4. Unpermitted work and legalization: the framework
5. Basements, cellars and attics
6. Driveways and curb cuts
7. Sewer, septic, gas and oil tanks
8. No owner exemption for plumbing, gas and electrical work

## 1. Datasets the script queries

| Data | Socrata ID | Key | Answers |
|---|---|---|---|
| PLUTO | 64uk-42ks | bbl | Zoning, building class, areas, floors, lot size, number of buildings, basement code, year built, assessed value, exemptions |
| DOB Violations | 3h2n-5cm9 | bin | Open DOB violations |
| DOB ECB Violations | 6bgk-3dad | bin | ECB and OATH violations and penalties |
| HPD Violations | wvxf-dwi5 | bbl | Housing maintenance violations |
| DOB Complaints | eabe-havv | bin | Complaint category, disposition code and date |
| DOB Job Filings (BIS) | ic3t-wcy2 | bin__ | Older jobs and permits |
| DOB NOW Build | w9ak-ipjd | bin | Newer jobs |
| Certificates of Occupancy | bs8b-p36w | bin | Digitized COs |
| DOF assessment | yjxr-fw8i | boro, block, lot | Assessed value, exemption codes, owner (latest data 2018/19) |
| ACRIS Legals and Master | 8h5j-fqxa, bnx9-e6tj | borough, block, lot, then document_id | Deeds, mortgages, satisfactions, liens |
| 311 | erm2-nwe9 | within_circle(location, ...) | Nearby complaints, 2020 onward |
| Complaint disposition codes | 6v9u-ndjg | | Code meanings |

Geocoding: NYC Planning Labs Geosearch returns the BBL and BIN in `addendum.pad`. Towns across the Nassau County line have no BBL; if there is no match, check the address is inside the city.

## 2. Reading the results

- **Zero rows is not clean.** Pre-BIS paper jobs, whether an old job was ever signed off, and undigitized COs cannot be seen online. The BIS "Actions" page shows job number, type and year only, never the disposition. Only microfilm answers that.
- **Microfilm is open to buyers.** Register a free DOB eFiling account (choose the option for people with no license or DOB ID), then DOB NOW: BIS Options, Record Request. Searching is free; copies cost a few dollars per page and take about two business days (fees and pickup location checked 2026-09; confirm before going).
- **Decode codes from official tables**, not from search snippets. Example: complaint category 36 is Driveway/Carport - Illegal; disposition I2 means no violation was warranted at the time of inspection, which is not the same as legal.
- **Baseline against the block.** Run the same fields for neighbors before calling something unusual. A second building on the lot with zero garage area is often a detached garage common to the whole street.
- **DOF assessment data is not a tax bill.** Use it to see owner changes and disappearing exemptions (an elderly-owner exemption that disappears can mean the owner died). Get the actual bill from DOF, ideally through the buyer's attorney.
- **Three names must match:** the seller in the contract, the owner in PLUTO and ACRIS, and the seller in any rider. If they differ, ask the attorney to confirm the chain of title and the seller's capacity (individual, heir, executor, trustee).

## 3. Other sources to check by hand

| Source | Answers |
|---|---|
| ZoLa (zola.planning.nyc.gov) | Zoning, historic districts, coastal zone, special districts, all layer intersections |
| FEMA NFHL (use us_flood.py), NYC Stormwater Flood Map, sea-level-rise maps | Insurance requirement, rainfall flooding, long-term risk |
| NYS DEC wetlands mapper | Real distance to regulated wetlands. The DOB "map check" flag is only a citywide screen |
| NYC DEP | Whether the lot connects to a city sewer; free sewer maps on request |
| Gas utility (Con Edison or National Grid) | Whether there is a gas main on the street |
| NYC Street Tree Map | Whether the tree out front is a city tree (cannot be removed; sidewalk damage is still the owner's problem) |
| NYC DOE school search | The actual zoned school |
| Surrogate's Court records (WebSurrogate) | Estate cases for the owner; online coverage is only reliable for recent years |
| Municipal Archives tax photos (1940s and 1980s) | What the house looked like, to date additions |

## 4. Unpermitted work and legalization: the framework

Use this to size the problem, then confirm with an architect or expediter.

- **Unpermitted additions are not "grandfathered".** Zoning protection for non-complying buildings applies to buildings that were lawful when built. An addition that never had a permit was never lawful, so age alone does not protect it. It has to be legalized.
- **Three thresholds decide the cost** (NYC Building Code, secondhand confirmation recommended):
  1. If an alteration increases the floor area of a prior-code building by more than 110 percent, the building is treated like new construction. Compute (current minus original) divided by original, with the original from microfilm, not from tax records.
  2. Prior-code buildings may generally follow the 1968 code for alterations, except plumbing, gas, electrical, mechanical, energy and a few others that must meet current code. Egress, ceiling height, stairs and fire separation can often stay at the 1968 standard, a large saving.
  3. Zoning: City of Yes added a "residential retrofit" path (ZR 54-53) that allows some additions to deepen non-compliance if they come no closer to the lot line than the existing building, with limits on open space and height. The general rule (ZR 54-31) is much stricter.
- **Measure setbacks three ways.** Eaves, open porches, steps and chimneys are permitted obstructions in yards. GIS footprints measure the roof outline, eaves included. Ask the surveyor to show the wall, the eave edge and the steps separately.
- **Penalties are capped.** For one- and two-family homes, the work-without-permit penalty was a multiple of the permit fee with a floor and a cap (checked 2026-09: floor $600, cap $10,000). Worst case is bounded.
- **Certificate of occupancy.** Buildings from before 1938 that were lawfully occupied without a CO may continue without one if the use and occupancy class do not change. Adding a second kitchen can create a second dwelling unit and change the class, which requires a CO. A Letter of No Objection only confirms use; it does not legalize added floor area.
- **Variance is a last resort.** A zoning variance requires hardship not created by the owner, which unpermitted work usually fails. Treat it as the point to walk away, not a plan.

## 5. Basements, cellars and attics

- A habitable room in a one- or two-family basement needs at least about 7 ft of clear height (verify the current code section). Measure at the lowest beam or duct.
- A cellar (more than half below curb level) cannot be used for living in one- and two-family homes under the Housing Maintenance Code. Measure floor-to-grade on site.
- A bathroom without a permit can be legalized; a low ceiling cannot, short of lowering the floor (underpinning), which is a six-figure structural job.
- A separate bath plus a separate outside entrance in a basement is the combination that makes lenders, appraisers and insurers ask whether it is an accessory unit.
- Attic habitable-space rules also depend on clear height; measure the lowest and highest points.

## 6. Driveways and curb cuts

A driveway is legal only with a DOT-approved curb cut; its age does not matter. Zoning also limits curb cut and driveway widths (R2A figures used in 2026: 18 ft curb cut, 20 ft driveway in the front yard, secondhand; verify for the district). Driveway complaints in DOB records are a reason to ask for the curb cut permit.

## 7. Sewer, septic, gas and oil tanks

- Some older neighborhoods in northeast Queens were never connected to city sewers. Ask DEP; a field investigation request costs a non-refundable fee ($600 as of 2026-07).
- Septic capacity is set by bedroom count under state rules, and an expandable unfinished attic can count as a bedroom.
- No gas main on the street usually means staying on oil.
- A buried oil tank is the largest single environmental risk; sweep any house built before about 1970 or that ever burned oil.
- The sewer line to the street and the sidewalk are the owner's responsibility.

## 8. No owner exemption for plumbing, gas and electrical work

Unlike much of upstate New York, New York City has no homeowner exemption. All electrical work needs a permit and a licensed master electrician. Even minor plumbing (same-location fixture swaps, water heaters) must be done by a licensed master plumber. Gas work needs a licensed plumber and a utility re-inspection. License lending is prohibited. Carpentry, non-structural partitions, flooring, painting, cabinets, insulation, tile and similar work do not need a licensed trade. Budget any fixer-upper with that split (see house-renovation).
