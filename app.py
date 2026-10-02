#!/usr/bin/env python3
"""Career Bridge Japan MVP v2 Flask application."""

from __future__ import annotations

import csv
import hashlib
import hmac
import io
import json
import os
import secrets
import sqlite3
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import quote

from flask import Flask, Response, jsonify, redirect, request, send_from_directory
from werkzeug.middleware.proxy_fix import ProxyFix

ROOT = Path(__file__).resolve().parent
DB_PATH = ROOT / "data" / "career_bridge.db"
STATIC = ROOT / "static"

PRODUCTION = os.getenv("APP_ENV", "").lower() == "production" or os.getenv("RENDER", "").lower() == "true"
HOST = os.getenv("HOST", "0.0.0.0" if PRODUCTION else "127.0.0.1")
PORT = int(os.getenv("PORT", "8000"))
ADMIN_EMAIL = os.getenv("ADMIN_EMAIL", "admin@example.com")
ADMIN_PASSWORD = os.getenv("ADMIN_PASSWORD", "change-me")
SESSION_SECRET_TEXT = os.getenv("SESSION_SECRET", "dev-only-change-this-secret")
SESSION_SECRET = SESSION_SECRET_TEXT.encode()
LINE_OFFICIAL_URL = os.getenv("LINE_OFFICIAL_URL", "https://line.me/")
SUPABASE_URL = os.getenv("SUPABASE_URL", "").rstrip("/")
SUPABASE_SERVICE_ROLE_KEY = os.getenv("SUPABASE_SERVICE_ROLE_KEY", "")
COOKIE_SECURE = os.getenv("COOKIE_SECURE", "true" if PRODUCTION else "false").lower() == "true"
SUPABASE_CONFIGURED = bool(
    SUPABASE_URL
    and SUPABASE_SERVICE_ROLE_KEY
    and "your-project" not in SUPABASE_URL
    and SUPABASE_SERVICE_ROLE_KEY != "your-service-role-key"
)

SCORE_WEIGHTS = {
    "job_intent": 25,
    "start_timing": 20,
    "residence_work_feasibility": 20,
    "experience_skills": 15,
    "japanese_level": 10,
    "english_other": 5,
    "cv_readiness": 5,
}
STATUSES = {"new", "contacted", "interview", "shortlisted", "placed", "rejected", "on_hold"}
PUBLIC_FIELDS = [
    "full_name", "email", "phone", "nationality", "current_country", "residence_status",
    "work_permission", "desired_jobs", "job_intent", "japanese_level", "english_level",
    "other_languages", "years_experience", "skills", "start_timing", "cv_readiness",
    "interview_datetime", "timezone", "notes", "privacy_consent", "contact_consent",
]

app = Flask(__name__, static_folder=str(STATIC), static_url_path="/static")
app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1, x_host=1)


def now_iso():
    return datetime.now(timezone.utc).isoformat()


def validate_production_config():
    if not PRODUCTION:
        return
    missing = []
    if not SUPABASE_CONFIGURED:
        missing.extend(["SUPABASE_URL", "SUPABASE_SERVICE_ROLE_KEY"])
    if not ADMIN_EMAIL or ADMIN_EMAIL == "admin@example.com":
        missing.append("ADMIN_EMAIL")
    if not ADMIN_PASSWORD or ADMIN_PASSWORD == "change-me":
        missing.append("ADMIN_PASSWORD")
    if len(SESSION_SECRET_TEXT) < 32 or SESSION_SECRET_TEXT == "dev-only-change-this-secret":
        missing.append("SESSION_SECRET")
    if not LINE_OFFICIAL_URL.startswith("https://") or "replace-me" in LINE_OFFICIAL_URL:
        missing.append("LINE_OFFICIAL_URL")
    if missing:
        raise RuntimeError("Missing or unsafe production configuration: " + ", ".join(sorted(set(missing))))


def init_db():
    if PRODUCTION:
        return
    DB_PATH.parent.mkdir(exist_ok=True)
    with sqlite3.connect(DB_PATH) as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS candidates (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                candidate_id TEXT UNIQUE NOT NULL,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'new',
                score INTEGER NOT NULL,
                priority TEXT NOT NULL,
                score_breakdown TEXT NOT NULL,
                full_name TEXT NOT NULL,
                email TEXT NOT NULL,
                phone TEXT,
                nationality TEXT,
                current_country TEXT,
                residence_status TEXT,
                work_permission TEXT,
                desired_jobs TEXT,
                job_intent TEXT,
                japanese_level TEXT,
                english_level TEXT,
                other_languages TEXT,
                years_experience TEXT,
                skills TEXT,
                start_timing TEXT,
                cv_readiness TEXT,
                interview_datetime TEXT,
                timezone TEXT,
                notes TEXT,
                privacy_consent INTEGER NOT NULL,
                contact_consent INTEGER NOT NULL
            )
        """)


def score_candidate(data):
    ratios = {
        "job_intent": {"actively_looking": 1, "open_to_offers": .7, "researching": .35}.get(data.get("job_intent"), 0),
        "start_timing": {"immediately": 1, "within_1_month": .9, "within_3_months": .7, "within_6_months": .45, "later": .2}.get(data.get("start_timing"), 0),
        "residence_work_feasibility": 1 if data.get("work_permission") == "yes" else .55 if data.get("work_permission") == "needs_support" else .15,
        "experience_skills": min(1, {"0": .2, "1-2": .5, "3-5": .8, "6+": 1}.get(data.get("years_experience"), 0) + (.15 if data.get("skills", "").strip() else 0)),
        "japanese_level": {"native": 1, "n1": 1, "n2": .85, "n3": .65, "n4": .4, "n5": .2, "none": 0}.get(data.get("japanese_level"), 0),
        "english_other": min(1, {"native": 1, "business": .9, "conversational": .65, "basic": .35, "none": 0}.get(data.get("english_level"), 0) + (.15 if data.get("other_languages", "").strip() else 0)),
        "cv_readiness": {"ready": 1, "needs_update": .6, "need_help": .25}.get(data.get("cv_readiness"), 0),
    }
    breakdown = {key: round(SCORE_WEIGHTS[key] * ratios[key]) for key in SCORE_WEIGHTS}
    total = sum(breakdown.values())
    priority = "high" if total >= 75 else "medium" if total >= 50 else "low"
    return total, priority, breakdown


def make_candidate_id():
    return f"CBJ-{datetime.now().strftime('%Y%m%d')}-{secrets.token_hex(2).upper()}"


def normalize(data):
    return {
        key: data.get(key, "").strip() if isinstance(data.get(key, ""), str) else data.get(key, "")
        for key in PUBLIC_FIELDS
    }


def validate_candidate(data):
    required = [
        "full_name", "email", "current_country", "residence_status", "work_permission",
        "desired_jobs", "job_intent", "japanese_level", "english_level", "years_experience",
        "skills", "start_timing", "cv_readiness", "interview_datetime", "timezone",
    ]
    missing = [field for field in required if not data.get(field)]
    if missing:
        return f"Missing required fields: {', '.join(missing)}"
    if "@" not in data["email"]:
        return "Please enter a valid email address."
    if data.get("privacy_consent") is not True:
        return "Privacy consent is required."
    return None


def db_rows(priority="", status="", query=""):
    sql, params = "SELECT * FROM candidates WHERE 1=1", []
    if priority in {"high", "medium", "low"}:
        sql += " AND priority=?"
        params.append(priority)
    if status in STATUSES:
        sql += " AND status=?"
        params.append(status)
    if query:
        sql += " AND (full_name LIKE ? OR email LIKE ? OR candidate_id LIKE ?)"
        params.extend([f"%{query}%"] * 3)
    sql += " ORDER BY created_at DESC"
    with sqlite3.connect(DB_PATH) as conn:
        conn.row_factory = sqlite3.Row
        return [dict(row) for row in conn.execute(sql, params)]


def supabase_request(method, path, payload=None, prefer="return=representation"):
    if not SUPABASE_CONFIGURED:
        raise RuntimeError("Supabase is not configured")
    body = json.dumps(payload).encode() if payload is not None else None
    req = urllib.request.Request(
        f"{SUPABASE_URL}/rest/v1/{path}",
        data=body,
        method=method,
        headers={
            "apikey": SUPABASE_SERVICE_ROLE_KEY,
            "Authorization": f"Bearer {SUPABASE_SERVICE_ROLE_KEY}",
            "Content-Type": "application/json",
            "Prefer": prefer,
        },
    )
    with urllib.request.urlopen(req, timeout=12) as response:
        raw = response.read()
        return json.loads(raw) if raw else []


def save_candidate(data):
    score, priority, breakdown = score_candidate(data)
    record = {
        **data,
        "candidate_id": make_candidate_id(),
        "created_at": now_iso(),
        "updated_at": now_iso(),
        "status": "new",
        "score": score,
        "priority": priority,
        "score_breakdown": breakdown,
        "privacy_consent": bool(data["privacy_consent"]),
        "contact_consent": bool(data.get("contact_consent")),
    }
    if SUPABASE_CONFIGURED:
        for _ in range(3):
            try:
                result = supabase_request("POST", "candidates", record)
                return result[0] if result else record
            except urllib.error.HTTPError as exc:
                if exc.code != 409:
                    raise
                record["candidate_id"] = make_candidate_id()
    if PRODUCTION:
        raise RuntimeError("Supabase is required in production")
    local = record.copy()
    local["score_breakdown"] = json.dumps(breakdown)
    local["privacy_consent"] = int(record["privacy_consent"])
    local["contact_consent"] = int(record["contact_consent"])
    columns = list(local)
    with sqlite3.connect(DB_PATH) as conn:
        conn.execute(
            f"INSERT INTO candidates ({','.join(columns)}) VALUES ({','.join('?' for _ in columns)})",
            [local[column] for column in columns],
        )
    return record


def sign_session(email):
    payload = f"{email}|{int(datetime.now().timestamp())}"
    signature = hmac.new(SESSION_SECRET, payload.encode(), hashlib.sha256).hexdigest()
    return f"{payload}|{signature}"


def valid_session(value):
    try:
        email, issued, signature = value.rsplit("|", 2)
        expected = hmac.new(SESSION_SECRET, f"{email}|{issued}".encode(), hashlib.sha256).hexdigest()
        age = datetime.now().timestamp() - int(issued)
        return email == ADMIN_EMAIL and hmac.compare_digest(signature, expected) and 0 <= age < 43200
    except Exception:
        return False


def session_ok():
    return valid_session(request.cookies.get("cbj_admin", ""))


def candidate_rows():
    priority = request.args.get("priority", "")
    status = request.args.get("status", "")
    query = request.args.get("q", "").strip()
    if not SUPABASE_CONFIGURED:
        return db_rows(priority, status, query)
    suffix = "candidates?select=*&order=created_at.desc"
    if priority in {"high", "medium", "low"}:
        suffix += f"&priority=eq.{priority}"
    if status in STATUSES:
        suffix += f"&status=eq.{status}"
    if query:
        encoded = quote(query, safe="")
        suffix += f"&or=(full_name.ilike.*{encoded}*,email.ilike.*{encoded}*,candidate_id.ilike.*{encoded}*)"
    rows = supabase_request("GET", suffix) or []
    for row in rows:
        if isinstance(row.get("score_breakdown"), str):
            row["score_breakdown"] = json.loads(row["score_breakdown"])
    return rows


def page(filename):
    return send_from_directory(STATIC, filename)


@app.after_request
def security_headers(response):
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
    response.headers["Permissions-Policy"] = "camera=(), microphone=(), geolocation=()"
    return response


@app.get("/")
def home(): return page("index.html")


@app.get("/apply")
def apply_page(): return page("apply.html")


@app.get("/success")
def success_page(): return page("success.html")


@app.get("/privacy")
def privacy_page(): return page("privacy.html")


@app.get("/terms")
def terms_page(): return page("terms.html")


@app.get("/about")
def about_page(): return page("about.html")


@app.get("/admin/login")
def admin_login_page(): return page("admin-login.html")


@app.get("/admin")
def admin_page():
    return page("admin.html") if session_ok() else redirect("/admin/login")


@app.get("/healthz")
def healthcheck():
    storage_ready = SUPABASE_CONFIGURED if PRODUCTION else True
    return jsonify({"status": "ok" if storage_ready else "misconfigured"}), 200 if storage_ready else 503


@app.get("/api/config")
def api_config():
    return jsonify({"lineUrl": LINE_OFFICIAL_URL, "storage": "supabase" if SUPABASE_CONFIGURED else "local"})


@app.get("/api/admin/session")
def api_admin_session():
    return jsonify({"authenticated": session_ok()}), 200 if session_ok() else 401


@app.get("/api/admin/candidates")
def api_admin_candidates():
    if not session_ok():
        return jsonify({"error": "Unauthorized"}), 401
    return jsonify(candidate_rows())


@app.get("/api/admin/candidates/export")
def api_admin_export():
    if not session_ok():
        return jsonify({"error": "Unauthorized"}), 401
    rows = candidate_rows()
    output = io.StringIO()
    fields = ["candidate_id", "created_at", "status", "score", "priority"] + PUBLIC_FIELDS
    writer = csv.DictWriter(output, fieldnames=fields, extrasaction="ignore")
    writer.writeheader()
    writer.writerows(rows)
    return Response(
        output.getvalue().encode("utf-8-sig"),
        mimetype="text/csv",
        headers={"Content-Disposition": "attachment; filename=candidates.csv"},
    )


@app.post("/api/candidates")
def api_create_candidate():
    data = request.get_json(silent=True) or {}
    clean = normalize(data)
    clean["privacy_consent"] = data.get("privacy_consent") is True
    clean["contact_consent"] = data.get("contact_consent") is True
    error = validate_candidate(clean)
    if error:
        return jsonify({"error": error}), 400
    try:
        record = save_candidate(clean)
        return jsonify({"candidate_id": record["candidate_id"], "score": record["score"], "priority": record["priority"]}), 201
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode(errors="replace")
        app.logger.error("Supabase HTTP error %s: %s", exc.code, detail)
        return jsonify({"error": "Cloud database request failed. Please try again."}), 502
    except Exception:
        app.logger.exception("Candidate save failed")
        return jsonify({"error": "Unable to save. Please try again."}), 500


@app.post("/api/admin/login")
def api_admin_login():
    data = request.get_json(silent=True) or {}
    email_ok = hmac.compare_digest(str(data.get("email", "")), ADMIN_EMAIL)
    password_ok = hmac.compare_digest(str(data.get("password", "")), ADMIN_PASSWORD)
    if not (email_ok and password_ok):
        return jsonify({"error": "Invalid email or password"}), 401
    response = jsonify({"ok": True})
    response.set_cookie(
        "cbj_admin",
        sign_session(ADMIN_EMAIL),
        max_age=43200,
        httponly=True,
        secure=COOKIE_SECURE,
        samesite="Strict",
        path="/",
    )
    return response


@app.post("/api/admin/logout")
def api_admin_logout():
    response = jsonify({"ok": True})
    response.delete_cookie("cbj_admin", path="/", secure=COOKIE_SECURE, httponly=True, samesite="Strict")
    return response


@app.patch("/api/admin/candidates/<candidate_id>")
def api_update_candidate(candidate_id):
    if not session_ok():
        return jsonify({"error": "Unauthorized"}), 401
    data = request.get_json(silent=True) or {}
    status = data.get("status")
    if status not in STATUSES:
        return jsonify({"error": "Invalid status"}), 400
    if SUPABASE_CONFIGURED:
        encoded_id = quote(candidate_id, safe="")
        supabase_request("PATCH", f"candidates?candidate_id=eq.{encoded_id}", {"status": status}, "return=minimal")
    else:
        with sqlite3.connect(DB_PATH) as conn:
            conn.execute("UPDATE candidates SET status=?, updated_at=? WHERE candidate_id=?", (status, now_iso(), candidate_id))
    return jsonify({"ok": True})


validate_production_config()
init_db()


if __name__ == "__main__":
    print(f"Career Bridge Japan: http://{HOST}:{PORT}")
    print(f"Admin: http://{HOST}:{PORT}/admin")
    if ADMIN_PASSWORD == "change-me":
        print("WARNING: Set ADMIN_PASSWORD before sharing this server.")
    app.run(host=HOST, port=PORT, threaded=True)
