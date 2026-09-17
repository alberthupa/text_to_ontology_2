# 202606 Talk to Data — Lingaro
*Extracted from: 202606 Talk to Data - Lingaro.pptx*

---

## Slide 1 — Title

**Talk-to-Data**
Enabling self-service access to enterprise data and knowledge through conversational AI

*Lingaro DS&AI Offering, June 2026*

---

## Slide 2 — Today's dashboards and reports are no longer enough

**Subtitle:** Users expect more intuitive experience and instant answers to business questions

Organizations have invested significantly in modern data platforms.
Yet accessing insight still feels slow, fragmented, and technical.

**The Challenge:**

| Pain point | Detail |
|---|---|
| Static dashboards and reports | Only support pre-defined questions |
| Dependency on technical teams | Answers often require analyst or IT support |
| Slow time to insight | Partly manual workflows delay answers |
| Fragmented information | Data is spread across systems and documents |

**The Opportunity:** GenAI-powered conversational, self-service access to enterprise intelligence allowing each user to:
- Ask in plain language
- Explore with guidance
- Get instant answers
- Access all data in one interface

*From consumption → To conversation*

---

## Slide 3 — Talk-to-Data enables conversational access to enterprise information

**Subtitle:** A natural-language interface for trusted business answers

**How it works:**

| Step | Action | Description |
|---|---|---|
| 1 | 💬 Ask in natural language | No SQL, schemas, or tool training required |
| 2 | 🧠 Understand intent | AI interprets the question and maps business meaning |
| 3 | 🔍 Query the right sources | Structured data, documents, or both |
| 4 | ✅ Return the answer | Summary, metric, chart, explanation, citation |

Instead of searching across dashboards, reports, and documents, users simply ask a question.

---

## Slide 4 — Talk-to-Data works with different data and knowledge sources

**Subtitle:** Bringing structured data and unstructured business knowledge together

### Structured Data — NL2SQL

**Data sources:**
- Data warehouses & semantic models
- Relational databases
- Governed analytical platforms

**Best suited for:**
- KPIs and metrics
- Trends and comparisons
- Drill-down analysis
- Performance questions

*Example: "What were total sales in Germany in Q1 vs. last year?"*

### Unstructured Knowledge — RAG

**Knowledge sources:**
- PDFs, policies, and SOPs
- Documents and presentations
- Contracts and knowledge repositories

**Best suited for:**
- Policy and process questions
- Document search and summarization
- Contextual business knowledge
- Narrative explanations

*Example: "What does our policy say about discount limits in Europe?"*

### Unified conversational experience
The strongest Talk-to-Data Assistants combine both approaches, bringing analytical precision and business context into one conversational experience.

---

## Slide 5 — Talk-to-Data business use case examples span across the enterprise

**Subtitle:** Faster access to insights and decision support across business functions

### Front Office & Operations

**Commercial**
- Sales and margin analysis
- Pricing and discount insights
- Commercial policy Q&A

**Marketing**
- Campaign performance analysis
- Promotion effectiveness
- Brand guideline retrieval

**Supply Chain**
- Inventory and service-level monitoring
- Root cause analysis for disruptions
- SOP and process guidance

### Business Support Functions

**Finance**
- P&L and cost analysis
- Forecast vs. actual explanations
- Finance policy retrieval

**Procurement**
- Spend and supplier analysis
- Contract and clause search
- Sourcing policy Q&A

**Customer Service**
- Service KPI monitoring
- Complaint driver analysis
- Agent knowledge support

### Corporate & Leadership Functions

**Human Resources**
- Headcount and attrition analysis
- HR policy Q&A
- Manager self-service support

**Legal & Compliance**
- Policy and regulation retrieval
- Contract summarization
- Audit support

**Executive Decision Support**
- Cross-functional summaries
- Driver-based business explanations
- Metrics with business context

---

## Slide 6 — Text and voice: two ways to interact with data

**Subtitle:** Optimal Talk-to-Data experience depends on the user context, task complexity, and interaction environment

| | Text-based T2D | Voice-based T2D |
|---|---|---|
| **Common use cases** | Detailed and complex business questions; iterative analysis and follow-up exploration; reviewing tables, charts, and cited answers; desktop and knowledge-worker workflows | Quick questions and immediate answers; mobile, hands-free, or on-the-go scenarios; field operations, manufacturing, logistics, and frontline use; executive access to answers in meetings or while traveling |
| **Key advantages** | High precision and control; easy to edit, refine, and compare questions; well suited for structured analysis; supports visual outputs naturally | Intuitive and natural interaction; faster input for simple questions; more accessible for broader user groups; useful when typing is inconvenient |
| **Example questions** | "Compare Q2 sales by region vs. last year" / "Show top 10 customers by margin decline" / "Summarize the policy differences between markets" | "What were yesterday's sales?" / "How is inventory performing this week?" / "What does the procedure say about returns handling?" |

In many scenarios, the strongest UX is **multimodal**: text and visuals for precision, traceability, and deeper analysis; voice for convenience and accessibility.

---

## Slide 7 — Talk-to-data technical platforms

**Subtitle:** Broad expertise across low-code, cloud, and open-source ecosystems

| Category | Platforms |
|---|---|
| **Low-code** | MS Copilot Studio, Azure Fabric, Databricks Genie, Google Agent Builder |
| **Cloud** | Azure AI Foundry, Google Vertex AI, Azure AI Search, Timbr.ai |
| **Open-source** | LangGraph, LangChain, Langfuse, n8n |

---

## Slide 8 — Lingaro Talk-to-Data Implementation Blueprint

**Subtitle:** A structured approach to designing, building, and scaling enterprise Talk-to-Data solutions

### 1. Strategy & Planning
- **Use-case prioritization & refinement** — Identify the highest-value business use cases, clarify user needs, and refine scope based on feasibility, value, and implementation readiness.
- **Business case & value targets** — Define the expected business impact, success metrics, and ROI targets to guide investment decisions and measure outcomes.
- **Solution scope & operating model** — Determine the implementation boundaries, ownership model, governance structure, and target operating model for the solution.
- **Feasibility assessment & pilot roadmap** — Assess technical and business feasibility, validate assumptions, and define a phased roadmap from pilot to scale.

### 2. Data Foundation
- **Data & knowledge source assessment** — Identify the structured and unstructured sources required to answer priority business questions, including data systems, documents, and repositories.
- **Data quality, readiness & governance** — Evaluate whether the available data is accurate, complete, governed, and suitable for trusted conversational access.
- **Integration, preparation & access setup** — Connect required data and content sources, prepare them for use, and establish secure access for the assistant.
- **Semantic layer & metadata alignment** — Align business definitions, metrics, hierarchies, and metadata to improve consistency, traceability, and answer quality.

### 3. Intelligence Layer
- **GenAI architecture & model strategy** — Define the target GenAI architecture, model choices, deployment pattern, and supporting components needed for the solution.
- **NL2SQL & RAG solution design** — Design how the assistant will answer questions from structured data, unstructured content, or hybrid combinations of both.
- **Knowledge graph & semantic enrichment** — Use enterprise relationships and business context to improve understanding, retrieval relevance, and answer accuracy.
- **Intent routing & orchestration** — Enable the system to interpret user intent, select the right tools and sources, and coordinate the end-to-end response flow.

### 4. Experience Layer
- **Conversational interface design** — Design the user interaction model, including how users ask questions, receive answers, and navigate follow-up exploration.
- **Interaction channels & modalities** — Define where and how users engage with the assistant, including text, voice, chat, copilot, mobile, or embedded experiences.
- **Application & workflow integration** — Integrate the assistant into enterprise tools, applications, and business workflows where users already work.
- **Action enablement & automation** — Extend the assistant beyond answering questions to support downstream actions, recommendations, and workflow automation.

### 5. Adoption & Value
- **Stakeholder communication & engagement** — Build awareness, alignment, and sponsorship across business and technical stakeholders to support adoption and scale.
- **Change management** — Prepare the organization for new ways of working by addressing processes, behaviors, governance, and user acceptance.
- **User enablement & training** — Equip users with the knowledge, guidance, and confidence needed to effectively use the solution in daily work.
- **Value measurement & continuous improvement** — Track usage, impact, and business outcomes, and continuously improve the solution based on feedback and performance insights.
