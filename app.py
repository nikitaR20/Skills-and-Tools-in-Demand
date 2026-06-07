import streamlit as st
import pandas as pd
import asyncio
import os
import re
import random
import urllib.parse
import requests
from collections import Counter
from playwright.async_api import async_playwright
from dotenv import load_dotenv

load_dotenv()

# ============================================================
# 1. LOCAL SKILL BANK
# ============================================================
LOCAL_SKILL_BANK = [
    "Jira", "Agile", "Scrum", "Kanban", "Confluence", "DevOps",
    "HIPAA", "Data Security", "Cybersecurity", "GDPR", "SOC2",
    "Prometheus", "Grafana", "Splunk", "ELK Stack", "Datadog", "New Relic",
    "Manual Testing", "Automation Testing", "Regression Testing", "API Testing",
    "Test Case Management", "Defect Tracking", "Bug Tracking", "QA Best Practices",
    "Python", "Java", "C++", "C#", "TypeScript", "JavaScript", "Go", "Rust", "R",
    "Selenium", "Cypress", "Playwright", "Appium", "JUnit", "TestNG", "PyTest",
    "Cucumber", "Postman", "JMeter", "RestAssured",
    "AWS", "Azure", "GCP", "Docker", "Kubernetes", "Jenkins", "Git", "Terraform", "Linux",
    "SQL", "MySQL", "PostgreSQL", "MongoDB", "Redis", "Oracle", "Snowflake",
    "PowerBI", "Tableau", "Spark", "Kafka",
    "React", "Angular", "Vue", "Node.js", "Django", "FastAPI", "Spring Boot",
    "Machine Learning", "Deep Learning", "TensorFlow", "PyTorch",
    "Communication", "Leadership", "Problem Solving", "Teamwork",
]


def extract_skills_locally(job_text):
    found, text_lower = [], job_text.lower()
    for skill in LOCAL_SKILL_BANK:
        if re.search(rf"\b{re.escape(skill.lower())}\b", text_lower):
            found.append(skill)
    return found[:8] if found else ["General Requirements"]


# ============================================================
# 2. AI SKILL EXTRACTOR  (Groq → local bank fallback)
# ============================================================
def extract_skills_with_ai(job_text, status_widget=None):
    if not job_text or "requires expertise in" in job_text.lower():
        return ["General Requirements"]
    groq_token = os.getenv("GROQ_API_KEY", "")
    if not groq_token:
        return extract_skills_locally(job_text)
    try:
        response = requests.post(
            "https://api.groq.com/openai/v1/chat/completions",
            headers={"Authorization": f"Bearer {groq_token}",
                     "Content-Type": "application/json"},
            json={
                "model": "llama3-8b-8192",
                "messages": [
                    {
                        "role": "system",
                        "content": (
                            "You are a technical recruiting AI. Extract up to 8 key skills, tools, "
                            "frameworks, or compliance requirements from the job description. "
                            "Return ONLY a comma-separated list — no markdown, no numbering."
                        )
                    },
                    {"role": "user", "content": job_text.strip()[:4000]}
                ],
                "temperature": 0.1, "max_tokens": 200
            },
            timeout=10
        )
        if response.status_code == 200:
            raw = response.json()["choices"][0]["message"]["content"]
            return [s.strip() for s in raw.split(",") if s.strip()][:8]
        if response.status_code == 429:
            if status_widget:
                status_widget.warning(
                    "⚠️ Groq rate limited — using local skill bank...")
        return extract_skills_locally(job_text)
    except Exception:
        return extract_skills_locally(job_text)


# ============================================================
# 3. ANTI-BOT BROWSER SETUP
#    Hides the "I am a bot" signals that sites look for.
# ============================================================
STEALTH_SCRIPT = """
    Object.defineProperty(navigator, 'webdriver',   { get: () => undefined });
    Object.defineProperty(navigator, 'plugins',     { get: () => [1, 2, 3, 4, 5] });
    Object.defineProperty(navigator, 'languages',   { get: () => ['en-US', 'en'] });
    Object.defineProperty(navigator, 'platform',    { get: () => 'Win32' });
    window.chrome = { runtime: {}, loadTimes: () => {}, csi: () => {}, app: {} };
"""

BROWSER_ARGS = [
    "--no-sandbox",
    "--disable-blink-features=AutomationControlled",
    "--disable-dev-shm-usage",
    "--disable-infobars",
    "--disable-extensions",
    "--start-maximized",
]

USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/124.0.0.0 Safari/537.36"
)


async def new_stealth_page(playwright):
    """Launch a browser + context that looks like a real human visitor."""
    browser = await playwright.chromium.launch(headless=True, args=BROWSER_ARGS)
    context = await browser.new_context(
        user_agent=USER_AGENT,
        viewport={"width": 1280, "height": 900},
        locale="en-US",
        timezone_id="America/New_York",
        extra_http_headers={
            "Accept-Language": "en-US,en;q=0.9",
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8",
        }
    )
    await context.add_init_script(STEALTH_SCRIPT)
    page = await context.new_page()
    return browser, context, page


async def human_scroll(page, scrolls=12):
    """Scroll the page with small random pauses — looks more human."""
    for _ in range(scrolls):
        await page.mouse.wheel(0, random.randint(600, 2500))
        await asyncio.sleep(random.uniform(0.4, 1.3))


# ============================================================
# 4. DESCRIPTION SCRAPER
# ============================================================
DESCRIPTION_SELECTORS = {
    "LinkedIn":     [".show-more-less-html__markup", ".description__text"],
    "Indeed":       ["#jobDescriptionText", ".jobsearch-jobDescriptionText"],
    "Glassdoor":    ["[data-test='jobDescriptionContent']", ".jobDescriptionContent"],
    "Dice":         [".job-description", "#jobdescSec", "[data-testid='jobDescription']"],
    "ZipRecruiter": ["[data-testid='job-description']", "#job_description"],
    "Wellfound":    ["[class*='description']", "main p"],
    "JobRight.ai":  ["[class*='description']", ".job-details", "main"],
}


async def scrape_description(page, url, platform, fallback_role):
    """Open a job link and extract the full description text."""
    try:
        await page.goto(url, wait_until="domcontentloaded", timeout=15000)
        await asyncio.sleep(random.uniform(1, 2))
        for sel in DESCRIPTION_SELECTORS.get(platform, ["[class*='description']"]):
            try:
                await page.wait_for_selector(sel, timeout=2500)
                text = await page.locator(sel).first.inner_text()
                if text and len(text) > 80:
                    return text.strip()
            except Exception:
                continue
        body = await page.locator("body").inner_text()
        return body[:3000].strip() if body else f"Requires expertise in {fallback_role}"
    except Exception:
        return f"Requires expertise in {fallback_role}"


# ============================================================
# 5. PLATFORM SCRAPERS
# ============================================================

# ── LinkedIn ──────────────────────────────────────────────
async def fetch_linkedin_jobs(query, max_jobs):
    url = (
        f"https://www.linkedin.com/jobs/search/"
        f"?keywords={urllib.parse.quote(query)}&sortBy=DD&f_TPR=r604800&start=0"
    )
    results = []
    async with async_playwright() as p:
        browser, context, page = await new_stealth_page(p)
        try:
            await page.goto(url, wait_until="domcontentloaded", timeout=15000)
            await page.wait_for_selector(".jobs-search__results-list", timeout=10000)

            prev_count = 0
            for attempt in range(60):                          # up from 15 → 60
                await human_scroll(page, scrolls=3)

                # Click "See more jobs" / "Load more" buttons when they appear
                for btn_text in ["See more jobs", "Show more results", "Load more"]:
                    try:
                        btn = page.locator(f"button:has-text('{btn_text}')")
                        if await btn.is_visible(timeout=600):
                            await btn.click()
                            await asyncio.sleep(1.5)
                    except Exception:
                        pass

                current_count = await page.locator(".jobs-search__results-list > li").count()
                if current_count >= max_jobs * 2:
                    break
                if current_count == prev_count:               # no new jobs loaded
                    break
                prev_count = current_count

            for card in await page.locator(".jobs-search__results-list > li").all():
                try:
                    title_el = card.locator(".base-search-card__title")
                    company_el = card.locator(".base-search-card__subtitle")
                    link_el = card.locator("a.base-card__full-link")
                    date_el = card.locator("time")
                    if await title_el.count() > 0 and await link_el.count() > 0:
                        results.append({
                            "role":        (await title_el.inner_text()).strip(),
                            "company":     (await company_el.inner_text()).strip() if await company_el.count() > 0 else "Unknown",
                            "link":        (await link_el.get_attribute("href") or "").split("?")[0],
                            "date_posted": (await date_el.inner_text()).strip() if await date_el.count() > 0 else "Recent",
                            "platform":    "LinkedIn",
                        })
                except Exception:
                    continue
        except Exception:
            pass
        finally:
            await browser.close()
    return results


# ── Indeed ────────────────────────────────────────────────
async def fetch_indeed_jobs(query, max_jobs):
    url = f"https://www.indeed.com/jobs?q={urllib.parse.quote(query)}&sort=date&limit=50"
    results = []
    async with async_playwright() as p:
        browser, context, page = await new_stealth_page(p)
        try:
            await page.goto(url, wait_until="domcontentloaded", timeout=15000)
            await asyncio.sleep(2)
            await page.wait_for_selector(".job_seen_beacon, [data-testid='slider_item']", timeout=10000)
            await human_scroll(page, scrolls=10)

            card_sel = ".job_seen_beacon" if await page.locator(".job_seen_beacon").count() > 0 else "[data-testid='slider_item']"
            for card in await page.locator(card_sel).all():
                try:
                    title_el = card.locator(
                        "h2.jobTitle a, [data-testid='jobsearch-JobInfoHeader-title']")
                    company_el = card.locator(
                        "[data-testid='company-name'], .companyName")
                    date_el = card.locator(
                        "[data-testid='myJobsStateDate'], .date")
                    if await title_el.count() > 0:
                        href = await title_el.first.get_attribute("href") or ""
                        link = f"https://www.indeed.com{href}" if href.startswith(
                            "/") else href
                        results.append({
                            "role":        (await title_el.first.inner_text()).strip(),
                            "company":     (await company_el.first.inner_text()).strip() if await company_el.count() > 0 else "Unknown",
                            "link":        link.split("?")[0],
                            "date_posted": (await date_el.first.inner_text()).strip() if await date_el.count() > 0 else "Recent",
                            "platform":    "Indeed",
                        })
                except Exception:
                    continue
        except Exception:
            pass
        finally:
            await browser.close()
    return results


# ── Glassdoor ─────────────────────────────────────────────
async def fetch_glassdoor_jobs(query, max_jobs):
    url = f"https://www.glassdoor.com/Job/jobs.htm?sc.keyword={urllib.parse.quote(query)}"
    results = []
    async with async_playwright() as p:
        browser, context, page = await new_stealth_page(p)
        try:
            await page.goto(url, wait_until="domcontentloaded", timeout=15000)
            await asyncio.sleep(3)
            await page.wait_for_selector("[data-test='jobListing'], li[class*='JobsList']", timeout=10000)
            await human_scroll(page, scrolls=8)

            card_sel = "[data-test='jobListing']" if await page.locator("[data-test='jobListing']").count() > 0 else "li[class*='JobsList']"
            for card in await page.locator(card_sel).all():
                try:
                    title_el = card.locator(
                        "[data-test='job-title'], a[class*='JobCard_jobTitle']")
                    company_el = card.locator(
                        "[data-test='employer-name'], span[class*='EmployerProfile']")

                    # Grab the description snippet — visible on the card without login
                    snippet_el = card.locator(
                        "[data-test='job-snippet'], [class*='jobDescriptionSnippet'], "
                        "[class*='JobCard_jobDescriptionSnippet'], p[class*='desc'], "
                        "[class*='description']"
                    )
                    snippet = (await snippet_el.first.inner_text()).strip() if await snippet_el.count() > 0 else ""

                    if await title_el.count() > 0:
                        href = await title_el.first.get_attribute("href") or ""
                        link = f"https://www.glassdoor.com{href}" if href.startswith(
                            "/") else href
                        results.append({
                            "role":               (await title_el.first.inner_text()).strip(),
                            "company":            (await company_el.first.inner_text()).strip() if await company_el.count() > 0 else "Unknown",
                            "link":               link,
                            "date_posted":        "Recent",
                            "platform":           "Glassdoor",
                            "description_preview": snippet,   # used instead of visiting the login-walled page
                        })
                except Exception:
                    continue
        except Exception:
            pass
        finally:
            await browser.close()
    return results


# ── Dice ──────────────────────────────────────────────────
async def fetch_dice_jobs(query, max_jobs):
    url = f"https://www.dice.com/jobs?q={urllib.parse.quote(query)}&countryCode=US"
    results = []
    async with async_playwright() as p:
        browser, context, page = await new_stealth_page(p)
        try:
            await page.goto(url, wait_until="networkidle", timeout=20000)
            await asyncio.sleep(3)
            await page.wait_for_selector("dhi-search-card, [data-cy='search-card']", timeout=10000)
            await human_scroll(page, scrolls=8)

            card_sel = "dhi-search-card" if await page.locator("dhi-search-card").count() > 0 else "[data-cy='search-card']"
            for card in await page.locator(card_sel).all():
                try:
                    title_el = card.locator(
                        "a.card-title-link, [data-cy='card-title-link']")
                    company_el = card.locator(
                        "a.card-company, [data-cy='card-company-name']")
                    if await title_el.count() > 0:
                        href = await title_el.first.get_attribute("href") or ""
                        link = f"https://www.dice.com{href}" if href.startswith(
                            "/") else href
                        results.append({
                            "role":        (await title_el.first.inner_text()).strip(),
                            "company":     (await company_el.first.inner_text()).strip() if await company_el.count() > 0 else "Unknown",
                            "link":        link,
                            "date_posted": "Recent",
                            "platform":    "Dice",
                        })
                except Exception:
                    continue
        except Exception:
            pass
        finally:
            await browser.close()
    return results


# ── ZipRecruiter ──────────────────────────────────────────
async def fetch_ziprecruiter_jobs(query, max_jobs):
    url = f"https://www.ziprecruiter.com/Jobs/{urllib.parse.quote(query.replace(' ', '-'))}"
    results = []
    async with async_playwright() as p:
        browser, context, page = await new_stealth_page(p)
        try:
            await page.goto(url, wait_until="domcontentloaded", timeout=15000)
            await asyncio.sleep(3)
            await page.wait_for_selector("article, [class*='job_result']", timeout=10000)
            await human_scroll(page, scrolls=8)

            for card in await page.locator("article").all():
                try:
                    title_el = card.locator("h2 a, [class*='title'] a")
                    company_el = card.locator(
                        "[class*='company'], [data-testid*='company'], [class*='t_org']")
                    if await title_el.count() > 0:
                        href = await title_el.first.get_attribute("href") or ""
                        results.append({
                            "role":        (await title_el.first.inner_text()).strip(),
                            "company":     (await company_el.first.inner_text()).strip() if await company_el.count() > 0 else "Unknown",
                            "link":        href,
                            "date_posted": "Recent",
                            "platform":    "ZipRecruiter",
                        })
                except Exception:
                    continue
        except Exception:
            pass
        finally:
            await browser.close()
    return results


# ── Wellfound ─────────────────────────────────────────────
async def fetch_wellfound_jobs(query, max_jobs):
    url = f"https://wellfound.com/jobs?q={urllib.parse.quote(query)}"
    results = []
    async with async_playwright() as p:
        browser, context, page = await new_stealth_page(p)
        try:
            await page.goto(url, wait_until="networkidle", timeout=20000)
            await asyncio.sleep(4)
            await human_scroll(page, scrolls=10)

            card_sel = "[data-test='startup-result'], [class*='JobCard'], [class*='styles_result']"
            for card in await page.locator(card_sel).all():
                try:
                    title_el = card.locator(
                        "[data-test='job-title'], a[class*='title'], a[class*='job']")
                    company_el = card.locator(
                        "[data-test='startup-link'], a[class*='company'], a[class*='startup']")
                    if await title_el.count() > 0:
                        href = await title_el.first.get_attribute("href") or ""
                        link = f"https://wellfound.com{href}" if href.startswith(
                            "/") else href
                        results.append({
                            "role":        (await title_el.first.inner_text()).strip(),
                            "company":     (await company_el.first.inner_text()).strip() if await company_el.count() > 0 else "Unknown",
                            "link":        link,
                            "date_posted": "Recent",
                            "platform":    "Wellfound",
                        })
                except Exception:
                    continue
        except Exception:
            pass
        finally:
            await browser.close()
    return results


# ── JobRight.ai ───────────────────────────────────────────
async def fetch_jobright_jobs(query, max_jobs):
    url = f"https://jobright.ai/jobs?q={urllib.parse.quote(query)}"
    results = []
    async with async_playwright() as p:
        browser, context, page = await new_stealth_page(p)
        try:
            await page.goto(url, wait_until="networkidle", timeout=20000)
            await asyncio.sleep(4)
            await human_scroll(page, scrolls=10)

            card_sel = "[class*='JobCard'], [class*='job-card'], li[class*='job']"
            for card in await page.locator(card_sel).all():
                try:
                    title_el = card.locator(
                        "a[class*='title'], h3 a, h2 a, [class*='job-title'] a")
                    company_el = card.locator(
                        "[class*='company'], [class*='employer']")
                    if await title_el.count() > 0:
                        href = await title_el.first.get_attribute("href") or ""
                        link = f"https://jobright.ai{href}" if href.startswith(
                            "/") else href
                        results.append({
                            "role":        (await title_el.first.inner_text()).strip(),
                            "company":     (await company_el.first.inner_text()).strip() if await company_el.count() > 0 else "Unknown",
                            "link":        link,
                            "date_posted": "Recent",
                            "platform":    "JobRight.ai",
                        })
                except Exception:
                    continue
        except Exception:
            pass
        finally:
            await browser.close()
    return results


PLATFORM_SCRAPERS = {
    "LinkedIn":    fetch_linkedin_jobs,
    "Indeed":      fetch_indeed_jobs,
    "Glassdoor":   fetch_glassdoor_jobs,
    "Dice":        fetch_dice_jobs,
    "ZipRecruiter": fetch_ziprecruiter_jobs,
    "Wellfound":   fetch_wellfound_jobs,
    "JobRight.ai": fetch_jobright_jobs,
}


# ============================================================
# 6. MAIN PIPELINE
# ============================================================
async def main_pipeline(search_role, company_input, max_jobs, selected_platforms, ui_progress, ui_status):
    companies = [c.strip() for c in company_input.split(",") if c.strip()]
    jobs_per_platform = max(8, max_jobs // max(len(selected_platforms), 1))
    all_raw = []
    platform_summary = {}                 # track results per platform

    total_platforms = len(selected_platforms)

    # ── Phase 1: scrape ──────────────────────────────────────
    for idx, platform in enumerate(selected_platforms, 1):
        ui_status.info(f"📡 [{idx}/{total_platforms}] Searching {platform}…")
        ui_progress.progress(idx / (total_platforms + 1))
        scraper = PLATFORM_SCRAPERS.get(platform)
        if not scraper:
            continue
        try:
            if companies:
                res = []
                for company in companies:
                    res.extend(await scraper(f"{search_role} {company}", jobs_per_platform))
            else:
                res = await scraper(search_role, jobs_per_platform)
            platform_summary[platform] = len(res)
            all_raw.extend(res)
            ui_status.info(f"✅ {platform}: found {len(res)} listings")
        except Exception as e:
            platform_summary[platform] = 0
            ui_status.warning(f"⚠️ {platform} failed: {str(e)[:60]}")

    # ── Deduplicate + company filter ─────────────────────────
    seen, job_listings = set(), []
    for job in all_raw:
        if not job.get("link") or job["link"] in seen:
            continue
        if companies:
            norm = [c.lower() for c in companies]
            if not any(t in job["company"].lower() for t in norm):
                continue
        seen.add(job["link"])
        job_listings.append(job)

    job_listings = job_listings[:max_jobs]

    if not job_listings:
        st.error(
            "❌ No jobs found across any platform. Try different search terms or fewer filters.")
        return

    # ── Phase 2: extract skills ──────────────────────────────
    all_skills, processed = [], []
    total = len(job_listings)
    ui_status.info(f"🧠 Phase 2: Reading {total} job descriptions…")

    async with async_playwright() as p:
        browser, context, page = await new_stealth_page(p)
        try:
            for i, job in enumerate(job_listings, 1):
                pct = (total_platforms + i) / (total_platforms + total + 1)
                ui_progress.progress(pct)
                ui_status.text(
                    f"[{i}/{total}] {job['platform']} — {job['company']}: {job['role']}")

                # Glassdoor hides full descriptions behind a login wall.
                # Use the snippet captured from the search results page instead.
                preview = job.get("description_preview", "")
                if job["platform"] == "Glassdoor" and len(preview) > 60:
                    desc = preview
                else:
                    desc = await scrape_description(page, job["link"], job["platform"], job["role"])
                    # If full page scrape still failed, fall back to snippet
                    if (not desc or "requires expertise in" in desc.lower()) and len(preview) > 30:
                        desc = preview

                skills = extract_skills_with_ai(desc, ui_status)
                all_skills.extend(skills)
                job["extracted_skills"] = ", ".join(
                    skills) if skills else "General Requirements"
                processed.append(job)
        finally:
            await browser.close()

    ui_progress.progress(1.0)

    # ── Save to Excel ────────────────────────────────────────
    df_jobs = pd.DataFrame(processed)
    skill_counts = Counter(all_skills)
    df_skills = (
        pd.DataFrame(skill_counts.items(), columns=[
                     "Skill/Tool", "Demand Count"])
        .sort_values("Demand Count", ascending=False)
        .reset_index(drop=True)
    )
    df_platforms = pd.DataFrame([
        {"Platform": p, "Jobs Found": platform_summary.get(p, 0),
         "Status": "✅ OK" if platform_summary.get(p, 0) > 0 else "⚠️ No results"}
        for p in selected_platforms
    ])

    with pd.ExcelWriter("job_market_analysis.xlsx", engine="openpyxl") as writer:
        df_jobs.to_excel(
            writer, sheet_name="Job Listings",         index=False)
        df_skills.to_excel(
            writer, sheet_name="Skill Demand Metrics", index=False)
        df_platforms.to_excel(
            writer, sheet_name="Platform Summary",    index=False)

    ui_status.success(
        f"✅ Done — {len(processed)} jobs analysed across {len(selected_platforms)} platforms.")


# ============================================================
# 7. STREAMLIT DASHBOARD
# ============================================================
st.set_page_config(page_title="Job Market Skill Analyzer",
                   page_icon="🎯", layout="wide")
st.title("🎯 Job Market Skill Demand Analyzer")
st.caption("Multi-platform scraper · AI skill extraction · Excel export")

st.sidebar.header("⚙️ Configuration")

groq_key = os.getenv("GROQ_API_KEY", "")
if groq_key:
    st.sidebar.success("🟢 Groq API loaded")
else:
    st.sidebar.error("🔴 GROQ_API_KEY missing in .env")

st.sidebar.markdown("---")
st.sidebar.subheader("🔍 Search")
role_input = st.sidebar.text_input("Job Role", value="Software QA Engineer")
company_input = st.sidebar.text_input(
    "Filter by Companies (optional)", placeholder="Google, Microsoft")
job_count = st.sidebar.slider("Max jobs to analyse", 5, 150, 30, 5)

st.sidebar.markdown("---")
st.sidebar.subheader("🌐 Platforms")
selected = []
defaults = {"LinkedIn", "Indeed", "Wellfound"}
for platform in PLATFORM_SCRAPERS:
    if st.sidebar.checkbox(platform, value=(platform in defaults)):
        selected.append(platform)

if not selected:
    st.sidebar.warning("Select at least one platform.")

st.sidebar.markdown("---")
run_button = st.sidebar.button("🚀 Run Analysis", use_container_width=True,
                               disabled=(not groq_key or not selected))

# ── Run ───────────────────────────────────────────────────
if run_button:
    status_box = st.empty()
    progress_box = st.progress(0)
    try:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        loop.run_until_complete(
            main_pipeline(role_input, company_input, job_count,
                          selected, progress_box, status_box)
        )
        loop.close()
        st.rerun()
    except Exception as e:
        st.error(f"❌ Pipeline error: {e}")

# ── Results ───────────────────────────────────────────────
excel_file = "job_market_analysis.xlsx"
if os.path.exists(excel_file):
    st.markdown("---")
    df_jobs = pd.read_excel(excel_file, sheet_name="Job Listings")
    df_skills = pd.read_excel(excel_file, sheet_name="Skill Demand Metrics")
    df_platforms = pd.read_excel(excel_file, sheet_name="Platform Summary")
    clean_df = df_skills[~df_skills["Skill/Tool"]
                         .isin(["General Requirements"])]

    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Jobs Analysed",  len(df_jobs))
    c2.metric("Unique Skills",  len(clean_df))
    c3.metric("Platforms Used", len(df_platforms))
    c4.metric("Top Skill",
              clean_df.iloc[0]["Skill/Tool"] if not clean_df.empty else "N/A")

    st.markdown("---")
    col1, col2 = st.columns([3, 2])
    with col1:
        st.subheader("📊 Top 15 In-Demand Skills")
        if not clean_df.empty:
            st.bar_chart(clean_df.head(15).set_index(
                "Skill/Tool")["Demand Count"])
    with col2:
        st.subheader("📋 Skill Breakdown")
        if not clean_df.empty:
            clean_df["Demand %"] = (
                clean_df["Demand Count"] / len(df_jobs) * 100).round(1)
            st.dataframe(
                clean_df.head(15)[["Skill/Tool", "Demand Count", "Demand %"]]
                .style.format({"Demand %": "{:.1f}%"}),
                hide_index=True, use_container_width=True
            )

    st.markdown("---")
    st.subheader("🌐 Platform Results")
    st.dataframe(df_platforms, hide_index=True, use_container_width=True)

    st.markdown("---")
    st.subheader("💼 Job Listings")
    cols = [c for c in ["role", "company", "platform", "date_posted",
                        "extracted_skills", "link"] if c in df_jobs.columns]
    st.dataframe(df_jobs[cols], hide_index=True, use_container_width=True)

    with open(excel_file, "rb") as f:
        st.download_button(
            "📥 Download Excel Report",
            data=f,
            file_name=f"{role_input.replace(' ', '_')}_skills_report.xlsx",
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            use_container_width=True
        )
