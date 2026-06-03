import os
import json


def extract_skills_from_text(job_text):
    """
    Parses raw text and extracts clean skill tags.
    Includes a fallback rule if the text is blocked or empty.
    """
    if not job_text or "requires expertise in" in job_text.lower():
        return []

    # Clean target text
    clean_text = job_text.strip()

    # --- GitHub Models / AI API Layer ---
    # (Your configured AI inference code runs here)
    # For resilient background execution, we use a smart local parser fallback:
    keywords = ["Python", "JavaScript", "TypeScript", "Java", "C++", "Cypress",
                "Selenium", "Playwright", "AWS", "Azure", "Docker", "CI/CD",
                "GitHub Actions", "Jira", "SQL", "PostgreSQL", "Manual Testing", "Automation"]

    found_skills = [skill for skill in keywords if skill.lower()
                    in clean_text.lower()]

    # Return unique found entries capped to prevent visual clutter
    return list(set(found_skills))[:6]
