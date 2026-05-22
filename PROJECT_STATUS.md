# AI Job Scout Agent — Project Status

## Overview
Intelligent job search automation system that scrapes 5 job boards daily, evaluates each job against 6 specialized resumes using Claude AI, and presents results in a GitHub Pages dashboard for 15-minute daily review.

**GitHub Repo:** https://github.com/developerof1/AI_JobScout_Agent  
**Dashboard:** https://developerof1.github.io/AI_JobScout_Agent/ (live after first Actions run)

---

## ✅ COMPLETED — Phase 1

### Project Structure & Configuration
- [x] `.gitignore` — excludes `.env`, ephemeral data, Python cache, chromedriver
- [x] `requirements.txt` — all dependencies listed (anthropic, requests, beautifulsoup4, selenium, pdfplumber, etc.)
- [x] `.env.example` — template for API keys (placeholder format)
- [x] `config/system_config.json` — AI provider, scraping limits, scoring thresholds (70-84 review, ≥85 apply)
- [x] `config/scoring_rules.json` — keyword-based adjustments, auto-reject triggers, bonus criteria

### AI Provider Layer
- [x] `scoring/ai_provider.py` — abstraction layer supporting Anthropic (default), OpenAI, Google Gemini
  - Respects `AI_PROVIDER` and `AI_MODEL` env var overrides
  - Lazy imports SDK clients to avoid dependency bloat

### Scrapers (5 sources)
- [x] `scrapers/linkedin_scraper.py` — undetected-chromedriver stealth mode, 100 job limit
- [x] `scrapers/wellfound_scraper.py` — role + seniority filters, 50 job limit
- [x] `scrapers/builtin_scraper.py` — keyword-based search, 30 job limit
- [x] `scrapers/indeed_scraper.py` — indeed.com with date filter, 50 job limit
- [x] `scrapers/yc_jobs_scraper.py` — workatastartup.com, 25 job limit
- [x] `scrapers/scraper_orchestrator.py` — dynamic orchestrator (add/remove scraper = edit config only)
  - Reads `enabled_sources` from `system_config.json`
  - Outputs `data/jobs_raw.json`

### Deduplication & Scoring
- [x] `utils/deduplicator.py` — MD5 hash-based dedup (company|title|desc snippet), merges multi-source records
  - Input: `data/jobs_raw.json` → Output: `data/jobs_unique.json`
- [x] `utils/resume_embedder.py` — one-time setup, PDF→profile extraction via Claude
  - Reads 6 PDFs from `resumes/` folder
  - Outputs `config/resume_profiles.json`
- [x] `scoring/multi_resume_scorer.py` — multi-resume evaluation engine
  - Evaluates all 6 resumes per job in single Claude call
  - Scoring breakdown: Title(40) + Seniority(20) + Domain(20) + Experience(20) + adjustments
  - Returns: primary resume, backup resume, score 0-100, reasoning, highlights, red flags
  - Merges with existing `jobs_scored.json` (marks old jobs as not new)
  - Batch processing with configurable delay
  - Outputs `data/jobs_scored.json` (sorted by score desc, then age asc)

### Dashboard (GitHub Pages)
- [x] `dashboard/index.html` — stats bar, filter bar, three job sections (Apply Now ≥85, Review 70-84, Maybe <70)
- [x] `dashboard/styles.css` — dark theme, urgency badges (green <4h, blue <12h), score color coding, mobile responsive
- [x] `dashboard/app.js` — full app logic:
  - Loads `jobs_scored.json` once on page open (NO auto-refresh)
  - Renders job cards with score badges, primary/backup resumes, reasoning, breakdown, highlights, red flags
  - Apply button: opens job URL in new tab + copies resume filename to clipboard
  - Mark Applied: saves to localStorage, updates UI
  - Filtering: by new/today/urgent/high/applied/all
  - Stats bar with resume usage breakdown

### GitHub & CI/CD
- [x] GitHub repository created (public, for GitHub Pages)
- [x] Local git initialized and first commit pushed
- [x] `.github/workflows/daily_job_scout.yml` — 4x daily automation:
  - Cron triggers: 8 AM EST, 1 PM EST, 5 PM EST (weekdays), 9 PM EST
  - Manual dispatch via `workflow_dispatch`
  - Steps: checkout → python setup → pip install → scrape → dedup → score → commit → deploy Pages
  - Secrets: `ANTHROPIC_API_KEY`, `GITHUB_TOKEN` (auto-provided)

### Setup & Configuration
- [x] GitHub MCP server configured at `C:\Users\satwi\.claude\mcp.json` with PAT
- [x] Project permissions set at `C:\Projects\.claude\settings.json` (PowerShell(*), Bash(*) allowed)
- [x] `.env` file created with Anthropic API key (gitignored, never committed)

---

## ⏳ PENDING — Next Actions

### Immediate (Local Testing)
1. **Extract resume profiles** (one-time setup)
   ```bash
   python utils/resume_embedder.py
   ```
   - Reads 6 PDFs from `resumes/` folder
   - Creates `config/resume_profiles.json`
   - Required before scoring

2. **Scrape job boards**
   ```bash
   python scrapers/scraper_orchestrator.py
   ```
   - Outputs `data/jobs_raw.json` with jobs from all 5 sources

3. **Deduplicate jobs**
   ```bash
   python utils/deduplicator.py
   ```
   - Outputs `data/jobs_unique.json`

4. **Score jobs with Claude**
   ```bash
   python scoring/multi_resume_scorer.py
   ```
   - Outputs `data/jobs_scored.json`
   - This uses your API key and incurs costs (~$0.05-$0.20 per run depending on job count)

5. **Test dashboard locally**
   ```bash
   python -m http.server 8000
   ```
   - Open `http://localhost:8000/dashboard/`
   - Verify job cards render, scores display, apply buttons work

### Optional (Polish & Deployment)
- [ ] Commit `config/resume_profiles.json` and first `data/jobs_scored.json` to repo
- [ ] Push to GitHub to trigger first Actions run
- [ ] Verify GitHub Pages deployment and dashboard goes live
- [ ] (Future) Add email notifications via Gmail (scaffolding in `.env.example`)
- [ ] (Future) Implement Phase 2 features (e.g., cover letter generation, job comparison)

---

## Key Context

### Architecture Decisions
- **Single broad scraper + multi-resume evaluation** — each job appears once in dashboard (not 6 duplicates)
- **No auto-apply** — all apply is fully manual (apply button opens URL + copies resume filename)
- **Dashboard is static** — loads once on page open, NO polling/auto-refresh (data updates only when Actions redeploys)
- **GitHub Pages deployment** — free hosting, public repo required, Pages redeploys on every Actions commit
- **Applied jobs tracking** — localStorage + `data/applied_jobs.json` (persists across sessions)

### Resume Setup
6 specialized resumes expected in `resumes/` folder:
1. VP Product Operations
2. Head of Product
3. Senior Product Manager
4. Technical Program Manager
5. Founding Product Manager
6. Product Delivery Manager

(Names/positioning defined in `resume_embedder.py` RESUME_REGISTRY)

### Scoring Thresholds
- **≥85** → "Apply Now" (high priority, green badge)
- **70-84** → "Review & Apply" (yellow badge)
- **<70** → "Maybe" (gray badge, hidden by default)
- Auto-reject keywords (Rails, React, on-site only, etc.) skip API cost

### Cost Estimate
- Claude Sonnet 4: ~2000 tokens per job evaluation
- 100 jobs/run × 4 runs/day = 400 jobs/day
- At ~$3 per 1M input tokens: ~$0.12 per run, ~$0.50/day, ~$15/month
- (Much cheaper than Claude Pro)

---

## File Structure
```
AI_JobScout_Agent/
├── .github/workflows/daily_job_scout.yml     ✓ GitHub Actions automation
├── resumes/                                    ← User drops 6 PDFs here
├── config/
│   ├── system_config.json                     ✓ AI provider & scraping settings
│   ├── scoring_rules.json                     ✓ Keyword rules & adjustments
│   └── resume_profiles.json                   ← Generated by resume_embedder.py
├── scrapers/
│   ├── linkedin_scraper.py                    ✓ Stealth scraper
│   ├── wellfound_scraper.py                   ✓ Requests + BeautifulSoup
│   ├── builtin_scraper.py                     ✓ Requests + BeautifulSoup
│   ├── indeed_scraper.py                      ✓ Requests + BeautifulSoup
│   ├── yc_jobs_scraper.py                     ✓ Requests + BeautifulSoup
│   └── scraper_orchestrator.py                ✓ Dynamic orchestrator
├── scoring/
│   ├── ai_provider.py                         ✓ Provider abstraction
│   └── multi_resume_scorer.py                 ✓ Scoring engine
├── utils/
│   ├── resume_embedder.py                     ✓ PDF→profiles
│   └── deduplicator.py                        ✓ Dedup & merge
├── data/
│   ├── .gitkeep                               ✓
│   └── applied_jobs.json                      ✓ Applied jobs tracking
├── dashboard/
│   ├── index.html                             ✓ Main page
│   ├── styles.css                             ✓ Dark theme styling
│   └── app.js                                 ✓ Full app logic
├── .env                                       ✓ API key (gitignored)
├── .env.example                               ✓ Template
├── .gitignore                                 ✓
└── requirements.txt                           ✓
```

---

## Quick Start Checklist

- [x] Repo created and pushed
- [x] `.env` file created with API key
- [ ] 6 resume PDFs placed in `resumes/` folder
- [ ] `python utils/resume_embedder.py` completed
- [ ] `python scrapers/scraper_orchestrator.py` completed
- [ ] `python utils/deduplicator.py` completed
- [ ] `python scoring/multi_resume_scorer.py` completed
- [ ] Dashboard tested locally at `http://localhost:8000/dashboard/`
- [ ] (Optional) First run committed and pushed to GitHub

---

## Notes for Next Chat

To continue this project in a new chat:
1. Open VS Code directly in `c:\Projects\AI_JobScout_Agent` folder
2. This file (`PROJECT_STATUS.md`) summarizes all context
3. Start with the "PENDING" section above
4. Run the scripts in order as listed in "Immediate (Local Testing)"
5. All code is in place — no further implementation needed for Phase 1

**Current state:** Phase 1 complete, ready for local testing and first data run.
