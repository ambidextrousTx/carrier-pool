# Decisions made during development

## Development
* Models used: 
  * Backend, Database: Claude Sonnet 5 with High Effort (free)
  * Frontend: Gemini 3.6 Flash
* Style used: conversational in the free web console. The model was instructed to work with me as a co-worker, brainstorm-er, rubber duck, buddy, guide, and mentor. It was asked to really nail down the details and build the system brick by brick, adding unit tests as we go to keep the system robust

## Architectural Decisions
* For multi-tenancy, since this was supposed to be a quick turnaround project, I chose support for 1-5 brokers (aka scaling was not considered for this iteration). This means a single database and a single schema (no support for multiple schemas / databases and sharding etc.)
* For data separation between brokers - again for this pilot the separation was just logical, nothing physical
* Isolation is enforced with Postgres Row-Level Security (RLS) policies, not just `remember to add WHERE broker_id = ?`, so we have a database-level guarantee instead of relying on the ORM / code. RLS also helps with the shared carrier pool feature

## Data Model
* Since HaulDesk's status 40 is ambiguous, an assumption is made that HaulDesk's status stays at 30 until pickup
* Since BrokerOS has 7 statuses and we need to map them to 6, Invoiced -> DELIVERED and Paid -> COMPLETED for BrokerOS. The source's raw status is stored for future audits
* The RateLineItem can live as an optional table for when data is available because HaulDesk provides richer data related to money
* The canonical model stores US units (converted from the metric system when needed)
* Equipment for FreightFlow are derived by doing text processing, and then mapped to the canonical ones provided for the other two
* Freightflow's `stops`, HaulDesk's `pu_city` and `del_city` etc., and BrokerOS's `stops` with `reference records` are used to derive the stops as cleanly as possible
* Timestamps are normalized to UTC-aware datetimes
