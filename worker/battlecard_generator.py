import os
import sys
import json
import re
import asyncio
import asyncpg
import dotenv
from openai import AsyncOpenAI

dotenv.load_dotenv()

def safe_parse_json(response):
    """Extracts and parses JSON safely, tolerating unescaped newlines and code fences."""
    msg = response.choices[0].message
    raw_text = msg.content or getattr(msg, "reasoning_content", None)
    
    if not raw_text:
        return {}

    # Strip markdown code blocks like ```json ... ```
    cleaned = re.sub(r"^```(?:json)?\s*", "", raw_text.strip(), flags=re.IGNORECASE)
    cleaned = re.sub(r"\s*```$", "", cleaned)
    
    try:
        # strict=False allows literal newlines/tabs inside JSON string fields
        return json.loads(cleaned, strict=False)
    except json.JSONDecodeError:
        # Fallback: find outer-most JSON curly braces
        match = re.search(r"(\{.*\})", cleaned, re.DOTALL)
        if match:
            try:
                return json.loads(match.group(1), strict=False)
            except json.JSONDecodeError:
                pass
        return {}

# The client is now passed as an argument to ensure it uses the active event loop
async def filter_and_extract_diff(client, raw_markdown: str, baseline_summary: str):
    print("    [Nemotron Nano] Evaluating significance score (1-10)...")
    triage_prompt = (
        "Evaluate this website update. Is it a significant pricing or feature change? "
        "Score 1-10. You must return ONLY raw valid JSON with keys 'significance_score' (int) and 'category' (str). "
        "Do not wrap in markdown or backticks.\n\n"
        f"Data:\n{raw_markdown[:3500]}"
    )
    
    nano_response = await client.chat.completions.create(
        model="nvidia/NVIDIA-Nemotron-3-Nano-30B-A3B",
        messages=[{"role": "user", "content": triage_prompt}],
        temperature=0.1
    )
    
    triage_result = safe_parse_json(nano_response)
    score = triage_result.get("significance_score", 0)
    
    if score < 6:
        print(f"    [Noise Filtered] Update discarded (Score: {score}/10).")
        return None, score

    print(f"    [Nemotron Super] Significant change detected (Score: {score}/10). Extracting delta...")
    diff_prompt = (
        "Compare the old baseline to the new web data. Isolate the exact changes.\n"
        "Return ONLY raw valid JSON with keys 'previous_state' and 'new_state'. "
        "Do not include explanation or markdown code fences.\n\n"
        f"Old Baseline:\n{baseline_summary}\n\n"
        f"New Data:\n{raw_markdown[:3500]}"
    )
    
    super_response = await client.chat.completions.create(
        model="nvidia/nemotron-3-super-120b-a12b",
        messages=[
            {"role": "system", "content": "You are a precise data diff extractor. Output valid JSON only."},
            {"role": "user", "content": diff_prompt}
        ],
        temperature=0.1
    )
    
    diff_data = safe_parse_json(super_response)
    return diff_data, score

async def main():
    db_url = os.environ.get("DATABASE_URL")
    nebius_key = os.environ.get("NEBIUS_API_KEY")
    
    if not db_url:
        print("[ERROR] DATABASE_URL environment variable is missing.", file=sys.stderr)
        sys.exit(1)
    if not nebius_key:
        print("[ERROR] NEBIUS_API_KEY environment variable is missing. Did you open a new PowerShell window?", file=sys.stderr)
        sys.exit(1)

    # Initialize client INSIDE the main event loop with auto-retries enabled
    client = AsyncOpenAI(
        base_url="https://api.tokenfactory.nebius.com/v1/",
        api_key=nebius_key,
        timeout=30.0,
        max_retries=3
    )

    print("Connecting to Supabase Database...")
    pool = await asyncpg.create_pool(db_url, min_size=1, max_size=5)
    
    async with pool.acquire() as conn:
        staging_rows = await conn.fetch("SELECT * FROM raw_recon_staging WHERE processed = FALSE")
        print(f"Found {len(staging_rows)} unprocessed row(s) in raw_recon_staging.\n")

        if not staging_rows:
            print("No new data to process.")
            await pool.close()
            return

        for row in staging_rows:
            staging_id = row['id']
            comp_id = row['competitor_id']
            category = row['intel_category']
            raw_markdown = row['raw_markdown']
            source_url = row['source_url']

            print(f"--> Processing staging ID {staging_id} ({source_url})")

            snapshot = await conn.fetchrow(
                "SELECT baseline_summary FROM competitor_snapshots WHERE competitor_id = $1 AND intel_category = $2",
                comp_id, category
            )
            baseline = snapshot['baseline_summary'] if snapshot else "No previous baseline available."

            try:
                diff_result, score = await filter_and_extract_diff(client, raw_markdown, baseline)

                await conn.execute(
                    "UPDATE raw_recon_staging SET processed = TRUE, significance_score = $1 WHERE id = $2",
                    score, staging_id
                )

                if diff_result:
                    print(f"    [SUCCESS] Semantic Diff Extracted for ID {staging_id}:")
                    print(json.dumps(diff_result, indent=4))
                print()

            except Exception as e:
                print(f"    [ERROR] Failed processing row {staging_id}: {str(e)}", file=sys.stderr)
                await asyncio.sleep(2) # Brief pause to prevent connection rate limits

    await pool.close()
    print("Phase 2 Execution Complete.")

if __name__ == "__main__":
    asyncio.run(main())