Archival Note: Mars / Lexie Proposal Demo

  #ClientMars #MarsPetcare #Proposal #EarlyStage #LexieNewlands #AlexandraNewlands #Lingaro #AgentDemo #Chainlit #CommercialPerformance #PetNutrition

  This demo is an early-state proposal for client Mars, positioned around a potential business user: Lexie Newlands, Alexandra Newlands, 3rd-degree connection, Allocation & Planning Lead at Mars Petcare. From the Lingaro side, the
  proposal/demo is led by Maciej Mroz.

  The concept is a Pet Nutrition Commercial Performance Copilot: an agent-based assistant for commercial performance questions. It uses a Chainlit front end for chat and voice interaction, with Codex-style repository skills behind it to
  run deterministic analyses and return business-ready answers, tables, and charts.

  What the agent does

  The agent lets a business user ask questions such as:

  - What data do you have?
  - How are we doing in 2026 through P04 versus last year?
  - Where is margin pressure concentrated?
  - What gross margin gap must we close to reach a target?
  - What would happen under a modeled promotion scenario?

  It is designed as a proposal prototype, not a production Mars system.

  Current skills

  - dataset-profile: explains dataset coverage, measures, dimensions, and distributions.
  - kpi-compare: provides year-over-year KPI comparison.
  - variance-contributors: identifies where sales or margin variance is concentrated.
  - margin-target-gap: calculates margin required to reach a gross-margin target.
  - promotion-causal-scenario: models a declared Pedigree promotion scenario.
  - sql-analysis: supports bounded read-only descriptive analysis when fixed skills do not fit.
  - skill-smoke: internal validation skill for repository execution.

  Data used

  The demo uses a Pet Nutrition synthetic demo database:

  - 50,400 fact rows.
  - FY 2024 P01-P13 as inferred baseline.
  - FY 2025 P01-P13 as dashboard-anchored data.
  - FY 2026 P01-P04 as synthetic demo data.
  - 15 reporting units.
  - 14 customers.
  - 8 brands.

  Measures include net sales in USD millions, volume in kilotonnes, gross margin in USD millions, and gross margin percentage calculated after aggregation.

  Main dimensions include brand, customer, global channel, reporting unit, reporting region, fiscal year and period. Brands include Sheba, Pedigree, Whiskas, Dreamies, Cesar Essence, Iams, Perfect Fit, and Catsan. Channels include Modern
  Grocery, Pet Specialist, Digital Commerce, and Convenience.

  Important disclosure: 2026 values and detailed allocations are synthetic. Promotion scenarios are modeled assumptions and should not be presented as proven historical causality.