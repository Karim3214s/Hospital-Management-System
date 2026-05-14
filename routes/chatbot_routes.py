from flask import Blueprint, request, jsonify, session
import requests

chatbot_bp = Blueprint("chatbot", __name__)


@chatbot_bp.route("/api/chatbot", methods=["POST"])
def chatbot_ai():

    data = request.get_json()
    user_message = data.get("message", "").strip()

    if not user_message:
        return jsonify({"reply": "Please type something."})

    try:
        # 🔹 RESET OLD BAD SESSION FORMAT (IMPORTANT FIX)
        if "chat_history" not in session:
            session["chat_history"] = []

        # Ensure only strings exist (fix previous dict error)
        clean_history = []
        for item in session["chat_history"]:
            if isinstance(item, str):
                clean_history.append(item)

        chat_history = clean_history

        # 🔹 MINIMAL SYSTEM PROMPT (FAST)
        system_prompt = """You are a hospital assistant.

Use action tags when needed:
- booking → ACTION:BOOK_APPOINTMENT
- appointments → ACTION:VIEW_APPOINTMENTS
- billing → ACTION:VIEW_BILL
- doctors → ACTION:VIEW_DOCTORS

Keep answers short.
"""

        # 🔹 ADD USER MESSAGE
        chat_history.append(f"User: {user_message}")

        # 🔹 LIMIT HISTORY (VERY IMPORTANT FOR SPEED)
        chat_history = chat_history[-1:]

        # 🔹 BUILD PROMPT
        chat_text = "\n".join(chat_history)
        full_prompt = system_prompt + "\n\n" + chat_text + "\nAssistant:"

        # 🔥 FAST MODEL CALL (CHANGE MODEL HERE IF NEEDED)
        res = requests.post(
            "http://localhost:11434/api/generate",
            json={
                "model": "phi",   # ⚡ FAST MODEL (change to mistral if not installed)
                "prompt": full_prompt,
                "stream": False
            },
            timeout=120
        )

        print("STATUS:", res.status_code)
        print("RAW:", res.text)

        if res.status_code != 200:
            return jsonify({"reply": "⚠️ Ollama API error"})

        result = res.json()
        reply = result.get("response", "").strip()

        if not reply:
            return jsonify({"reply": "⚠️ Empty AI response"})

        # 🔹 SAVE RESPONSE
        chat_history.append(f"Assistant: {reply}")
        session["chat_history"] = chat_history

        return jsonify({"reply": reply})

    except requests.exceptions.ConnectionError:
        return jsonify({"reply": "⚠️ Ollama is not running. Start it first."})

    except requests.exceptions.Timeout:
        return jsonify({"reply": "⚠️ AI is slow. Try again."})

    except Exception as e:
        print("🔥 ERROR:", str(e))
        return jsonify({"reply": "🤖 Backend error. Check logs."})