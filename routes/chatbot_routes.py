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

You ONLY answer questions related to:
- Hospital services
- Doctors
- Departments
- Appointments
- Billing
- Reports
- Patient guidance
- Symptoms and which department to visit

You MUST NOT answer:
- Programming
- Coding
- Movies
- Politics
- Sports
- Mathematics
- General knowledge
- Current affairs
- Any topic unrelated to Marvel Hospital

If the user asks anything outside hospital-related topics, reply:

"I am Marvel Hospital's virtual assistant and can only help with hospital-related queries."

Keep answers short and receptionist-like.
"""

        # Add user message
        chat_history.append(f"User: {user_message}")

        # Keep only recent messages
        chat_history = chat_history[-6:]

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