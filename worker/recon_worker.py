import os
import sys
import asyncio
import asyncpg
import dotenv
from datetime import datetime, timezone
from tavily import TavilyClient

dotenv.load_dotenv()

# Concurrency limit to avoid database/API bottlenecks
MAX_CONCURRENT_COMPETITORS = 3

# Initialize Tavily client globally to reuse the session
tavily_client = TavilyClient(api_key=os.environ.get("TAVILY_API_KEY"))

async def process_single_competitor(conn_pool, job_run_id: str, comp: dict, semaphore: asyncio.Semaphore):
    async with semaphore:
        comp_id = comp["id"]
        comp_name = comp["name"]
        comp_domain = comp["domain"]
        print(f"[{datetime.now(timezone.utc).strftime('%H:%M:%S')}] Starting recon for {comp_name}...")

        try:
            # STEP 1.2: Targeted Live Web Reconnaissance
            search_query = f"site:{comp_domain} pricing OR changelog"
            print(f"  -> Searching Tavily: {search_query}")
            
            search_response = await asyncio.to_thread(
                tavily_client.search,
                query=search_query,
                search_depth="advanced",
                max_results=2
            )

            urls_to_extract = [result['url'] for result in search_response.get('results', [])]

            if not urls_to_extract:
                print(f"  -> No relevant pricing/changelog URLs found for {comp_name}.")
                return True

            # STEP 1.3: Deep Raw Page Extraction
            print(f"  -> Extracting raw Markdown from {len(urls_to_extract)} pages...")
            extract_response = await asyncio.to_thread(
                tavily_client.extract,
                urls=urls_to_extract
            )

            # STEP 1.4: Save to Supabase Staging Table
            async with conn_pool.acquire() as conn:
                for extracted_page in extract_response.get('results', []):
                    source_url = extracted_page['url']
                    raw_markdown = extracted_page['raw_content']
                    
                    # Tag as PRICING if the URL contains 'pricing', otherwise CHANGELOG
                    intel_category = "PRICING" if "pricing" in source_url.lower() else "CHANGELOG"

                    await conn.execute(
                        """
                        INSERT INTO raw_recon_staging 
                        (job_run_id, competitor_id, intel_category, source_url, raw_markdown)
                        VALUES ($1, $2, $3, $4, $5)
                        """,
                        job_run_id, comp_id, intel_category, source_url, raw_markdown
                    )
                
                # Update the timestamp indicating a successful scan
                await conn.execute(
                    "UPDATE competitors SET last_scanned_at = NOW() WHERE id = $1", comp_id
                )
                
            print(f"[SUCCESS] Saved extracted data for {comp_name}")
            return True
            
        except Exception as e:
            print(f"[ERROR] Failed recon for {comp_name}: {str(e)}", file=sys.stderr)
            return False

async def main():
    db_url = os.environ.get("DATABASE_URL")
    if not db_url:
        raise ValueError("DATABASE_URL environment variable is missing.")

    print("Connecting to Supabase...")
    pool = await asyncpg.create_pool(db_url, min_size=2, max_size=10)

    async with pool.acquire() as conn:
        # Create a tracking record for this batch run
        job_run_id = await conn.fetchval(
            "INSERT INTO recon_job_runs (status, nebius_job_id) VALUES ('RUNNING', 'local-windows-run') RETURNING id"
        )

        # Fetch active competitors from Supabase
        competitors = await conn.fetch("SELECT * FROM competitors WHERE is_active = TRUE")

    print(f"Found {len(competitors)} active competitor(s) to scan.")

    # Execute concurrent extraction tasks
    semaphore = asyncio.Semaphore(MAX_CONCURRENT_COMPETITORS)
    tasks = [process_single_competitor(pool, job_run_id, dict(comp), semaphore) for comp in competitors]
    results = await asyncio.gather(*tasks)
    
    success_count = sum(1 for r in results if r)

    async with pool.acquire() as conn:
        await conn.execute(
            """
            UPDATE recon_job_runs 
            SET status = 'COMPLETED', competitors_scanned = $1, completed_at = NOW()
            WHERE id = $2
            """,
            success_count, job_run_id
        )

    await pool.close()
    print(f"Phase 1 Complete: Successfully scraped {success_count}/{len(competitors)} competitors.")

if __name__ == "__main__":
    asyncio.run(main())