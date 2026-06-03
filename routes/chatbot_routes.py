from flask import Blueprint, request, jsonify, session
from google import genai
import os
import time
from collections import defaultdict

chatbot_bp = Blueprint("chatbot", __name__)

# ─────────────────────────────────────────────────────────
# Gemini client
# ─────────────────────────────────────────────────────────
client = genai.Client(api_key=os.getenv("GEMINI_API_KEY"))

# ─────────────────────────────────────────────────────────
# Simple in-memory rate limiter (per session)
# 10 API calls per minute per session
# ─────────────────────────────────────────────────────────
_rate_store = defaultdict(list)
RATE_LIMIT   = 10   # max calls
RATE_WINDOW  = 60   # seconds


def is_rate_limited(session_id: str) -> bool:
    now = time.time()
    calls = _rate_store[session_id]
    # Drop timestamps outside window
    calls = [t for t in calls if now - t < RATE_WINDOW]
    _rate_store[session_id] = calls
    if len(calls) >= RATE_LIMIT:
        return True
    calls.append(now)
    return False


# ─────────────────────────────────────────────────────────
# System prompt — strict hospital-only, no action tags
# ─────────────────────────────────────────────────────────
SYSTEM_PROMPT = """You are the virtual receptionist at Marvel Hospitals. You speak like a warm, professional hospital front-desk assistant.

STRICT RULES:
1. ONLY answer questions related to the hospital: symptoms, departments, doctors, appointments, bills, reports, pharmacy, visiting hours, insurance, procedures, and general medical guidance.
2. If the user asks ANYTHING unrelated to health or the hospital (e.g. weather, sports, coding, cooking), respond ONLY with:
   "I can only assist with hospital and health-related queries. How can I help you today?"
3. NEVER mention fees or consultation costs unless the user explicitly asks about cost, price, fees, or billing.
4. When the user describes symptoms, always:
   - Empathetically acknowledge what they are feeling
   - Reason through the symptoms and recommend the most appropriate department
   - Name the department clearly
   - Ask if they would like to book an appointment
5. For multi-symptom queries, reason carefully. For example:
   - Fever + joint pain + skin rash → could indicate dengue, chikungunya, or viral arthritis → recommend General Medicine with a note to also see Dermatology if rash worsens
   - Chest tightness + breathlessness → Cardiology or Pulmonology
   - Nausea + severe headache → Neurology (rule out migraine, raised ICP)
6. Keep responses concise — 3 to 5 sentences max. No bullet walls. No markdown headers.
7. Never output action tags, system commands, or technical text. Speak naturally.
8. For appointment booking, say: "You can book an appointment online or call us at +91-7569486938."

Remember: You are a receptionist, not a doctor. Always recommend consulting a specialist for diagnosis.
"""


@chatbot_bp.route("/api/chatbot", methods=["POST"])
def chatbot_ai():

    data         = request.get_json(silent=True) or {}
    user_message = data.get("message", "").strip()

    if not user_message:
        return jsonify({"reply": "Please type something."})

    if len(user_message) > 500:
        return jsonify({"reply": "Your message is too long. Please keep it under 500 characters."})

    # ── Rate limiting ─────────────────────────────────────
    sid = session.get("_id") or request.remote_addr
    if is_rate_limited(str(sid)):
        return jsonify({"reply": "You're sending messages too quickly. Please wait a moment."})

    try:
        # ── Session history (last 6 turns = 3 exchanges) ──
        if "chat_history" not in session or not isinstance(session["chat_history"], list):
            session["chat_history"] = []

        history = [h for h in session["chat_history"] if isinstance(h, str)]

        # Build prompt: system + history + new message
        history.append(f"User: {user_message}")
        history = history[-6:]  # Keep only last 6 lines

        full_prompt = SYSTEM_PROMPT + "\n\n" + "\n".join(history) + "\nAssistant:"

        # ── Gemini call ───────────────────────────────────
        response = client.models.generate_content(
            model="gemini-2.5-flash",
            contents=full_prompt
        )

        reply = (response.text or "").strip()

        if not reply:
            return jsonify({"reply": "I didn't get a response. Please try again."})

        # ── Save assistant reply to history ───────────────
        history.append(f"Assistant: {reply}")
        session["chat_history"] = history
        session.modified = True

        return jsonify({"reply": reply})

    except Exception as e:
        print("CHATBOT ERROR:", str(e))
        return jsonify({"reply": "Something went wrong on our end. Please call +91-7569486938 for immediate help."})