from flask import Blueprint, request, jsonify, session
from google import genai
import os

chatbot_bp = Blueprint("chatbot", __name__)

# Gemini Client
client = genai.Client(
    api_key=os.getenv("GEMINI_API_KEY")
)


@chatbot_bp.route("/api/chatbot", methods=["POST"])
def chatbot_ai():

    data = request.get_json()
    user_message = data.get("message", "").strip()

    if not user_message:
        return jsonify({"reply": "Please type something."})

    try:
        # Initialize session history
        if "chat_history" not in session:
            session["chat_history"] = []

        # Keep only valid strings
        clean_history = []
        for item in session["chat_history"]:
            if isinstance(item, str):
                clean_history.append(item)

        chat_history = clean_history

        # System Prompt
        system_prompt = """
You are Marvel Hospital's virtual receptionist assistant.

STRICT RULES:
1. If the user describes ANY symptom (fever, pain, cough, dizziness, etc.), ALWAYS respond by:
   - Empathetically acknowledging the symptom
   - Recommending the appropriate department
   - Asking if they'd like to book an appointment
   NEVER respond to symptoms with fee information.

2. Only provide fee/cost information when the user EXPLICITLY asks about cost, price, fees, or billing.

3. You can help with: doctors, departments, appointments, billing, reports, basic symptom guidance.

4. Speak naturally and professionally like a friendly hospital receptionist.

5. Only answer hospital-related questions. For anything unrelated, politely redirect.

Example:
User: "I have fever"
You: "I'm sorry to hear that. A fever could indicate a viral or bacterial infection. I'd recommend visiting our General Medicine department. Our doctors Dr. Suresh Babu and Dr. Meena Reddy can help. Would you like to book an appointment?"
"""

        # Add user message
        chat_history.append(f"User: {user_message}")

        # Keep only recent messages
        chat_history = chat_history[-10:]

        # Build prompt
        chat_text = "\n".join(chat_history)
        full_prompt = f"{system_prompt}\n\n{chat_text}\nAssistant:"

        # Gemini API Call
        response = client.models.generate_content(
            model="gemini-2.5-flash",
            contents=full_prompt
        )

        reply = response.text.strip()

        if not reply:
            return jsonify({"reply": "⚠️ Empty AI response"})

        # Save response
        chat_history.append(f"Assistant: {reply}")
        session["chat_history"] = chat_history

        return jsonify({"reply": reply})

    except Exception as e:
        print("🔥 ERROR:", str(e))
        return jsonify({"reply": f"🤖 Backend error: {str(e)}"})