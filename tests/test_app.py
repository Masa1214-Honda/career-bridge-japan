import json
import tempfile
import unittest
from pathlib import Path

import app as application


class CareerBridgeTestCase(unittest.TestCase):
    def setUp(self):
        self.tempdir = tempfile.TemporaryDirectory()
        application.DB_PATH = Path(self.tempdir.name) / "test.db"
        application.PRODUCTION = False
        application.SUPABASE_CONFIGURED = False
        application.COOKIE_SECURE = False
        application.init_db()
        application.app.config.update(TESTING=True)
        self.client = application.app.test_client()

    def tearDown(self):
        self.tempdir.cleanup()

    @staticmethod
    def candidate():
        return {
            "full_name": "Render Test Candidate",
            "email": "render-test@example.invalid",
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
            "notes": "Automated test",
            "privacy_consent": True,
            "contact_consent": True,
        }

    def login(self):
        return self.client.post(
            "/api/admin/login",
            json={"email": application.ADMIN_EMAIL, "password": application.ADMIN_PASSWORD},
        )

    def test_pages_and_healthcheck(self):
        for path in ["/", "/apply", "/privacy", "/terms", "/about", "/admin/login", "/healthz"]:
            response = self.client.get(path)
            self.assertEqual(response.status_code, 200, path)
            response.close()

    def test_candidate_admin_and_csv_flow(self):
        created = self.client.post("/api/candidates", json=self.candidate())
        self.assertEqual(created.status_code, 201)
        body = created.get_json()
        self.assertRegex(body["candidate_id"], r"^CBJ-\d{8}-[A-F0-9]{4}$")
        self.assertEqual(body["score"], 95)
        self.assertEqual(body["priority"], "high")

        self.assertEqual(self.login().status_code, 200)
        listed = self.client.get("/api/admin/candidates?q=Render%20Test")
        self.assertEqual(listed.status_code, 200)
        candidates = listed.get_json()
        self.assertEqual(len(candidates), 1)
        self.assertEqual(candidates[0]["timezone"], "Asia/Tokyo (UTC+9)")

        changed = self.client.patch(
            f"/api/admin/candidates/{body['candidate_id']}", json={"status": "contacted"}
        )
        self.assertEqual(changed.status_code, 200)
        exported = self.client.get("/api/admin/candidates/export")
        self.assertEqual(exported.status_code, 200)
        self.assertIn(body["candidate_id"].encode(), exported.data)

    def test_consent_is_required(self):
        candidate = self.candidate()
        candidate["privacy_consent"] = False
        response = self.client.post("/api/candidates", json=candidate)
        self.assertEqual(response.status_code, 400)

    def test_https_cookie_flags(self):
        application.COOKIE_SECURE = True
        response = self.login()
        cookie = response.headers["Set-Cookie"]
        self.assertIn("Secure", cookie)
        self.assertIn("HttpOnly", cookie)
        self.assertIn("SameSite=Strict", cookie)

    def test_production_requires_supabase(self):
        original = (application.PRODUCTION, application.SUPABASE_CONFIGURED)
        try:
            application.PRODUCTION = True
            application.SUPABASE_CONFIGURED = False
            with self.assertRaisesRegex(RuntimeError, "SUPABASE"):
                application.validate_production_config()
        finally:
            application.PRODUCTION, application.SUPABASE_CONFIGURED = original


if __name__ == "__main__":
    unittest.main()
