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

# Pass 'client' into the Phase 3 function to maintain the stable connection pool
async def generate_sales_battlecard(client, competitor_name: str, structured_diff: dict, our_product_context: str):
    print(f"    [Nemotron 3 Ultra] Synthesizing sales strategy for {competitor_name}...")
    
    strategy_prompt = (
        f"Competitor '{competitor_name}' made this update: {json.dumps(structured_diff)}\n\n"
        f"Our product baseline capabilities: {our_product_context}\n\n"
        "Write a strategic sales battlecard. You must output ONLY raw valid JSON with exactly these keys: "
        "'executive_summary' (string: a 2-sentence bottom-line overview), "
        "'landmine_questions' (list of 2 strings: trap questions for sales reps to ask prospects to expose the competitor's weakness), "
        "and 'objection_rebuttal' (string: direct script handling a prospect objection).\n"
        "Do not include explanation or markdown code fences."
    )

    ultra_response = await client.chat.completions.create(
        # Note: If this 404s, replace with exact Ultra ID from Nebius Models Catalog
        model="nvidia/Nemotron-3-Ultra-550b-a55b", 
        messages=[
            {"role": "system", "content": "You are an expert enterprise software sales strategist. Output valid JSON only."},
            {"role": "user", "content": strategy_prompt}
        ],
        temperature=0.2
    )
    
    return safe_parse_json(ultra_response)

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
            print("No new data to process. Verify raw_recon_staging has unhandled rows.")
            return # Safely exit without deadlocking the pool

        # Fetch your own product's context once to use in Phase 3
        our_product_row = await conn.fetchrow("SELECT name, value_proposition, key_differentiators FROM our_product LIMIT 1")
        our_context = f"{our_product_row['name']}: {our_product_row['value_proposition']} Differentiators: {our_product_row['key_differentiators']}"

        for row in staging_rows:
            staging_id = row['id']
            comp_id = row['competitor_id']
            category = row['intel_category']
            raw_markdown = row['raw_markdown']
            source_url = row['source_url']

            # Fetch competitor name for the prompt
            comp_row = await conn.fetchrow("SELECT name FROM competitors WHERE id = $1", comp_id)
            comp_name = comp_row['name']

            print(f"--> Processing staging ID {staging_id} ({comp_name})")

            snapshot = await conn.fetchrow(
                "SELECT baseline_summary FROM competitor_snapshots WHERE competitor_id = $1 AND intel_category = $2",
                comp_id, category
            )
            baseline = snapshot['baseline_summary'] if snapshot else "No previous baseline available."

            try:
                # PHASE 2: Pass 'client' as the first argument
                diff_result, score = await filter_and_extract_diff(client, raw_markdown, baseline)

                await conn.execute(
                    "UPDATE raw_recon_staging SET processed = TRUE, significance_score = $1 WHERE id = $2",
                    score, staging_id
                )

                if diff_result:
                    print(f"    [SUCCESS] Semantic Diff Extracted for {comp_name}")
                    
                    # PHASE 3: Generate the battlecard using the diff and client
                    battlecard = await generate_sales_battlecard(client, comp_name, diff_result, our_context)
                    
                    if battlecard:
                        print(f"    [SUCCESS] Battlecard generated successfully!")
                        
                        await conn.execute(
                            """
                            INSERT INTO battlecards 
                            (competitor_id, detected_change_type, executive_summary, previous_state, new_state, landmine_questions, objection_rebuttal, verified_source_url)
                            VALUES ($1, $2, $3, $4, $5, $6::jsonb, $7, $8)
                            """,
                            comp_id,
                            category,
                            battlecard.get("executive_summary", "No summary generated."),
                            str(diff_result.get("previous_state", "")),
                            str(diff_result.get("new_state", "")),
                            json.dumps(battlecard.get("landmine_questions", [])),
                            battlecard.get("objection_rebuttal", "No rebuttal generated."),
                            source_url
                        )

                print()

            except Exception as e:
                print(f"    [ERROR] Failed processing row {staging_id}: {str(e)}", file=sys.stderr)
                await asyncio.sleep(2) # Brief pause to prevent connection rate limits

    await pool.close()
    print("Phase 2 & 3 Execution Complete.")

if __name__ == "__main__":
    asyncio.run(main())