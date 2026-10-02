# Career Bridge Japan — MVP v2

A mobile-first candidate application and lightweight recruitment admin dashboard. It uses Flask, runs locally with SQLite, and requires Supabase in production.

## Start locally

```sh
cp .env.example .env
# Edit ADMIN_PASSWORD and SESSION_SECRET in .env
python3 -m pip install -r requirements.txt
chmod +x run.sh
./run.sh
```

- Candidate site: http://127.0.0.1:8000/
- Application: http://127.0.0.1:8000/apply
- Admin: http://127.0.0.1:8000/admin
- Default development login (only if `.env` is not configured): `admin@example.com` / `change-me`

The local database is created at `data/career_bridge.db`. Application drafts stay in the candidate's browser until submission, so Back and section navigation do not erase entered values.

## Supabase setup

1. Create a Supabase project.
2. Open **SQL Editor**, paste `supabase/schema.sql`, and run it.
3. In **Project Settings → API**, copy the Project URL and the service-role key.
4. Add them to `.env` as `SUPABASE_URL` and `SUPABASE_SERVICE_ROLE_KEY`.
5. Restart `./run.sh`. The server prints and exposes which storage backend is active.

The service-role key is used only by the Python server and is never sent to the browser. Do not commit `.env` or expose the key in frontend code.

## Render deployment

The repository includes `render.yaml`. Create a Render Blueprint or a Python Web Service connected to the GitHub repository.

- Build Command: `pip install -r requirements.txt`
- Start Command: `gunicorn --bind 0.0.0.0:$PORT --workers 2 --threads 4 --timeout 60 app:app`
- Health Check Path: `/healthz`

Set `APP_ENV=production` and `COOKIE_SECURE=true`. Add `ADMIN_EMAIL`, `ADMIN_PASSWORD`, `SESSION_SECRET`, `LINE_OFFICIAL_URL`, `SUPABASE_URL`, and `SUPABASE_SERVICE_ROLE_KEY` in Render's Environment settings. Production startup fails if Supabase or required security settings are missing, so SQLite cannot silently become the production data store.

Render terminates HTTPS at its proxy. The application trusts Render's forwarded protocol and host headers and sets the admin session cookie with `Secure`, `HttpOnly`, and `SameSite=Strict` in production.

Run the local test suite with:

```sh
python3 -m unittest discover -s tests -v
```

## Scoring

Weights live in `SCORE_WEIGHTS` near the top of `app.py`: Job intent 25, Start timing 20, Residence & work feasibility 20, Experience & skills 15, Japanese 10, English/other 5, CV readiness 5. Rating mappings are isolated in `score_candidate()` and can be changed without editing the form or database.

## Before public launch

- Deploy the server to a public HTTPS host and set `HOST=0.0.0.0` there.
- Set a strong admin password and long random session secret; consider Supabase Auth/MFA for multiple admins.
- Replace `LINE_OFFICIAL_URL` with the official LINE account URL.
- Have Privacy and Terms reviewed; add the operating entity, address, contact, retention, and cross-border transfer disclosures.
- Add email/LINE notifications, audit logs, rate limiting/CAPTCHA, backups, and automated tests.
- Confirm recruitment licensing and personal-information obligations with a qualified Japanese professional.
