# 🎯 Job Search Workflow

קובץ זה מתאר את התהליך המלא לשימוש בכלי חיפוש המקומות וכיווץ ה-CV המותאם.

---

## 📋 שלב 0: הכנה ראשונית

### קבלת קלט מהקלט:

כאשר אתה מתחיל לעבוד עם קלט חדש, אנא סדרו אותו בתבנית זו:

```
שם: [שם המועמד]
דואר אלקטרוני: [כתובת דוא"ל]
טלפון: [מספר טלפון]
מיקום: [עיר / אזור]
סוגי תפקידים: [Data Analyst, Data Scientist, Analytics Engineer, etc.]
מיקומים מעדיפים: [תל אביב, ירושלים, היברידי, וכו']
כולל remote? [כן / לא]
```

---

## 🚀 שלב 1: סריקה וחיפוש

### סריקה מלאה של כל המקורות:

**Recommended (GUI):**
```
Double-click START.bat → סורק אוטומטית (כ-10 דקות) ורק אז מציג את הרשימה
```

**Alternative (Command Line):**
```bash
python TOOL_FILES/engine/find_jobs_combined.py
```

**מה זה עושה:**
- סורק **97 חברות** בלוחות ציבוריים (Greenhouse, Lever, Ashby, Comeet, Workday, SmartRecruiters, SuccessFactors) — כולל monday, Wix, Teva, Mobileye, Fiverr, eToro
- **סורק את כל המשק** במילות מפתח: LinkedIn (משרות), **פוסטי גיוס ב-LinkedIn** (דרך חיפוש Yahoo, בלי התחברות), דרושים, AllJobs, JobMaster, **מכרזי נציבות שירות המדינה** ו-**דרושים ב-gov.il**
- לוקח **כ-10 דקות**
- לא מכוסים (נבדק 2026-10-02): אתרי קריירה עם חסימת בוטים או JS בלבד (אמדוקס, אלביט, רפאל, בזק, Max, כללית ועוד — הרשימה ב-`_not_covered` בקובץ ההגדרות), Indeed, Glassdoor, קבוצות פייסבוק/וואטסאפ
- **מסנן בנקים וחברות ביטוח** (לפי שם החברה, ולפי טקסט המשרה כשחברת השמה מסתירה את הלקוח). ביטוח לאומי, חברות האשראי ובתי ההשקעות לא מסוננים
- מסנן לפי סוגי תפקידים ומיקומים (מתוך `job_search_config.json`), כולל כותרות בעברית
- מסתיר משרות שסימנת `כן` בעמודת `הוגש?`
- כותב תוצאות ל-`jobs_found.json` (בתיקייה הראשית — שם הבורר קורא)
- מדרג את התוצאות לפי **top 15** עם ציון התאמה אישי. משרות מ-LinkedIn/דרושים מסומנות

**פלט:**
```
jobs_found.json        # כל המקומות בפורמט JSON (200+ usually)
Top 15 ranked         # המקומות התואמים ביותר (displayed in UI)
```

---

## ✏️ שלב 2: כיווץ וקישור ל-CV מותאם

### בחירת מקום עבודה ויצירת CV מותאם:

```bash
python TOOL_FILES/engine/find_jobs.py --pick <JOB_NUMBER>
```

**מה זה עושה:**
- מביא את פרסום דרושים מהרשימה ב-`jobs_found.md`
- יוצר תיקייה בתאריך: `applications/YYYY-MM-DD__<company>__<role>/`
- שומר את תאור המקום: `job_description.txt`
- **משתמש ב-Claude API לכיווץ ה-CV:**
  - קורא את ה-CV המקורי שלך
  - מתאים אותו לפרסום הספציפי
  - שומר זכרון של הישגים, מטריקות ומילות מפתח
  - יוצר `CV - Tailored.docx` ו-`CV - Tailored.pdf`

**תוצאות בתיקייה:**
```
job_description.txt        # הפרסום המלא
CV - Tailored.docx        # CV מותאם (Word)
CV - Tailored.pdf         # CV מותאם (PDF) — הזה לשלוח!
APPLY.url                 # קישור ישיר לעמוד היחוד
candidate_memory.json     # זכרון מתמשך של הישגים וכו'
```

### בחירת מספר מקומות בבת אחת:

```bash
# Pick specific jobs by number
python TOOL_FILES/engine/find_jobs.py --pick <NUM1>,<NUM2>,<NUM3>

# Or pick a range
python TOOL_FILES/engine/find_jobs.py --pick <NUM1>-<NUM2>
```

### בלי כיווץ CV (רק להורדת הפרסום):

```bash
python TOOL_FILES/engine/find_jobs.py --pick 3 --no-tailor
```

---

## 🔄 שלב 3: כיווץ ידני (Posting שלא מהלוח)

אם מצאת מקום בלינקדין, אולJobs, או כל לוח שני - הכנס אותו ידנית:

1. **עתק את הפרסום המלא** להצמדה לקובץ:
   ```
   copy → TOOL_FILES/engine/job_description.txt
   ```

2. **הרץ כיווץ ידני:**
   ```bash
   python TOOL_FILES/engine/find_jobs.py --manual
   ```

**תוצאות:**
- תיקייה חדשה: `applications/YYYY-MM-DD__manual/`
- CV מותאם + PDF מוכן

---

## 📊 שלב 4: עדכון Tracker (אופציונלי)

אם אתה רוצה לעקוב אחר ההגשות:

```bash
python TOOL_FILES/engine/find_jobs.py --pick 2 --add-tracker
```

זה יעדכן את `applications.xlsx` עם הקישור וסטטוס ההגשה.

---

## 🧠 How the Learning Works

### זכרון דעות:

כל הרצה של כיווץ CV שומרת:

- **Verified Achievements**: הישגים טובים ניתנים לשימוש חוזר (עד 30)
- **Key Metrics**: מספרים חשובים שחזרו מעבר פרסומים (עד 20)
- **Keyword Frequency**: מילות מפתח שחזרו והשכיחות שלהן
- **Phrasing Strategies**: דפוסים שעבדו טוב
- **Application History**: הדברים שהודגשו בהגשות קודמות

↳ **כתוצאה מכך:** כל הרצה של כיווץ CV משתמשת בידע מכל ההרצות הקודמות.

---

## ⚙️ Configuration

### הגדרת פילטרים:

קובץ `TOOL_FILES/engine/job_search_config.json` מכיל את כל ההגדרות למסנן החיפוש:

```json
{
  "title_keywords": ["<JOB_TYPE_1>", "<JOB_TYPE_2>", "<SKILL_1>", "<SKILL_2>"],
  "exclude_title_keywords": ["<UNWANTED_TYPE_1>", "<UNWANTED_TYPE_2>"],
  "locations": ["<LOCATION_1>", "<LOCATION_2>", "<LOCATION_3>"],
  "include_bare_remote": true|false,
  "companies": [
    {"name": "<COMPANY_NAME>", "ats": "greenhouse|lever|ashby|comeet|workday", "slug": "<COMPANY_SLUG>"},
    ...
  ]
}
```

**אזורים:**
- `locations` — רק **ירושלים, גוש דן, מודיעין** (כולל שוהם ואיירפורט סיטי). משרה שכתוב בה רק "Israel" או "Center District" לא עוברת
- `exclude_locations` — שמות שדומים ליעד ונחתכים (מודיעין עילית, אבן יהודה)

**אתרי קריירה שהסריקה לא קוראת:**
- `START.bat` → **[5]** פותח בדפדפן 36 אתרי קריירה (אמדוקס, אלביט, רפאל, בזק, Max, כללית, שיבא...). הרשימה ב-`career_sites`

**טווח זמן:**
- `max_age_days` (כרגע **12**) — משרות שפורסמו/עודכנו לפני יותר מזה נזרקות, בכל המקורות. משרות בלי תאריך (Lever) נשארות

**כל המשק / סינון ענפים:**
- `market_sources.linkedin.keywords` / `market_sources.drushim.keywords` — מילות החיפוש בכל המשק
- `exclude_companies` — ביטויים על שם החברה (כרגע: בנקים וביטוח). להוציא ענף נוסף = להוסיף שורה
- `exclude_companies_except` — חריגים שתמיד נשארים (למשל ביטוח לאומי)

**כדי להתאים לקלט חדש:**
1. ערוך `TOOL_FILES/engine/job_search_config.json`
2. הוסף את סוגי התפקידים שאתה מחפש ב-`title_keywords`
3. הוסף את המיקומים שלך ב-`locations`
4. עדכן `include_bare_remote` אם רוצה עבודה מרחוק
5. שחזר `python TOOL_FILES/engine/find_jobs.py`

---

## 🔗 Typical Workflow

### זרימה כללית (Command Line):

```bash
# 1. סריקה מלאה לפי ההגדרות בקובץ config
python TOOL_FILES/engine/find_jobs.py

# 2. צפייה בתוצאות ב-jobs_found.md
# תראה רשימה של כל המקומות התואמים

# 3. בחר מקום אחד וכווץ CV
python TOOL_FILES/engine/find_jobs.py --pick <NUM>

# או בחר מספר מקומות בבת אחת
python TOOL_FILES/engine/find_jobs.py --pick <NUM1>,<NUM2>,<NUM3>
python TOOL_FILES/engine/find_jobs.py --pick <NUM1>-<NUM2>

# 4. תיקיות יוצרות אוטומטית ב-applications/
#    כל תיקייה מכילה:
#    - CV - Tailored.docx ✅
#    - CV - Tailored.pdf  ✅
#    - job_description.txt
#    - APPLY.url

# 5. עבור מקום שמצאת בעצמך (לא מהלוח):
# - העתק את הפרסום ל-TOOL_FILES/engine/job_description.txt
# python TOOL_FILES/engine/find_jobs.py --manual
```

### זרימה דרך START.bat (GUI) - Recommended:

**מאז 2026-11-07 הכל בדפדפן** (`TOOL_FILES/engine/web_app.py` + `web/index.html`):

```
1. לחיצה כפולה על START.bat → נפתחת לשונית http://127.0.0.1:8765
2. הסריקה (~10 דק') רצה עם פס התקדמות בדף; אפשר "להציג בינתיים את הסריקה הקודמת"
3. בסיום: כל המשרות עם ציון, ממוינות. סינון לפי: חיפוש חופשי, מועד פרסום,
   אזור (גוש דן/ירושלים/מודיעין/אחר), עיר, ציון מינימלי, רק ניהול, סטטוס, מקור.
   מיון בלחיצה על כותרת עמודה. הסינונים נשמרים בין הפעלות.
4. בכל שורה: פתח | + לרשימה (שורה ב-applications.xlsx, הוגש=לא) | ✓ הוגש (הוגש=כן + תאריך)
   | הסתר (נשמר בדפדפן בלבד)
5. כפתורים למעלה: סרוק מחדש, פתח מעקב (Excel), אתרי קריירה שלא נסרקים, התאמת קו"ח ידנית
6. אין חלון שחור (pythonw). השרת נסגר לבד ~3 דק' אחרי סגירת הלשונית (אלא אם סריקה רצה). שגיאות: TOOL_FILES/engine/web_app.log
```
הבורר הישן בקונסול (`interactive_picker.py`) עדיין קיים, START.bat כבר לא קורא לו.

---

## 📁 File Structure

```
JOB_SEARCH/
├── WORKFLOW.md                      # This file
├── START.bat                        # GUI launcher (Windows)
│
├── TOOL_FILES/
│   └── engine/
│       ├── tailor_resume.py        # CV tailoring engine (Claude API)
│       ├── find_jobs.py            # Job board scanning & picking
│       ├── tracker.py              # Applications tracker
│       ├── job_search_config.json   # Configurable filters
│       │                             # (edit with your job types & locations)
│       ├── personalized_ranking.py # Optional ranking
│       └── adapters/               # Job board connectors
│           ├── greenhouse_adapter.py
│           ├── lever_adapter.py
│           ├── ashby_adapter.py
│           └── comeet_adapter.py
│
├── applications/                    # Output folder (auto-created)
│   ├── YYYY-MM-DD__<company>__<role>/
│   │   ├── CV - Tailored.docx      # Send this
│   │   ├── CV - Tailored.pdf       # Or this
│   │   ├── job_description.txt
│   │   └── APPLY.url
│   └── ...
│
├── jobs_found.json                  # All matching jobs (last scan)
├── jobs_found.md                    # Human-readable job list
├── applications.xlsx                # Tracker (auto-created on first use)
│
└── TOOL_FILES/_archive/             # Documentation & legacy code
```

---

## 🆘 Troubleshooting

### "No API key"
```
Set ANTHROPIC_API_KEY in .env
```

### "No matching roles"
- Edit `job_search_config.json`: make `title_keywords` less specific
- Try `include_bare_remote: true`

### "CV generation failed"
- Keep `job_description.txt` under 20,000 characters
- Original CV should be readable (not a scanned image)

### "Token limit hit"
- Use `--model claude-sonnet-5` (cheaper, often enough)
- Trim the job description to the essentials

---

## 🎓 Tips & Tricks

1. **First run takes time** — let it scan and learn. The second run will be faster (your learned achievements help).

2. **Keep the memory file** — `candidate_memory.json` is your learning profile. It grows smarter with each run.

3. **Batch mode is your friend** — `--pick 3,4,5` is faster than three separate runs.

4. **Check the Markdown** — always review `CV - Tailored.docx` before sending. The match report tells you what was emphasized.

5. **Manual additions** — LinkedIn jobs, AllJobs, Drushim: paste them into `job_description.txt` and use `--manual`.

---

## 🚀 Getting Started

### Quick Start (Recommended):
```
1. Double-click START.bat
2. Wait for the scan (~10 min), then see top 15 ranked jobs
3. Enter numbers: 1,3,5 (or 1-5 or single number)
4. Review links in submission_*.json
5. For each job: copy description → [3] Manual tailor
6. Tailored CV ready in applications/ folder
```

### Full Configuration Flow:

1. **Prepare Input:**
   - CV file (place in TOOL_FILES/engine/ or elsewhere)
   - List of job types you're seeking
   - Preferred locations
   - Remote work preference (yes/no)

2. **Configure:**
   - Edit `TOOL_FILES/engine/job_search_config.json`
   - Update `title_keywords` with your job types + skills
   - Update `locations` with your preferred cities
   - Set `include_bare_remote` (true/false)
   - Verify company list matches your target companies

3. **First Scan:**
   - Run: `python TOOL_FILES/engine/find_jobs_combined.py`
   - Or: Double-click `START.bat` → [1]

4. **Review & Pick:**
   - Double-click `START.bat`
   - See top 15 automatically ranked
   - Enter numbers to select
   - Saves to `submission_YYYY-MM-DD_HH-MM-SS.json`

5. **Tailor & Apply:**
   - Click each link in the submission file
   - Copy full job description
   - Use `[3] Manual tailor` to create CV
   - Review `CV - Tailored.pdf` in `applications/` folder
   - Apply via the link

---

## 📚 More Info

- **Help text:** Add `--help` to any python command
- **Configuration details:** See `TOOL_FILES/engine/job_search_config.json` comments
- **Documentation:** Check `TOOL_FILES/_archive/` for docs
- **Questions:** Review the Troubleshooting section above
