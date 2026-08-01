# Decisions made during development

## Development
* Models used: 
  * Backend, Database: Claude Sonnet 5 with High Effort (free)
  * Frontend: Gemini 3.6 Flash (free)
* Style used: conversational in the free web console. The model was instructed to work with me as a co-worker, brainstormer, rubber duck, buddy, guide, and mentor. It was asked to really nail down the details and build the system brick by brick, adding unit tests as we go to keep the system robust

## Backend
### Architectural Decisions
* For multi-tenancy, for this quick turnaround project, I chose support for 1-5 brokers (aka scaling was not considered). This means a single database and a single schema (no support for multiple schemas / databases and sharding etc. No physical separation of data)
* Isolation is enforced with Postgres Row-Level Security (RLS) policies, not just `remember to add WHERE broker_id = ?`, so we have a database-level guarantee instead of relying on the ORM / code. RLS also helps with the shared carrier pool feature
* Data ingestion uses 'upserts' and is idempotent and transactional. When no ID is provided for a data item (e.g. Stops), data is wholesale-replaced at next sync. Status updates result in the corresponding row being updated, not a duplicate. Ingestion supports multi-tenancy because the connection to the database sets the broker-specific tenant context 

### Data Model
* Since HaulDesk's status 40 is ambiguous, an assumption is made that HaulDesk's status stays at 30 until pickup
* Since BrokerOS has 7 statuses and we need to map them to 6, Invoiced is mapped to DELIVERED and Paid to COMPLETED for BrokerOS. The source's raw status is stored for future audits
* The RateLineItems live as a separate table for when data is available because HaulDesk provides richer data related to money
* The canonical model stores US units (converted from the metric system when needed)
* Equipment for FreightFlow are derived by doing text processing, and then mapped to the canonical ones provided for the other two
* Freightflow's `stops`, HaulDesk's `pu_city` and `del_city` etc., and BrokerOS's `stops` with `reference records` are used to derive the stops as cleanly as possible
* Timestamps are normalized to UTC-aware datetimes

### Synthetic Data
* Data is generated with the following rules: (i) one broker per TMS, (ii) 90 days of history, (iii) 300 loads per broker (3/4 a day), (iv) 5-8 days of 'ACTIVE' status data, (v) 8-12 random 'primary' lanes per broker, (vi) one lane per broker kept sparse, (vii) 25-35 carriers per broker (regular and occasional)
* There is a TMS-agnostic 'world model' with loads on a day-by-day basis

### Recommendation Engine (Intelligence)
* Instead of relying on a black-box machine learning model, it was decided to weight-rank factors which enables explaining why a carrier or a rate is being recommended

## FrontEnd
### Authentication
* For this demo, I'm using React Contexts that simulate authenticated sessions instead of messing with a real authn/authz mechanism
