# jobctl -- Product Specification v1.0
## Overview
jobctl is a CLI tool with a TUI interface that acts as an AI-powered job search assistant. It learns about your professional experience through document ingestion and conversation, builds a knowledge graph of your career, and generates tailored, ATS-optimized application materials for specific job postings. It tracks all applications as a personal CRM.

## Target User
Technical users (engineers, data scientists) comfortable with the terminal.

## Core Philosophy
- Document-first onboarding -- ingest what already exists (resume, GitHub repos), then fill gaps through conversation
- Human-in-the-loop -- AI prepares everything, you review and approve before anything leaves your machine
- Preparation, not submission -- v1 generates materials; you apply manually. Automation comes later
- Grounded generation -- knowledge graph with embeddings prevents hallucination by anchoring all output in verified facts
## Tech Stack
| Component	|Technology|
| -| -|
| Language| Python|
| LLM|  GPT-5.4 via OpenAI API (Codex)|
| Embeddings|  OpenAI text-embedding-3-small or 3-large|
| TUI|  Textual|
| Knowledge Graph| SQLite (nodes/edges tables)|
| Vector Storage|  sqlite-vec (virtual table in same SQLite DB)|
| PDF Generation|  HTML/CSS template + WeasyPrint or Playwright|
| GitHub Ingestion|  PyGitHub or gitingest|
| Job Fetching| httpx with Playwright fallback|
| Resume Format| YAML (intermediate) -> HTML template -> PDF|
## Data Storage
Project-directory model (like git). Users run jobctl init to create a new job search projec
```
my-job-search/
├── .jobctl/
│   ├── config.yaml              # API keys, preferences, template choice
│   ├── jobctl.db                # SQLite: knowledge graph + vectors + tracker
│   ├── templates/
│   │   ├── resume.html          # Resume HTML/CSS template
│   │   └── cover-letter.html    # Cover letter template
│   └── exports/                 # Generated PDFs
│       └── 2026-04-16-acme-corp/
│           ├── resume.yaml      # Tailored content (reviewable)
│           ├── resume.pdf       # Rendered output
│           ├── cover-letter.yaml
│           └── cover-letter.pdf
├── .gitignore
```
## Knowledge Graph Schema
### Nodes (each with text representation + vector embedding):

- `Person` -- the user
- `Company` -- places worked
- `Role` -- titles held, with dates
- `Project` -- things built or led
- `Skill` -- technologies, methodologies, soft skills
- `Achievement` -- quantified results
- `Education` -- degrees, certifications
- `Story` -- STAR narratives, anecdotes, context
### Edges:

`worked_at`, `held_role`, `used_skill`, `led_project`, `achieved`, `studied_at`, `collaborated_on`, `reported_to`, etc.

Retrieval uses both structural graph queries (filter by type, relationship traversal) and vector similarity search (semantic matching of JD requirements against node embeddings via sqlite-vec).

## Modes of Operation
1. **Onboarding Mode (jobctl onboard)**
    1. User provides existing documents (resume file/paste, GitHub username/repo URLs)
    2. AI ingests and extracts facts into the knowledge graph
    3. AI asks targeted follow-up questions to fill gaps and add depth
    4. User confirms extracted facts before they are persisted
2. **Yap Mode (jobctl yap)**
    1. Open-ended conversation where the user talks freely about past experiences
    2. AI listens, extracts factual claims, and proposes new graph entries
    3. User confirms or rejects each proposed fact before it is persisted
    4. Captures nuance, war stories, and context that resumes typically miss
3. **Apply Mode (jobctl apply <url>)**
    1. Fetch JD from URL (httpx -> Playwright fallback -> paste fallback if both fail)
    2. LLM extracts structured requirements from JD
    3. Query knowledge graph (structural + vector similarity) for relevant experience
    4. LLM evaluates fit (score + gap analysis)
    5. LLM generates tailored resume.yaml and cover-letter.yaml if requested
    6. User reviews and edits the YAML
    7. Render to PDF via HTML template
    8. Application added to tracker
4. **Tracker Mode (jobctl track)**
    1. TUI table view of all applications
    2. Columns: company, role, status, date, fit score, comp, notes
    3. Status pipeline: evaluated -> materials_ready -> applied -> interviewing -> offer -> accepted / rejected / ghosted
    4. Drill into any application to see: original JD, tailored YAML, notes, recruiter contacts, follow-up dates, salary/comp details, timeline log
5. **Profile Mode (jobctl profile)**
    1. View and browse your knowledge graph
    2. See what the AI knows about you
    3. Manually add, edit, or delete facts
    4. Useful for sanity-checking before a round of applications
## CLI Commands
```
jobctl init                  # Initialize a new job search project
jobctl onboard               # Start onboarding (ingest docs + Q&A)
jobctl yap                   # Freeform experience capture
jobctl apply <url|paste>     # Evaluate a job + generate materials
jobctl track                 # Open tracker TUI
jobctl profile               # View/edit your knowledge graph
jobctl render <path>         # Re-render a YAML to PDF (after manual edits)
jobctl config                # Edit configuration
```
## Resume Output Requirements
The generated resume must follow ATS optimization best practices and target a high ATS compatibility score.

### Formatting
- Clean, single-column layout -- no tables, multi-column layouts, or text boxes that ATS parsers cannot read
- Standard section headings that ATS systems recognize: "Experience," "Education," "Skills," "Certifications" -- not creative alternatives
- No critical information in headers or footers (some ATS systems skip these regions)
- No images, icons, or graphics embedded in the content
- Standard fonts, consistent formatting throughout
### Content
- Keyword matching -- the LLM cross-references JD requirements against the knowledge graph and naturally incorporates relevant keywords and phrases into experience bullets. Strategic placement, not keyword stuffing.
- Quantified achievements -- the graph stores metrics (percentages, dollar amounts, team sizes, scale numbers) and the LLM prioritizes surfacing these: "Reduced deployment time by 40%" over "Improved deployment process"
- Action verb-led bullets -- each bullet starts with a strong verb (designed, led, implemented, reduced, scaled)
- Relevance ordering -- experience bullets are reordered per JD so the most relevant achievements appear first within each role
- Skills section -- extracted from the graph and filtered to match JD requirements, organized by category (languages, frameworks, tools, platforms, methodologies)
### Tailoring
- Each resume is fully customized for the specific job -- not a generic document with minor tweaks
- The LLM selects which experiences, achievements, and skills to highlight (and which to omit) based on the JD's priorities
- Role descriptions are reframed to emphasize the aspects most relevant to the target position

All of this happens at the YAML generation step, so content can be reviewed for accuracy before rendering to PDF. The HTML template handles visual formatting in a way that is both human-readable and ATS-friendly.

## Job Description Fetching Pipeline
```
User provides URL
  -> try httpx fetch (fast, lightweight)
  -> if page looks empty or JS-heavy, try Playwright fetch (headless browser)
  -> if either succeeds, LLM extracts structured JD fields:
     title, company, requirements, responsibilities,
     qualifications, compensation, location
  -> if both fail, prompt user to paste the JD text
  -> structured JD stored alongside the application in the tracker
```
## v1 Scope (MVP)
### In
- jobctl init, onboard, yap, apply, track, profile, render, config
- Resume ingestion (file or paste)
- GitHub repo ingestion (metadata + README + key files via API)
- Knowledge graph with embeddings in SQLite + sqlite-vec
- JD fetching (httpx + Playwright fallback + paste fallback)
- Fit evaluation with score and gap analysis
- Tailored, ATS-optimized resume generation (YAML -> review -> PDF)
- Cover letter generation (YAML -> review -> PDF)
- Job tracker CRM (status pipeline, JD, tailored YAML, notes, recruiter contacts, comp details, timeline)
- TUI interface via Textual
### Out (later)
- Blog / personal site ingestion
- Browser automation for application submission
- Batch processing (evaluate many jobs in parallel)
- Multiple resume templates (v1 ships with one)
- Platform-specific ATS parsers