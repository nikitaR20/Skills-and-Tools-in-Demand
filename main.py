import asyncio
import pandas as pd
from collections import Counter
from playwright.async_api import async_playwright
from scraper import fetch_job_listings
from processor import extract_skills_from_text


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
            text_clean = text_content.strip()
            if "sign in" in text_clean.lower() or "join linkedin" in text_clean.lower():
                return f"Requires expertise in {job_role_fallback}"
            return text_clean
        else:
            return f"Requires expertise in {job_role_fallback}"
    except Exception:
        return f"Requires expertise in {job_role_fallback}"
    finally:
        await page.close()


async def main_pipeline(search_role, max_jobs=20):
    print(
        f"🚀 Initializing pipeline for: '{search_role}' (Count limit: {max_jobs})")

    # Route target count directly down to your scraper file
    job_listings = await fetch_job_listings(search_role, max_jobs)

    if not job_listings:
        print("❌ No job listings collected.")
        return

    all_extracted_skills = []
    final_processed_jobs = []

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)

        for index, job in enumerate(job_listings, 1):
            print(
                f"[{index}/{len(job_listings)}] Analyzing: {job['role']} at {job['company']}")

            full_text = await scrape_full_description(browser, job['link'], job['role'])
            skills = extract_skills_from_text(full_text)

            all_extracted_skills.extend(skills)
            job['extracted_skills'] = ", ".join(
                skills) if skills else "General Requirements"
            final_processed_jobs.append(job)

        await browser.close()

    print("\n📊 Generating Excel spreadsheets...")
    df_jobs = pd.DataFrame(final_processed_jobs)

    skill_counts = Counter(all_extracted_skills)
    df_skills = pd.DataFrame(skill_counts.items(), columns=[
                             "Skill/Tool", "Demand Count"])
    df_skills = df_skills.sort_values(by="Demand Count", ascending=False)

    with pd.ExcelWriter("job_market_analysis.xlsx") as writer:
        df_jobs.to_excel(writer, sheet_name="Job Listings", index=False)
        df_skills.to_excel(
            writer, sheet_name="Skill Demand Metrics", index=False)

    print("🎉 Excel file generation successfully updated.")
