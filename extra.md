Here is the developer-ready specification, organized by phases and written so a senior developer can turn it into backlog items immediately.

This specification assumes the dashboard must present **asset condition, supporting evidence, and AI guidance** as the primary user story. That is consistent with the oil contracts, where report-level and machine-level outputs already expose `report_status`, `essay_score`, `breached_essays`, `ai_analysis`, `ai_recommendation`, `lastReportStatus`, `avgEssayScore`, and `lastAiRecommendation`, and with the telemetry contracts, where machine and component outputs expose `overall_status`, `priority_score`, `component_details`, `total_signals_triggered`, `component_status`, `component_coverage`, `triggering_signals`, and a reserved `ai_recommendation`.  

# MultiTechnique Dashboard UX/UI Specification

## Version

Draft 1.0

## Goal

Redesign the current dashboard so that each module answers, in this order:

1. What is the condition of the asset?
2. Why is it in that condition?
3. What does AI recommend?
4. What changed over time?

## In Scope

* Oil Data

  * Fleet Overview tab
  * Report Detail tab
* Telemetry Data

  * Fleet Overview tab
  * Component Detail tab
* Shared visual system and shared reusable components
* Future-proofing for Maintenance module

## Out of Scope

* Maintenance functional module implementation
* Changes to telemetry analytical methodology
* Hourly telemetry analytics implementation
* Backend data contract changes, except minor adapter/mapping work needed by the UI

## Priority Model

* **P0**: Mandatory for the next usable release
* **P1**: High-value improvement for the next iteration after foundations are stable
* **P2**: Nice-to-have or future-proofing work

---

# Phase 1 — Shared Foundations

## Objective

Create one coherent product shell and one shared interaction language before changing individual tabs.

## PH1-01 — Shared dashboard shell

**Priority:** P0
**Applies to:** Oil / Fleet Overview, Oil / Report Detail, Telemetry / Fleet Overview, Telemetry / Component Detail

### Requirement

Implement one reusable page shell for all modules with:

* module title
* subtitle
* breadcrumb/location line
* sticky filter/action bar
* standard content width
* standard spacing scale
* standard card styling
* standard section headers

### Acceptance criteria

* All four current tabs use the same shell layout component.
* All top-level headers align to the same grid.
* Filter areas remain visible while scrolling long pages.
* Cards, sections, and charts use the same border radius, padding, and shadow tokens.

---

## PH1-02 — Shared status system

**Priority:** P0
**Applies to:** All sections / all tabs

### Requirement

Create a reusable status design system with:

* `Normal`
* `Alerta`
* `Anormal`
* `InsufficientData` for telemetry only

Oil essay-level categories must remain separate from report-level status and only appear in evidence views: `Normal`, `Marginal`, `Condenatorio`, `Critico`. Oil already distinguishes report-level status from essay-level classifications, and telemetry already distinguishes `InsufficientData` from anomalous states.  

### Acceptance criteria

* Every status label in the UI uses a shared badge/chip component.
* `InsufficientData` is rendered with neutral styling, never red or orange.
* Oil report-level status never mixes visually with essay-level thresholds in the same badge style.
* The same status color mapping is used in tables, legends, filters, and detail headers.

---

## PH1-03 — Shared chart policy

**Priority:** P0
**Applies to:** All sections / all tabs

### Requirement

Define and enforce chart standards:

* all pie-style charts must be donuts
* donut center must show total population
* category comparisons with many items must use bars, stacked bars, or heatmaps
* empty chart states must show explanatory placeholders, not blank graphs

### Acceptance criteria

* No full pie charts remain in the application.
* Telemetry Fleet Overview no longer contains a full pie; it is converted to a donut.
* Oil and telemetry donut charts show count and percentage in legend and interactive tooltip.
* No section renders an empty plot without explicit empty-state messaging.

---

## PH1-04 — Shared table policy

**Priority:** P0
**Applies to:** All sections / all tabs

### Requirement

Create one shared table behavior standard:

* sticky header
* sortable columns
* search/filter support
* row selection state
* status chip rendering
* loading / empty / error states
* action affordances for drill-down

### Acceptance criteria

* All major tables use the same interaction pattern.
* Row selection is visually persistent.
* Table headers remain visible while scrolling.
* Empty-state copy explains what filter or data condition caused the empty table.

---

## PH1-05 — Shared AI insight card

**Priority:** P0
**Applies to:** Oil / Report Detail, Telemetry / Fleet Overview, future Maintenance

### Requirement

Create one reusable AI insight component with:

* title
* diagnosis summary
* recommended action
* severity emphasis
* unavailable state
* expandable long text

This aligns with oil’s `ai_analysis` and `ai_recommendation` outputs, and telemetry’s reserved `ai_recommendation` field for later activation.  

### Acceptance criteria

* Oil Report Detail uses this shared component instead of custom text blocks.
* Telemetry Fleet Overview shows the same card with placeholder content when AI is unavailable.
* Long AI text is truncated with expand/collapse behavior.
* Unavailable AI does not render as raw placeholder text inside a generic card.

---

## PH1-06 — Shared copy and labeling rules

**Priority:** P1
**Applies to:** All sections / all tabs

### Requirement

Replace vague technical labels with user-centered labels. Preferred vocabulary:

* asset condition
* evidence
* recommended action
* change over time
* latest evaluation
* affected components
* triggering signals

### Acceptance criteria

* No primary section title is only “Analysis” or only “Score”.
* Tables and cards use labels that can be understood without backend knowledge.
* “Score” is always paired with meaning, such as “Severity score” or “Priority score”.

---

# Phase 2 — Fleet Views Redesign

## Objective

Make both fleet tabs decision-oriented and consistent.

## PH2-01 — Oil Fleet Overview first-row redesign

**Priority:** P0
**Applies to:** Oil / Fleet Overview

### Requirement

Redesign the first row into a linked pair:

* left: donut for fleet status distribution
* right: priority machine table

The donut must filter the table. The table must explain which asset needs action now, using the oil machine-level fields already available in `machine_status.parquet`, especially `lastSampleDate`, `lastReportStatus`, `alertaCount`, `anormalCount`, `avgEssayScore`, and `lastAiRecommendation`. 

### Acceptance criteria

* Clicking a donut segment filters the priority table.
* A visible filter chip shows the active segment filter.
* The table default sort is worst assets first.
* The table contains at least: unit, machine type/model, latest sample date, current status, affected history summary, latest AI recommendation snippet.

---

## PH2-02 — Oil Fleet machine detail as master-detail

**Priority:** P0
**Applies to:** Oil / Fleet Overview, Machine Component Details section

### Requirement

Replace the current dropdown-first experience with a master-detail layout:

* searchable machine selector or table selection
* selected machine summary strip
* component evidence table beneath

Use original `componentName` in detail views, since the oil contracts explicitly preserve original granularity for visibility, while `componentNameNormalized` exists for grouped analysis and thresholding. 

### Acceptance criteria

* The selected machine is always visible in a summary strip.
* The component table is sorted by worst status first.
* The component table surfaces condition-first fields before raw technical fields.
* A grouped/normalized view toggle is optional, not the default.

---

## PH2-03 — Oil Fleet component distribution redesign

**Priority:** P1
**Applies to:** Oil / Fleet Overview, Component Status Distribution section

### Requirement

Replace the current component distribution layout with a sorted stacked horizontal bar chart by component:

* Normal
* Alerta
* Anormal

Add a toggle:

* Original component granularity
* Normalized grouped component

This is justified by the oil contract distinction between `componentName` and `componentNameNormalized`. 

### Acceptance criteria

* No donut is used for this many-category component comparison.
* Components are sorted by highest abnormal/alert burden.
* The grouping toggle changes the aggregation basis without changing the visual grammar.

---

## PH2-04 — Oil Fleet quick navigation repositioning

**Priority:** P1
**Applies to:** Oil / Fleet Overview

### Requirement

Move “Quick Navigation to Report Detail” nearer to the first decision area and redesign it as:

* machine selector
* component selector
* sample selector

### Acceptance criteria

* The navigation control is discoverable without scrolling to the bottom.
* It takes at most three interactions to open a report detail page.
* It reflects current machine selection when applicable.

---

## PH2-05 — Telemetry Fleet remove KPI cards

**Priority:** P0
**Applies to:** Telemetry / Fleet Overview

### Requirement

Remove the KPI cards from the top of the page. Replace them with a single donut chart that summarizes the fleet, because the telemetry fleet status already includes `overall_status`, including `InsufficientData`, and the cards duplicate the same story. 

### Acceptance criteria

* No KPI summary cards remain at the top of Telemetry Fleet Overview.
* The fleet donut includes `InsufficientData` as a separate segment.
* Clicking a segment filters the machine table.

---

## PH2-06 — Telemetry Fleet priority table redesign

**Priority:** P0
**Applies to:** Telemetry / Fleet Overview

### Requirement

Redesign the priority table to explain telemetry condition using machine-level fields already available:

* `unit_id`
* `overall_status`
* `priority_score`
* `latest_sample_date`
* `components_anormal`
* `components_alerta`
* `components_insufficient_data`
* `total_signals_triggered`

### Acceptance criteria

* The default sort is descending by `priority_score`.
* The table shows freshness using `latest_sample_date`.
* `InsufficientData` rows are visually distinguishable from truly anomalous rows.
* The table does not prioritize low-context fields over condition and evidence.

---

## PH2-07 — Telemetry Fleet selected-machine master-detail

**Priority:** P0
**Applies to:** Telemetry / Fleet Overview

### Requirement

When the user selects a machine, render a stable detail panel below the fleet area using the `component_details` JSON as the source of truth. That JSON already contains component `status`, `score`, `coverage`, `signals_count`, and `triggering_signals`. 

### Acceptance criteria

* The selected machine row remains highlighted.
* The detail area updates without navigating away.
* The component table shows component, status, severity score, coverage, signals count, and triggering signals preview.
* A clear CTA navigates to component detail.

---

## PH2-08 — Telemetry Fleet AI card placeholder

**Priority:** P1
**Applies to:** Telemetry / Fleet Overview

### Requirement

Implement the shared AI insight card now with a telemetry placeholder state that is compatible with the reserved future `ai_recommendation` field. 

### Acceptance criteria

* The right-side AI panel no longer contains informal placeholder text.
* The component can later receive telemetry AI text without redesign.
* The placeholder state explains that AI guidance is not yet available for telemetry.

---

# Phase 3 — Detail Views Redesign

## Objective

Make both detail tabs explain diagnosis, evidence, and change over time.

## PH3-01 — Oil Report Detail sticky report identity bar

**Priority:** P0
**Applies to:** Oil / Report Detail

### Requirement

Replace the current top filter block with a sticky identity bar showing:

* client
* family / machine type
* unit
* component
* sample date
* report status

### Acceptance criteria

* The selected report identity remains visible while scrolling.
* The current report status is always visible in the identity bar.
* The user never loses context about which report is open.

---

## PH3-02 — Oil Report Detail summary card redesign

**Priority:** P0
**Applies to:** Oil / Report Detail, Sample Information section

### Requirement

Elevate condition-first report facts:

* `report_status`
* `essay_score`
* breached essays count
* previous sample date
* `daysSincePrevious`

Those fields exist in the oil silver/golden layers and should be surfaced before secondary metadata. 

### Acceptance criteria

* The summary card shows the current condition in the first visual row.
* Previous sample context is present when available.
* Breached essays are visible as chips or summarized count.

---

## PH3-03 — Oil evidence visualization redesign

**Priority:** P0
**Applies to:** Oil / Report Detail, Report Analysis section

### Requirement

Radar charts must not be the primary evidence view. Replace the first-level evidence UI with grouped threshold tables or bullet charts showing:

* essay
* current value
* essay status
* threshold bands

This is more consistent with the oil data model, where each report has essay classifications and thresholds are stored separately in Stewart limits. 

### Acceptance criteria

* The first evidence view is no longer a radar chart.
* Each essay row exposes current value and threshold context.
* Grouping by `group_element` is supported.
* Radar can remain as optional secondary visualization only.

---

## PH3-04 — Oil AI diagnosis and recommendation split

**Priority:** P0
**Applies to:** Oil / Report Detail

### Requirement

Present AI content in two explicit areas:

* diagnosis = `ai_analysis`
* recommended action = `ai_recommendation`

### Acceptance criteria

* Diagnosis and recommendation are visually distinct.
* Recommendation block receives stronger emphasis.
* Long text remains readable and collapsible.

---

## PH3-05 — Oil time-series defaults redesign

**Priority:** P1
**Applies to:** Oil / Report Detail, Time Series section

### Requirement

Improve time-series defaults so the page opens with useful content:

* preselect breached essays
* display thresholds
* highlight current sample versus previous sample
* prevent empty chart states on first render

### Acceptance criteria

* Time-series renders meaningful data on initial load when data exists.
* Breached essays are auto-selected.
* Current and previous sample are visually differentiated.

---

## PH3-06 — Oil previous-report comparison redesign

**Priority:** P1
**Applies to:** Oil / Report Detail, Comparison with Previous Reports section

### Requirement

Replace the current broad comparison layout with a prioritized delta summary:

* worsening essays
* improving essays
* status change
* largest value deltas

### Acceptance criteria

* The section answers “what changed?” in one screen without scanning multiple wide tables.
* Largest worsening items appear first.
* Status change is explicitly labeled.

---

## PH3-07 — Telemetry Component Detail summary header

**Priority:** P0
**Applies to:** Telemetry / Component Detail

### Requirement

Create a strong summary header using telemetry component fields:

* unit
* component
* `component_status`
* `component_score`
* `component_coverage`
* triggering signals count
* last evaluation week/date

### Acceptance criteria

* The selected component context is visible at all times.
* Status, severity, and coverage appear before raw technical detail.
* The header supports a future AI recommendation slot.

---

## PH3-08 — Telemetry weekly view redesign

**Priority:** P0
**Applies to:** Telemetry / Component Detail, Weekly Analysis section

### Requirement

Replace the current dense weekly visualization with:

* primary: signal-by-week heatmap
* secondary: focused trend panel for the selected signal

Use telemetry `signals_evaluation` data and baseline percentile bands where available. The telemetry contracts already define `signals_evaluation`, `triggering_signals`, `observed_range`, `anomaly_percentage`, `sample_count`, and baseline percentiles `p2`, `p5`, `p95`, `p98`. 

### Acceptance criteria

* The weekly section no longer renders a dense multi-panel layout as the default view.
* The user can identify worst signals in one scan.
* Selecting a signal updates the focus chart below.

---

## PH3-09 — Telemetry signal evaluation table redesign

**Priority:** P0
**Applies to:** Telemetry / Component Detail

### Requirement

Redesign the signal table so columns are:

* signal
* status
* anomaly percentage
* observed range
* sample count
* severity
* baseline thresholds

### Acceptance criteria

* The table is populated from `signals_evaluation`.
* Baseline context is shown in a user-readable way.
* The table selection drives the focus chart.

---

## PH3-10 — Telemetry daily analysis tied to selected signal

**Priority:** P1
**Applies to:** Telemetry / Component Detail, Daily Analysis section

### Requirement

Daily analysis must be subordinate to the active signal selection and show:

* daily distribution or time series
* threshold bands
* anomaly highlights
* date / state context

### Acceptance criteria

* Changing the selected signal updates the daily chart.
* Threshold bands are visible.
* The chart does not appear disconnected from the selected signal table row.

---

## PH3-11 — Telemetry granularity scaffold

**Priority:** P2
**Applies to:** Telemetry / Component Detail

### Requirement

Add a granularity switch with:

* Weekly
* Daily
* Hourly

Hourly may be disabled initially.

### Acceptance criteria

* The component detail layout can support future granularities without redesign.
* Disabled granularities are clearly marked as upcoming.

---

# Phase 4 — Cross-Module Polish and Future-Proofing

## Objective

Lock consistency, prepare for maintenance, and reduce long-term redesign cost.

## PH4-01 — Cross-module section naming cleanup

**Priority:** P1
**Applies to:** All sections / all tabs

### Requirement

Rename section headers to describe purpose, for example:

* Fleet requiring attention
* Why this unit is in alert
* Evidence behind current diagnosis
* AI recommended action
* Change since previous evaluation

### Acceptance criteria

* The UI reads as a guided diagnostic workflow, not a set of unrelated widgets.
* Section titles are consistent across oil and telemetry where the intent is the same.

---

## PH4-02 — Maintenance-ready information architecture

**Priority:** P2
**Applies to:** Shared architecture

### Requirement

The future Maintenance module must inherit:

* same shell
* same status chips
* same AI card
* same summary hierarchy
* same table and chart standards

### Acceptance criteria

* Shared components require no module-specific rewrite to support Maintenance.
* The architecture does not assume only oil and telemetry exist.

---

## PH4-03 — Performance and rendering cleanup

**Priority:** P1
**Applies to:** All tabs with large tables/charts

### Requirement

Implement:

* virtualization or pagination for large tables
* lazy rendering for below-the-fold sections
* memoization/caching for derived chart datasets
* controlled rerender strategy for cross-filter interactions

### Acceptance criteria

* Selecting filters or rows does not visibly freeze the page.
* Large tables remain responsive.
* Detail sections do not fully rerender unrelated components.

---

## PH4-04 — UX states completion pass

**Priority:** P1
**Applies to:** All sections / all tabs

### Requirement

Every component must support:

* loading
* empty
* partial data
* unavailable AI
* insufficient data
* hard error

### Acceptance criteria

* No blank container remains in any supported state.
* Every non-happy path tells the user what happened and what to do next.

---

# Proposed Component Map

## Core layout components

**1. `DashboardShell`**
Used by all modules.
Responsibilities:

* page width
* section spacing
* sticky header zones
* responsive layout rules

**2. `ModuleHeader`**
Used by all top-level tabs.
Props:

* title
* subtitle
* icon
* breadcrumb items

**3. `StickyContextBar`**
Used by all detail tabs and fleet tabs with active selection.
Props:

* active asset context
* current status
* key dates
* quick actions

**4. `SectionCard`**
Used for all blocks.
Responsibilities:

* title
* subtitle
* optional toolbar area
* standardized body padding

---

## Shared semantic components

**5. `StatusBadge`**
Single source for all statuses.

**6. `SeverityPill`**
For scores, threshold classes, or warning emphasis.

**7. `KeyValueSummary`**
For top-level report/machine/component identity summaries.

**8. `AIInsightCard`**
Inputs:

* diagnosis text
* recommendation text
* severity
* availability state

**9. `EmptyStatePanel`**
Reusable blank/empty/loading/error view.

---

## Shared analytical components

**10. `DonutDistributionCard`**
Used by:

* Oil Fleet Overview
* Telemetry Fleet Overview

Inputs:

* segment labels
* counts
* percentages
* total
* click callbacks

**11. `PriorityTable`**
Used by:

* Oil Fleet Overview
* Telemetry Fleet Overview

Responsibilities:

* sorting
* row click
* status rendering
* AI snippet column
* freshness column

**12. `MasterDetailPanel`**
Used by:

* Oil Fleet machine selection area
* Telemetry Fleet machine selection area

**13. `EvidenceTable`**
Used by:

* Oil report evidence
* Telemetry signal evaluation

**14. `StackedDistributionChart`**
Used by:

* Oil component distribution
* possible future maintenance distributions

**15. `TrendPanel`**
Used by:

* Oil time series
* Telemetry selected signal trend

**16. `ComparisonPanel`**
Used by:

* Oil previous report comparison
* future telemetry week-over-week comparison

**17. `SignalHeatmap`**
Used by:

* Telemetry Component Detail weekly analysis

**18. `FocusSignalChart`**
Used by:

* Telemetry Component Detail weekly/daily focused chart

---

# Data-to-UI Mapping

## Oil Fleet Overview

Primary source:

* `machine_status.parquet`

Use these fields directly in the first decision table:

* `unitId`
* `machineName`
* `machineModel`
* `lastSampleDate`
* `lastReportStatus`
* `alertaCount`
* `anormalCount`
* `avgEssayScore`
* `lastAiRecommendation` 

Secondary source:

* `classified.parquet` for deeper machine/component drill-down
* `stewart_limits.parquet` for threshold-aware component/essay explanations 

## Oil Report Detail

Primary source:

* `classified.parquet`

Use directly:

* `sampleNumber`
* `sampleDate`
* `previousSampleDate`
* `daysSincePrevious`
* `componentName`
* `componentNameNormalized`
* `breached_essays`
* `essay_score`
* `report_status`
* `ai_analysis`
* `ai_recommendation` 

Secondary source:

* `stewart_limits.parquet` for threshold presentation by essay/component grouping 

## Telemetry Fleet Overview

Primary source:

* `machine_status.parquet`

Use directly:

* `unit_id`
* `latest_sample_date`
* `overall_status`
* `priority_score`
* `components_normal`
* `components_alerta`
* `components_anormal`
* `components_insufficient_data`
* `component_details`
* `total_signals_triggered` 

## Telemetry Component Detail

Primary source:

* `classified.parquet`

Use directly:

* `component`
* `component_status`
* `component_score`
* `component_coverage`
* `signals_evaluation`
* `triggering_signals`
* `ai_recommendation`
* `baseline_version` 

Derived UI data from `signals_evaluation`:

* signal status
* anomaly percentage
* observed range
* sample count
* p2 / p5 / p95 / p98 thresholds 

---

# Delivery Sequence Recommendation

## Release A

Phase 1 + Phase 2 P0 items
This gives you a coherent product shell and fixes the highest-impact fleet-level UX problems first.

## Release B

Phase 3 P0 items
This fixes the detail tabs and makes diagnosis/evidence readable.

## Release C

Phase 2 P1 + Phase 3 P1 + Phase 4 P1
This adds polish, better comparison flows, and stronger empty/error states.

## Release D

Phase 3 P2 + Phase 4 P2
This is future-proofing for hourly telemetry and maintenance module expansion.

---

# Definition of Done

A phase is complete only when:

* all in-scope screens use shared foundation components where specified
* all acceptance criteria for that phase pass
* oil and telemetry feel like the same product, not two different dashboards
* the top of every screen communicates condition first
* AI content, when available, is presented consistently
* no chart or table remains without a clear reason for existing

If you want, I can convert this into a **Jira-ready backlog** with epic, story, and ticket breakdown.
