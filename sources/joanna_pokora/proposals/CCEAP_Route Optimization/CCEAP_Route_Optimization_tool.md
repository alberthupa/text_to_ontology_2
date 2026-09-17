**Type:** Proposal 
**Client**: [[Coca-Cola_Phillippines_(CCEAP)]]
**Client Stakeholders:** Leiner Nebab, Abby Cenzon
**Lingaro Sales:** Jacq Marras


## Q&A with the client
**From:** Leiner Nebab <[leiner.nebab@ccep.com](mailto:leiner.nebab@ccep.com)> 
**Date:** Monday, April 27, 2026 at 10:06 AM  
**To:** Jacq Marras <[jacqueline.marras@lingarogroup.com](mailto:jacqueline.marras@lingarogroup.com)>  
**Cc:** Abby Cenzon <[abigail.cenzon@ccep.com](mailto:abigail.cenzon@ccep.com)>  
**Subject:** RE: Route Optimization Tool

Hi Jacq,

Please see my responses below highlighted in green.  We can also have a quick discussion tomorrow, 4 pm to 4:30 pm.

- How route planning and optimization are being done currently. (As mentioned by Abby, it’s largely manual) 
  – Yes, it is currently manual in relation to uploading of excel files for routing.  However we have an existing tool called being used, but this is outdated.
- The key challenges or inefficiencies this creates to day-to-day operations.  
  – Key challenges and pain points involves manual uploading of files, outdated user interface, tool is not flexible, the tool is also not intuitive, has complex calculations for routings in the backend, will always need inputs from users.
- How these challenges affect the business.  For example, in terms of costs, service levels, planning cycle time, or scalability. 
  – Service levels in terms of scheduled called list, route planning, route compliance are affected, and these are affected, sales and volume delivery are also affected, and will also affect financials (no actual data yet).
- What prompted this initiative (e.g. growth, complexity, performance gaps) 
  – outdated platform, complexity of usage and manual interventions.

In addition, to ensure alignment:
- Who is sponsoring or leading this initiative internally from the business and IT side. 
  – From the business side, the sponsor is the Director of Commercial Excellence, and from IT side, it is Abby and myself.
- Is this already funded or still in an exploratory phase. 
  – Still on an exploratory phase.  We are currently sourcing for vendors as of this time.
- Expected timeline, particularly in relation to the possible RFP. – Q3 2026.
-
## Meeting Minutes
**From:** Jacq Marras <[jacqueline.marras@lingarogroup.com](mailto:jacqueline.marras@lingarogroup.com)>  
**Date:** Monday, May 4, 2026 at 10:34 AM  
**To:** Leiner Nebab <[leiner.nebab@ccep.com](mailto:leiner.nebab@ccep.com)>  
**Cc:** Abby Cenzon <[abigail.cenzon@ccep.com](mailto:abigail.cenzon@ccep.com)>  
**Subject:** Re: Route Optimization Tool

**Discussion Points:**
1. **Key Business Pain Points**
	- **Outdated routing platform** - Current tool is very old (Windows XP-era) with maps last updated around 2018-2019, resulting in inaccurate routing and poor usability. 
	- **Highly manual process** - Routing planning requires frequent manual CSV uploads and manual lat-long adjustments, making updates slow and error-prone.
	- **Limited flexibility despite highly dynamic operations** - Routes change frequently due to promos, upsell priorities, weather, accidents, and weekly tactical adjustments, but the existing tool struggles to adapt to daily changes. 
	- **Compliance-focused, not optimization driven.** - The current routing approach primarily tracks compliance (whether reps follow assigned routes) rather than true route efficiency or optimization. 
	- **No clear financial impact** - The business does not currently correlate routing inefficiencies directly to financial impact, making it hard to build a traditional ROI-led business case at this stage. 
	- **Underserved areas remain a challenge** - Ensuring coverage of underserved territories while respecting territory boundaries difficult with the current platform. 

2. **Current State - How Things Are Done Today**
	- Routes are planned centrally by the Go-To-Market team for nationwide coverage across - 11 commercial units
	- Sales reps (pre-sellers/account developers) receive weekly route plans ahead of the week. 
	- Route plans are uploaded via CSV files, with manual intervention required for:
		- Adjusting lat-long values
		- Handling exceptions and daily changes
		- Adapting to weather, traffic, accidents, or ad-hoc business needs. 
	- Mapping and navigation are often supplemented by manually checking Google Maps on tablets due to outdated platform maps. 
	- Territory control is strict (commercial units cannot cross territories), and any deviation requires managerial judgement rather than system-guided optimization. 
	- Financial impact and revenue optimization are handled separately by Finance and are not embedded into the routing tool.

3. **Target/Envisioned Future State**
	-  A modern, flexible routing platform that:
		- Uses updated maps (e.g Google Maps 2024 or similar)
		- Supports dynamic, daily route adjustments
		- Optimizes routes within assigned territories without penalizing valid deviations. 
	- A tool that supports both:
		- Frontliners (clear, optimal routes considering traffic and distance)
		- Go-to-Market team (nationwide planning with better visibility and control)
	- Ability to surface insights such as:
		- Fastest and most efficient way to complete weekly routes. 
		- Better coverage of underserved areas
		- Real-time or near-real-time visibility on route compliance and execution. 
	- Initial focus remains routing optimization with revenue impact considered secondary and potentially addressed later once routing basics are solved. 

4. **Agreed Next Steps**
	- Lingaro (Jacq) 
		- Review internally for similar routing optimization implementation or relevant use cases. 
		- Assess whether Lingaro has demonstrable capabilities aligned to CCEAP’s routing needs. 
		- Prepare a high-level demo or presentation showcasing applicable routing capabilities (no deep financial modeling required at this stage)
	- CCEAP (Leiner)
		- Involve GTM business stakeholders to review the demo/presentation
	- Joint CCEAP/Lingaro
		- Use the demo as input to determine whether to proceed toward a pilot/MVP and subsequently, a formal RFP. 
	- Indicative Direction
		- Initial pilot or MVP potentially around October-November, starting with a limited scope (e.g one commercial unit or zone) before broader roll out.


# Routing Optimization Solution – Client Discovery Questions (proposed by Jacek Myna)

## 1. Business Scope and MVP Definition

- **Q6.** What is the minimum viable scope for the MVP across the Frontliner and GTM tools: which capabilities must be included in the pilot, and which can be deferred to later phases?
- **Q10.** What are the key optimization objectives that must be supported in the MVP: minimizing travel time, minimizing distance, maximizing visit completion, improving underserved-area coverage, balancing workload, or preserving territory compliance? Or all of them?
- **Q11.** What route-planning objects must be optimized in the MVP: customer visits, store visits, sales representative schedules, territories, weekly routes, daily routes, or individual stops?

## 2. Frontliner Tool Functional Requirements

- **Q1.** What are the expected core backend capabilities for the Frontliner: route generation, route recalculation, route execution tracking, compliance monitoring, or all of the above?
- **Q2.** For each Frontliner tool, what is the expected frequency of route updates: daily, multiple times per day, on-demand, or near real-time?
- **Q3.** What is the maximum acceptable latency for route recalculation or route update delivery to Frontliners?
- **Q14.** What level of route execution tracking is required in the MVP: planned versus actual route comparison, GPS-based tracking, visit status updates, deviation detection, or only post-day reporting?

## 3. Go-to-Market Planning Tool Requirements

- **Q4.** What are the core backend capabilities expected for the Go-to-Market planning tool: national route planning, territory simulation, coverage analysis, route approval, reporting, or scenario comparison?
- **Q5.** How frequently will the Go-to-Market planning tool be used for route planning or replanning: weekly, monthly, quarterly, or ad hoc?

## 4. Users, Scale, and Performance

- **Q7.** What is the expected number of active users in the MVP for each of the tools, and what is the expected number of concurrent users during peak usage?
- **Q3.** What is the maximum acceptable latency for route recalculation or route update delivery to Frontliners?

## 5. Data Inputs, Data Availability, and Data Quality

- **Q12.** What input datasets may be required for route optimization, and which systems currently own them, including customer/store master data, representative assignments, territory definitions, visit plans, historical routes, GPS traces, and compliance data?
- **Q13.** What is the current quality and completeness of location data, especially addresses, latitude/longitude coordinates, customer identifiers, duplicate locations, and missing or outdated records?
- **Q15.** What historical data is available for the route planning experimentation phase?

## 6. Integration and Enterprise Architecture

- **Q8.** Are there existing enterprise APIs, data platforms, data lakes, or middleware components that the solution is expected to use for data ingestion or data publishing?

## 7. Delivery Model, Roles, and Responsibilities

- **Q9.** What responsibilities should remain with the client team versus Lingaro during MVP delivery, especially: data preparation, business rule validation, integration support, user acceptance testing, and pilot operations?