Type: Presentation draft

# Current & Target State

## From today's constraints to tomorrow's capability

### Today

- Outdated routing platform: Current tool is very old (Windows XP-era) with maps last updated around 2018-2019, resulting in inaccurate routing and poor usability.
- Highly manual process: Routing planning requires frequent manual CSV uploads and manual lat-long adjustments, making updates slow and error-prone.
- Limited flexibility despite highly dynamic operations: Routes change frequently due to promos, upsell priorities, weather, accidents, and weekly tactical adjustments, but the existing tool struggles to adapt to daily changes.
- Compliance-focused, not optimization driven: The current routing approach primarily tracks compliance (whether reps follow assigned routes) rather than true route efficiency or optimization.
- No clear financial impact: The business does not currently correlate routing inefficiencies directly to financial impact, making it hard to build a traditional ROI-led business case at this stage.
- Underserved areas remain a challenge: Ensuring coverage of underserved territories while respecting territory boundaries difficult with the current platform.

### Target state

1. A modern, flexible routing platform that:
   - Uses updated maps (e.g., Google Maps 2024 or similar)
   - Supports dynamic, daily route adjustments
   - Optimizes routes within assigned territories without penalizing valid deviations.

2. A tool that supports both:
   - Frontliners (clear, optimal routes considering traffic and distance)
   - and Go-to-Market team (nationwide planning with better visibility and control)

3. Ability to surface insights such as:
   - Fastest and most efficient way to complete weekly routes,
   - Better coverage of underserved areas
   - Real-time or near-real-time visibility on route compliance and execution.

Initial focus remains routing optimization with revenue impact considered secondary and potentially addressed later once routing basics are solved.

---

# Current State: How routing gets done today

- 11 commercial units, nationwide coverage
- Territory control is strict (commercial units cannot cross territories) and any deviation requires managerial judgement rather than system guided optimization

## GTM Team

- Plan routes centrally
- 11 commercial units, nationwide
- Build & prepare CSV files
- Weekly route data packaged for upload
- Manual lat-long value adjustments required per route
- Upload & distribute plans
- Via CSV to sales reps each week
- Exceptions & daily changes require manual intervention

## Sales Reps

- Receive weekly route plan
- Ahead of the working week
- Execute daily routes
- Pre-sellers & account developers
- Ad-hoc changes (weather, traffic, accidents) - no system guidance
- Navigate to customers
- Platform maps used in field
- Reps check Google Maps manually  platform maps outdated
- Customer visit & sales
- Territory-bound — mgr approval for any deviation

## Finance

- Revenue & financial optimisation
- Managed by Finance team
- Handled separately - no integration with routing tool
- Route revenue analysis
- Separate tooling & reporting
- Financial impact not embedded in routing decisions

---

# Lingaro's Approach

A structured, low risk path from current state assessment to a live pilot built around CCEAP's operations, not off-the-shelf tooling. [1]

---

# What Lingaro brings to routing optimisation

## Capabilities: Four areas directly aligned to CCEAP's needs

### Routing Engine Integration

- Google Maps / HERE Maps API with 2024+ data
- Real-time traffic and road condition awareness
- Turn-by-turn mobile navigation for field reps [1]

### Dynamic Route Management

- Daily & intra-day adjustments
- no CSV uploads
- Automated exception handling for weather & accidents
- Promo and upsell priority routing support [1]

### Territory & Compliance

- Hard territory boundary enforcement across all CUs
- Route optimisation within assigned territories
- Compliance tracking with deviation flagging [1]

### Analytics & Visibility

- Near-real-time route execution dashboards
- Coverage gap analysis for underserved areas
- KPI tracking for efficiency and rep performance [1]

---

# Solution Architecture

Modular, backend-driven routingoptimization platform supporting operational and planning use cases [1]

## Business Applications / Consumption Layer

- Frontliner Tool 1
  - frequent route consumption
- Frontliner Tool 2
  - daily / intra-day updates
- Go-to-Market Tool
  - scenario planning & visibility
- Dashboards
  - KPls, compliance, coverage

## Source Systems & Data Inputs

- Customer / Outlet master data
- Territories boundaries
- Assignments reps / visits
- Execution Data GPS /status

## Platform Components

### Data Ingestion & Validation Layer

- quality checks, geocoding readiness, refresh orchestration

### API & Integration Layer

- route plans, updates, execution status, compliance signals

### Monitoring & Audit

- performance, data quality, route versions

### Core Routing Platform

- External Map Services
  - maps, traffic, distance matrix, geocoding
- Map / Traffic Adapter
  - provider abstraction
- Routing Optimization Engine
  - route calculation & recalculation
- Rules & Constraints Service
  - territories, feasibility, priorities

MVP focus: one Commercial Unit, routing fundamentals first; extensible for national rollout and advanced optimization. [1]

---

# A structured path from assessment to scaled deployment

## Methodology · Five phases for controlled risk and rapid value delivery

### 1. Discover

#### Current State Assessment

- Audit tools, processes & data flows.
- Map pain points to technical requirements. [1]

### 2. Design

#### Solution Architecture

- Define routing engine, APIs, territory model & UX for GTM and frontliners. [1]

### 3. Build

#### MVP Development

- Core routing: updated maps, dynamic adjustments, territory rules, analytics. [1]

### 4. Pilot

#### Controlled Validation

- Deploy to one commercial unit.
- Measure KPIs, gather feedback, iterate. [1]

### 5. Scale

#### Nationwide Rollout

- Extend to all 11 commercial units with advanced optimisation features. [1]

**Key principle:** We start with routing fundamentals - updated maps, dynamic adjustments, territory compliance and layer revenue optimisation only after the foundation is proven. [1]