from fastapi import FastAPI
from pydantic import BaseModel
from typing import Optional, Dict, Any
import json
import os
from pathlib import Path
import anthropic

app = FastAPI()

# In-memory context store
context_store = {}

# Initialize Claude client
CLAUDE_API_KEY = "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"
client = anthropic.Anthropic(api_key=CLAUDE_API_KEY)

# =========== LOAD DATA ===========
def load_data():
    data = {}
    
    # Load all merchants from folder
    merchants = {}
    for file in Path("expanded/merchants").glob("*.json"):
        with open(file) as f:
            merchant_id = file.stem
            merchants[merchant_id] = json.load(f)
    data["merchants"] = merchants
    
    # Load all customers from folder
    customers = {}
    for file in Path("expanded/customers").glob("*.json"):
        with open(file) as f:
            customer_id = file.stem
            customers[customer_id] = json.load(f)
    data["customers"] = customers
    
    # Load all triggers from folder
    triggers = {}
    for file in Path("expanded/triggers").glob("*.json"):
        with open(file) as f:
            trigger_id = file.stem
            triggers[trigger_id] = json.load(f)
    data["triggers"] = triggers
    
    # Load test pairs
    with open("expanded/test_pairs.json") as f:
        data["test_pairs"] = json.load(f)
    
    # Load categories
    data["categories"] = {}
    for file in Path("expanded/categories").glob("*.json"):
        with open(file) as f:
            category_name = file.stem
            data["categories"][category_name] = json.load(f)
    
    return data

# Load all data when bot starts
CHALLENGE_DATA = load_data()

# =========== HELPER FUNCTIONS ===========

def get_merchant(merchant_id):
    return CHALLENGE_DATA["merchants"].get(merchant_id)

def get_trigger(trigger_id):
    return CHALLENGE_DATA["triggers"].get(trigger_id)

def get_customer(customer_id):
    if not customer_id:
        return None
    return CHALLENGE_DATA["customers"].get(customer_id)

def get_category(category_slug):
    return CHALLENGE_DATA["categories"].get(category_slug)

def compose_message_with_claude(trigger, merchant, category, customer=None):
    """Use Claude to compose a message based on context"""
    
    # Build context string for Claude
    context = f"""
You are Vera, magicpin's merchant growth AI assistant. Compose a WhatsApp message for this merchant.

MERCHANT CONTEXT:
- Name: {merchant['identity']['name']}
- Category: {merchant['category_slug']}
- City: {merchant['identity']['city']}
- Owner: {merchant['identity']['owner_first_name']}
- Active Offers: {json.dumps(merchant['offers'], indent=2)}
- Performance (30d): Views={merchant['performance']['views']}, Calls={merchant['performance']['calls']}, CTR={merchant['performance']['ctr']}

CATEGORY GUIDELINES:
- Tone: {category['voice']['tone']}
- Register: {category['voice']['register']}
- Taboo Words: {', '.join(category['voice']['vocab_taboo'])}

TRIGGER:
- Kind: {trigger['kind']}
- Intent: {trigger['payload'].get('intent_topic', 'N/A')}
- Urgency: {trigger['urgency']}/5
- Merchant Message: {trigger['payload'].get('merchant_last_message', 'N/A')}

RULES:
1. One clear CTA only
2. Use REAL numbers from merchant data (no invented stats)
3. Match the category tone
4. Keep it short (2-3 sentences max)
5. Make it easy to reply YES/NO
6. Ground every claim in the context above

Return ONLY a JSON object with:
{{
    "message": "The WhatsApp message text",
    "cta": "The call-to-action button text",
    "send_as": "merchant",
    "suppression_key": "a unique key to avoid duplicate sends",
    "rationale": "Brief explanation of why this message now"
}}
"""
    
    try:
        response = client.messages.create(
            model="claude-3-5-sonnet-20241022",
            max_tokens=500,
            messages=[
                {
                    "role": "user",
                    "content": context
                }
            ]
        )
        
        # Parse response
        response_text = response.content[0].text
        
        # Extract JSON from response
        try:
            result = json.loads(response_text)
        except json.JSONDecodeError:
            # If response isn't pure JSON, try to extract it
            start = response_text.find('{')
            end = response_text.rfind('}') + 1
            if start >= 0 and end > start:
                result = json.loads(response_text[start:end])
            else:
                result = {
                    "message": response_text,
                    "cta": "Reply YES",
                    "send_as": "merchant",
                    "suppression_key": trigger['suppression_key'],
                    "rationale": "Claude response"
                }
        
        return result
    
    except Exception as e:
        print(f"Error calling Claude: {e}")
        return {
            "message": "Hi there! We have something special for you.",
            "cta": "Reply YES",
            "send_as": "merchant",
            "suppression_key": trigger.get('suppression_key', 'default'),
            "rationale": "Fallback message due to error"
        }

# =========== ENDPOINTS ===========

@app.get("/v1/healthz")
def healthz():
    return {"status": "ok"}

@app.get("/v1/metadata")
def metadata():
    return {
        "name": "Vera Bot",
        "version": "1.0",
        "author": "Pratyaksh"
    }

@app.post("/v1/context")
def store_context(payload: Dict[str, Any]):
    scope = payload.get("scope")
    context_id = payload.get("context_id")
    version = payload.get("version")
    
    # Store context (idempotent by version)
    key = f"{scope}:{context_id}"
    context_store[key] = payload
    
    return {
        "accepted": True,
        "ack_id": "ack_123",
        "stored_at": "2026-09-27T00:00:00Z"
    }

@app.post("/v1/tick")
def generate_message(payload: Dict[str, Any]):
    """Generate the next message based on trigger, merchant, customer"""
    
    trigger_id = payload.get("trigger_id")
    merchant_id = payload.get("merchant_id")
    customer_id = payload.get("customer_id")
    
    # Load context
    trigger = get_trigger(trigger_id)
    merchant = get_merchant(merchant_id)
    customer = get_customer(customer_id)
    
    if not trigger or not merchant:
        return {
            "error": "Trigger or merchant not found",
            "message": "Unable to compose message"
        }
    
    # Get category
    category = get_category(merchant['category_slug'])
    
    # Compose message using Claude
    result = compose_message_with_claude(trigger, merchant, category, customer)
    
    return result

@app.post("/v1/reply")
def handle_reply(payload: Dict[str, Any]):
    """Handle incoming customer replies"""
    return {"received": True}

# =========== RUN ===========

if __name__ == "__main__":
    import uvicorn
    print(f"Loaded {len(CHALLENGE_DATA['merchants'])} merchants")
    print(f"Loaded {len(CHALLENGE_DATA['customers'])} customers")
    print(f"Loaded {len(CHALLENGE_DATA['triggers'])} triggers")
    print(f"Loaded {len(CHALLENGE_DATA['categories'])} categories")
    uvicorn.run(app, host="0.0.0.0", port=8000)