"""
One-time setup: reads all 6 resume PDFs from resumes/ and uses Claude to
extract structured profiles, saving them to config/resume_profiles.json.

Run once before the first scraping/scoring run:
    python utils/resume_embedder.py
"""

import json
import sys
from pathlib import Path

import pdfplumber

ROOT = Path(__file__).parent.parent
RESUMES_DIR = ROOT / "resumes"
OUTPUT_PATH = ROOT / "config" / "resume_profiles.json"

# Maps PDF filename → resume metadata used to seed the extraction prompt
RESUME_REGISTRY = [
    {
        "id": 1,
        "name": "TPM - Healthcare",
        "file": "Bardhan_Satwik_H_TPJM_v2026.pdf",
        "positioning": "Technical Program Manager focused on healthcare technology",
    },
    {
        "id": 2,
        "name": "TPM - Fintech",
        "file": "Bardhan_Satwik_F_TPJM_v2026.pdf",
        "positioning": "Technical Program Manager with founder experience in fintech",
    },
    {
        "id": 3,
        "name": "Technical PM",
        "file": "Bardhan_Satwik_Ldr_TPDM_v2026.pdf",
        "positioning": "Technical Product Manager with founder DNA, domain-agnostic",
    },
    {
        "id": 4,
        "name": "Executive Leadership - Healthcare",
        "file": "Bardhan_Satwik_H_Ldr_D_v2026.pdf",
        "positioning": "VP/Director-level product-delivery executive in healthcare",
    },
    {
        "id": 5,
        "name": "Executive Leadership - Fintech",
        "file": "Bardhan_Satwik_F_Ldr_PD_v2026.pdf",
        "positioning": "VP/Director-level product-delivery executive with founder experience",
    },
    {
        "id": 6,
        "name": "Product Engineering Leader",
        "file": "Bardhan_Satwik_Ldr_PE_v2026.pdf",
        "positioning": "Founding/Head of Product for early-stage startups, AI-first",
    },
]

EXTRACTION_PROMPT = """\
You are extracting a structured profile from a resume for use in AI job matching.

Resume positioning: {positioning}

Full resume text:
{resume_text}

Extract and return ONLY valid JSON (no markdown, no preamble) matching this schema exactly:
{{
  "target_criteria": {{
    "titles": ["list of 4-6 exact target job titles this resume is optimized for"],
    "domains": ["list of industries/domains this resume targets"],
    "seniority": ["list of seniority levels, e.g. Senior, Director, VP"],
    "company_stages": ["list of company stages, e.g. Series B, Series C, PE-backed"],
    "locations": ["Remote", "Chicago, IL"]
  }},
  "key_experiences": [
    "5-7 specific experiences with company names and context"
  ],
  "key_metrics": [
    "5-7 quantified achievements, e.g. '$8M program delivery', '20+ client implementations'"
  ],
  "differentiators": [
    "4-6 unique differentiators that make this resume stand out for its target roles"
  ]
}}
"""


def extract_text_from_pdf(pdf_path: Path) -> str:
    text_parts = []
    with pdfplumber.open(pdf_path) as pdf:
        for page in pdf.pages:
            text = page.extract_text()
            if text:
                text_parts.append(text)
    return "\n".join(text_parts)


def extract_profile(resume_meta: dict, resume_text: str, ai) -> dict:
    prompt = EXTRACTION_PROMPT.format(
        positioning=resume_meta["positioning"],
        resume_text=resume_text[:8000],  # cap to avoid token limits
    )
    response = ai.score_job(prompt)

    # Strip markdown code fences if present
    text = response.strip()
    if text.startswith("```"):
        text = text.split("```")[1]
        if text.startswith("json"):
            text = text[4:]
    text = text.strip()

    return json.loads(text)


def main():
    # Late import so embedder only needs AI provider when actually run
    sys.path.insert(0, str(ROOT))
    from scoring.ai_provider import AIProvider

    ai = AIProvider()
    print(f"Using {ai.get_provider_info()['provider']} - {ai.get_provider_info()['model']}")

    profiles = []

    for meta in RESUME_REGISTRY:
        pdf_path = RESUMES_DIR / meta["file"]
        if not pdf_path.exists():
            print(f"  SKIPPED (file not found): {meta['file']}")
            continue

        print(f"  Extracting profile for Resume {meta['id']}: {meta['name']} ...")
        resume_text = extract_text_from_pdf(pdf_path)

        if not resume_text.strip():
            print(f"  WARNING: Could not extract text from {meta['file']}")
            continue

        try:
            extracted = extract_profile(meta, resume_text, ai)
        except (json.JSONDecodeError, Exception) as e:
            print(f"  ERROR extracting {meta['name']}: {e}")
            continue

        profile = {
            "id": meta["id"],
            "name": meta["name"],
            "file": meta["file"],
            "positioning": meta["positioning"],
            **extracted,
        }
        profiles.append(profile)
        print(f"  Done: {len(profile.get('key_experiences', []))} experiences, "
              f"{len(profile.get('key_metrics', []))} metrics extracted")

    if not profiles:
        print("No profiles extracted. Check that PDFs are in the resumes/ directory.")
        sys.exit(1)

    output = {"resumes": profiles}
    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(OUTPUT_PATH, "w") as f:
        json.dump(output, f, indent=2)

    print(f"\nSaved {len(profiles)} resume profiles to {OUTPUT_PATH}")


if __name__ == "__main__":
    main()
