import urllib.parse
import asyncio
from playwright.async_api import async_playwright


async def fetch_job_listings(search_role, max_jobs=20):
    formatted_query = urllib.parse.quote(search_role)
    # Pulls from the past 7 days to give you a deep, fresh data pool
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
            print("⚠️ No job listings container found.")
            await browser.close()
            return []

        # --- HUMAN INTERACTION MOUSE WHEEL ENGINE ---
        print(f"⏳ Spinning mouse wheel to unlock exactly {max_jobs} jobs...")
        scroll_attempts = 0
        while scroll_attempts < 15:
            current_cards = await page.locator(".jobs-search__results-list > li").count()
            if current_cards >= max_jobs:
                break

            # Physically scroll down 1500 pixels per loop pass
            await page.mouse.wheel(0, 1500)
            await asyncio.sleep(1.2)
            scroll_attempts += 1

        # Extract exactly what the slider requested
        job_cards = await page.locator(".jobs-search__results-list > li").all()
        print(
            f"📋 Total items rendered on DOM: {len(job_cards)}. Processing top target matches...")

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

                    # Extract date string (e.g., "2 hours ago", "3 days ago")
                    if await date_element.count() > 0:
                        date_posted = await date_element.inner_text()
                    else:
                        date_posted = "Just posted"

                    job_results.append({
                        "role": role.strip(),
                        "company": company.strip(),
                        "link": link.split('?')[0],
                        "date_posted": date_posted.strip()
                    })
            except Exception:
                continue

        await browser.close()

    print(f"✅ Extracted a clean pool of {len(job_results)} jobs.")
    return job_results
