# Job Search

A one-click job-search tool for the Israeli market. It scans 120+ company career boards and the main Israeli job sites, keeps only data/analytics roles in the chosen regions, ranks every posting against the candidate's own CV, and shows the result in a local browser page that writes straight to an Excel application tracker.

## How it works

```mermaid
flowchart LR
    subgraph SRC["1 · Sources (scanned in parallel, ~7 min)"]
        direction TB
        ATS["Company ATS boards<br/>Greenhouse · Lever · Ashby · Comeet<br/>Workday · SmartRecruiters · SuccessFactors"]
        OWN["Company career sites<br/>own readers for 27 sites<br/>(Elbit, Matrix, Clalit, Max, Bezeq, ...)"]
        MKT["Whole market<br/>LinkedIn · Drushim · AllJobs<br/>JobMaster · gov.il · civil-service tenders"]
        POSTS["LinkedIn recruiting posts<br/>found through Yahoo search"]
    end

    subgraph FLT["2 · Filter"]
        direction TB
        F1["Role keywords<br/>(English + Hebrew)"]
        F2["Regions: Tel Aviv district,<br/>Jerusalem, Holon, Rishon, Modi'in"]
        F3["Posted in the last 12 days"]
        F4["Banks & insurers excluded<br/>Already-submitted jobs hidden"]
    end

    subgraph RANK["3 · Rank against the CV"]
        direction TB
        R1["Role fit<br/>from the title"]
        R2["Skill fit<br/>description vs. skills read<br/>from the master CV"]
        R3["Overall fit 0-100<br/>+ level"]
    end

    subgraph UI["4 · Browser page (local)"]
        direction TB
        U1["TOP 15"]
        U2["Deep dive<br/>filters by district, date,<br/>score, source"]
        U3["Job details<br/>skills you have / missing"]
        U4["My applications"]
    end

    XL[("applications.xlsx<br/>tracker")]

    ATS --> FLT
    OWN --> FLT
    MKT --> FLT
    POSTS --> FLT
    FLT --> RANK
    R1 --> R3
    R2 --> R3
    RANK --> UI
    UI -- "+ add / ✓ submitted" --> XL
    XL -- "submitted jobs hidden<br/>on the next scan" --> FLT
```

## Run it

Double-click `START.bat`. It starts a small local server (127.0.0.1 only, no console window), opens the page in the browser and runs a fresh scan with live progress. When the scan ends the page shows the TOP 15; the skill-fit scores fill in over the next few minutes as job descriptions are read in the background.

Requirements: Python 3.12 with `pip install -r TOOL_FILES/engine/requirements.txt`. The interpreter path is set at the top of `START.bat`.

Personal files are not in this repository: the CV (pointed to by `RESUME_INPUT` in `TOOL_FILES/.env`), the `applications.xlsx` tracker, the API key and the scan results all stay on the local machine.

## Code map

| Path | What it does |
|---|---|
| `TOOL_FILES/engine/web_app.py` + `web/index.html` | Local server and the browser page |
| `TOOL_FILES/engine/find_jobs_combined.py` | Runs all sources in parallel, merges, ranks |
| `TOOL_FILES/engine/find_jobs.py` | ATS adapters, role/location/sector filters, tracker matching |
| `TOOL_FILES/engine/company_sites*.py` | Readers for companies' own career sites |
| `TOOL_FILES/engine/market_sources.py`, `israeli_boards.py`, `extra_sources.py` | LinkedIn, Drushim, AllJobs, JobMaster, posts, government sources |
| `TOOL_FILES/engine/personalized_ranking.py` | Role fit from the job title |
| `TOOL_FILES/engine/skill_match.py` | Skill fit: posting text vs. skills found in the CV |
| `TOOL_FILES/engine/tracker.py` | The Excel tracker |
| `TOOL_FILES/engine/tailor_resume.py` | Optional: tailor the CV to one posting with the Claude API |
| `TOOL_FILES/engine/job_search_config.json` | Keywords, regions, companies, exclusions |
