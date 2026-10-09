import os
import sys
import json
import time
import asyncio
import asyncpg
import re
import dotenv
from openai import AsyncOpenAI

dotenv.load_dotenv()

# Initialize Token Factory Client
client = AsyncOpenAI(
    base_url="https://api.tokenfactory.nebius.com/v1/",
    api_key=os.environ.get("NEBIUS_API_KEY")
)

# EXACT MODEL IDs (Update ULTRA_MODEL to match what you used in Phase 3)
NANO_MODEL = "nvidia/NVIDIA-Nemotron-3-Nano-30B-A3B"
SUPER_MODEL = "nvidia/nemotron-3-super-120b-a12b"
ULTRA_MODEL = "nvidia/Nemotron-3-Ultra-550b-a55b" 

def safe_parse_json(raw_text):
    """Safely extract JSON from model output."""
    if not raw_text: return {}
    cleaned = re.sub(r"^```(?:json)?\s*", "", raw_text.strip(), flags=re.IGNORECASE)
    cleaned = re.sub(r"\s*```$", "", cleaned)
    try:
        return json.loads(cleaned, strict=False)
    except json.JSONDecodeError:
        match = re.search(r"(\{.*\})", cleaned, re.DOTALL)
        if match:
            try:
                return json.loads(match.group(1), strict=False)
            except: pass
        return {}

async def fetch_sales_context(pool):
    """Fetch the latest battlecards and product context from Supabase."""
    async with pool.acquire() as conn:
        our_product = await conn.fetchrow("SELECT name, value_proposition, key_differentiators FROM our_product LIMIT 1")
        battlecards = await conn.fetch("""
            SELECT c.name as competitor, b.executive_summary, b.objection_rebuttal, b.verified_source_url 
            FROM battlecards b
            JOIN competitors c ON b.competitor_id = c.id
            ORDER BY b.created_at DESC LIMIT 5
        """)
        
    context = f"Our Product ({our_product['name']}): {our_product['value_proposition']} | {our_product['key_differentiators']}\n\n"
    context += "LATEST COMPETITOR BATTLECARDS:\n"
    for b in battlecards:
        context += f"- {b['competitor']}: {b['executive_summary']} (Source: {b['verified_source_url']})\n"
        context += f"  Recommended Rebuttal: {b['objection_rebuttal']}\n"
    
    return context

async def triage_query_intent(question: str):
    """Step 4.1: Use Nano to route the query."""
    prompt = (
        "Classify this sales representative's question. Is it a 'COMPLEX' technical/legal/architectural query, "
        "or a 'STANDARD' feature/pricing objection?\n"
        f"Question: {question}\n\n"
        "Return ONLY a JSON object with a single key 'intent' mapping to either 'COMPLEX' or 'STANDARD'."
    )
    
    start_time = time.time()
    response = await client.chat.completions.create(
        model=NANO_MODEL,
        messages=[{"role": "user", "content": prompt}],
        temperature=0.1
    )
    latency = time.time() - start_time
    
    msg = response.choices[0].message
    raw_text = msg.content or getattr(msg, "reasoning_content", "")
    result = safe_parse_json(raw_text)
    
    intent = result.get("intent", "STANDARD").upper()
    if intent not in ["COMPLEX", "STANDARD"]:
        intent = "STANDARD"
        
    return intent, latency

async def generate_copilot_response(question: str, context: str, intent: str):
    """Steps 4.2 & 4.3: Generate grounded response using Super or Ultra."""
    # Escalate to Ultra for complex queries, use Super for standard ones
    target_model = ULTRA_MODEL if intent == "COMPLEX" else SUPER_MODEL
    
    prompt = (
        "You are an expert sales copilot assisting a representative on a live call.\n"
        f"Use the following verified intelligence to answer the rep's question directly and concisely.\n\n"
        f"Context Data:\n{context}\n\n"
        f"Rep's Question: {question}\n\n"
        "Provide a direct counter-argument, pricing breakdown if applicable, and cite the source URL."
    )

    start_time = time.time()
    response = await client.chat.completions.create(
        model=target_model,
        messages=[
            {"role": "system", "content": "You are a sharp, concise enterprise sales copilot."},
            {"role": "user", "content": prompt}
        ],
        temperature=0.3
    )
    latency = time.time() - start_time
    
    return response.choices[0].message.content, target_model, latency

async def main():
    db_url = os.environ.get("DATABASE_URL")
    if not db_url:
        print("[ERROR] DATABASE_URL missing.", file=sys.stderr)
        return

    print("Connecting to nvidia-hack Supabase Database...")
    pool = await asyncpg.create_pool(db_url, min_size=1, max_size=5)
    
    print("Fetching active battlecard context...")
    context = await fetch_sales_context(pool)
    
    print("\n" + "="*50)
    print("🚀 nvidia-hack Live Sales Copilot Initialized")
    print("Type your objection or question below (or 'exit' to quit).")
    print("="*50 + "\n")

    while True:
        # Step 4.1: Sales rep inputs query
        question = input("Sales Rep 👤: ")
        if question.lower() in ['exit', 'quit']:
            break
        if not question.strip():
            continue

        print("\n  [Nano] Triaging query intent...")
        intent, nano_latency = await triage_query_intent(question)
        
        # Step 4.4: Display Telemetry for routing
        print(f"  --> Intent classified as: {intent} (Latency: {nano_latency:.2f}s)")
        
        print(f"  [Generator] Synthesizing grounded response...")
        answer, model_used, gen_latency = await generate_copilot_response(question, context, intent)
        
        print("\nCopilot 🤖:")
        print(answer)
        
        # Step 4.4: Display Telemetry for generation
        print("-" * 50)
        print(f"📡 Telemetry Badge: Routed to {model_used} | Total Latency: {(nano_latency + gen_latency):.2f}s")
        print("=" * 50 + "\n")

    await pool.close()

if __name__ == "__main__":
    asyncio.run(main())