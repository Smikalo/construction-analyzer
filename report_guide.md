# Report Generation Guide for German Engineering Project Documentation

## Purpose

This guide defines how construction-analyzer should generate draft final reports
from civil-engineering project documentation in Germany.

The intended reader is a future engineer or coding agent implementing report
generation. After reading this guide, they should be able to choose the right
report template, extract the right evidence from MemoryPalace, preserve
appendix structure, and avoid presenting an AI-generated draft as an official
or certified engineering deliverable.

This guide is deliberately self-contained. Source names and dates are kept as
provenance labels, but the operational content from those sources is embedded
directly in the guide so a reader can work offline.

## Core Position

The generated report must be an evidence-backed draft. It can summarize,
organize, and cite project documentation, but it must not claim to be a
certified `Standsicherheitsnachweis`, `Baugrundgutachten`, `Pruefbericht`,
`Abnahmeprotokoll`, or other official deliverable unless a qualified human
engineer reviews and signs it.

For Germany, there is no single universal final-report structure that fits all
civil-engineering projects. The correct report shape depends on the project
type, document family, contract context, federal-state building law, and the
technical rules referenced by the source documents.

## German Regulatory and Technical Context

### State Building Law and Technical Building Rules

German building law is state-based. The `Landesbauordnungen` define general
requirements for buildings and construction products. The DIBt publishes the
`Muster-Verwaltungsvorschrift Technische Baubestimmungen` (`MVV TB`) on behalf
of the federal states. The MVV TB is a model technical-building-rules framework
that the states implement in state law.

Report generation must therefore avoid hard-coding one nationwide legal answer.
It should record the state or project location when available and mark any
state-specific legal applicability as requiring human verification.

Offline rule notes captured from DIBt technical-building-rules material,
checked on 2026-05-03:

- The MVV TB is a model administrative regulation for technical building
  provisions. It is not itself the final state law; the federal states adopt or
  adapt it through their own administrative rules.
- The purpose of the MVV TB is to collect technical provisions that concretize
  building-law requirements. For report generation, it should be treated as a
  technical-rule framework that may be relevant when the source documents or
  jurisdiction point to it.
- The MVV TB groups technical provisions by use case. In practical report
  terms, this means the generator should expect rules for planning, design,
  execution, construction products, construction types, and evidence of product
  usability or conformity to appear in source documents.
- DIBt publishes implementation-status information by federal state. A
  generated report should therefore capture `Bundesland` and project location
  when available, but it must not assert state-specific legal applicability
  without human verification.
- DIBt material distinguishes the model rule text from supporting technical
  annexes and lists. A report generator should record which named rule,
  appendix, list, edition, or state implementation appears in the source
  evidence instead of collapsing them into a generic "German building code"
  label.

Implementation implication: store `jurisdiction_hint`, `rule_family`,
`rule_edition`, and `source_document_mentions_rule` as separate fields. The
system may say "the source documents mention MVV TB" only when the project
evidence contains that mention. It should not infer that MVV TB is binding for
the project from Germany alone.

### Bautechnische Nachweise

Projects can require technical proofs for topics such as:

- `Standsicherheit`
- fire protection
- sound protection
- heat protection
- vibration protection

The exact requirement and review path depend on the state, project type, risk,
and technical difficulty. For example, the Bavarian ministry describes
`bautechnische Nachweise` as proof that certain technical requirements are met,
and notes that higher-risk or technically difficult projects can trigger
special authoring, review, or certification requirements.

Report generation should therefore distinguish between:

- extracted source evidence,
- a draft summary of technical proofs,
- and an actual official proof that needs qualified preparation or review.

Offline rule notes captured from Bavarian `bautechnische Nachweise` material,
checked on 2026-05-03:

- `Bautechnische Nachweise` are technical proofs showing that specific
  technical requirements are met.
- Typical proof families include `Standsicherheit`, fire protection, sound
  protection, heat protection, and vibration protection.
- In Bavaria, technical proofs are generally needed for projects that are not
  procedure-free. They are normally prepared by a person with the required
  professional entitlement.
- These proofs are not always submitted with a building application and are not
  always checked by the authority before permit issuance. In many cases they
  must be available by construction start instead.
- Higher-risk or technically difficult cases can trigger stricter authoring,
  review, or certification requirements, especially for structural safety and
  fire protection. The exact route depends on project class, risk, and state
  law.

Implementation implication: the report generator must keep three statuses
separate: `evidence_found`, `draft_summary_generated`, and
`official_proof_verified`. A report section may summarize a proof document, but
it must not state that the official proof is complete, checked, or authority-
ready unless the source evidence explicitly says so and a qualified reviewer
confirms it.

### Geotechnical Reports

For documents such as `Baugrundgutachten`, `Bodengutachten`,
`Geotechnischer Bericht`, `Bericht+Anlagen`, `Anhang`, and `Anlage`, the main
technical context is Eurocode 7. In Germany, DIN EN 1997-2 covers ground
investigation and testing, with a German National Annex.

Important implication: geotechnical report generation must preserve the
connection between the report body and its appendices. Soil parameters,
boreholes, lab results, grain-size distributions, profiles, groundwater
observations, and location plans often live in appendices rather than in the
main narrative.

Offline standard notes captured from DIN EN 1997-2 and DIN EN 1997-2/NA
metadata, checked on 2026-05-03:

- DIN EN 1997-2 is the German version of Eurocode 7 Part 2 for geotechnical
  design, focused on ground investigation and testing.
- The standard family supports the chain from exploration and testing to
  geotechnical parameters and design input. In a report-generation system, this
  means boreholes, probes, field tests, lab tests, soil profiles, groundwater
  observations, and derived soil parameters are not decorative appendices; they
  are central evidence.
- DIN EN 1997-2/NA is the German National Annex. It supplies national
  provisions for applying DIN EN 1997-2 in Germany and is used together with
  the main standard, not as a standalone substitute.
- National annex material can affect which informative annexes, laboratory test
  rules, and national choices are relevant. The generator should therefore
  extract explicitly mentioned annexes, test standards, editions, and national
  choices from source documents instead of inventing them.
- Geotechnical reports often distribute the decisive evidence across the main
  body and appendices: location plans, exploratory-point lists, borehole
  profiles, layer descriptions, lab-result tables, groundwater notes,
  grain-size distributions, and characteristic parameter tables.

Implementation implication: geotechnical report summaries must keep
`parent_report`, `appendix_label`, `appendix_topic`, `test_type`,
`location_or_borehole_id`, `parameter_name`, `value`, `unit`, and `source_page`
together. If any of those links are missing, the fact belongs in the
uncertainty section or needs a warning marker.

### HOAI Documentation and Closeout Context

If the generated report is a construction closeout or project documentation
package, HOAI may be relevant. HOAI Anlage 10 includes Leistungsphase 8
activities such as construction-process documentation, acceptance organization,
cost determination, handover, and systematic compilation of documentation,
drawings, and calculation results.

This does not mean every generated report is an HOAI deliverable. It means the
generator should support closeout-oriented sections when the source material
contains construction supervision, acceptance, handover, cost, or defect
documentation.

Offline rule notes captured from HOAI Anlage 10, checked on 2026-05-03:

- HOAI Anlage 10 describes the service profile for buildings and interiors.
  The closeout-relevant material mainly appears in Leistungsphase 8
  (`Objektueberwachung`, construction supervision and documentation).
- Leistungsphase 8 includes monitoring execution against permits, contracts,
  execution documents, technical rules, and generally accepted engineering
  practice.
- It also includes coordination of involved parties, schedule monitoring,
  construction-process documentation, joint measurements with contractors,
  invoice checking, comparison against contract sums and change orders, cost
  control, and cost determination.
- Acceptance and handover are part of this closeout context: organizing
  acceptance, identifying defects, recommending acceptance decisions, applying
  for authority acceptances when required, handing over the object, listing
  limitation periods for defect claims, and monitoring defect remedy.
- HOAI Anlage 10 also mentions systematic compilation of documentation,
  drawings, and calculation results.

Implementation implication: a closeout-style generated report should support
sections for construction process, acceptance, defects, handover, cost/status
material, and compiled final documentation. The report must still avoid saying
that an HOAI service was performed unless the source documents or user context
show that contractual role.

## Report Types to Support

The generator should select or combine templates based on the source material.
Do not force every project into one universal structure.

Recommended initial templates:

- `general_project_dossier`: broad project summary from mixed documentation.
- `geotechnical_report_summary`: soil, ground, investigation, and appendix-heavy
  evidence.
- `structural_static_summary`: statics, calculations, load assumptions, proofs,
  and plan references.
- `converted_drawing_summary`: CAD/export-derived drawing evidence, labels,
  annotations, dimensions, views, layers, and revision markers.
- `tender_offer_documentation`: requests, offers, contract documents,
  schedules, and pricing-related attachments.
- `project_closeout_documentation`: construction progress, acceptance, defects,
  handover, and compiled final documentation.

## Appendix-Aware Evidence Handling

The real project corpus contains many report-plus-appendix patterns:

- `Anhang A`, `Anhang B`, `Anhang C`
- `Anlage 1`, `Anlage 2`, `Anlage 3.1`
- `Bericht+Anlagen`
- `Geotechnischer Bericht+Anlagen`
- `Baugrundgutachten` with drilling, profile, soil-parameter, and plan
  appendices
- `Statikdokument` with construction sketches, calculations, and appendices

The generator must treat appendices as first-class evidence. It should not
summarize only the main report and ignore attachments.

For every extracted memory related to a report or appendix, prefer metadata
like:

- `document_role`: `report`, `appendix`, `attachment`, `plan`, `calculation`,
  `drawing`, `email`, `offer`, or `unknown`.
- `appendix_label`: examples: `Anhang A`, `Anhang B`, `Anlage 3.1`.
- `appendix_topic`: examples: `Bodenkennwerte`, `Bohrungen`, `Lageplan`,
  `Korngroessenverteilung`, `Pfahldiagramme`, `Fundamentdiagramme`.
- `parent_report_hint`: a nearby or naming-based hint such as
  `Bericht+Anlagen`, `Statikdokument`, or `Baugrundgutachten`.
- `project_context`: year, project folder, discipline folder, and source path.
- existing provenance fields: source file, page, sheet, cell, range, drawing
  artifact, extraction mode, confidence, and warnings.

When relationship inference is uncertain, store it as a hint with a warning.
Do not silently merge unrelated appendices into a report.

## Required Draft Report Structure

A generated German project report draft should use the following base outline.
Sections may be omitted only when the source evidence is absent, and omissions
should be listed in the uncertainty section.

### 1. Deckblatt

Include:

- project name and location, if available;
- client and involved parties, if available;
- report date and version;
- generation status, for example:
  `Automatisch generierter Entwurf zur fachlichen Pruefung`;
- clear statement that qualified review is required before official use.

### 2. Aufgabenstellung und Berichtszweck

Explain why the report was generated and what it is allowed to claim.

Examples:

- project documentation summary;
- geotechnical evidence summary;
- structural/static evidence summary;
- closeout documentation draft;
- tender or offer documentation summary.

### 3. Grundlagen und ausgewertete Unterlagen

List all source documents and group them by role:

- reports;
- appendices;
- plans and drawings;
- statics and calculations;
- spreadsheets;
- CAD/export-derived artifacts;
- correspondence;
- tender/contract documents;
- photos or image material.

Each listed source must be traceable to MemoryPalace evidence.

### 4. Projekt- und Bauwerksbeschreibung

Summarize the project, site, structure, construction method, and relevant
engineering scope. Only use facts found in the source evidence.

### 5. Normen, Regelwerke und Randbedingungen

List standards, rules, and assumptions explicitly found in source documents.
Do not invent applicable rules from project type alone.

Potential rule families and source-document mentions may include:

- Eurocodes and national annexes;
- DIN standards named in the project documents;
- MVV TB or state technical rules;
- HOAI/VOB context when the source documents show contractual or closeout
  material.

### 6. Baugrund und geotechnische Grundlagen

Use this section when the project contains geotechnical evidence.

Include, when extractable:

- investigation scope;
- boreholes, probes, or lab tests;
- soil layers and soil parameters;
- groundwater observations;
- geotechnical category if explicitly stated;
- derived design values;
- appendix references for profiles, location plans, and soil tables.

### 7. Tragwerks- und Standsicherheitsrelevante Angaben

Use this section when statics or structural evidence exists.

Include, when extractable:

- structural system;
- load assumptions;
- static calculation references;
- foundation, wall, anchor, pile, or shoring concepts;
- relevant calculation sheets;
- proof status if explicitly stated;
- warnings where the source is incomplete or not review-ready.

### 8. Plaene, Zeichnungen und CAD-Auswertungen

Include:

- drawing list;
- drawing revisions;
- plan numbers and titles;
- sections, views, layers, entities, and labels where extracted;
- dimensions and annotations;
- derived artifact paths for converted CAD/export files;
- confidence/warnings for approximate visual interpretation.

### 9. Berechnungen, Tabellen und Werte

Include extracted tabular and spreadsheet facts:

- sheet and cell references;
- formulas;
- cached/displayed values;
- units and labels;
- warnings for missing cached formula results or ambiguous units;
- table source page, sheet, or appendix.

Do not recompute engineering workbooks unless a separate verified computation
feature exists.

### 10. Ausfuehrung, Bauablauf, Abnahme und Uebergabe

Use this section for closeout-style documentation.

Include, when available:

- construction-process evidence;
- dates and schedules;
- inspection or acceptance notes;
- defects or open points;
- handover documentation;
- compiled drawings and calculation results.

### 11. Ergebnisse und Empfehlungen

Only include recommendations that are supported by the source evidence. Mark
interpretive recommendations as draft engineering interpretation requiring
human review.

### 12. Unsicherheiten, Widersprueche und fehlende Nachweise

This section is mandatory.

Include:

- missing appendices;
- unreadable scans;
- unsupported file types;
- failed conversions;
- conflicting drawing versions;
- ambiguous units;
- approximate visual readings;
- absent page/sheet/cell provenance;
- documents that require qualified human review.

### 13. Anlagenverzeichnis

List every appendix and attachment detected in the project corpus. Preserve the
original labels and topics when possible.

Each entry should include:

- label;
- title or topic;
- source file;
- parent report hint;
- extraction status;
- warnings.

### 14. Quellennachweise

Provide machine-readable citations back to the retrieved evidence. Each claim
in the generated report should be traceable to source file and location
metadata.

## Evidence Rules

The report generator must follow these rules:

- Never make unsupported engineering claims.
- Prefer exact extracted facts over inferred facts.
- Keep exact values separate from approximate or model-derived values.
- Preserve all available provenance.
- Show missing evidence explicitly.
- Treat unsupported/skipped/failed files as reportable diagnostics, not as
  invisible absence.
- Never use private project documents as committed fixtures.
- Never claim legal, regulatory, or engineering certification without human
  review.

## MemoryPalace Retrieval Requirements

Report generation should retrieve from MemoryPalace using structured intent,
not one broad query.

Recommended retrieval passes:

1. project identity and scope;
2. report and appendix inventory;
3. geotechnical evidence;
4. statics and calculations;
5. drawings and converted CAD/export evidence;
6. spreadsheet facts;
7. correspondence and tender context, if allowed;
8. failures, skipped files, and warnings;
9. conflicting or superseded documents.

The generated report should cite the specific evidence used in each section.

## Lite LLM Report Agent Inspired by GSD-2

### Embedded Research Snapshot

GSD-2 was reviewed on 2026-05-03 at inspected commit
`2d3fd6e71192e1d39816ee8a5e5011051d256257`. The notes below embed the useful
mechanics directly. A reader does not need the upstream repository to
understand what should be adapted.

GSD-2 architecture facts relevant to this project:

- It is a TypeScript CLI/runtime built around an agent engine, extensions, and
  project-management primitives.
- The runtime can operate interactively, in headless mode, or as an MCP server.
  For construction-analyzer, the equivalent should be an API-driven report
  workflow that can run from the web UI and resume later, not a shell-oriented
  coding agent.
- GSD-2 bundles extensions for workflow orchestration, browser automation, web
  search, library documentation lookup, background shell jobs, subagents,
  structured questions, remote questions, memory, GitHub sync, and local model
  access. For report generation, only the orchestration, structured questions,
  retrieval, memory, and observability ideas are relevant.
- It uses a "fresh session per unit" approach: every task/research/planning
  unit gets a clean context window with only the artifacts it needs. This is
  the key pattern to preserve for long engineering reports.
- It treats markdown files as human-readable projections. Runtime truth lives
  in structured state, normally SQLite. This prevents a half-written markdown
  file from becoming the only source of truth after a crash.
- The auto-mode dispatch pipeline derives state, determines the next unit,
  classifies complexity, selects a model, builds a focused prompt, starts a
  fresh session, waits for completion, verifies expected artifacts, records
  metrics, persists state, and repeats.
- It has explicit stuck-loop, timeout, provider-error, artifact-verification,
  and crash-recovery behavior. The report agent needs the same class of
  recovery behavior because report generation may process thousands of files.

GSD-2 data-model facts to adapt:

- A workflow engine has four core responsibilities: derive current state,
  decide the next dispatch action, reconcile state after a completed step, and
  return display metadata for progress views.
- Custom workflows use a graph of steps with statuses such as `pending`,
  `active`, `complete`, and `expanded`. Steps can depend on prior steps, and
  the next step is the first pending step whose dependencies are complete.
- Step graphs are written atomically and include timestamps. This makes the
  workflow inspectable and crash-tolerant.
- Iteration steps can expand one planned step into many concrete instances.
  The report equivalent is expanding `draft_sections` into one section-drafting
  unit per selected report section.

GSD-2 context-manifest facts to adapt:

- A `UnitContextManifest` declares what a unit may see and do before the unit
  runs.
- It separates skills catalog policy, knowledge policy, memory policy,
  preferences policy, codebase-map inclusion, tool policy, and artifact
  handling.
- Artifact keys are stable logical identifiers, not file paths. Path or record
  resolution is handled by the composer. For construction-analyzer, use stable
  evidence roles such as `source_inventory`, `appendix_index`,
  `geotechnical_evidence`, `drawing_evidence`, `section_plan`,
  `validation_findings`, and `evidence_manifest`.
- Manifest tool policies are runtime-enforced. The GSD-2 policy modes include
  unrestricted execution for implementation units, read-only mode, planning
  mode, planning-with-dispatch mode, and docs mode with explicit write globs.
  The report equivalent should enforce `planning`, `retrieval_only`,
  `draft_write`, `validation`, and `export` modes in application code.

GSD-2 structured-question facts to adapt:

- The question tool accepts one to three questions, but prefers one.
- Each question has a stable `id`, a short header, a one-sentence prompt, and
  two or three concrete options.
- Options have a short label and a sentence explaining the tradeoff.
- The recommended option is placed first when there is a defensible default.
- Single-select prompts automatically include a free-form fallback. Multi-
  select prompts allow multiple choices.
- Question calls are deduplicated by a stable signature so the same prompt is
  not sent repeatedly in one turn.
- Remote-question support can send the same structured prompt through
  channels such as Slack, Discord, or Telegram, then poll for a response and
  persist prompt status. For construction-analyzer, this suggests storing
  report questions as durable objects even if the first version only asks in
  the web UI.

GSD-2 memory facts to adapt:

- Durable memories are categorized. GSD-2 uses categories such as
  `architecture`, `convention`, `gotcha`, `preference`, `environment`, and
  `pattern`.
- Memories have confidence, source unit, scope, tags, hit counts, and optional
  structured fields.
- Query ranking combines confidence and hit count, and can combine keyword and
  semantic results.
- Background memory extraction is non-blocking, skips unsuitable unit types,
  redacts secrets, and asks for a small set of high-quality durable memories
  instead of many low-value notes.
- For construction-analyzer, report memory should not be generic model memory.
  It should be typed around report decisions, confirmed project facts,
  warnings, section artifacts, and claim-to-evidence links.

GSD-2 write-gate facts to adapt:

- Tool access is blocked by policy before the tool executes, not merely by a
  prompt instruction.
- During gated discussion, only the structured question tool may run, so the
  actual question is not buried under unrelated tool output.
- Planning mode allows broad reading but restricts writes to planning state and
  safe diagnostic commands.
- The write-gate snapshot is persisted under runtime state so gate status can
  survive restarts.
- For report generation, this means the backend should enforce write scope:
  a drafting unit may write only its own report-run artifacts, a validation
  unit may write validation findings, and no production report unit may perform
  live web search for project facts.

The important observation is that GSD-2 is not only a prompt collection. It is
a stateful agent runtime. Its useful ideas for this project are the explicit
workflow state, bounded units of work, fresh context per unit, typed context
manifests, controlled tool policies, structured user questions, verification
gates, and durable memory. The report generator should adapt those ideas to
engineering documentation instead of copying GSD-2's coding-agent workflow
directly.

### Target Shape for construction-analyzer

The report feature should be a lightweight report-composition agent that talks
with the user, retrieves evidence from MemoryPalace, and writes a cited draft.
It should not be a fully autonomous coding agent and should not execute
uncontrolled tools.

Recommended workflow:

1. `start_report_session`: create a durable report run with project id, target
   report type, language, jurisdiction hints, and output format.
2. `inventory_sources`: retrieve the project document inventory, appendices,
   failures, skipped files, and extraction warnings.
3. `clarify_scope`: ask the user only for missing decisions that materially
   change the report, such as report type, intended audience, state/project
   location, cutoff date, and whether correspondence or offers may be included.
4. `select_template`: choose one or more report templates from this guide and
   record why.
5. `plan_report`: create a section plan with required evidence families for
   each section.
6. `retrieve_evidence_by_section`: run separate MemoryPalace retrieval passes
   for each section, preserving source roles and appendix relationships.
7. `draft_sections`: draft one section at a time from retrieved evidence only.
8. `validate_sections`: check every factual claim for citation coverage and
   flag unsupported, conflicting, or approximate claims.
9. `assemble_report`: compile the reviewed sections, appendix list, source
   list, and uncertainty section.
10. `user_review_loop`: let the user request corrections, exclusions, or a new
    emphasis, then rerun only the affected sections.
11. `finalize_draft`: export the draft with clear non-certification language
    and a machine-readable evidence manifest.

Each step should have a recorded status: `pending`, `active`, `blocked`,
`complete`, or `failed`. A report run should be resumable after a crash or
server restart.

### GSD-2 Patterns to Adapt

#### 1. DB-Authoritative State

GSD-2 treats its database as the runtime source of truth and renders markdown
files as projections for humans. The report agent should use the same pattern:
the authoritative state should be structured application state, not a partially
written markdown report.

For construction-analyzer, this means storing report-session state such as:

- report run id;
- project id and selected report type;
- selected template and rationale;
- user answers and unresolved questions;
- source inventory snapshot;
- section plan;
- section draft status;
- citations used per section;
- validation findings;
- unresolved contradictions, missing files, and extraction warnings;
- final export metadata.

The generated `report.md` or PDF should be an output projection. If the user
edits or restarts the run, the system should resume from structured state and
regenerate affected projections rather than trusting the last markdown draft as
the only source of truth.

#### 2. Fresh Context Per Unit

GSD-2 creates a fresh agent session per unit of work so context does not fill
with stale reasoning. The report agent should do the same conceptually, even if
implemented as LangGraph nodes or ordinary service calls rather than separate
agent processes.

Do not ask one LLM call to read the whole project and write the final report.
Instead:

- one call classifies the reporting goal;
- one call plans sections;
- one call drafts each section;
- one call validates citations for each section;
- one call assembles the final draft from validated section outputs.

Each call should receive only the relevant evidence, user decisions, and
section contract. Prior model chatter should not be injected unless it was
converted into durable state.

#### 3. Unit Context Manifests

GSD-2's `UnitContextManifest` idea is directly useful. Each report-agent unit
should declare:

- allowed inputs;
- required MemoryPalace retrieval passes;
- citation/provenance requirements;
- maximum context budget;
- whether user answers are needed;
- allowed output artifact;
- allowed tool surface;
- validation rules.

Example manifest concept:

```yaml
unit: draft_geotechnical_section
inputs:
  - selected_template
  - user_scope_answers
  - source_inventory
retrieval:
  - geotechnical_reports
  - appendices_soil_parameters
  - appendices_boreholes
  - extraction_warnings
output:
  artifact: section_draft
  section: Baugrund und geotechnische Grundlagen
tool_policy: retrieval_only
requires_citations: true
must_include_uncertainties: true
```

This prevents the report agent from relying on vague prompts like "look at the
project and write a report." It also makes the system testable because each
unit has a clear input/output contract.

#### 4. Tool Policy and Write Gates

GSD-2 enforces tool policies instead of relying only on prompt instructions.
The report agent should have similar hard boundaries.

Recommended policy modes:

- `planning`: read project metadata, ask user questions, and write report-run
  state only.
- `retrieval_only`: query MemoryPalace and document registry, but do not write
  final report output.
- `draft_write`: write only report draft artifacts for the active report run.
- `validation`: read draft and evidence manifest, write validation findings.
- `export`: produce final draft exports only after validation passes or the
  user explicitly accepts remaining warnings.

Production report generation should not use live web search for project facts.
External web or standards research can be used during product planning and
template maintenance, but the report draft itself must be based on project
documentation stored in MemoryPalace plus explicit user answers.

#### 5. Structured User Questions

GSD-2's `ask_user_questions` tool is a strong model for this project. The
report agent should ask short structured questions at decision gates instead of
conducting an unbounded chat.

Question rules:

- ask one question when possible and never more than three at once;
- provide two or three concrete options when possible;
- include a recommended option only when the system has a defensible reason;
- always allow a free-form answer;
- persist the answer with a stable id;
- do not re-ask the same question unless the underlying context changed.

Useful report gates:

- target report type: project dossier, geotechnical summary, statics summary,
  drawing summary, closeout documentation, or tender/offer documentation;
- audience: internal engineer, client, authority reviewer, contractor, or
  archive;
- language and terminology preference: German draft, English draft, or bilingual
  outline;
- project location/federal state if missing;
- document inclusion policy for emails, offers, prices, and personal data;
- whether to include failed/skipped files in the main uncertainty section or an
  appendix;
- whether to continue when mandatory evidence is missing.

#### 6. Human-in-the-Loop Gates

GSD-2 uses discussion and approval gates before risky transitions. The report
agent should require user review at points where the system cannot safely infer
intent.

Mandatory gates:

- before selecting a report type when multiple types fit the same corpus;
- before excluding large source families such as emails, offers, appendices, or
  drawings;
- before final export when validation found unsupported claims, missing
  appendices, conflicting revisions, or failed conversions;
- before wording a conclusion as a recommendation rather than a neutral
  evidence summary.

The system may proceed without asking when the decision is reversible and low
risk, for example choosing a default citation format or section ordering from
this guide.

#### 7. Durable Memory and Decisions

GSD-2 separates durable memories, requirements, decisions, and artifacts. For
report generation, the equivalent should be a small set of durable records:

- `report_decision`: user-approved choices such as template, included document
  families, language, and audience.
- `report_memory`: reusable project-specific facts confirmed by citations, such
  as project name, location, client, structure type, and key dates.
- `report_warning`: unresolved issues such as missing appendices, unsupported
  formats, contradictory revisions, or low-confidence extraction.
- `report_section_artifact`: section drafts and validation status.
- `report_evidence_link`: claim-to-source mappings.

These records should be queryable independently of the final report text. This
lets a later user ask, "Why did the report say this?" and get the evidence
chain, not only the prose.

#### 8. Verification and Citation Gates

GSD-2 runs verification after units and retries or stops on failure. The report
agent needs analogous gates:

- every section must cite the source evidence used;
- every numeric value must include unit and source location when available;
- every appendix mentioned in the text must appear in the `Anlagenverzeichnis`;
- every high-level conclusion must be backed by at least one source citation or
  be moved to the uncertainty section;
- every failed or skipped source family must be visible in the draft;
- generated German legal/regulatory wording must be phrased as context, not
  certification;
- the final report cannot omit the uncertainty section.

If validation fails, the system should either revise the affected section or
block final export with a clear issue list.

#### 9. Crash Recovery and Observability

GSD-2 records workflow progress, journal events, metrics, and recovery context.
For report generation, this is important because real projects can have
thousands of files and long-running extraction/retrieval flows.

The report agent should record:

- current step and active section;
- retrieval queries issued;
- number of evidence chunks considered and selected;
- source families included/excluded;
- user questions asked and answered;
- validation failures and fixes;
- model used per step;
- cost/token estimate if available;
- export path and export timestamp.

This should make a stalled report run debuggable without reading private source
documents directly.

#### 10. Workflow Templates and Variants

GSD-2 supports workflow templates and custom workflows. The report agent should
use template variants rather than one universal flow.

Recommended initial variants:

- `quick_project_dossier`: broad summary with source inventory and uncertainty
  section, optimized for speed.
- `full_project_dossier`: broad summary plus separate evidence passes for every
  supported document family.
- `geotechnical_report_summary`: appendix-heavy, requires borehole/soil/lab
  retrieval passes.
- `structural_static_summary`: calculation-heavy, requires proof/status and
  drawing references.
- `closeout_documentation`: emphasizes acceptance, defects, handover, final
  drawings, and calculation-result compilation.
- `audit_only`: does not draft a report; only lists available evidence,
  missing appendices, extraction failures, and likely report templates.

Template selection should be explicit and recorded as a report decision.

### What Not to Copy from GSD-2

Do not copy GSD-2's full autonomous coding-agent machinery into report
generation. The report agent does not need git worktrees, code commits, shell
execution, broad subagent dispatch, or self-modifying project workflows.

Avoid these anti-patterns:

- a single all-powerful "final report agent" with access to every tool;
- free-form chat state as the only memory;
- regenerating the whole report for a small user correction;
- mixing source extraction, retrieval, drafting, validation, and export in one
  opaque LLM call;
- live internet research during production report drafting;
- treating GSD-style "complete" status as equivalent to engineering approval;
- presenting the generated report as signed, checked, or authority-ready.

### Recommended Minimal Architecture

Use the existing FastAPI/LangGraph backend and MemoryPalace. The first version
can be implemented without a new external orchestration framework.

Suggested components:

- `ReportSessionStore`: durable report-run state and user decisions.
- `ReportWorkflow`: LangGraph/state-machine flow for the steps listed above.
- `ReportContextManifest`: per-step declaration of required state, retrieval
  passes, allowed tools, output artifact, and validation rules.
- `ReportQuestionService`: structured user-question gate with stable ids and
  persisted answers.
- `ReportRetriever`: section-scoped MemoryPalace retrieval with appendix-aware
  filters.
- `ReportDraftWriter`: section-by-section drafting that only consumes retrieved
  evidence.
- `ReportValidator`: citation, appendix, uncertainty, and unsupported-claim
  checks.
- `ReportExporter`: Markdown/PDF/DOCX export from validated state.

The first vertical slice should not try to support every report type. A good
initial slice is:

1. create a report session for `general_project_dossier`;
2. inventory reports, appendices, drawings, calculations, spreadsheets, and
   failures from MemoryPalace/document registry;
3. ask the user for audience, language, and inclusion policy;
4. draft sections 1, 3, 12, 13, and 14 from cited evidence;
5. validate citations and mandatory uncertainty coverage;
6. export a Markdown draft.

After that works, add geotechnical and statics-specific section generation.

### Report Agent State Contract

A report run should keep enough structured state to resume and explain itself.
At minimum:

```yaml
report_run:
  id: string
  project_id: string
  status: pending|active|blocked|complete|failed
  report_type: string
  language: de|en|bilingual
  audience: string
  jurisdiction_hint: string|null
  selected_template: string
  template_rationale: string
  user_decisions: []
  source_inventory_snapshot: {}
  section_plan: []
  section_artifacts: []
  validation_findings: []
  unresolved_warnings: []
  evidence_manifest: []
  exports: []
```

The evidence manifest is mandatory. It should map report claims or paragraphs
to MemoryPalace evidence ids and original provenance such as file, page, sheet,
cell, drawing artifact, appendix label, extraction mode, confidence, and
warnings.

### Implementation Priorities from the GSD-2 Review

Apply the GSD-2 ideas in this order:

1. durable report-session state;
2. structured user-question gates;
3. section-scoped context manifests;
4. appendix-aware retrieval manifests;
5. citation validation gates;
6. partial regeneration for user corrections;
7. observability and recovery for long report runs;
8. optional remote/user notification later, only if report runs become long
   enough to justify it.

This keeps the system "lite" while preserving the qualities that make GSD-2
precise: explicit state, bounded steps, clear user gates, and verifiable
outputs.

## Implementation Notes for Future Work

Useful future tasks:

- Add appendix-aware classification during folder ingestion.
- Add parent-report hints for `Bericht+Anlagen`, `Statikdokument`,
  `Baugrundgutachten`, and similar naming patterns.
- Add durable report-session state before adding multi-section generation.
- Add structured user-question gates for report type, audience, language,
  jurisdiction hint, and inclusion policy.
- Add report context manifests so each drafting/validation unit declares its
  inputs, retrieval passes, output artifact, tool policy, and citation rules.
- Add report-template selection based on detected evidence families.
- Add a report-generation prompt that requires citations for every factual
  claim.
- Add a report validation pass that fails the draft if mandatory uncertainty,
  source-list, or appendix-list sections are missing.
- Add tests with synthetic German report/appendix names, not private project
  files.

## Non-Goals

The first report-generation feature should not attempt to:

- replace a licensed or qualified engineer;
- certify structural safety;
- certify geotechnical design;
- create an official building-authority submission;
- perform quantity takeoff or code-compliance review;
- infer missing dimensions from drawings as exact values;
- resolve legal state-specific applicability without human review.

## Reader-Test Checklist

A cold reader should be able to answer:

- Which report template should be used for a given project?
- Which German rule families may matter?
- Why appendices must be first-class evidence?
- What sections a generated draft should contain?
- Which claims require citations?
- Which parts require human engineering review?
- Which GSD-2 patterns should be adapted for the lite report agent?
- Which GSD-2 mechanisms should not be copied into report generation?
- What state must be stored so a report run can resume and explain itself?
- Where should the system ask the user instead of inferring intent?

If any answer is missing, update this guide before implementing report
generation.
