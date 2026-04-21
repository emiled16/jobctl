# Resume Ingest Agent Behavior

## Purpose

Resume ingestion should do more than extract facts from a resume and append them
to the career graph. Its job is to turn an existing resume into higher-quality,
truthful graph knowledge that improves future resume generation.

The agent has two primary objectives:

1. Filter out duplicates so the graph does not accumulate repeated roles,
   skills, projects, achievements, or edges.
2. Refine extracted experience by asking targeted questions that uncover scope,
   impact, ownership, leadership, metrics, and stronger truthful positioning.

The agent should be biased toward positive career framing. It should surface the
strongest accurate interpretation of the user's experience, but it must not
invent experience, titles, metrics, team sizes, responsibilities, or outcomes.

Refinement should be available both during ingestion and later. Ingestion-time
refinement is important because the resume context is fresh and the user can
immediately clarify the most valuable gaps. Later refinement is equally
important because the user may not want to answer an interview-style sequence
while simply trying to import a resume.

## High-Level Flow

```text
Resume file selected
  -> parse resume text
  -> extract candidate facts
  -> compare candidate facts to current graph
  -> classify each fact as duplicate, update, new, ambiguous, or conflict
  -> persist safe facts and skip duplicates
  -> detect positioning and refinement opportunities
  -> ask whether the user wants to answer now or later
  -> if now, ask the highest-value follow-up questions one at a time
  -> if later, store pending questions for future refinement
  -> convert confirmed answers into graph updates
  -> use the enriched graph for future resume generation
```

The current extraction step remains useful, but extracted facts are not treated
as final writes. They are candidate facts that must be reconciled with the
existing graph first.

Ingestion should not be blocked by unanswered refinement questions. If the user
chooses to defer, safe facts are still stored, duplicates are still skipped, and
the refinement questions remain pending for a later session.

## Current Implementation Notes

The v4.0 implementation keeps the legacy `persist_facts()` function for GitHub
and older tests, and adds `ingest_resume_enriched()` for normal resume
ingestion. The enriched flow:

- extracts resume facts using the existing structured extraction prompt
- reconciles each fact with deterministic exact/fuzzy/vector candidate matching
- asks the LLM to classify only within a bounded candidate list when needed
- skips duplicates and avoids duplicate edges
- persists high-confidence new facts with `node_sources` evidence
- turns additive updates into `update_fact` Curate proposals
- stores durable `refinement_questions`
- resumes pending questions from chat with `/refine resume`

The first refinement planner is conservative and deterministic: it prioritizes
missing metrics, ownership, and technical-leadership evidence. Strong
positioning from answered refinement questions is routed to review proposals
when it requires confirmation.

## Fact Classification

Each extracted fact should be classified before persistence.

### Duplicate

The graph already represents this fact.

Expected behavior:

- Do not create a new node.
- Do not create a duplicate edge.
- Optionally attach the resume as an additional source if source tracking is
  useful.

Example:

```text
Extracted: Skill: Python
Graph already has: Skill: Python
Action: skip as duplicate
```

### Update

The graph has the same underlying experience, but the resume adds useful detail.

Expected behavior:

- Merge new factual details into the existing node.
- Preserve stronger existing detail unless the user confirms a replacement.
- Add missing properties such as dates, tools, scope, metrics, or source text.
- Re-embed the updated node after persistence.

Example:

```text
Extracted: Built Airflow pipelines for reporting.
Graph has: Project: Data Platform
Action: update Data Platform with Airflow/reporting context if matched confidently
```

### New

The fact is not represented in the graph.

Expected behavior:

- Add a new node and any high-confidence relationships.
- Prefer adding source evidence alongside the new fact.
- If the fact is vague but important, ask a refinement question before or after
  adding it.

Example:

```text
Extracted: Project: Fraud detection pipeline
Graph has no similar project
Action: add project, then ask about impact, scale, and ownership
```

### Ambiguous

The fact could match more than one existing graph node.

Expected behavior:

- Do not merge automatically.
- Ask the user to identify the right match or confirm that it is a new
  experience.

Example:

```text
Extracted: Platform modernization
Graph candidates: Internal Developer Platform, Data Platform Migration
Question: Is this the same as one of these projects, or a separate project?
```

### Conflict

The resume contradicts existing graph data.

Expected behavior:

- Do not overwrite automatically.
- Ask the user to resolve the conflict.
- Preserve both values only if they represent different contexts.

Example:

```text
Resume: Senior ML Engineer, 2022-2024
Graph: ML Engineer, 2021-2024
Question: Did your title change from ML Engineer to Senior ML Engineer in 2022?
```

## Matching Strategy

The agent should match candidate facts to graph facts in layers.

1. Normalize and compare entity type and name.
2. Search graph nodes by type and partial name.
3. Compare candidate text to existing node text and nearby connected nodes.
4. Use embeddings/vector similarity where available.
5. Ask the LLM to classify only after a small candidate set has been assembled.

The LLM should receive:

- the extracted fact
- the best matching graph candidates
- nearby graph context for those candidates
- instructions to classify conservatively

The output should be structured, not prose-only.

```json
{
  "classification": "duplicate | update | new | ambiguous | conflict",
  "confidence": 0.0,
  "matched_node_ids": [],
  "reason": "",
  "proposed_action": "",
  "requires_user_confirmation": true
}
```

## Refinement Objective

After deduplication, the agent should inspect the extracted and matched
experience for weak spots that limit future resume quality.

The agent should prioritize questions that uncover:

- measurable impact
- scale
- ownership
- leadership
- technical decision-making
- architecture responsibility
- business/customer value
- before/after state
- collaboration
- mentorship
- production or operational responsibility

The agent should ask the fewest questions that are likely to produce the most
resume value. A good default is three to five questions per ingestion session,
with more only if the user chooses to continue.

Refinement questions should be durable backlog items. A user may answer them:

- immediately after resume ingestion when the chat/UI starts a session from the
  pending question IDs
- later from a curation/refinement view
- later through chat with `/refine resume`
- opportunistically during resume generation when the graph lacks strong
  evidence for a target job

Each question should have a lifecycle:

```text
pending -> answered -> converted_to_update
pending -> skipped
pending -> dismissed
```

Skipping means "not now"; dismissing means "do not ask again unless manually
reopened."

## Positive Positioning

The agent should be intentionally biased toward strong, favorable phrasing when
the user's facts support it.

This is allowed:

```text
Raw fact:
I was responsible for leading the technical choices of the ML team.

Positioning opportunity:
This may be fairly represented as ML technical leadership or de facto ML tech
lead responsibility if confirmed.
```

The agent should respond with a positioning suggestion and ask for evidence:

```text
This sounds stronger than a generic ML engineering contribution. If you were
responsible for technical choices across the ML team, we can position this as
ML technical leadership or de facto ML tech lead experience.

Were you the main owner of ML architecture or tooling decisions? Did other
engineers follow your technical direction? Was this formal, informal, or de
facto leadership?
```

If confirmed, the graph may store:

```json
{
  "raw_evidence": "Responsible for leading technical choices of the ML team",
  "positioning": "de facto ML technical lead",
  "leadership_scope": "ML technical choices",
  "confirmation_status": "confirmed_by_user",
  "allowed_resume_phrasing": [
    "Acted as de facto ML technical lead for architecture and tooling choices",
    "Provided technical leadership for ML systems and implementation decisions"
  ]
}
```

## Guardrails

The agent must preserve factual integrity.

Allowed:

- Strengthen wording when it is supported by confirmed facts.
- Infer seniority signals from ownership, decision-making, leadership, scope,
  and impact.
- Use phrases such as "acted as", "served as", "provided technical leadership",
  or "owned technical direction" when the user confirms the behavior.
- Ask whether a stronger title-like positioning is accurate.

Needs confirmation:

- "Tech Lead"
- "Team Lead"
- "Architect"
- "Owned roadmap"
- "Led a team of N"
- "Managed"
- "Principal-level"

Not allowed without evidence:

- inventing official titles
- inventing metrics
- inventing team sizes
- inventing revenue/cost impact
- claiming people management when the user only described technical influence
- changing dates, companies, or promotions without confirmation

The distinction matters:

```text
Allowed if confirmed:
Acted as de facto ML technical lead.

Not allowed unless true:
Was officially promoted to ML Tech Lead.
```

## Refinement Question Style

Questions should be specific to the experience being refined.

Questions should be asked interactively, one at a time. The user should always
know their progress through the session.

```text
Question 1 of 5
```

When the answer space is predictable, the agent should offer multiple-choice
answers and still allow a custom free-text answer.

Example:

```text
You mention leading technical choices for the ML team. Which description is
most accurate?

1. I was the main technical decision-maker
2. I strongly influenced decisions, but final approval came from someone else
3. I contributed to decisions as part of the team
4. Other / I will explain in my own words
5. Skip for now
```

When the answer depends on domain-specific metrics or context, the agent should
ask for free text and provide examples.

Weak:

```text
Tell me more about this project.
```

Better:

```text
For the fraud detection pipeline, what scale did it operate at: number of
transactions, users, models, alerts, or daily events?
```

Better:

```text
You mention leading ML technical choices. Were you deciding architecture,
modeling approaches, tooling, deployment patterns, review standards, or all of
those?
```

Better:

```text
What changed because of this work: accuracy, latency, cost, manual review time,
deployment speed, reliability, or business adoption?
```

## Graph Update Behavior

Confirmed answers should become durable graph improvements.

Possible graph changes:

- update an existing role, project, or achievement node
- add a new achievement node with metrics
- add structured properties for scope, scale, and impact
- connect skills to projects or roles
- connect achievements to roles or projects
- add source records for resume text and user-confirmed answers
- add resume-ready phrasing that generation can use later

Example:

```text
User answer:
The pipeline processed about 20M events per day and reduced reporting delay
from 24 hours to under 2 hours.

Graph updates:
- update Project: Data Platform with event volume and reporting context
- add Achievement: Reduced reporting delay from 24 hours to under 2 hours
- add properties: events_per_day=20M, delay_before=24h, delay_after=<2h
- connect Data Platform -> achieved -> Reduced reporting delay
```

## Interaction Model

Resume ingestion should not become exhausting.

The agent should:

- summarize what it found
- skip obvious duplicates quietly
- surface only meaningful updates
- ask whether the user wants to refine now or later
- ask the highest-value refinement questions first, one at a time
- show progress through the refinement session
- allow the user to answer in free text
- offer multiple-choice answers when the answer space is predictable
- convert answers into proposed graph changes
- ask for confirmation before applying ambiguous, conflict-prone, or strongly
  positioned updates

Suggested assistant summary:

```text
I found 18 resume facts. 9 are already in the graph, 5 can enrich existing
experience, 3 look new, and 1 needs clarification.

The biggest resume-improvement opportunity is your ML leadership work. A few
answers could let me position it much more strongly.

Start refinement now?

[Start refinement] [Later] [Review graph]
```

If the user chooses later:

```text
No problem. I stored the safe facts and saved 5 refinement questions for later.
You can continue from Curate or by asking me to continue resume refinement.
```

If the user stops midway:

```text
Saved your progress. 2 answered, 3 pending.
```

## Implementation Shape

The preferred implementation is a dedicated resume enrichment flow launched by
the existing ingest node.

```text
ingest_node
  -> resume_extract_node
  -> resume_match_node
  -> resume_safe_persist_node
  -> resume_refinement_planner_node
  -> resume_refinement_offer_node
  -> resume_question_node
  -> resume_graph_update_node
```

This may be implemented as a separate LangGraph subflow or as explicit pipeline
functions behind the current background ingestion job. The important design
constraint is that extraction, reconciliation, refinement, and persistence stay
separate.

Suggested modules:

```text
src/jobctl/ingestion/resume.py          existing parsing/extraction
src/jobctl/ingestion/reconcile.py       fact matching and classification
src/jobctl/ingestion/refinement.py      question generation and positioning
src/jobctl/ingestion/enrichment.py      answer-to-graph update planning
src/jobctl/ingestion/questions.py       durable refinement question storage
```

Suggested structured objects:

```text
ExtractedFact
FactMatch
FactReconciliation
PositioningOpportunity
RefinementQuestion
GraphUpdatePlan
```

For the next implementation version, the required scope is:

- duplicate-aware resume reconciliation
- safe fact persistence after reconciliation
- ingestion-time refinement with one-question-at-a-time interaction
- durable deferral of unanswered questions for later refinement

## Success Criteria

The new behavior is successful when:

- repeated resume ingestion does not create duplicate graph nodes
- existing experiences become richer over time
- users can refine immediately during ingestion
- users can defer refinement without losing extracted facts
- deferred questions can be resumed later
- vague resume bullets turn into evidence-backed achievements
- leadership and ownership signals are detected and elevated
- strong phrasing is used only when grounded in user-confirmed facts
- generated resumes have better impact, specificity, and seniority positioning
  because the graph contains better evidence
