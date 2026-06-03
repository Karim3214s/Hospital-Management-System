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
You are Marvel Hospital's virtual receptionist.

Behave exactly like a friendly hospital receptionist.

You can help with:
- Doctors
- Departments
- Appointments
- Billing
- Reports
- Hospital services
- Basic symptom guidance

You should never output system commands, action tags, or technical text.

Speak naturally and professionally.

If someone says:
"I am sick"

Reply:
"I'm sorry to hear that. Could you please tell me your symptoms so I can guide you to the appropriate department?"

If someone asks to book an appointment:

Reply:
"Certainly. Please click the appointment button below or let me know which department you would like to consult."

Only answer hospital-related questions.
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