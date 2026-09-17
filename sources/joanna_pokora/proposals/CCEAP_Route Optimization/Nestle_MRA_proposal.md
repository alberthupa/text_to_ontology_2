**Type:** proposal

# Lingaro for Nestlé
## Technical proposal for Sales Analytics – Merchandisers Resource Allocation
**27 Oct 2023**

*Information Sensitivity: General\Internal*


---

## Table of Contents

**01 — Our Proposal**
- 1.1 Solution Architecture
- 1.2 Project Timeline
- 1.3 Proposed Team
- 1.4 Way of Working

**02 — Company Details**

---

## 01 — Our Proposal

### Accelerating digital transformation through analytics initiatives

---

## Executive Summary — Collaborating with you to attain digital transformation excellence

We thank Nestlé for allowing us to submit our proposal to support your strategic initiative of becoming a 'Data Centric' organization.

With our understanding of the Nestlé requirements and RFP, Lingaro proposes an iterative model-driven approach to implement the 'eBusiness' and 'Sales Analytics' projects. We strongly believe we are the best partners for Nestlé in this journey for the following reasons:

- **Dedicated Design Workshops** – before commencing the projects, to ensure meeting all Nestlé business criteria and KPIs we will provide dedicated workshops for each case, to cover all important aspects and provide business-trimmed deliverables
- **Fully Scalable and Robust Architecture solution:** all projects from eBA and eSales cases, were entangled into one program platform on Azure Cloud
- **Global Team:** Lingaro is bringing the best of talent with a mix of team based in Manila and Europe. This will bring the best practices across the globe in our implementations.
- **Value Add:** Lingaro's relationship with Nestlé is strategic; hence, we bring in Value Add on top of the requirements. We will conduct 'Responsible AI' workshop at no cost to Nestle to educate the users on how to leverage AI responsibly in their business.
- **Strong Management Commitment:** Nestlé being a strategic customer for Lingaro, will have the attention of senior leadership at the regional level to ensure the success of the engagement.

Once again, thank you for the opportunity, and we are eagerly poised to take our mutually beneficial relationship to the next level through this strategic engagement.

---

## Value Adds — Committed to quality: exceeding expectations and enhancing client experience

1. **Engagement Manager Investment**
   Nestlé is a strategic customer, so Lingaro will have an engagement manager as an investment to ensure that all projects are synchronized and learnings across the projects.

2. **Continuous Feedback**
   As a process, Lingaro will have regular governance at an agreed frequency with Nestlé to ensure all feedback is captured and necessary actions are taken to address all feedback.

3. **Nestlé Orientation**
   It is essential for all consultants who are engaged in the Nestlé project to be aware of Nestlé's ways of working, environment, and policies. Lingaro will establish an orientation program all consultants must undergo before being deployed in the projects.

4. **Nestlé Specific Training**
   Any program of this nature may need some project-specific technology training. Lingaro will invest in training its consultants for any such needs based on the feedback from Nestlé and our consultants and will provide it at no additional cost to Nestlé.

5. *One session to enable users to enable self service.*

---

## Power BI Fundamentals – 1-day training (Dashboard in a Day - DIAD)

Lingaro will cover critical concepts of Power BI to enable Nestlé developers to jump-start new projects in their organizations.

Ideally suited for business users, report creators, and readers of the report, with a touch of basic visualization process.

By the end of the session, attendees will better understand how to:
- Connect, import, and transform data from various sources such as SharePoint and Excel/CSV.
- Define business rules and KPI measures.
- Explore data with powerful visualization tools.
- Build reports.
- Share dashboards with their team and business partners and publish them online.
- And more….

**Terms:**
- The training will be delivered remotely and in a mixed presentation/hands-on exercise manner.
- Pre-requisites shall be given by Lingaro a week before the workshop.
- Max number of participants for the workshop – 20 participants from Nestlé.
- Direct connection from Power BI to Azure SQL shall be provided as a demo if participants cannot access Azure SQL Database before the workshop.
- The workshop can be recorded and shared only with the prior consent of both parties and the participants.

---

## 1.1 — Solution Architecture

### Requirements eSales — Merchandisers Resource Allocation

- Develop a tool within the system to determine the best and most cost-efficient way to deploy merchandisers on the field based on various parameters (e.g., political constraints, proximity/geographic location, sales, account type, roving/stationary status).
- Enable the system to utilize proximity and geographic location data for optimized merchandiser deployment planning.
- Implement functionality to input and manage business and political restrictions affecting merchandiser deployment.
- Ensure the system is built to adapt merchandiser resource allocation strategies in response to dynamic market and political conditions.

---

## Merchandisers Resource Allocation — Overview

Merchandisers are people deployed in the field who visits multiple retail stores (doors) to check on inventories and place orders to replenish shelves. These merchandisers are limited, and can therefore only visit a limited number of doors. Deploying them costs PHP 1B annually, and will only continue to increase as more doors open.

### Objective
To develop a tool that can determine the best/most cost-efficient way to deploy merchandisers on the field to cover the most doors, based on business restrictions (political), proximity/geographic location, sales, account, roving/stationary, etc.

### Project Scope
1. **Data Input:** Historical sales per door (offtake / sell-in), merchandisers deployment history, door Masterfile (includes mapping), costs to deploy, OSA, MH
2. **Model** generates optimized deployment plan (sched/location) based on business constraints.
3. **WebApp/PowerBI Dashboard** — deployment plan / map view / Masterfile maintenance of door and deployment list

### Project Milestones (for discussion)
Input Scope, Parameter/Restriction setting, Optimization Methodology, Output Wireframe, Output Application Trial

### KPIs that must not be negatively impacted by Optimization
Sales, Market Hygiene, OSA, Reporting Requirements

### Optimization Parameters / Constraints
- **Volume Standard:** 50 cs/day (SMKT) or 70 cs/day (Cash & Carry / Wholesaler)
- **NPS (value) Standard:** 95,000 / day (SMKT) or 133,000 / day (CNCWS)
- **Time in Store Standard (ROVING):** 30–45 minutes per door.
- **Travel Time Standard (ROVING):** Max of 1 hour / headcount for Urban areas. Max of 1.5 hour / head for Rural Areas.
- **Political Constraint:** No Mix Accounts sharing of Merchandisers — A merchandiser assigned to an SM store cannot be assigned to a Puregold store. Applicable to Modern Trade Accounts / Chain Accounts
- **Cluster Constraint:** Geographical boundary (i.e. South Manila). Model can suggest new Geographical Boundary / Cuts.
- **Dropped Doors:** will there be any based on previous optimization models?
- **New Doors / Headcount Assumption:** 100 doors / year with 1.5 headcount deployment per door.
- **Unknown Sales Constraint:** Accounts where we deliver centrally and have no per door view but we deploy merchandisers based on Top Stores List from Commercial.
- **Refresh Frequency:** QUARTERLY
- **Optimization Target Benefit:** 5% – 10% Savings (coming from simple calculator of 20% over-deployment)
- **2023 Cost:** OOM
- **Savings Target:** 45M – 90M, ROI – 5 months ROI at 5% Savings

![Image placeholder: Merchandisers Resource Allocation | High Level Process — Input → Cyclic Scheduling & Allocation Process → Prediction of input data for New Stores]

---

## Our Understanding – Use case C from eBusiness (MRA)

Going to the last case of one of the most-difficult optimization problems to solve is NP-hard, Traveling Salesman Problem – with MRA, here it's basically on steroids, by adding additional factors the equation, so we are looking for most cost-efficient way to deploy merchandisers on the field taking into consideration additional variables.

---

## MRA – Case Summary (Use case C from eBusiness)

Our approach to solve this problem is to use Mixed Integer Linear Programming. On input we have data about merchandisers and point of sales, that after needed pre-processing will be used to define constraints in our Mixed Integer Problem definition. Together with unique constraints like political ones, we define an objective function that takes care of optimization target. Whole definition is then solved by dedicated solver, that ensures that solution calculation is quick enough. Commercial solvers like FICO press that we recommend here, are able to solve bigger optimization problems faster and using less computing power than OpenSource solvers, as they use patented algorithms to optimize problem definition itself and then state of the art implementation of linear algebra solving techniques. To be able to generate plans also for new stores, we want to use clustering Machine Learning algorithm to find most similar existing stores and calculate average metrics from it, that we can put into the solver.

In this project we encourage to use Fico Express solver, as it has free community license that is able to solve small problems using same algorithms as full version (there is constraints and variable limit). There is also 60 day trial that should enable us to test solver in the PoC. Top alternatives for Fico Xpress are Gurobi and Cplex - as from answers to our questions we learnt that Nestle do not have solver license yet, it's good to ask for price for this project. Fico often is able to give best offer, but we recommend validating it. We are able to switch to different technology.

---

## Case Summary - Use case C from eBusiness (MRA)

**Objectives of POC** are to use historical data from merchandisers routes & historical sales data during those routes, up-to-date POS localization & sales data and up-to-date salesman data (availability) to build data processing pipelines and defining mixed integer programming problem model that will calculate the most fitting POS in best possible order for each of the salesman available, recalculated on snapshots and accessible via PowerBI.

**MVP** will industrialize the POC by putting all data (from all regions) into solver, adding new constraints and modifying objective function to cover all needed business requirements and optimization targets. Whole process will be automatized and monitored.

MVP will utilize Web Application to visualize scheduled plan, with acceptance and possible manual modification. With WebApp, user would also have ability to view plan for single merchandiser, single POS, all merchandisers from selected region and all POS from selected region. On top would be functionality if modified plan is feasible to execute.

---

## POC and MVP Approach

Our **Proof of Concept (POC)** leverages historical merchandiser routes, sales data, up-to-date POS localization, and salesman availability data. We are crafting here data processing pipelines and a mixed-integer programming model. This model strategically calculates the most fitting POS in the optimal order for each salesman, with recalculations made accessible via PowerBI.

As we evolve to the **Minimum Viable Product (MVP)** stage, we scale and globalize our approach. We integrate comprehensive data from all regions into our solver, adding new constraints and tailoring the objective function to meet specific business and optimization goals. The entire process is streamlined, automated, and continuously monitored.

Our MVP features a user-focused Web Application, offering visualization of the scheduled plan. Users have the ability to review and manually modify these plans, catering to individual merchandisers, POS, or broader regional scopes. A key feature is the real-time assessment of the feasibility of any modified plan.

In summary, we are building a comprehensive, adaptive, and user-centric solution that seamlessly aligns with the complex dynamics of retail strategy.

---

## Two Programs – One Platform

**Key points:**
- Architecture accommodates batch processing.
- With Azure Kubernetes Services, the FICO solver operates as a computation engine, the API exposes services, Graph DB Node4j manages relationships, and Vector DB Chroma handles vector search and analytics. Azure Kubernetes Services provides a scalable and managed environment for deploying, managing, and scaling containerized applications using Kubernetes.
- Azure DevOps is the primary tool for code management, user stories & task management, and CI/CD.
- Ingestion and Orchestration will be performed mainly by Azure Data Factory and Logic App for SharePoint sources.

---

## Technology Stack

| Category | Technology | Purpose |
|---|---|---|
| Programming Languages | Python, SQL | Data Integration / Analytic / Science – Programming Language |
| AI/Machine Learning | Azure Machine Learning, Azure Databricks | Experimentation, Data Science, Model training |
| Solver* | FICO Xpress | Optimizes complex decision problems by mathematically determining the best solution from a set of feasible options |
| Version Control Tool | Azure DevOps | Source Code Repository |
| Data Processing | Azure Databricks | Data & AI Platform |
| CI/CD Tool | Azure DevOps | CI / CD Tool |
| Reporting & Visualization | Power BI | Reporting and Visualization |
| Web Application | Custom WebApp for UI | — |

\*FICO solver is a recommended solution for MRA case, that license needs to be obtained by Nestle

---

## Infrastructure Architecture - FICO as a solver

![Image placeholder: Infrastructure Architecture diagram]

**Components depicted:**
- vNet
- Developer / Azure Active Directory
- ADO CI/CD, ADO Repo, Pipelines
- Local Development PoC
- PowerBI Reports / POC / MVP
- Public subnet / Private subnet
- AKS (Azure Kubernetes Services)
- Public Endpoint
- Public Address
- Service Principal
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

## AI/Data Science Success Story — Global snacks manufacturer Demand Forecasting

### Customer description
Leading global manufacturer in a CPG sector with large number of products and distribution channels.

### Challenge
- Facing a growing number of overstocks and out-of-stocks, a leading global manufacturer decided to invest in better, more accurate demand forecasting capabilities
- Current forecasting solution delivered unsatisfactory results

### Solution
- Advanced analytics as a key step to data-driven planning
- Additional, enhancing data sources
- Combination of several machine learning models outperforming the currently used solutions

### Technologies
R, Azure

### Value delivered
- Improvement of the forecasting accuracy and reduction of mean absolute percentage error to 25.5% through the usage of statistical forecasts
- Automation of the forecasting process without the need of human attention providing unlimited scalability and substantial staff cost reduction
- Easy-to-scale, cloud-based tool

**Themes:** Machine Learning and Deep Learning · Predictive Modeling

---

## AI/Data Science Success Story — Forecasting System – operationalization and migration to different PaaS

### Customer description
A large multinational corporation in the Fast-Moving Consumer Goods sector.

### Challenge
- Massive and frequent code changes in external DS/business logic part.
- A huge number of models needed to train in parallel (180+ countries, ~40k products).
- Rapidly changing/early-stage PaaS.
- Complex environment - corporate security restrictions.
- Long execution time, not stable, manual interventions needed.
- Dev Platform different to target production Platform.

### Solution
- Model operationalization.
- Platform agnostic – code ready to be deployed in any spark-compatible PaaS
- CICD – automatic code quality checks & Deployment.
- Standardization and code modularization – logical separation of code (slowly vs rapidly changing code, data layer separated from ML layer) simplifies collaboration and coordination of Engineering and Data Science teams.

### Technologies
Azure Synapse Analytics, Azure Databricks, Azure Data Factory, Azure DevOps, Azure Datalake Storage, Python

### Value delivered
- Better execution time: initial 48hrs to 10hrs.
- Increased stability, manual interventions not needed.
- Cost reduction and infrastructure simplification – 4 Databricks clusters reduced to a single Synapse cluster.
- Reduced time-to-market.
- Better forecast quality.
- Data Science and Big Data tech stacks combined – lower operational costs

**Themes:** Machine & Deep Learning · Forecasting · Machine Learning Engineering & Operations · Modeling Lifecycle · AI Operationalization

---

## AI/Data Science Success Story — Taking over the workhouse optimization project and getting it back on track

### Solution
- Mapping existing solution with business requirements and identifying weak points and gaps
- Incorporating code quality checks and automatic tests into CICD
- Preparing and implementing data-based test strategy for solver part of solution
- Documenting the solution
- Refactoring the solution
- Splitting solution from monolith into functional blocks

### Technologies
Python, Fico Express

### Value delivered
- Eliminating over 500 code smells
- Eliminating 13000 lines of code duplications
- Reducing codebase by 10%, adding tests and extending functionality at the same time.

**Themes:** Supply Chain Analytics · Statistics, Exploration & Rules · ML Productization

*Lingaro joining the project → Recovery plan finish → Maintenance & development*

---

## 1.2 — Project Timeline

### Combined eBusiness Analytics and Sales Analytics Proposed Timeline

**Notes:**
- 1st month is planned for the setup of the architecture, gathering business requirements, data maturity, and validation of available data – sources and quality. Projects can start earlier if the conditions are captured and confirmed before.
- Phased implementation for the projects. All projects will have POC phase to check and evaluate with the client to ensure all items are aligned before moving to MVP.
- Project schedule in this RFP is heavily based on assumptions, thus can change upon requirements gathering and analysis.

---

## Use Case #3 — Merchandisers Resource Allocation: Work Breakdown

### Roles
- **PM:** 18 effort units distributed across phases
- **BA:** 16 effort units distributed across phases

### Initialization
| Activity | Effort |
|---|---|
| Design Workshop | 6 |
| Cloud and Infra Setup | 8 |

### POC
| Activity | Effort |
|---|---|
| One time source data load & familiarizing with data | 6 |
| Aggregating & cleaning data | 9 |
| Objective function and output test plan | 4 |
| Setting up project structure | 2 |
| Defining Variables, Constraints, business reqs, obj func. | 57 |
| Testing and fine tuning | 5 |
| Solver out postprocessing | 2 |
| KNN approach | 5 |
| Simplified output visualization | 1 |
| UX Design in PBI | 4 |
| PBI Dev (POC only) | 10 |

### MVP
| Activity | Effort |
|---|---|
| Data model optimization | 5 |
| Data cleansing, integration, harmonization processing development | 15 |
| Output data storing | 3 |
| Orchestration development | 3 |
| QA and Prod setup | 2 |
| Deployment to QA and Prod | 1 |
| Monitoring setup | 2 |
| Performance tests and optimization | 3 |
| Adding more PoS and regions into solver | 3 |

### Data Science (POC)
| Activity | Effort |
|---|---|
| Data Understanding | 5.33 |
| Data Preparation | 5 |
| Modeling | 10.33 |
| Applying postprocessing rules | 5 |
| Evaluation | 4.33 |

### Engineering (POC)
| Activity | Effort |
|---|---|
| Setup environment | 2.33 |
| Create ADF extraction pipeline for necessary data (5–10 tables) | 1.5 |
| Data transformation scripts (bronze, silver, gold) | 2 |
| Simple feature store | 1.17 |
| UI/UX Design | 4 |

### Data Science (PROD)
| Activity | Effort |
|---|---|
| Data Understanding | 4.33 |
| Data Preparation | 4.33 |
| Modeling | 4.33 |
| Evaluation | 6.67 |

### Engineering (PROD)
| Activity | Effort |
|---|---|
| Setup environment/infrastructure/pipelines | 10 |
| Create and schedule extraction pipeline for necessary data (5–10 tables) | 5.33 |
| Data transformation scripts (bronze, silver, gold) | 17 |
| Testing | 7.33 |
| Feature stores, meta-data | 9 |
| Data Model | 3.67 |
| Model inference/prediction pipeline | 4.67 |
| Model training pipeline | — |
| PowerBI Development (Measures/KPIs, Visuals, Slicers, Mobile View) | 9.6 |

---

## General Technical Assumptions

- Each use case is split into 2 parts: PoC and MVP (Final Solution). Once PoC phase is completed, we establish the final goals for the efficiency.
- There are approximately up to 10 datasets total and few most important Platforms
- The input data contains all the necessary information to create the model (either for feature selection and feature engineering)
- The input data is factually correct, there are no contradicting pieces of information (e.g. duplicate sales records with different values)
- The input data doesn't require a lot of filtering/cleaning
- The data volume is big enough to divide it into testing and training datasets and then assess the model reliably
- We can reuse data available in Snowflake to conduct all cases
- For PoC we will prepare models for 1 campaign platform (Meta) and 1 sales platform (Shopee)
- Data transformations are not complex (both technically and business-wise)
- We work on customer infrastructure and the customer will create necessary components and grant the necessary access permissions
- Lingaro will be able to configure the previously created resources
- The input data is available in a data warehouse and is ready to consume by data scientist (tabular format, predictable structure, relatively high data quality)

---

## Project Delivery & Technology Assumptions

**Project will be delivered remotely.**

### Technology
- Lingaro team will be provided with the required license(s) to execute the given role. This includes both Project Management and Technology tools in the scope of the engagement.
- Nestlé will provide all available technical documentation to the Lingaro team relevant to the roles in the scope of the engagement.
- The details for the Security implemented will be agreed upon between Nestlé and Lingaro as part of the project execution.
- Lingaro is not responsible for the Infrastructure hosting the technologies in scope.
- Proposal does not cover any Infrastructure costs.

---

## MRA Data Assumptions

- Sales per door data is available in SnowFlake
- Merchandisers data is available in SnowFlake
- Point of Sales data (including sales GAP) is available in SnowFlake
- Merchandiser historical deployment cost data is available in SnowFlake
- Visit time data or algorithm recipe is provided by Nestle
- Distance or travel time matrix between point of sales is available or Lingaro is allowed to use 3rd party API to get this data and NESTLE will pay for such API (as Google Distance Matrix API)
- Historical data is uploaded into SnowFlake on frequency basis that enables solution to include fresh information in expected plan generation frequency
- Start data for new stores (cold start) are calculated using average data for similar stores with history (using KNN algorithm)

---

## Main Risks and Challenges

| Risk | Consequence | Mitigation |
|---|---|---|
| Unavailability of Stakeholders and SMEs for user interviews and discussions | Leads to delays in documentation, finalization of the key aspects, including requirements, technology selection, and next steps | Upfront scheduling of sessions based on the availability of the SMEs / Key stakeholders. Work closely with the project contact to identify the right key stakeholders / SMEs |
| Infrastructure Failures | Leads to delays in the overall engagement | In case of infra failure, Nestlé and Lingaro to agree on delivery delays and work with Nestlé IT to fix immediately |
| Information Gap/Absence | Leads to the delay in the overall project schedule | In case of information gaps, Lingaro shall alter the product managers and relook the priorities and plan |
| Lack of clarity in Scope | Leads to the delay in planning and execution | Lingaro to raise and work closely with stakeholders/SMEs |

---

I can convert the missing sections, but only based on the content actually available in the provided context. Here's what I can extract for the sections that were missing:

---

## 1.3 — Proposed Team

### Smooth, on-time delivery of the solution — With all answers available from one source

For the project, Lingaro will assign a person to serve as your Single Point of Contact – Project Manager.

Nestlé will have simple and easy access to a wide range of talent working on the solution's front end, its back end, and everything in between. The Account Manager and Delivery Leader will support the Project Manager.

### Team Structure

**Nestlé side:**
- Business Owner
- Technical Owner

**Lingaro side:**
- Project Manager *(Single Point of Contact)*
- Solution Architect
- Power BI Developer(s)
- AI Engineer(s)
- UX Designer
- Data Scientist(s)
- Full-Stack Developer
- DevOps CI/CD Engineer

---

### Role Descriptions

**Project Manager**
A project manager is a professional who organizes, plans, and executes projects while working within restraints like budgets and schedules. They lead entire teams, define project goals, communicate with stakeholders, and see a project through to its closure. Project managers are involved in the planning, implementation and ongoing support work for company-wide undertakings.

**Solution Architect**
A solution architect designs and implements technology solutions to address business problems, considering feasibility, scalability, and security. They work closely with stakeholders and ensure alignment with the organization's technology strategy and standards.

**Power BI Engineer**
More than 11 years of data visualization and UI/UX design experience. Manages and mentors frontend developers and consultants, providing guidance and technical support.

**Data Scientist**
Over 10 years of experience in data analysis, machine learning, and building predictive and statistical models; has a keen eye for detail and a focus on quality solutions; skilled in working with large datasets, designing and building systems that combine data from different sources to support analysis and visualization.

---

### Sample Team Profile

**Ma. Ruth Julianne Ong — Engagement Manager**
Over 13 years of experience in the IT industry covering enterprise systems and data analysis in multiple industries including CPG, finance, and manufacturing. Focused on delivery management, program management, and project management with PMI-PMP, SAFe, and ITIL4 certifications.

> *Our proposed team is subject to availability based on the time of awarding and initiation.*

---

## Governance / Communication Cadence

| Lingaro Role | Nestlé Counterpart | Frequency |
|---|---|---|
| APAC Business Head / Account Manager / Delivery Leader | Business Sponsor / CIO / Program Director | Monthly |
| Engagement Manager / Project Manager | Program Director / Project Manager / Business User Lead | Fortnight |
| Engagement Manager / Project Manager / Solution Architect | Project Manager / Product Owner / Business User Lead | Weekly |
| Project Manager / Solution Architect | — | Direction (subject to confirmation from Nestlé) |

---

## Risk Management Process

### Process Flow

**Communication & Consultation** → **Continuous Monitoring and Review\***

1. **Establish Context** — Parameter definition for managing risks
   - Objectives
   - Risk criteria

2. **Risk Assessment**
   - **Risk Identification:** Identify as many knowable risks and opportunities as practicable
   - **Risk Analysis:** Perform qualitative and quantitative analysis
   - **Prioritize:** Rank risks
   - **Risk Evaluation:** Compare results of risk analysis; evaluate combined effects of risks on project outcome

3. **Risk Treatment**
   - Identify and determine risk response strategy and actions
   - Implement responses and assess effectiveness

\**Includes Project Closure & Lessons Learned documentation. Will be documented in the RAID log*

---

## General Project Assumptions

### General
- Nestlé will designate Business Owner and IT Owner who will have the authority to make decisions related to the Project.
- Nestlé will answer Lingaro's project-related questions within two working days.
- Nestlé will ensure adequate availability of people for the respective phases of the project.
- Lingaro will designate a Project Manager to coordinate the service activities and to serve as a Single Point of Contact for Nestlé.
- Nestlé confirmation of the completed deliverables, or lack of response from Nestlé after five working days from the date of received notification, will be the basis for the invoicing.
- Project will be delivered remotely.

---

## 1.4 — Way of Working

### DevOps Culture

Lingaro's DevOps culture focuses on strong collaboration and synergy between self-organizing Stream-Aligned Teams comprising highly motivated technology, security, and operational experts who securely and reliably deliver quality solutions.

We focus on the following key DevOps culture principles:
- DevOps Principles
- Continuous Learning Culture
- Customer Centricity

Culture, Automation, Lean, Measure and Sharing methods are embedded into our Continuous Delivery Pipeline via DevOps Enablers following Lingaro Delivery Methods and focusing on the Value Adds component of Lingaro Delivery Foundations.

---

### Iterative and User-Centered Proprietary Process of Delivering Dashboards

> *To deliver rapid results, meeting stakeholders' requirements and users' needs*

**Process Cycle:**
1. **UNDERSTAND** — Solution envisioning
2. **IDEATE & VALIDATE** — Mockup creation with iterative feedback; Prototype and interaction design
3. **DELIVER** — Solution delivery
4. **REFINE** — Adoption monitoring and user feedback

---

## 02 — About Lingaro / Company Details

### Our Services

**Consulting and Advisory**
- Data management strategy
- Corporate architecture
- Technology choice
- Cloud transformation

**IT Development**
- Agile, Waterfall or Factory model
- Multi-vendor environment

---

## AI and Machine Learning — Our Differentiators

We equip organizations with the skills and expertise needed to harness the power of cutting-edge innovations in data science and AI.

### Lingaro Data Transformation Experience
- **30+** countries where Lingaro built and deployed scalable AI- and machine learning-powered solutions
- **20%–30%** reduction in costs of operations based on data science projects delivered to clients

### Core Capabilities
- **Data Discovery and Consulting** — Auditing the existing analytical landscape and identifying opportunities and synergies to use AI

### Competitive Edge
- Unique MLOps framework for automating and operationalizing AI projects
- A dedicated center of excellence that brings together top talent, knowledge, and resources for AI projects
- Industry-recognized practice built on XOps-inspired initiatives — AIOps, MLOps, DataOps
- Use case approach for building and deploying solutions at scale to various business units

---

