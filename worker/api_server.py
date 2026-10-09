import os
import sys
import time
import json
import re
import asyncpg
import dotenv
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from openai import AsyncOpenAI

dotenv.load_dotenv()

app = FastAPI(title="nvidia-hack Copilot API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

client = AsyncOpenAI(
    base_url="https://api.tokenfactory.nebius.com/v1/",
    api_key=os.environ.get("NEBIUS_API_KEY")
)

NANO_MODEL = "nvidia/NVIDIA-Nemotron-3-Nano-30B-A3B"
SUPER_MODEL = "nvidia/nemotron-3-super-120b-a12b"
ULTRA_MODEL = "nvidia/Nemotron-3-Ultra-550b-a55b" 

def safe_parse_json(raw_text):
    if not raw_text: return {}
    cleaned = re.sub(r"^```(?:json)?\s*", "", raw_text.strip(), flags=re.IGNORECASE)
    cleaned = re.sub(r"\s*```$", "", cleaned)
    try:
        return json.loads(cleaned, strict=False)
    except:
        match = re.search(r"(\{.*\})", cleaned, re.DOTALL)
        if match:
            try: return json.loads(match.group(1), strict=False)
            except: pass
        return {}

class CopilotRequest(BaseModel):
    question: str

@app.post("/api/copilot")
async def copilot_chat(req: CopilotRequest):
    db_url = os.environ.get("DATABASE_URL")
    pool = await asyncpg.create_pool(db_url, min_size=1, max_size=3)
    
    async with pool.acquire() as conn:
        our_product = await conn.fetchrow("SELECT name, value_proposition, key_differentiators FROM our_product LIMIT 1")
        battlecards = await conn.fetch("""
            SELECT c.name as competitor, b.executive_summary, b.objection_rebuttal, b.verified_source_url 
            FROM battlecards b
            JOIN competitors c ON b.competitor_id = c.id
            ORDER BY b.created_at DESC LIMIT 5
        """)
    await pool.close()
    
    context = f"Our Product ({our_product['name']}): {our_product['value_proposition']} | {our_product['key_differentiators']}\n\nBattlecards:\n"
    for b in battlecards:
        context += f"- {b['competitor']}: {b['executive_summary']} (Source: {b['verified_source_url']})\n  Rebuttal: {b['objection_rebuttal']}\n"

    triage_prompt = (
        "Classify this sales objection. Is it 'COMPLEX' (deep technical/compliance) or 'STANDARD' (pricing/feature)?\n"
        f"Question: {req.question}\nReturn ONLY raw JSON with key 'intent'."
    )
    start_triage = time.time()
    nano_res = await client.chat.completions.create(
        model=NANO_MODEL,
        messages=[{"role": "user", "content": triage_prompt}],
        temperature=0.1
    )
    nano_latency = time.time() - start_triage
    raw_nano = nano_res.choices[0].message.content or getattr(nano_res.choices[0].message, "reasoning_content", "")
    intent = safe_parse_json(raw_nano).get("intent", "STANDARD").upper()
    if intent not in ["COMPLEX", "STANDARD"]: intent = "STANDARD"

    target_model = ULTRA_MODEL if intent == "COMPLEX" else SUPER_MODEL
    prompt = (
        "You are an enterprise sales copilot on a live prospect call.\n"
        f"Context Data:\n{context}\n\n"
        f"Rep Question: {req.question}\n"
        "Provide a concise, direct counter-argument citing the source URL."
    )
    start_gen = time.time()
    gen_res = await client.chat.completions.create(
        model=target_model,
        messages=[
            {"role": "system", "content": "You are a sharp, concise enterprise sales copilot."},
            {"role": "user", "content": prompt}
        ],
        temperature=0.3
    )
    gen_latency = time.time() - start_gen

    return {
        "answer": gen_res.choices[0].message.content,
        "model_used": target_model,
        "intent": intent,
        "routing_latency": round(nano_latency, 2),
        "generation_latency": round(gen_latency, 2),
        "total_latency": round(nano_latency + gen_latency, 2)
    }

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("api_server:app", host="0.0.0.0", port=8000, reload=True)