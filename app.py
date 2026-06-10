import streamlit as st
import pandas as pd
import asyncio
import os
import re
import json
import random
import urllib.parse
import requests
from collections import Counter
from playwright.async_api import async_playwright
from dotenv import load_dotenv

load_dotenv()

# ============================================================
# 1. LOCAL SKILL BANKS  (3 separate banks for fallback)
# ============================================================
TECHNICAL_BANK = [
    "Python", "Java", "C++", "C#", "TypeScript", "JavaScript", "Go", "Rust", "R", "MATLAB",
    "Selenium", "Cypress", "Playwright", "Appium", "JUnit", "TestNG", "PyTest", "Cucumber",
    "Postman", "JMeter", "RestAssured", "Karate", "SoapUI",
    "AWS", "Azure", "GCP", "Docker", "Kubernetes", "Jenkins", "Git", "Terraform", "Linux", "CI/CD",
    "SQL", "MySQL", "PostgreSQL", "MongoDB", "Redis", "Oracle", "Snowflake", "Cassandra",
    "React", "Angular", "Vue", "Node.js", "Django", "FastAPI", "Spring Boot", "Flask",
    "Machine Learning", "Deep Learning", "TensorFlow", "PyTorch", "Spark", "Kafka",
    "Manual Testing", "Automation Testing", "API Testing", "Performance Testing", "Load Testing",
    "Regression Testing", "Smoke Testing", "Unit Testing", "Integration Testing",
    "Grafana", "Datadog", "Splunk", "Prometheus", "New Relic", "ELK Stack",
    "PowerBI", "Tableau", "Excel", "MATLAB",
]

SOFT_SKILL_BANK = [
    "Communication", "Leadership", "Teamwork", "Collaboration", "Problem Solving",
    "Critical Thinking", "Attention to Detail", "Time Management", "Adaptability",
    "Mentoring", "Coaching", "Stakeholder Management", "Presentation Skills",
    "Written Communication", "Interpersonal Skills", "Self-motivated", "Initiative",
    "Analytical Thinking", "Decision Making", "Conflict Resolution", "Empathy",
    "Creativity", "Multitasking", "Organisational Skills", "Fast Learner",
]

DOMAIN_BANK = [
    "Agile", "Scrum", "Kanban", "Jira", "Confluence", "SDLC", "DevOps", "Waterfall",
    "HIPAA", "GDPR", "SOC2", "PCI-DSS", "ISO 27001", "NIST",
    "Healthcare", "FinTech", "E-commerce", "Banking", "Insurance", "Retail",
    "SaaS", "Startup", "Enterprise", "B2B", "B2C", "ERP",
    "Cybersecurity", "Data Security", "Risk Management", "Compliance",
    "Financial Services", "Telecommunications", "Automotive", "Aerospace",
    "Product Management", "Project Management", "ITIL", "PMP", "Six Sigma",
]


def extract_skills_locally(job_text):
    text_lower = job_text.lower()
    technical = [s for s in TECHNICAL_BANK if re.search(
        rf"\b{re.escape(s.lower())}\b", text_lower)][:8]
    soft = [s for s in SOFT_SKILL_BANK if re.search(
        rf"\b{re.escape(s.lower())}\b", text_lower)][:6]
    domain = [s for s in DOMAIN_BANK if re.search(
        rf"\b{re.escape(s.lower())}\b", text_lower)][:6]
    return {"technical": technical, "soft": soft, "domain": domain}


# ============================================================
# 2. AI SKILL EXTRACTOR  (Groq → 3-category JSON → local fallback)
# ============================================================
def extract_skills_with_ai(job_text, status_widget=None):
    empty = {"technical": [], "soft": [], "domain": []}
    if not job_text or "requires expertise in" in job_text.lower():
        return empty

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
                            "You extract job skills into exactly 3 categories.\n"
                            "Return ONLY this JSON structure, nothing else before or after:\n"
                            '{"technical":["max 8 items"],"soft":["max 5 items"],"domain":["max 5 items"]}\n\n'
                            "technical  = languages, frameworks, tools, testing tools, cloud, databases, CI/CD\n"
                            "soft       = communication, leadership, teamwork, problem-solving, attention to detail\n"
                            "domain     = industry (healthcare, fintech), compliance (HIPAA, GDPR), "
                            "methodologies (Agile, Scrum), business domains (SaaS, B2B)"
                        )
                    },
                    {"role": "user", "content": job_text.strip()[:3500]}
                ],
                "temperature": 0.1,
                "max_tokens": 350,
            },
            timeout=12
        )

        if response.status_code == 200:
            raw = response.json()["choices"][0]["message"]["content"].strip()
            try:
                data = json.loads(raw)
            except Exception:
                match = re.search(r"\{.*\}", raw, re.DOTALL)
                data = json.loads(match.group()) if match else None

            if data and isinstance(data, dict):
                return {
                    "technical": [s.strip() for s in data.get("technical", []) if s.strip()][:8],
                    "soft":      [s.strip() for s in data.get("soft",      []) if s.strip()][:5],
                    "domain":    [s.strip() for s in data.get("domain",    []) if s.strip()][:5],
                }

        if response.status_code == 429 and status_widget:
            status_widget.warning(
                "⚠️ Groq rate limited — using local skill bank...")

        return extract_skills_locally(job_text)

    except Exception:
        return extract_skills_locally(job_text)


# ============================================================
# 3. ANTI-BOT BROWSER SETUP
# ============================================================
STEALTH_SCRIPT = """
    Object.defineProperty(navigator, 'webdriver',   { get: () => undefined });
    Object.defineProperty(navigator, 'plugins',     { get: () => [1, 2, 3, 4, 5] });
    Object.defineProperty(navigator, 'languages',   { get: () => ['en-US', 'en'] });
    Object.defineProperty(navigator, 'platform',    { get: () => 'Win32' });
    window.chrome = { runtime: {}, loadTimes: () => {}, csi: () => {}, app: {} };
"""
BROWSER_ARGS = [
    "--no-sandbox", "--disable-blink-features=AutomationControlled",
    "--disable-dev-shm-usage", "--disable-infobars", "--disable-extensions",
]
USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
)


async def new_stealth_page(playwright):
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
    return browser, context, await context.new_page()


async def human_scroll(page, scrolls=10):
    for _ in range(scrolls):
        await page.mouse.wheel(0, random.randint(600, 2500))
        await asyncio.sleep(random.uniform(0.4, 1.2))


# ============================================================
# 4. UNIVERSAL HELPERS
# ============================================================
async def extract_jsonld_jobs(page, platform):
    jobs = []
    try:
        for script in await page.locator("script[type='application/ld+json']").all():
            try:
                data = json.loads(await script.inner_text())
                items = data if isinstance(data, list) else [data]
                for item in items:
                    if item.get("@type") == "JobPosting":
                        org = item.get("hiringOrganization", {})
                        company = org.get("name", "Unknown") if isinstance(
                            org, dict) else "Unknown"
                        desc = re.sub(r"<[^>]+>", " ",
                                      item.get("description", ""))[:2000]
                        jobs.append({
                            "role":               item.get("title", "").strip(),
                            "company":            company.strip(),
                            "link":               item.get("url", ""),
                            "date_posted":        item.get("datePosted", "Recent"),
                            "platform":           platform,
                            "description_preview": desc.strip(),
                        })
            except Exception:
                continue
    except Exception:
        pass
    return jobs


async def extract_generic_jobs(page, platform, base_url=""):
    jobs, seen = [], set()
    try:
        for link in await page.locator("a[href*='/job'], a[href*='/jobs/']").all():
            try:
                href = await link.get_attribute("href") or ""
                title = (await link.inner_text()).strip()
                if not title or len(title) < 4 or href in seen:
                    continue
                seen.add(href)
                full = f"{base_url}{href}" if href.startswith("/") else href
                jobs.append({"role": title[:120], "company": "Unknown", "link": full,
                             "date_posted": "Recent", "platform": platform, "description_preview": ""})
            except Exception:
                continue
    except Exception:
        pass
    return jobs


async def get_snippet(card, selectors):
    for sel in selectors:
        try:
            el = card.locator(sel)
            text = (await el.first.inner_text()).strip() if await el.count() > 0 else ""
            if text and len(text) > 20:
                return text
        except Exception:
            continue
    return ""


# ============================================================
# 5. PLATFORM SCRAPERS
# ============================================================

async def fetch_linkedin_jobs(query, max_jobs):
    url = f"https://www.linkedin.com/jobs/search/?keywords={urllib.parse.quote(query)}&sortBy=DD&f_TPR=r604800"
    results = []
    async with async_playwright() as p:
        browser, context, page = await new_stealth_page(p)
        try:
            await page.goto(url, wait_until="domcontentloaded", timeout=15000)
            await page.wait_for_selector(".jobs-search__results-list", timeout=10000)
            prev = 0
            for _ in range(60):
                await human_scroll(page, scrolls=3)
                for txt in ["See more jobs", "Show more results", "Load more"]:
                    try:
                        btn = page.locator(f"button:has-text('{txt}')")
                        if await btn.is_visible(timeout=500):
                            await btn.click()
                            await asyncio.sleep(1.5)
                    except Exception:
                        pass
                cur = await page.locator(".jobs-search__results-list > li").count()
                if cur >= max_jobs * 2 or cur == prev:
                    break
                prev = cur
            for card in await page.locator(".jobs-search__results-list > li").all():
                try:
                    t = card.locator(".base-search-card__title")
                    c = card.locator(".base-search-card__subtitle")
                    l = card.locator("a.base-card__full-link")
                    d = card.locator("time")
                    snip = await get_snippet(card, [".base-search-card__info p", "[class*='description']"])
                    if await t.count() > 0 and await l.count() > 0:
                        results.append({
                            "role":               (await t.inner_text()).strip(),
                            "company":            (await c.inner_text()).strip() if await c.count() > 0 else "Unknown",
                            "link":               (await l.get_attribute("href") or "").split("?")[0],
                            "date_posted":        (await d.inner_text()).strip() if await d.count() > 0 else "Recent",
                            "platform":           "LinkedIn",
                            "description_preview": snip,
                        })
                except Exception:
                    continue
        except Exception:
            pass
        finally:
            await browser.close()
    return results


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
            results = await extract_jsonld_jobs(page, "Indeed")
            if not results:
                sel = ".job_seen_beacon" if await page.locator(".job_seen_beacon").count() > 0 else "[data-testid='slider_item']"
                for card in await page.locator(sel).all():
                    try:
                        t = card.locator(
                            "h2.jobTitle a, [data-testid='jobsearch-JobInfoHeader-title']")
                        c = card.locator(
                            "[data-testid='company-name'], .companyName")
                        d = card.locator(
                            "[data-testid='myJobsStateDate'], .date")
                        snip = await get_snippet(card, ["[data-testid='job-snippet']", ".job-snippet", "[class*='snippet']"])
                        if await t.count() > 0:
                            href = await t.first.get_attribute("href") or ""
                            link = f"https://www.indeed.com{href}" if href.startswith(
                                "/") else href
                            results.append({
                                "role":               (await t.first.inner_text()).strip(),
                                "company":            (await c.first.inner_text()).strip() if await c.count() > 0 else "Unknown",
                                "link":               link.split("?")[0],
                                "date_posted":        (await d.first.inner_text()).strip() if await d.count() > 0 else "Recent",
                                "platform":           "Indeed",
                                "description_preview": snip,
                            })
                    except Exception:
                        continue
            if not results:
                results = await extract_generic_jobs(page, "Indeed", "https://www.indeed.com")
        except Exception:
            pass
        finally:
            await browser.close()
    return results


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
            sel = "[data-test='jobListing']" if await page.locator("[data-test='jobListing']").count() > 0 else "li[class*='JobsList']"
            for card in await page.locator(sel).all():
                try:
                    t = card.locator(
                        "[data-test='job-title'], a[class*='JobCard_jobTitle']")
                    c = card.locator(
                        "[data-test='employer-name'], span[class*='EmployerProfile']")
                    snip = await get_snippet(card, ["[data-test='job-snippet']", "[class*='jobDescriptionSnippet']", "[class*='description']", "p"])
                    if await t.count() > 0:
                        href = await t.first.get_attribute("href") or ""
                        link = f"https://www.glassdoor.com{href}" if href.startswith(
                            "/") else href
                        results.append({
                            "role":               (await t.first.inner_text()).strip(),
                            "company":            (await c.first.inner_text()).strip() if await c.count() > 0 else "Unknown",
                            "link":               link,
                            "date_posted":        "Recent",
                            "platform":           "Glassdoor",
                            "description_preview": snip,
                        })
                except Exception:
                    continue
            if not results:
                results = await extract_generic_jobs(page, "Glassdoor", "https://www.glassdoor.com")
        except Exception:
            pass
        finally:
            await browser.close()
    return results


async def fetch_dice_jobs(query, max_jobs):
    url = f"https://www.dice.com/jobs?q={urllib.parse.quote(query)}&countryCode=US"
    results = []
    async with async_playwright() as p:
        browser, context, page = await new_stealth_page(p)
        try:
            await page.goto(url, wait_until="networkidle", timeout=20000)
            await asyncio.sleep(3)
            await page.wait_for_selector("dhi-search-card, [data-cy='search-card'], article", timeout=10000)
            await human_scroll(page, scrolls=8)
            results = await extract_jsonld_jobs(page, "Dice")
            if not results:
                sel = "dhi-search-card" if await page.locator("dhi-search-card").count() > 0 else (
                      "[data-cy='search-card']" if await page.locator("[data-cy='search-card']").count() > 0 else "article")
                for card in await page.locator(sel).all():
                    try:
                        t = card.locator(
                            "a.card-title-link, [data-cy='card-title-link'], h5 a, h3 a, h2 a")
                        c = card.locator(
                            "a.card-company, [data-cy='card-company-name'], [class*='company']")
                        snip = await get_snippet(card, ["[data-cy='card-summary']", ".card-description", "[class*='summary']", "p"])
                        if await t.count() > 0:
                            href = await t.first.get_attribute("href") or ""
                            link = f"https://www.dice.com{href}" if href.startswith(
                                "/") else href
                            results.append({
                                "role":               (await t.first.inner_text()).strip(),
                                "company":            (await c.first.inner_text()).strip() if await c.count() > 0 else "Unknown",
                                "link":               link,
                                "date_posted":        "Recent",
                                "platform":           "Dice",
                                "description_preview": snip,
                            })
                    except Exception:
                        continue
            if not results:
                results = await extract_generic_jobs(page, "Dice", "https://www.dice.com")
        except Exception:
            pass
        finally:
            await browser.close()
    return results


async def fetch_ziprecruiter_jobs(query, max_jobs):
    url = f"https://www.ziprecruiter.com/Jobs/{urllib.parse.quote(query.replace(' ', '-'))}"
    results = []
    async with async_playwright() as p:
        browser, context, page = await new_stealth_page(p)
        try:
            await page.goto(url, wait_until="domcontentloaded", timeout=15000)
            await asyncio.sleep(3)
            await page.wait_for_selector("article, [class*='job_result'], [class*='JobCard']", timeout=10000)
            await human_scroll(page, scrolls=8)
            results = await extract_jsonld_jobs(page, "ZipRecruiter")
            if not results:
                for card in await page.locator("article").all():
                    try:
                        t = card.locator(
                            "h2 a, [class*='title'] a, [class*='job_title'] a")
                        c = card.locator(
                            "[class*='company'], [data-testid*='company'], [class*='t_org']")
                        snip = await get_snippet(card, ["[class*='job_description']", "[class*='snippet']", "p"])
                        if await t.count() > 0:
                            href = await t.first.get_attribute("href") or ""
                            results.append({
                                "role":               (await t.first.inner_text()).strip(),
                                "company":            (await c.first.inner_text()).strip() if await c.count() > 0 else "Unknown",
                                "link":               href,
                                "date_posted":        "Recent",
                                "platform":           "ZipRecruiter",
                                "description_preview": snip,
                            })
                    except Exception:
                        continue
            if not results:
                results = await extract_generic_jobs(page, "ZipRecruiter")
        except Exception:
            pass
        finally:
            await browser.close()
    return results


async def fetch_wellfound_jobs(query, max_jobs):
    url = f"https://wellfound.com/jobs?q={urllib.parse.quote(query)}"
    results = []
    async with async_playwright() as p:
        browser, context, page = await new_stealth_page(p)
        try:
            await page.goto(url, wait_until="networkidle", timeout=20000)
            await asyncio.sleep(4)
            await human_scroll(page, scrolls=10)
            results = await extract_jsonld_jobs(page, "Wellfound")
            if not results:
                sel = "[data-test='startup-result'], [class*='JobCard'], [class*='styles_result'], [class*='job-card']"
                for card in await page.locator(sel).all():
                    try:
                        t = card.locator(
                            "[data-test='job-title'], a[class*='title'], a[class*='job'], h3 a")
                        c = card.locator(
                            "[data-test='startup-link'], a[class*='company'], a[class*='startup']")
                        snip = await get_snippet(card, ["[class*='description']", "[class*='snippet']", "p"])
                        if await t.count() > 0:
                            href = await t.first.get_attribute("href") or ""
                            link = f"https://wellfound.com{href}" if href.startswith(
                                "/") else href
                            results.append({
                                "role":               (await t.first.inner_text()).strip(),
                                "company":            (await c.first.inner_text()).strip() if await c.count() > 0 else "Unknown",
                                "link":               link,
                                "date_posted":        "Recent",
                                "platform":           "Wellfound",
                                "description_preview": snip,
                            })
                    except Exception:
                        continue
            if not results:
                results = await extract_generic_jobs(page, "Wellfound", "https://wellfound.com")
        except Exception:
            pass
        finally:
            await browser.close()
    return results


async def fetch_jobright_jobs(query, max_jobs):
    results = []
    url_patterns = [
        f"https://jobright.ai/jobs?q={urllib.parse.quote(query)}",
        f"https://jobright.ai/jobs/search?q={urllib.parse.quote(query)}",
        f"https://jobright.ai/jobs/all?q={urllib.parse.quote(query)}",
    ]
    async with async_playwright() as p:
        browser, context, page = await new_stealth_page(p)
        try:
            loaded = False
            for url in url_patterns:
                try:
                    await page.goto(url, wait_until="networkidle", timeout=20000)
                    await asyncio.sleep(4)
                    if await page.locator("a[href*='/job'], a[href*='/jobs/'], [class*='job'], article, li").count() > 3:
                        loaded = True
                        break
                except Exception:
                    continue
            if not loaded:
                return []
            await human_scroll(page, scrolls=12)
            results = await extract_jsonld_jobs(page, "JobRight.ai")
            if not results:
                for sel in ["[class*='JobCard']", "[class*='job-card']", "[class*='JobItem']",
                            "[class*='job-item']", "[class*='JobResult']", "article", "li[class*='job']"]:
                    cards = await page.locator(sel).all()
                    if len(cards) > 2:
                        for card in cards:
                            try:
                                t = card.locator(
                                    "a[class*='title'], h3 a, h2 a, h4 a, [class*='title'] a")
                                c = card.locator(
                                    "[class*='company'], [class*='employer']")
                                snip = await get_snippet(card, ["[class*='description']", "[class*='summary']", "p"])
                                if await t.count() > 0:
                                    href = await t.first.get_attribute("href") or ""
                                    role = (await t.first.inner_text()).strip()
                                    if role and len(role) > 3:
                                        link = f"https://jobright.ai{href}" if href.startswith(
                                            "/") else href
                                        results.append({
                                            "role":               role,
                                            "company":            (await c.first.inner_text()).strip() if await c.count() > 0 else "Unknown",
                                            "link":               link,
                                            "date_posted":        "Recent",
                                            "platform":           "JobRight.ai",
                                            "description_preview": snip,
                                        })
                            except Exception:
                                continue
                        if results:
                            break
            if not results:
                results = await extract_generic_jobs(page, "JobRight.ai", "https://jobright.ai")
        except Exception:
            pass
        finally:
            await browser.close()
    return results


PLATFORM_SCRAPERS = {
    "LinkedIn":     fetch_linkedin_jobs,
    "Indeed":       fetch_indeed_jobs,
    "Glassdoor":    fetch_glassdoor_jobs,
    "Dice":         fetch_dice_jobs,
    "ZipRecruiter": fetch_ziprecruiter_jobs,
    "Wellfound":    fetch_wellfound_jobs,
    "JobRight.ai":  fetch_jobright_jobs,
}


# ============================================================
# 6. MAIN PIPELINE
# ============================================================
async def main_pipeline(search_role, company_input, max_jobs, selected_platforms, ui_progress, ui_status):
    companies = [c.strip() for c in company_input.split(",") if c.strip()]
    jobs_per_platform = max(8, max_jobs // max(len(selected_platforms), 1))
    all_raw, platform_summary = [], {}

    # ── Phase 1: scrape ──────────────────────────────────────
    for idx, platform in enumerate(selected_platforms, 1):
        ui_status.info(
            f"📡 [{idx}/{len(selected_platforms)}] Searching {platform}…")
        ui_progress.progress(idx / (len(selected_platforms) + 1))
        scraper = PLATFORM_SCRAPERS.get(platform)
        if not scraper:
            continue
        try:
            if companies:
                res = []
                for co in companies:
                    res.extend(await scraper(f"{search_role} {co}", jobs_per_platform))
            else:
                res = await scraper(search_role, jobs_per_platform)
            res = [j for j in res if j.get("role") and len(j["role"]) > 3]
            platform_summary[platform] = len(res)
            all_raw.extend(res)
            ui_status.info(f"✅ {platform}: {len(res)} listings found")
        except Exception as e:
            platform_summary[platform] = 0
            ui_status.warning(f"⚠️ {platform} error: {str(e)[:80]}")

    # ── Deduplicate ───────────────────────────────────────────
    seen, job_listings = set(), []
    for job in all_raw:
        key = job.get("link") or f"{job['role']}|{job['company']}"
        if key in seen:
            continue
        if companies:
            if not any(co.lower() in job["company"].lower() for co in companies):
                continue
        seen.add(key)
        job_listings.append(job)
    job_listings = job_listings[:max_jobs]

    if not job_listings:
        st.error(
            "❌ No jobs found. Try broader search terms, more platforms, or increase the count.")
        return

    # ── Phase 2: skill extraction ─────────────────────────────
    tech_counter, soft_counter, domain_counter = Counter(), Counter(), Counter()
    processed = []
    total = len(job_listings)
    ui_status.info(f"🧠 Phase 2: Extracting skills from {total} listings…")

    async with async_playwright() as p:
        browser, context, desc_page = await new_stealth_page(p)
        try:
            for i, job in enumerate(job_listings, 1):
                ui_progress.progress(
                    (len(selected_platforms) + i) / (len(selected_platforms) + total + 1))
                ui_status.text(
                    f"[{i}/{total}] {job['platform']} — {job['company']}: {job['role']}")

                preview = job.get("description_preview", "")

                # Use snippet if rich enough; visit page for LinkedIn only
                if len(preview) > 80:
                    desc = preview
                elif job["platform"] == "LinkedIn" and job.get("link"):
                    try:
                        await desc_page.goto(job["link"], wait_until="domcontentloaded", timeout=12000)
                        await asyncio.sleep(1)
                        desc = preview
                        for sel in [".show-more-less-html__markup", ".description__text"]:
                            try:
                                await desc_page.wait_for_selector(sel, timeout=2000)
                                t = await desc_page.locator(sel).first.inner_text()
                                if t and len(t) > 80:
                                    desc = t.strip()
                                    break
                            except Exception:
                                continue
                    except Exception:
                        desc = preview or f"Requires expertise in {job['role']}"
                else:
                    desc = preview or f"Requires expertise in {job['role']}"

                skills = extract_skills_with_ai(desc, ui_status)
                tech_counter.update(skills["technical"])
                soft_counter.update(skills["soft"])
                domain_counter.update(skills["domain"])

                job["technical_skills"] = ", ".join(skills["technical"]) or "—"
                job["soft_skills"] = ", ".join(skills["soft"]) or "—"
                job["domain_knowledge"] = ", ".join(skills["domain"]) or "—"
                processed.append(job)
        finally:
            await browser.close()

    ui_progress.progress(1.0)

    # ── Save to Excel (5 sheets) ──────────────────────────────
    df_jobs = pd.DataFrame(processed)
    df_jobs.drop(columns=["description_preview"],
                 errors="ignore", inplace=True)

    def make_freq_df(counter, col_name):
        total_jobs = len(processed)
        df = pd.DataFrame(counter.items(), columns=[col_name, "Count"]).sort_values(
            "Count", ascending=False).reset_index(drop=True)
        df["Demand %"] = (df["Count"] / total_jobs * 100).round(1)
        return df

    df_tech = make_freq_df(tech_counter,   "Technical Skill")
    df_soft = make_freq_df(soft_counter,   "Soft Skill")
    df_domain = make_freq_df(domain_counter, "Domain Knowledge")
    df_plat = pd.DataFrame([
        {"Platform": p, "Jobs Found": platform_summary.get(p, 0),
         "Status": "✅ OK" if platform_summary.get(p, 0) > 0 else "⚠️ No results"}
        for p in selected_platforms
    ])

    export_cols = [c for c in ["role", "company", "platform", "date_posted",
                               "technical_skills", "soft_skills", "domain_knowledge", "link"]
                   if c in df_jobs.columns]

    with pd.ExcelWriter("job_market_analysis.xlsx", engine="openpyxl") as writer:
        df_jobs[export_cols].to_excel(
            writer, sheet_name="Job Listings",       index=False)
        df_tech.to_excel(writer, sheet_name="Technical Skills",    index=False)
        df_soft.to_excel(writer, sheet_name="Soft Skills",         index=False)
        df_domain.to_excel(
            writer, sheet_name="Domain Knowledge",    index=False)
        df_plat.to_excel(writer, sheet_name="Platform Summary",    index=False)

    ui_status.success(
        f"✅ Done — {len(processed)} jobs across {sum(1 for v in platform_summary.values() if v > 0)} platforms.")


# ============================================================
# 7. STREAMLIT DASHBOARD
# ============================================================
st.set_page_config(page_title="Job Market Skill Analyzer",
                   page_icon="🎯", layout="wide")
st.title("🎯 Job Market Skill Demand Analyzer")
st.caption(
    "Technical · Soft Skills · Domain Knowledge  |  Multi-platform scraper  |  Excel export")

# ── Sidebar ───────────────────────────────────────────────
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
selected, defaults = [], {"LinkedIn", "Indeed", "Wellfound"}
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

    # Check the file has the current 5-sheet format (older runs have fewer sheets)
    available_sheets = pd.ExcelFile(excel_file).sheet_names
    required_sheets = ["Job Listings", "Technical Skills",
                       "Soft Skills", "Domain Knowledge", "Platform Summary"]
    missing_sheets = [s for s in required_sheets if s not in available_sheets]

    if missing_sheets:
        st.warning(
            "⚠️ The saved report is from an older run and is missing sheets: "
            + ", ".join(f"**{s}**" for s in missing_sheets)
            + ". Please delete **job_market_analysis.xlsx** and run a new analysis."
        )
        st.stop()

    df_jobs = pd.read_excel(excel_file, sheet_name="Job Listings")
    df_tech = pd.read_excel(excel_file, sheet_name="Technical Skills")
    df_soft = pd.read_excel(excel_file, sheet_name="Soft Skills")
    df_domain = pd.read_excel(excel_file, sheet_name="Domain Knowledge")
    df_plat = pd.read_excel(excel_file, sheet_name="Platform Summary")

    # ── KPI row ──────────────────────────────────────────────
    k1, k2, k3, k4, k5 = st.columns(5)
    k1.metric("Jobs Analysed",    len(df_jobs))
    k2.metric("Technical Skills", len(df_tech))
    k3.metric("Soft Skills",      len(df_soft))
    k4.metric("Domain Areas",     len(df_domain))
    k5.metric("Platforms",        int((df_plat["Status"] == "✅ OK").sum()))

    st.markdown("---")

    # ── 3 charts side by side ────────────────────────────────
    col_t, col_s, col_d = st.columns(3)

    with col_t:
        st.subheader("⚙️ Technical Skills")
        if not df_tech.empty:
            st.bar_chart(df_tech.head(12).set_index(
                "Technical Skill")["Count"])

    with col_s:
        st.subheader("🤝 Soft Skills")
        if not df_soft.empty:
            st.bar_chart(df_soft.head(10).set_index("Soft Skill")["Count"])

    with col_d:
        st.subheader("🌐 Domain Knowledge")
        if not df_domain.empty:
            st.bar_chart(df_domain.head(10).set_index(
                "Domain Knowledge")["Count"])

    st.markdown("---")

    # ── 3 tables side by side ────────────────────────────────
    t1, t2, t3 = st.columns(3)

    with t1:
        st.markdown("**Top Technical Skills**")
        if not df_tech.empty:
            st.dataframe(
                df_tech.head(15).style.format({"Demand %": "{:.1f}%"}),
                hide_index=True, use_container_width=True
            )

    with t2:
        st.markdown("**Top Soft Skills**")
        if not df_soft.empty:
            st.dataframe(
                df_soft.head(12).style.format({"Demand %": "{:.1f}%"}),
                hide_index=True, use_container_width=True
            )

    with t3:
        st.markdown("**Top Domain Knowledge**")
        if not df_domain.empty:
            st.dataframe(
                df_domain.head(12).style.format({"Demand %": "{:.1f}%"}),
                hide_index=True, use_container_width=True
            )

    st.markdown("---")

    # ── Platform results ─────────────────────────────────────
    st.subheader("🌐 Platform Results")
    st.dataframe(df_plat, hide_index=True, use_container_width=True)

    st.markdown("---")

    # ── Job listings ─────────────────────────────────────────
    st.subheader("💼 Job Listings")
    view_cols = [c for c in ["role", "company", "platform", "date_posted",
                             "technical_skills", "soft_skills", "domain_knowledge", "link"]
                 if c in df_jobs.columns]
    st.dataframe(df_jobs[view_cols], hide_index=True, use_container_width=True)

    # ── Download ──────────────────────────────────────────────
    with open(excel_file, "rb") as f:
        st.download_button(
            "📥 Download Full Excel Report  (5 sheets: Jobs · Technical · Soft · Domain · Platforms)",
            data=f,
            file_name=f"{role_input.replace(' ', '_')}_skills_report.xlsx",
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            use_container_width=True
        )
