from flask import Flask, jsonify
from flask_cors import CORS
from db import init_db, get_connection
from scheduler import start_scheduler

app = Flask(__name__)
CORS(app, origins=["http://localhost:3000"])

# --------------------------------
# 🧭 API ендпоінти
# --------------------------------
@app.route("/news", methods=["GET"])
def get_news():
    try:
        conn = get_connection()
        cur = conn.cursor(dictionary=True)
        cur.execute("""
            SELECT id, title, link, pubDate, source, shortText, created_at
            FROM news
            ORDER BY pubDate DESC, id DESC
            LIMIT 50
        """)
        rows = cur.fetchall()
        cur.close()
        conn.close()

        return jsonify({
            "status": "ok",
            "count": len(rows),
            "news": rows
        })
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500

# --------------------------------
# 🏁 Старт програми
# --------------------------------
if __name__ == "__main__":
    init_db()
    start_scheduler()
    print("🧭 Scheduler started. API is ready at http://localhost:8000")
    app.run(debug=True, port=8000)
