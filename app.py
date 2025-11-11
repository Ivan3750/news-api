from flask import Flask, request, jsonify
from flask_cors import CORS
from db import init_db, get_connection
from scheduler import start_scheduler
from flask_bcrypt import Bcrypt
import jwt
import datetime
import os

app = Flask(__name__)
CORS(app)
bcrypt = Bcrypt(app)

# секрет для JWT
app.config["SECRET_KEY"] = os.environ.get("SECRET_KEY", "supersecretkey123")

# --------------------------------
# 🧭 AUTH
# --------------------------------
@app.route("/api/auth/register", methods=["POST"])
def register():
    try:
        data = request.get_json()
        name = data.get("name")
        email = data.get("email")
        password = data.get("password")

        if not all([email, password, name]):
            return jsonify({"error": "Missing fields"}), 400

        conn = get_connection()
        cur = conn.cursor(dictionary=True)

        # перевірка чи існує email
        cur.execute("SELECT id FROM users WHERE email = %s", (email,))
        if cur.fetchone():
            cur.close()
            conn.close()
            return jsonify({"error": "Email already registered"}), 400

        password_hash = bcrypt.generate_password_hash(password).decode("utf-8")

        cur.execute(
            "INSERT INTO users (name, email, password_hash) VALUES (%s, %s, %s)",
            (name, email, password_hash),
        )
        conn.commit()
        user_id = cur.lastrowid

        # створення JWT токена
        token = jwt.encode(
            {
                "user_id": user_id,
                "email": email,
                "exp": datetime.datetime.utcnow() + datetime.timedelta(days=7),
            },
            app.config["SECRET_KEY"],
            algorithm="HS256",
        )

        cur.close()
        conn.close()

        return jsonify(
            {
                "status": "ok",
                "user": {"id": user_id, "name": name, "email": email},
                "token": token,
            }
        )

    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/api/auth/login", methods=["POST"])
def login():
    try:
        data = request.get_json()
        email = data.get("email")
        password = data.get("password")

        conn = get_connection()
        cur = conn.cursor(dictionary=True)
        cur.execute("SELECT * FROM users WHERE email = %s", (email,))
        user = cur.fetchone()

        if not user or not bcrypt.check_password_hash(user["password_hash"], password):
            return jsonify({"error": "Invalid email or password"}), 401

        token = jwt.encode(
            {
                "user_id": user["id"],
                "email": user["email"],
                "exp": datetime.datetime.utcnow() + datetime.timedelta(days=7),
            },
            app.config["SECRET_KEY"],
            algorithm="HS256",
        )

        cur.close()
        conn.close()

        return jsonify(
            {
                "status": "ok",
                "user": {"id": user["id"], "name": user["name"], "email": user["email"]},
                "token": token,
            }
        )

    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route("/news", methods=["GET"])
def get_news():
    try:
        conn = get_connection()
        cur = conn.cursor(dictionary=True)
        cur.execute("""
            SELECT id, title, link, pubDate, source, shortText, created_at, classified
            FROM news
            ORDER BY pubDate DESC, id DESC
            LIMIT 300
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
# 🏁 App startup
# --------------------------------
if __name__ == "__main__":
    # Initialize database and scheduler
    init_db()
    start_scheduler()

    # Get port from environment (for Render or Heroku)
    port = int(os.environ.get("PORT", 8000))
    print(f"🧭 Scheduler started. API is ready at http://0.0.0.0:{port}")

    # Run Flask on 0.0.0.0
    app.run(host="0.0.0.0", port=port, debug=True)
