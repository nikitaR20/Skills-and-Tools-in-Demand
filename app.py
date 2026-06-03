import streamlit as st
import pandas as pd
import asyncio
import os
import urllib.parse
import json
import requests
from collections import Counter
from playwright.async_api import async_playwright
from dotenv import load_dotenv

# Automatically load environment variables from a local .env file
load_dotenv()

# ==========================================================
# 1. DYNAMIC AI SKILL EXTRACTOR LAYER (No Hardcoded Keywords)
# ==========================================================


def extract_skills_with_ai(job_text, github_token):
    if not job_text or "requires expertise in" in job_text.lower():
        return []

    clean_text = job_text.strip()[:4000]
    url = "https://models.inference.ai.azure.com/chat/completions"
    headers = {
        "Authorization": f"Bearer {github_token}",
        "Content-Type": "application/json"
    }

    payload = {
        "messages": [
            {
                "role": "system",
                "content": (
                    "You are an expert technical recruiting AI. Analyze the job description provided "
                    "and extract a flat list of up to 8 core technical skills, programming languages, "
                    "software tools, hardware systems, or industry-specific engineering frameworks mentioned. "
                    "Provide ONLY a clean comma-separated list of names (e.g., Ansys, Abaqus, Python, Stress Analysis). "
                    "Do not include commentary, meta-descriptions, introductions, or markdown formatting blocks. "
                    "If no clear technical tools or skills are explicitly found, return 'General Requirements'."
                )
            },
            {"role": "user", "content": clean_text}
        ],
        "model": "gpt-4o-mini",
        "temperature": 0.1
    }

    try:
        response = requests.post(url, headers=headers,
                                 json=payload, timeout=10)
        if response.status_code == 200:
            ai_response = response.json()
            raw_skills = ai_response["choices"][0]["message"]["content"]
            skills_list = [skill.strip()
                           for skill in raw_skills.split(",") if skill.strip()]
            skills_list = [s for s in skills_list if len(
                s) < 30 and "here are" not in s.lower()]
            return skills_list[:8]
        else:
            return ["API Error Logs"]
    except Exception:
        return ["Connection Error"]


# ==========================================================
# 2. LIVE MOUSE-SCROLL SCRAPER LAYER (Upgraded for 100+ Jobs)
# ==========================================================
async def fetch_job_listings(search_role, max_jobs):
    formatted_query = urllib.parse.quote(search_role)
    url = f"https://www.linkedin.com/jobs/search/?keywords={formatted_query}&sortBy=DD&f_TPR=r604800"

    print(f"📡 Querying live feed: {url}")
    job_results = []

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        page = await browser.new_page()
        await page.set_viewport_size({"width": 1280, "height": 1024})

        await page.goto(url, wait_until="domcontentloaded")

        try:
            await page.wait_for_selector(".jobs-search__results-list", timeout=10000)
        except Exception:
            await browser.close()
            return []

        # --- AGGRESSIVE DEEP SCROLL ENGINE ---
        scroll_attempts = 0
        max_scroll_loops = 60  # Increased to allow deeper rendering

        while scroll_attempts < max_scroll_loops:
            current_cards = await page.locator(".jobs-search__results-list > li").count()
            if current_cards >= max_jobs:
                break

            await page.mouse.wheel(0, 2000)
            await asyncio.sleep(1.0)

            # Click the unauthenticated "See more jobs" pagination button if it spawns
            try:
                see_more_button = page.locator(
                    "button.infinite-scroller__button")
                if await see_more_button.is_visible():
                    await see_more_button.click()
                    await asyncio.sleep(1.5)
            except Exception:
                pass

            scroll_attempts += 1

        job_cards = await page.locator(".jobs-search__results-list > li").all()

        for card in job_cards:
            if len(job_results) >= max_jobs:
                break

            try:
                role_element = card.locator(".base-search-card__title")
                company_element = card.locator(".base-search-card__subtitle")
                link_element = card.locator("a.base-card__full-link")
                date_element = card.locator("time")

                if await role_element.count() > 0 and await link_element.count() > 0:
                    role = await role_element.inner_text()
                    company = await company_element.inner_text() if await company_element.count() > 0 else "Unknown"
                    link = await link_element.get_attribute("href")
                    date_posted = await date_element.inner_text() if await date_element.count() > 0 else "Just posted"

                    job_results.append({
                        "role": role.strip(),
                        "company": company.strip(),
                        "link": link.split('?')[0],
                        "date_posted": date_posted.strip()
                    })
            except Exception:
                continue

        await browser.close()

    return job_results


# ==========================================================
# 3. COORDINATION PIPELINE ENGINE (With Live Progress Updates)
# ==========================================================
async def scrape_full_description(browser, job_url, job_role_fallback):
    try:
        page = await browser.new_page()
        await page.set_extra_http_headers({
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
        })
        await page.goto(job_url, wait_until="domcontentloaded", timeout=12000)

        description_selector = ".show-more-less-html__markup"
        try:
            await page.wait_for_selector(description_selector, timeout=3000)
        except Exception:
            pass

        if await page.locator(description_selector).count() > 0:
            text_content = await page.locator(description_selector).inner_text()
            return text_content.strip()
        return f"Requires expertise in {job_role_fallback}"
    except Exception:
        return f"Requires expertise in {job_role_fallback}"
    finally:
        await page.close()


async def main_pipeline(search_role, max_jobs, github_token, ui_progress_bar, ui_status_text):
    ui_status_text.info(
        "📡 Phase 1/2: Querying live feed and scrolling for listings...")
    job_listings = await fetch_job_listings(search_role, max_jobs)

    if not job_listings:
        st.error(
            "❌ No jobs were extracted by the scraper. LinkedIn may be throttling requests.")
        return

    all_extracted_skills = []
    final_processed_jobs = []
    total_found = len(job_listings)

    ui_status_text.info(
        f"🧠 Phase 2/2: Found {total_found} listings. Extracting descriptions and running AI mapping...")

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)

        for index, job in enumerate(job_listings, 1):
            # Update visual UI trackers
            ui_status_text.text(
                f"Processing listing {index} of {total_found}: {job['company']} - {job['role']}")
            ui_progress_bar.progress(index / total_found)

            full_text = await scrape_full_description(browser, job['link'], job['role'])
            skills = extract_skills_with_ai(full_text, github_token)

            all_extracted_skills.extend(skills)
            job['extracted_skills'] = ", ".join(
                skills) if skills else "General Requirements"
            final_processed_jobs.append(job)

        await browser.close()

    df_jobs = pd.DataFrame(final_processed_jobs)
    skill_counts = Counter(all_extracted_skills)
    df_skills = pd.DataFrame(skill_counts.items(), columns=[
                             "Skill/Tool", "Demand Count"])
    df_skills = df_skills.sort_values(by="Demand Count", ascending=False)

    with pd.ExcelWriter("job_market_analysis.xlsx") as writer:
        df_jobs.to_excel(writer, sheet_name="Job Listings", index=False)
        df_skills.to_excel(
            writer, sheet_name="Skill Demand Metrics", index=False)


# ==========================================================
# 4. STREAMLIT USER INTERFACE LAYOUT
# ==========================================================
st.set_page_config(page_title="Job Market Skill Analyzer",
                   page_icon="🎯", layout="wide")

st.title("🎯 Job Market Skill Demand Analyzer")
st.write("Scrape openings, parse descriptions dynamically via AI, and visualize market distributions.")

st.sidebar.header("Configuration Panel")

env_token = os.getenv("GITHUB_TOKEN")

if env_token:
    st.sidebar.success("🔒 GitHub Token loaded from .env")
    token_input = env_token
else:
    token_input = st.sidebar.text_input(
        "GitHub Personal Access Token",
        type="password"
    )

role_input = st.sidebar.text_input("Target Job Role", value="FEA Engineer")

# Slider expanded to handle up to 100 jobs cleanly
job_count = st.sidebar.slider(
    "Number of jobs to analyze", min_value=5, max_value=100, value=50, step=5)
run_button = st.sidebar.button("Run Live Market Analysis")

if run_button:
    if not token_input:
        st.sidebar.error(
            "🔑 Access Denied: Provide a valid token signature via .env or manual panel field.")
    else:
        # Create active placeholder boxes for real-time progress layout tracking
        status_box = st.empty()
        progress_box = st.empty()

        try:
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            loop.run_until_complete(main_pipeline(
                role_input, job_count, token_input, progress_box, status_box))
            loop.close()

            status_box.empty()
            progress_box.empty()
            st.sidebar.success("Analysis complete!")
            st.rerun()
        except Exception as e:
            st.sidebar.error(f"Pipeline error: {e}")

excel_file = "job_market_analysis.xlsx"

if os.path.exists(excel_file):
    st.markdown("---")
    st.subheader(f"📊 Pure AI Insights Market Report")

    df_jobs = pd.read_excel(excel_file, sheet_name="Job Listings")
    df_skills = pd.read_excel(excel_file, sheet_name="Skill Demand Metrics")

    df_skills = df_skills[~df_skills["Skill/Tool"].isin(
        ["General Requirements", "API Error Logs", "Connection Error"])]

    kpi1, kpi2, kpi3 = st.columns(3)
    with kpi1:
        st.metric(label="Total Jobs Analyzed", value=len(df_jobs))
    with kpi2:
        st.metric(label="Unique Tools/Skills Found", value=len(df_skills))
    with kpi3:
        top_skill = df_skills.iloc[0]["Skill/Tool"] if not df_skills.empty else "N/A"
        st.metric(label="Most In-Demand Skill", value=top_skill)

    col_chart, col_data = st.columns([3, 2])

    with col_chart:
        st.subheader("🔥 Top 15 Auto-Extracted Skills & Tools")
        if not df_skills.empty:
            chart_data = df_skills.head(15).set_index("Skill/Tool")
            st.bar_chart(chart_data)
        else:
            st.info("No distinct tool groupings extracted.")

    with col_data:
        st.subheader("📈 Percentage Demand Distribution")
        if not df_skills.empty:
            df_skills["Demand %"] = (
                df_skills["Demand Count"] / len(df_jobs)) * 100
            st.dataframe(
                df_skills.head(10)[["Skill/Tool", "Demand %"]
                                   ].style.format({"Demand %": "{:.1f}%"}),
                use_container_width=True, hide_index=True
            )

    st.markdown("---")
    st.subheader("📋 Scraped Job Directory & Links")

    display_cols = ["role", "company",
                    "date_posted", "extracted_skills", "link"]
    available_cols = [col for col in display_cols if col in df_jobs.columns]

    st.dataframe(df_jobs[available_cols],
                 use_container_width=True, hide_index=True)

    with open(excel_file, "rb") as file:
        st.download_button(
            label="📥 Download Structured Excel Report",
            data=file,
            file_name=f"{role_input.replace(' ', '_')}_market_report.xlsx",
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
        )
else:
    st.info("👋 System ready. Slide the configuration scale up to 100, input your target title, and start the tracker.")
