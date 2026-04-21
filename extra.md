# Dash + Plotly UI Improvement Requirements

## Scope

* **Monitoring → Oil → Machines**
* **Monitoring → Oil → Reports**
* **Monitoring → Telemetry → Fleet Overview**
* **Monitoring → Telemetry → Component Detail**

## Global UX Rules

These rules apply to all requirements below.

### GR-01 — Remove redundant KPI cards where the same information is already encoded in a status distribution chart

* KPI cards must not be used when they duplicate the exact same totals/percentages already visible in the status distribution chart.
* This applies immediately to **Telemetry / Fleet Overview**.
* The goal is to reduce noise and avoid repeating counts in multiple places.

### GR-02 — Standardize all circular distribution charts as donuts

* Any status distribution currently rendered as a full pie must be converted to a **donut chart**.
* The center of the donut must show the total population.
* Segment hover state must show count and percentage.
* The legend must repeat the same count and percentage for quick scanning.
* No screen may mix pie and donut conventions.

### GR-03 — Re-orient all tables around “condition, evidence, action”

* Table columns must prioritize:

  * asset identifier
  * current condition/status
  * severity/priority
  * strongest evidence
  * latest AI guidance if available
  * freshness or evaluation period if relevant
* Low-value technical columns or internal scores must be demoted or hidden behind an expanded detail state.
* Column design must follow the current production data contracts, not deprecated fields. Oil machine-level schema now centers on `unit_id`, `overall_status`, `machine_score`, component status counts, `priority_score`, `component_details`, and `machine_ai_recommendation`, while Oil report-level outputs include `essays_broken`, `severity_score`, `desgaste_score`, `report_status`, `breached_essays`, and `ai_recommendation`. 
* Telemetry machine-level data now centers on `unit_id`, `overall_status`, `machine_score`, `priority_score`, `components_normal`, `components_alerta`, `components_anormal`, `components_insufficient`, `total_components`, `baseline_version`, and `component_details`; telemetry component-level detail includes `component_status`, `component_score`, `triggering_signals`, `signals_evaluation`, `signal_coverage`, `sample_count_avg`, `criticality`, and `baseline_version`.  

### GR-04 — Introduce a shared view-model layer between loaders and UI components

* Do not bind DataTable and Plotly traces directly to raw parquet schemas.
* Implement a transformation layer that maps current contracts into UI-friendly objects.
* This is required because both Oil and Telemetry contracts have changed in production and several older fields are deprecated or renamed.  

### GR-05 — Use a single status design language across Oil and Telemetry

* Reuse the same badge/chip pattern for:

  * `Normal`
  * `Alerta`
  * `Anormal`
  * `InsufficientData` where applicable in Telemetry
* `InsufficientData` must be visually neutral and must not look like `Anormal`.
* Status color tokens must be reused in charts, tables, chips, and summary headers.

---

# 1) Monitoring → Oil → Machines

## OIL-M-01 — Redesign the first fold as a condition-first fleet summary

**Apply to:** **Monitoring → Oil → Machines**, top section

### Requirement

Refactor the first visible row so it answers:

1. Which units require attention now?
2. Why?
3. What does AI recommend?

### Implementation detail

* Keep the left/right split structure if desired, but make the two panels work together.
* Left panel: donut chart for machine status distribution.
* Right panel: priority table of units.
* Clicking a donut segment must filter the table by status.

### Acceptance criteria

* The status chart is a **donut**, not a pie.
* Table rows update when a donut segment is selected.
* The active chart filter is visible as removable UI state.
* Default table sort is descending by urgency.

---

## OIL-M-02 — Replace current priority table columns with user-facing diagnostic columns

**Apply to:** **Monitoring → Oil → Machines**, priority table

### Requirement

Redefine the table columns to explain machine condition using the current oil machine schema.

### Required visible columns

* `unit_id`
* current overall status
* machine severity / machine score
* component burden summary:

  * components normal
  * components alerta
  * components anormal
* priority score
* AI recommendation summary from `machine_ai_recommendation`

### Optional secondary columns

* client
* evaluation freshness if derived from latest report data
* count of monitored components

### Explicit constraint

Do not use deprecated fields such as old machine name/model counters from previous contract versions unless they are derived from another valid source. The current production Oil `machine_status.parquet` contract removed several older columns and now uses the component-based summary model. 

### Acceptance criteria

* The first screen tells the user which unit is worse and why.
* AI guidance is visible without opening the row detail.
* Internal-only columns that do not help decision making are removed from the default view.

---

## OIL-M-03 — Convert machine selection into a persistent master-detail flow

**Apply to:** **Monitoring → Oil → Machines**, machine detail section

### Requirement

Replace the current large dropdown-first interaction with a master-detail pattern.

### Implementation detail

* The selected machine must be visible in a persistent summary bar.
* The component evidence table must update based on the selected machine.
* Selection can come from the priority table or from a searchable selector.

### Acceptance criteria

* The user always knows which machine is selected.
* Selection state is visually persistent.
* The user does not need to scroll back to the selector to confirm context.

---

## OIL-M-04 — Refocus component-level evidence around condition and evidence, not raw layout

**Apply to:** **Monitoring → Oil → Machines**, component detail table

### Requirement

The component table must explain why the machine is in `Alerta` or `Anormal`.

### Required visible columns

* `componentName` or display label
* latest report status for that component
* severity score
* essays broken
* breached essays summary
* AI recommendation summary

### Data rule

Use original `componentName` for detailed visibility and only use `componentNameNormalized` for grouped or aggregated comparisons. The oil contract explicitly preserves both because the original name is needed for detailed visibility and the normalized name is used for Stewart-limit grouping. 

### Acceptance criteria

* Components are sorted worst-first.
* Breached evidence is visible directly in the table.
* The user can identify the critical component without opening a separate report.

---

## OIL-M-05 — Move quick navigation to report detail earlier in the workflow

**Apply to:** **Monitoring → Oil → Machines**, quick navigation block

### Requirement

Relocate the “go to report detail” action so it appears near the selected machine or near the priority table, not as a late-page utility.

### Implementation detail

* Navigation inputs must follow:

  * machine
  * component
  * sample/report
* It must inherit the currently selected machine when available.

### Acceptance criteria

* The user can open the relevant report detail from the first half of the page.
* It takes no more than 3 explicit selections when context is not already set.

---

## OIL-M-06 — Replace the component-distribution visual with a more scalable categorical comparison

**Apply to:** **Monitoring → Oil → Machines**, component distribution section

### Requirement

Do not use a donut for component-level distribution across many categories.
Replace it with a sorted stacked horizontal bar chart.

### Implementation detail

* Each bar = component
* Stacks = `Normal`, `Alerta`, `Anormal`
* Sort by highest abnormal burden first
* Add toggle:

  * original component granularity
  * normalized grouped component

### Acceptance criteria

* Users can identify which component families are most problematic across the fleet.
* The chart scales cleanly with many component names.
* Grouped/normalized mode uses `componentNameNormalized`. 

---

# 2) Monitoring → Oil → Reports

## OIL-R-01 — Create a sticky report identity header

**Apply to:** **Monitoring → Oil → Reports**, top filter area

### Requirement

The current filter block must be redesigned as a sticky report context header.

### Required visible context

* client
* machine/unit
* component
* sample date
* report status
* severity score

### Data rule

The report view must be powered by the current oil classified schema, which includes base silver fields plus `essays_broken`, `severity_score`, `desgaste_score`, `report_status`, `breached_essays`, and `ai_recommendation`. 

### Acceptance criteria

* While scrolling, the user always knows which report is open.
* Status and severity remain visible at all times.

---

## OIL-R-02 — Redesign sample summary into a decision summary

**Apply to:** **Monitoring → Oil → Reports**, sample information section

### Requirement

Prioritize the fields that explain the report outcome.

### Required visible fields

* report status
* severity score
* desgaste score
* essays broken
* breached essays summary
* previous sample date
* days since previous sample

### Acceptance criteria

* The summary section answers “how bad is this report?” before showing generic metadata.
* Previous-sample context is visible without further clicks.

---

## OIL-R-03 — Remove radar charts as the primary evidence view

**Apply to:** **Monitoring → Oil → Reports**, evidence analysis section

### Requirement

Radar charts must not be the first or primary interpretation device.

### Replacement

Use grouped evidence tables or bullet/bar threshold views by essay group.

### Required row-level fields

* essay
* current value
* threshold band
* essay status
* whether it contributes to breached evidence

### Data rule

The report already exposes breached essay information and score aggregates, so the UI should first explain the threshold breach clearly and only then offer compact secondary visuals if needed. 

### Acceptance criteria

* The first evidence view is interpretable without training.
* The user can identify exactly which essays caused the report status.

---

## OIL-R-04 — Separate AI diagnosis from AI action

**Apply to:** **Monitoring → Oil → Reports**, AI section

### Requirement

Split the current AI block into:

* diagnostic explanation
* recommended action

### Implementation detail

* Diagnosis can summarize interpretation.
* Action must be visually stronger and scannable.
* Long AI text must collapse/expand.

### Acceptance criteria

* AI output is not shown as a single undifferentiated paragraph.
* Recommended action can be identified in one scan.

---

## OIL-R-05 — Improve time-series defaults and remove empty initial states

**Apply to:** **Monitoring → Oil → Reports**, time-series section

### Requirement

The time-series analysis must show useful content on first render.

### Implementation detail

* Preselect breached essays by default.
* Show the current sample highlighted against historical trend.
* Show previous sample explicitly.
* Overlay normal/alert/critical thresholds.

### Acceptance criteria

* The time-series section never opens as a blank chart when data exists.
* The user can immediately compare current vs prior behavior.

---

## OIL-R-06 — Redesign “comparison with previous reports” into a delta summary

**Apply to:** **Monitoring → Oil → Reports**, comparison section

### Requirement

The comparison block must answer “what changed from the previous report?”

### Required outputs

* worsening essays
* improving essays
* unchanged critical essays
* net status change
* major severity deltas

### Acceptance criteria

* The user can identify deterioration or improvement in one screen.
* The section is not a simple side-by-side repetition of the same metadata.

---

# 3) Monitoring → Telemetry → Fleet Overview

## TEL-F-01 — Remove KPI cards completely

**Apply to:** **Monitoring → Telemetry → Fleet Overview**, top summary section

### Requirement

Delete the KPI cards from the top of the page.

### Reason

The current telemetry implementation explicitly includes fleet KPI cards and a status distribution pie chart in the same screen, which duplicates the same high-level message. The implemented telemetry section currently includes Fleet Overview UI with KPI cards and a pie chart, and the module was simplified to two tabs: Fleet Overview and Component Detail. 

### Replacement

Use a single donut chart with total units in the center.

### Acceptance criteria

* No KPI summary cards remain in Telemetry Fleet Overview.
* The donut contains the full fleet distribution including `InsufficientData`.

---

## TEL-F-02 — Convert telemetry fleet pie chart to a donut and make it interactive

**Apply to:** **Monitoring → Telemetry → Fleet Overview**, fleet distribution chart

### Requirement

Replace the current full pie with a donut.

### Implementation detail

* Center label = total units
* Segments = `Normal`, `Alerta`, `Anormal`, `InsufficientData`
* Click on segment filters the fleet table
* Legend shows counts and percentages

### Data rule

Telemetry machine-level status explicitly includes `overall_status` with `InsufficientData`, plus counts for `components_normal`, `components_alerta`, `components_anormal`, and `components_insufficient`. 

### Acceptance criteria

* The chart is the primary fleet summary.
* Table filtering from chart interaction works reliably.
* `InsufficientData` has a neutral visual style.

---

## TEL-F-03 — Redesign the fleet table around operational condition and evidence

**Apply to:** **Monitoring → Telemetry → Fleet Overview**, fleet status table

### Requirement

The table must explain machine condition using the current telemetry machine contract.

### Required visible columns

* `unit_id`
* current overall status
* priority score
* machine score
* abnormal component count
* alert component count
* insufficient-data component count
* total components
* short evidence preview derived from `component_details`

### Optional derived column

* worst component name
* count of triggering signals derived from `component_details.signal_details`

### Constraint

Do not depend on removed contract fields such as `latest_sample_date` or `total_signals_triggered`; they are not in the current production contract. 

### Acceptance criteria

* The user can identify which unit is worse and why from the table alone.
* Internal schema noise is hidden from default presentation.
* Evidence preview is generated from current JSON fields, not fabricated.

---

## TEL-F-04 — Implement persistent machine selection and lower-page drill-down

**Apply to:** **Monitoring → Telemetry → Fleet Overview**, machine selection flow

### Requirement

Row selection in the fleet table must open a persistent machine detail zone below.

### Data source

Use `component_details`, which contains component `status`, `score`, `coverage`, `criticality_weight`, `signals_count`, `triggering_signals`, and per-signal detail under `signal_details`. 

### Acceptance criteria

* The selected row remains highlighted.
* The lower section updates deterministically.
* Selection survives secondary interactions such as sorting or filtering when possible.

---

## TEL-F-05 — Redesign component table under the selected machine

**Apply to:** **Monitoring → Telemetry → Fleet Overview**, selected-machine component table

### Requirement

The component table must answer “which component is driving the machine status?”

### Required visible columns

* component
* component status
* component score
* signal coverage
* triggering signals count
* strongest triggering signals preview

### Acceptance criteria

* Components are sorted worst-first.
* Coverage is visible because missing data quality affects interpretation.
* Triggering evidence is readable without opening the component detail page.

---

## TEL-F-06 — Add an AI-ready placeholder panel without inventing unsupported data

**Apply to:** **Monitoring → Telemetry → Fleet Overview**, right-side insight panel

### Requirement

Provide a stable “AI insight unavailable / coming next” card design, but do not invent telemetry AI fields that are not in the current contract.

### Reason

The current telemetry production contract does not expose `ai_recommendation` in the component classified schema anymore, so the UI must not imply that validated AI guidance exists there today. 

### Acceptance criteria

* The panel exists and fits the layout.
* It clearly states the current unavailability of telemetry AI recommendations.
* It can later accept real AI text without redesign.

---

# 4) Monitoring → Telemetry → Component Detail

## TEL-C-01 — Replace the current weekly multi-boxplot view

**Apply to:** **Monitoring → Telemetry → Component Detail**, weekly analysis section

### Requirement

Replace the current “many weekly boxplots” first view with a more readable diagnostic layout.

### Current issue

The implemented telemetry component detail currently uses weekly boxplots with baseline bands and signal evaluation tables. That is functional but visually dense and difficult to scan at scale. 

### Replacement

Use:

* primary view: signal-by-week heatmap or ranked signal matrix
* secondary view: focused trend chart for the selected signal

### Acceptance criteria

* The user can identify worst signals in one scan.
* The page is readable without comparing many small boxplots at once.
* The selected signal drives the lower detail chart.

---

## TEL-C-02 — Redesign the component summary header

**Apply to:** **Monitoring → Telemetry → Component Detail**, top header

### Requirement

The component detail page must start with a summary header that explains the current component condition.

### Required visible fields

* unit ID
* component
* component status
* component score
* signal coverage
* sample count average
* baseline version
* triggering signals count

### Data rule

These fields are available in the current telemetry `classified.parquet` schema. 

### Acceptance criteria

* The user does not need to read the signal table to understand the top-level component diagnosis.
* Coverage and baseline version are visible because they influence trust in the assessment.

---

## TEL-C-03 — Redesign the signal evaluation table around meaning, not only score

**Apply to:** **Monitoring → Telemetry → Component Detail**, signal evaluation table

### Requirement

The signal table must prioritize interpretability.

### Required visible columns

* signal name
* signal status
* anomaly percentage
* observed range
* baseline range summary
* sample count
* severity
* signal weight if meaningful for interpretation

### Data rule

`signals_evaluation` already provides signal status, `window_score_normalized`, `severity`, `weight`, baseline percentiles `p2`, `p5`, `p95`, `p98`, observed range, anomaly percentage, and sample count. 

### Acceptance criteria

* A user can understand why a signal is flagged from one table row.
* Threshold context is visible without opening a modal.

---

## TEL-C-04 — Make the focused chart selection-driven

**Apply to:** **Monitoring → Telemetry → Component Detail**, detailed chart section

### Requirement

The lower chart must always be driven by the selected signal from the signal table or heatmap.

### Implementation detail

* One selected signal at a time
* Overlay baseline bands
* Highlight anomalous region
* Show operational-state context where relevant

### Acceptance criteria

* The detail chart never feels disconnected from the table selection.
* State-aware context remains visible because the telemetry flow already supports `EstadoMaquina` filtering. 

---

## TEL-C-05 — Improve Estado filter usability

**Apply to:** **Monitoring → Telemetry → Component Detail**, state filter

### Requirement

The `EstadoMaquina` filter must be made more explicit and easier to interpret.

### Implementation detail

* Rename the visible label to a more explanatory user-facing label such as “Operating state”.
* Available values remain `Operacional`, `Ralenti`, `Apagada`, and `ND` if applicable.
* Filter state must be reflected in chart subtitles and table helper text.

### Acceptance criteria

* The user always knows whether they are looking at operational, idle, or stopped-state data.
* Changing the filter updates both chart and explanatory copy.

---

## TEL-C-06 — Add a compact evidence summary above the detailed charts

**Apply to:** **Monitoring → Telemetry → Component Detail**, between summary header and detailed visual analysis

### Requirement

Introduce a compact section that summarizes:

* number of non-normal signals
* top 3 worst signals
* average anomaly burden
* whether the component is affected by poor coverage

### Acceptance criteria

* The user gets a quick explanation before reading the detailed plots.
* Coverage issues are not hidden.

---

# 5) Cross-screen technical requirements

## X-01 — Introduce reusable chart and card primitives for Oil and Telemetry

**Apply to:** all four target tabs

### Requirement

Create shared UI primitives for:

* donut distribution card
* priority/status table wrapper
* summary header card
* AI / recommendation card
* evidence table
* empty/loading/error states

### Acceptance criteria

* Oil and Telemetry share the same spacing, status chip style, card headers, and empty-state behavior.
* Screen redesign does not require duplicating styling logic in each tab module.

---

## X-02 — Add table presets for “condition-first” sorting

**Apply to:** all tables in Oil and Telemetry

### Requirement

Each table must declare a default sort that reflects urgency:

* status severity
* priority score
* severity score
* broken evidence count
* anomaly burden

### Acceptance criteria

* No important table opens in a neutral or alphabetical state by default.
* Worst assets/components appear first.

---

## X-03 — Preserve current production architecture and callback safety

**Apply to:** all four target tabs

### Requirement

The redesign must be implemented without breaking the existing production Dash module structure and callback chain.

### Reason

The dashboard is already a production-ready, modular Dash application with dedicated tab modules, callback modules, and shared component modules.  

### Acceptance criteria

* Existing routes remain valid.
* Cross-navigation keeps working.
* New view-model logic is introduced behind existing loaders/callback wiring rather than through disruptive schema rewrites.

---

## X-04 — Respect performance constraints

**Apply to:** all four target tabs

### Requirement

UI improvements must preserve current production responsiveness and the existing optimized golden-layer loading approach.

### Reason

The implementation summary states production readiness, optimized chart rendering, and page-load expectations under 3 seconds. 

### Acceptance criteria

* No redesign introduces visibly slower first render on the target tabs.
* Heavy below-the-fold sections should be lazy-rendered where practical.
* Large tables should support paging or virtualization if needed.

---

# Final implementation intent

The redesigned interface must make each target screen answer, in this order:

1. **What is the condition of the asset?**
2. **What evidence explains that condition?**
3. **What action does AI recommend, when AI exists for that technique?**
4. **What changed over time?**

For **Oil**, AI is already part of the data product and must be surfaced directly in machine/report flows. For **Telemetry**, the current UI must focus on condition and evidence first, and only reserve space for future AI support where the production contract does not yet provide it.  

If you want, I can turn this into a **ticket-ready backlog** grouped by epics and stories.
