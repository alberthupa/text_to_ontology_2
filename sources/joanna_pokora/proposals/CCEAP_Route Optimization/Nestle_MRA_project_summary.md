**Type:** project
These are contents from a pptx presentation conversed into markdown format
# Merchandiser Resource Allocation
## High level overview

---

## Slide 2 — Introduction and Assumptions

**Approach\***: Three sequential optimization models: (1) assigning visit schedules to stores, (2) optimizing daily routes, (3) optimizing weekly schedules

**Outcomes**: reduction in FTE requirements (20% to 44% based on regional characteristics); overall estimated headcount reduction of 30%; identification of new opportunities for coverage expansion

**Technology**: Azure, Databricks, Python, SQL, FICO Xpress, OR-tools, Power BI, Azure Maps

\*Innovative methodology allowing for high quality solutions while greatly reducing computational effort and time

---

## Slide 3 — Case study

- **Client:** Nestle Philippines
- **Business challenge:** allocate merchandiser visits to stores while minimizing headcount and travel distance and maintaining proper service level for all stores
- **Motivation:** upcoming wage increase, lack of established processes for merchandiser allocation

---

## Slide 4 — Solution

### Problem Statement
The current challenge is to efficiently deploy merchandisers to cover a large number of doors while considering various business restrictions and optimizing the routes based on proximity, sales, and account information.

The existing process is not optimal and can result in inefficiencies in terms of headcount, travel distance, and time spent.

There was a need for a solution that could automate the deployment planning process and provide optimized routes to reduce cost and maximize coverage.

### Delivered Solution
Developed a tool that considers various factors and generates optimized deployment plans. By analyzing business restrictions, proximity, sales data, and account information, the tool determines the most effective routes for merchandisers.

This results in reduced cost, improved coverage and productivity.

---

## Slide 5 — Modeling Assumptions

- FTE requirements depend on business rules provided by the client:
  - Frequency based on sales volume (P12)
  - Duration based on product variety (P12)
- Political constraints: which account groups can be visited together
- Travel times are proportional to distances and based on the speed limits of the roads
- Merchandiser daily work hours <= 8
- Overdeployment possible if sum of store visits on a route < 8 → spread leftover time across all stores in a route
- Store can have both stationary merchandisers (visits 6 days a week/8 hours a day) and roving merchandisers (visit frequency < 6 days or visit duration < 8 hours)

---

## Slide 6 — OpenStreet Maps for travel network

> Sales regions as defined by client differ from official administrative boundaries

- Used osmnx python library,
- To create distance and travel time matrices, it was necessary to consider locations of the stores within a region (based on latitude & longitude),
- Buffer added to avoid cutting off roads and losing connections between locations,
- Distances (and travel times) calculated by finding shortest paths between all pairs of store locations,
- Distance and time matrices used as input in the optimization models.

![Image placeholder: Nodes and edges (crossroads and streets)]

---

## Solution Overview

---

## Slide 8 — High-level solution overview

### Input Layer

**Business Rules — How often and how long?**
Apply rules defined by the business or generated through clustering approaches to derive visit frequency and duration for each store

**Political Constraints — Which stores together?**
Apply constraints defined by the business to specify which stores can be visited as part of the same route

**Store Mapping — Where are the stores?**
Use OpenStreet Maps to map the location of the stores and calculate distance and time matrices

### Optimization Layer

**1. Store Schedule Assignment — What day(s) to visit each store on?**
Mixed integer programming model to find specific store schedules while minimizing headcount

**2. Daily Route Optimization — How to visit the stores?**
Vehicle routing model to find feasible daily routes while minimizing headcount & travel distance

**3. Weekly Schedule Creation — How to allocate merchandisers to routes?**
Heuristic model to find feasible weekly schedules while minimizing headcount & maximizing political constraints adherence

### Presentation Layer

**Dashboard — Solution at a glance**
PowerBI dashboard to visualize the solution. Filter by region, store chain, day of the week, etc.

**Performance Insights — What improved?**
A report showing existing and proposed FTE store assignments

**Opportunities — Where can we add new outlets?**
Identifies regions where new stores can be added with little extra cost

---

## Slide 9 — 1. Store Schedule Assignment: Idea behind the model

> Mixed integer programming model to select which roving stores should be visited on each day of the week

**Mixed-integer programming**

Linear programming models are well suited for Assignment problems such as:
- Assign something (e.g people) to something else (e.g. tasks)
- There is a measure of performance of such assignment (objective function) that we want to minimize or maximize (e.g. minimize cost of assignment)
- There are requirements or restrictions (e.g. every task has to be assigned to someone)

In our case study we:
- Assign stores to specific schedules (e.g. MWF, TuTh, etc)
- We want to minimize the number of merchandisers needed
- We have restrictions regarding visit frequency, duration, and what stores can be visited as part of the same route
- Used FICO xpress python library

---

## Slide 10 — High-level model description

**Decision variables – what are we actually deciding:**
- binary variables that tell us if a particular store is assigned to a particular schedule
- other auxiliary decision variables that help with model definition

**Objective function – how we measure the 'goodness' of the assignment:**
- avoid spikes in demand on any given day of the week
- take into account political constraints
- consider store proximity
- include schedule fitness

**Constraints: what are the restrictions**
- Every store has to be assigned to a schedule + other constraints to tie everything together

### Sample Assignment Comparison

| Day | Assignment #1 | Assignment #2 |
|---|---|---|
| M   | 1 | 4 |
| Tu  | 0 | 4 |
| Wed | 2 | 4 |
| Th  | 3 | 4 |
| Fr  | 4 | 4 |
| Sat | 2 | 4 |
| Sun | 6 | 4 |

---

## Slide 11 — 2. Daily Route Optimization: Idea behind the model

> Output of model #1 - set of stores to be visited on each day of the week.
> Goal of model #2 - how to visit these stores taking into account all restrictions

**Vehicle Routing Problem**

Vehicle routing problem can be stated as follows:
- Find a set of routes (one for each vehicle) that start and end at the depot and that visit each location exactly once that will minimize total travel distance
- Other variations might include time windows, deliveries with pick-up, vehicle capacities, etc.

In our case study we:
- Want to minimize travel distances and the number of merchandisers (vehicles)
- We have restrictions regarding what stores can be visited as part of the same route, max travel distances, and max working time
- We need to include visit time in the total time

---

## Slide 12 — High-level model description

Given a set of locations to visit, their corresponding visit duration, and travel time matrix between each location, find a set of routes that will minimize total travel time, minimize the number of vehicles (merchandisers) used while keeping total time per merchandiser (travel + in-store) to 8h maximum and respecting political constraints.

For stores with visit durations >= 2h, travel time up to 30 min is included as part of the visit time.

In case of route time < 8 hours, the extra merchandiser's time is spread equally across all stores in the route, creating overdeployment

![Image placeholder: Route diagram with weighted edges (2, 4, 1, 2, 2, 2, 4, 3, 1)]

---

## Slide 13 — Approach

- Used ortools python library
- **Modeling tricks:**
  - lack of central location for start/end points – include a dummy depot location with 0 travel distance/time to all other locations
  - political constraints adherence - different 'vehicle' types that can only visit stores belonging to the same political constraint group
  - limits on total work time and travel distance - included in the respective dimensions
  - Service time - added to the travel time in the time callback function
  - Consideration to disregard travel time <= 30 min for store durations >= 2 hours – added in time callback
  - Added fixed cost for using a merchandiser (vehicle)
- **Outputs:** set of routes for each day of the week, updated FTE values (due to potential over-deployment)

---

## Slide 14 — 3. Weekly Schedule Creation: Idea behind the model

> Output of model #2 – a set of routes for each day of the week.
> Goal of model #3 - design how to 'stitch' these routes together to derive feasible weekly schedules for merchandisers, taking into account the restrictions

**Combinatorial optimization**

In our case study we:
- Want to minimize the number of merchandisers needed to cover all routes and minimize the distances between routes assigned to the same merchandiser
- We have restrictions regarding the number of working days and the maximum distance allowed between routes assigned to the same merchandiser
- Simple greedy method proved to be superior to other approaches (both based on time and quality)

---

## Slide 15 — High-level model description

**allowed-pairs-dict:**
Dictionary of all pairs of routes with their distances that:
- Are on different DoW
- Are within max-distance from each other

**Algorithm flow:**

```
i = 1

Sort all routes based on the frequency of their appearance 
in allowed-pairs-dict in ascending order

Pick the top route (A) from sorted list that has not yet been 
assigned to any merchandiser. Assign route A to merch i

Create a list of all route pairs (A, j) from allowed-pairs-dict that:
  (1) j has not been assigned to any merchandiser,
  (2) j is within max-distance to all other routes assigned to merchandiser i

List non-empty?
  Yes → sort by distance in ascending order
        Assign top route to merch i and remove from the list
        Num routes assigned to i < 6?
          Yes → continue
          No  → i = i + 1
  No  → i = i + 1

Remove all pairs from pairs-dict that include assigned routes
```

---

## Results

---

## Slide 17 — Value Delivered

- Equal standards across the whole country, matching resources to store throuput/size/SKU variety
- Prevents resource wasting (overdeployment) or insufficient resource allocation (underdeployment) resulting in higher client satisfaction
- Significant reduction in headcount requirements – estimated overall reduction of 30% (1% to 41% depending on the region)
- Optimized travel routes to save time and money
- Identification of areas for potential growth with minimal extra investment
- Identification of routes with spare capacity, allowing for more store coverage

**Capability Pillars:**
- ML Productization
- Supply Chain Analytics
- Statistics, Exploration & Rules
- Operations Research

**Themes:** Process Standardization · Cost Savings · Additional Insights

---

## Slide 18 — Value Delivered (All things data)

- Estimated 30% overall reduction in headcount requirements.
- Optimized travel routes for 6,000+ stores, resulting in significant time and cost savings,
- Process standardization – equal standards implemented across the whole country, preventing resource wasting,
- Identification of areas for potential growth with minimal extra investment,
- Identification of spare capacity, allowing for more store coverage,
- Automated tool that adjusts the solution to new requirements, including the addition of new stores, ensuring flexibility and scalability of operations.

**Themes:** ML Productization · Operations Research

---

## Slide 20 — Regions under Analysis

Our analysis includes the following 9 regions:

- Northern Luzon
- Central Luzon
- Greater Manila Area (GMA)
- Southwest Luzon
- Southeast Luzon
- East Visayas
- West Visayas
- South Mindanao
- North Mindanao

> Regions vary based on network connectivity (road network development) and dispersion (how concentrated or spread-out stores are). GMA has the highest connectivity and concentration while Southern Luzon and Mindanao are the most spread out with many isolated islands

![Image placeholder: Map of the Philippines highlighting regions, including GMA, Palawan, Mindanao]

---

## Slide 21 — Performance metrics

**FTE**
- Store FTE: The total sum of hours to visit stores within a particular region / 48
- Merchandiser FTE: the total routes for a particular region divided by 6 (as merchandisers can work maximum 6 days a week)

**Headcount Efficiency**
Measures the percentage of a roving merchandiser FTE covered by one roving headcount.
Roving headcount is the result of the route stitching model and specifies how many merchandisers are needed to cover all the routes

**PC adherence**
Measures the percentage of full schedules (clustered routes) that do not violate the political constraints.

---

## Slide 22 — Numerical results

| REGION | HC Efficiency | PC adherence | Percent FTE savings | Percent HC savings |
|---|---|---|---|---|
| CL  | 0.86 | 0.34 | 42.98 | 35.03 |
| EV  | 0.76 | 0.48 | 24.73 | 12.15 |
| GMA | 0.95 | 0.67 | 43.82 | 41.30 |
| NL  | 0.74 | 0.45 | 37.86 | 23.39 |
| NM  | 0.72 | 0.60 | 19.96 | 1.14  |
| SEL | 0.83 | 0.61 | 37.26 | 27.15 |
| SM  | 0.76 | 0.55 | 29.01 | 17.08 |
| SWL | 0.77 | 0.49 | 41.60 | 27.25 |
| WV  | 0.78 | 0.38 | 37.47 | 25.42 |

---

## Slide 23 — Sample PBI output

**All roving routes for GMA**

![Image placeholder: PowerBI dashboard — All roving routes for GMA]

---

## Slide 24 — Sample PBI output

**Roving routes on specific day of the week for GMA**

![Image placeholder: PowerBI dashboard — Roving routes on specific day of the week for GMA]

---

## Slide 25 — Sample PBI output

**Roving routes for a specific merchandiser**

![Image placeholder: PowerBI dashboard — Roving routes for a specific merchandiser]

Sample metrics shown on dashboard:
- Weekly Stores FTE: 1.30
- Roving FTE — Proposed: 2.01 · Existing: 0.71
- Headcount Efficiency: 100.00%

---

## Slide 26 — Sample PBI output

**Identification of extra coverage opportunities – all GMA Friday routes with overdeployment > 2 hours**

![Image placeholder: PowerBI dashboard — GMA Friday routes with overdeployment > 2 hours]

Sample metrics shown on dashboard:
- Weekly Stores FTE: 20.68
- Roving FTE — Proposed: 27.20 · Existing: 6.53

---

## Architecture 

---

## Slide 28 — Infrastructure Architecture - FICO as a solver 

![Image placeholder: Infrastructure architecture diagram]

**Components depicted:**
- vNet with public and private subnets
- Developer / Azure Active Directory
- ADO CI/CD, ADO Repo, Pipelines
- Local Development PoC
- PowerBI Reports / POC / MVP
- Azure Active Directory + MLflow User
- Snowflake (Main Data Source)
- Azure Databricks
- Azure Data Factory (Additional flat file ingestion)
- Azure Logic Apps
- Client's Sharepoint Storage
- ADLS gen 2
- Model Store
- Data Layers: bronze, silver, gold
- Log Analytics
- Key Vault
- Application Insights Workspace
- OpenStreetMap API

---
