# Bugs

## [2026-04-20] B-001: Full suite could not import shared test fixtures
- Plan: v4.0
- Status: Fixed
- Severity: Medium
- Description: Full `pytest` collection failed when tests imported `tests.conftest`.
- Reproduction: Run `pytest` from the repository root.
- Root cause: The root `tests/` directory lacked `__init__.py`, so Python could resolve another installed `tests` package first.
- Fix: Added `tests/__init__.py`.
- Verification: `pytest` completed with 146 passed, 1 skipped.

## [2026-04-20] B-002: Resume graph contained nodes but no edges
- Plan: v4.0
- Status: Fixed
- Severity: Medium
- Description: The local graph had 32 resume-derived nodes and 0 edges because extracted facts were relationless.
- Reproduction: Query `.jobctl/jobctl.db` with `SELECT COUNT(*) FROM edges`.
- Root cause: The resume extractor populated useful text/properties but omitted `relation` and `related_to`, so persistence created standalone nodes.
- Fix: Added conservative `infer_resume_edges()` post-processing for explicit person-role-company-achievement/project/education/publication evidence and made Graph view render relationship leaves.
- Verification: Backfilled the local DB to 26 edges; `pytest` completed with 148 passed, 1 skipped.

## [2026-04-21] B-003: Resume ingestion failed on invalid OpenAI embedding model
- Plan: v4.0
- Status: Fixed
- Severity: High
- Description: Resume ingestion failed while embedding a newly persisted node.
- Reproduction: Ingest `/Users/emdim/Documents/unemployment/CV_Emile_Dimas_2026_3.pdf` with `llm.provider=openai` and `llm.embedding_model=sentence-transformers/all-MiniLM-L6-v2`.
- Root cause: The OpenAI embedding API received a local sentence-transformers model ID and returned `400 invalid model ID`; enriched persistence treated embedding failure as fatal.
- Fix: Changed local OpenAI embedding config to `text-embedding-3-small` and made resume node embedding best-effort so graph writes continue if embeddings fail.
- Verification: Retried the same resume ingestion successfully; focused tests passed.

## [2026-04-21] B-004: Resume skill graph underrepresented nested technologies
- Plan: v4.0
- Status: Fixed
- Severity: Medium
- Description: Many technologies were present only inside project/achievement properties and did not appear as first-class `skill` nodes.
- Reproduction: Inspect skill nodes after resume ingestion; nested values such as `Airflow`, `Terraform`, `MongoDB Atlas`, and `vLLM` were not consistently promoted.
- Root cause: Resume ingestion only persisted extracted top-level facts as nodes and did not scan technology-bearing property fields.
- Fix: Added `promote_resume_skill_nodes()` for technology/tool/framework/cloud/infrastructure/deployment/runtime/method properties, `used_skill` edge creation, and relation label normalization.
- Verification: Local graph now has 20 skill nodes and 31 `used_skill` edges; full `pytest` passed.

## [2026-04-21] B-005: Apply view crashed rendering validation error status
- Plan: v4.0
- Status: Fixed
- Severity: High
- Description: Launching `jobctl` could crash when ApplyView received a failed apply job lifecycle event whose message contained Pydantic text like `[type=string_type, input_value=None]`.
- Reproduction: Start an Apply workflow against a gated LinkedIn URL that yields an invalid `ExtractedJD`; restart/open the TUI while the failed job status is rendered.
- Root cause: Apply status used `Static.update(str)`, which Textual treated as Rich markup.
- Fix: Apply status now renders `rich.text.Text`, and Apply structured extraction failures include a clearer pasted-JD hint.
- Verification: Added ApplyView markup-like error test; full `pytest` passed.

## [2026-04-21] B-006: Apply pipeline failed to extract ExtractedJD
- Plan: v4.0
- Status: Fixed
- Severity: High
- Description: Apply jobs (both gated LinkedIn URLs and pasted text) failed with `5 validation errors for ExtractedJD ... Field required` or `Input should be a valid string [type=string_type, input_value=None]`.
- Reproduction: `/apply https://www.linkedin.com/jobs/...`; job moved to `failed` with a Pydantic validation traceback.
- Root cause: `apply_node._build_shim` bypassed the provider's native `chat_structured` (OpenAI structured outputs) and called `provider.chat(messages)` then tried to `json.loads` the reply, so the model returned free text or JSON with `null` fields that failed strict validation. `ExtractedJD` also rejected `null` list values emitted by noisy pages.
- Fix: Shim now delegates to `provider.chat_structured(messages, response_format=...)` when available, falling back to the JSON-parse path only for providers that don't implement it. `ExtractedJD` tolerates `None` for strings and lists via `field_validator`s. `extract_jd` raises a clear "paste the full job description" error when the page yields no usable title or company (e.g. gated pages).
- Verification: Added `tests/agent/test_apply_node_shim.py` and new `ExtractedJD` coercion / empty-page tests in `tests/test_fetcher.py`; full suite passed (167 passed, 1 skipped).

## [2026-04-21] B-007: Apply pipeline failed at resume generation (OpenAI strict schema rejected ResumeYAML)
- Plan: v4.0
- Status: Fixed
- Severity: High
- Description: After B-006, Apply jobs progressed past JD extraction but failed during resume YAML generation with `openai.BadRequestError: 400 - Invalid schema for response_format 'ResumeYAML': ... Extra required key 'sections' supplied.`
- Reproduction: Start any apply workflow on a successfully-extracted JD; job moved to `failed` at `_generate_reviewed_resume`.
- Root cause: `ResumeYAML` has optional fields and open-ended mapping types (`skills: dict[str, list[str]]`, `render.sections: dict[str, ResumeSectionConfig]`). OpenAI's strict JSON-schema mode (`client.beta.chat.completions.parse`) requires every property to be listed in `required` and does not support arbitrary-key object values, so the SDK's strict-schema transform produced an invalid schema that the API rejected. B-006's shim fix made every `chat_structured` call go through that path, so schemas that happen to be strict-incompatible now failed hard instead of silently falling back.
- Fix: `_build_shim.chat_structured` now catches non-validation exceptions from the provider's native structured path and degrades to a hinted JSON chat fallback (the schema JSON is appended as a system instruction, the reply is stripped of code fences, parsed, and validated with Pydantic). Strict-compatible schemas like `ExtractedJD` keep the fast native path; complex generation schemas (`ResumeYAML`, `CoverLetterYAML`) now succeed via fallback.
- Verification: Added shim fallback tests (`test_shim_falls_back_to_json_chat_when_provider_refuses_schema`, `test_shim_fallback_strips_markdown_code_fences`); full suite passed (169 passed, 1 skipped).
