"""Manual production-mode smoke test. Reads secrets only from environment."""

import json
import os
import secrets
import sys
import urllib.parse
import urllib.request
from http.cookies import SimpleCookie


BASE_URL = os.getenv("SMOKE_BASE_URL", "http://127.0.0.1:8011").rstrip("/")
SUPABASE_URL = os.environ["SUPABASE_URL"].rstrip("/")
SUPABASE_KEY = os.environ["SUPABASE_SERVICE_ROLE_KEY"]
candidate_id = None


def request_json(url, method="GET", payload=None, headers=None):
    body = json.dumps(payload).encode() if payload is not None else None
    request = urllib.request.Request(
        url,
        data=body,
        method=method,
        headers={"Content-Type": "application/json", **(headers or {})},
    )
    with urllib.request.urlopen(request, timeout=20) as response:
        raw = response.read()
        return response, json.loads(raw) if raw else None


try:
    _, health = request_json(f"{BASE_URL}/healthz")
    assert health == {"status": "ok"}

    marker = secrets.token_hex(4)
    email = f"render-smoke-{marker}@example.invalid"
    candidate = {
        "full_name": "Render Smoke Test",
        "email": email,
        "phone": "+81-00-0000-0000",
        "nationality": "Canada",
        "current_country": "Japan",
        "residence_status": "work_visa",
        "work_permission": "yes",
        "desired_jobs": "Software support",
        "job_intent": "actively_looking",
        "japanese_level": "n2",
        "english_level": "business",
        "other_languages": "French",
        "years_experience": "3-5",
        "skills": "Python, SQL, customer support",
        "start_timing": "within_1_month",
        "cv_readiness": "ready",
        "interview_datetime": "2026-10-15T14:30",
        "timezone": "Asia/Tokyo (UTC+9)",
        "notes": "Render production smoke test; delete after verification",
        "privacy_consent": True,
        "contact_consent": True,
    }
    _, created = request_json(f"{BASE_URL}/api/candidates", "POST", candidate)
    candidate_id = created["candidate_id"]
    assert candidate_id.startswith("CBJ-")

    login_response, _ = request_json(
        f"{BASE_URL}/api/admin/login",
        "POST",
        {"email": os.environ["ADMIN_EMAIL"], "password": os.environ["ADMIN_PASSWORD"]},
    )
    set_cookie = login_response.headers["Set-Cookie"]
    assert "Secure" in set_cookie
    assert "HttpOnly" in set_cookie
    assert "SameSite=Strict" in set_cookie
    jar = SimpleCookie(set_cookie)
    cookie_header = f"cbj_admin={jar['cbj_admin'].value}"

    query = urllib.parse.urlencode({"q": email})
    _, rows = request_json(
        f"{BASE_URL}/api/admin/candidates?{query}",
        headers={"Cookie": cookie_header},
    )
    assert any(row["candidate_id"] == candidate_id for row in rows)
    print("production_smoke=ok storage=supabase secure_cookie=ok admin_read=ok")
finally:
    if candidate_id:
        encoded = urllib.parse.quote(candidate_id, safe="")
        cleanup = urllib.request.Request(
            f"{SUPABASE_URL}/rest/v1/candidates?candidate_id=eq.{encoded}",
            method="DELETE",
            headers={
                "apikey": SUPABASE_KEY,
                "Authorization": f"Bearer {SUPABASE_KEY}",
                "Prefer": "return=minimal",
            },
        )
        with urllib.request.urlopen(cleanup, timeout=20):
            pass
        print("production_smoke_cleanup=ok")
