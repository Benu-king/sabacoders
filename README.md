# Saba Coders platform

`app.py` (backend, one file) · `static/index.html` (website) · `static/dashboard.html` (teacher/admin dashboard) · one database.

## Run on Windows (Python 3.11)
```
py -3.11 -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
$env:ADMIN_EMAIL="you@yourdomain.com"; $env:ADMIN_PASSWORD="a-long-password"      (PowerShell)
python app.py init
python app.py serve
```
- Website: http://127.0.0.1:8000  (Log in / Start learning use the real API)
- Dashboard: http://127.0.0.1:8000/dashboard.html  (teachers and admins only)

`init` creates the tables, seeds the 10 categories and creates the first admin (only if no admin exists yet).

## Who can do what (enforced by the server)
| Role | Can |
|---|---|
| Visitor | browse published courses only |
| Student (self-registered) | + enrol in free courses, lesson content, materials, progress. **No dashboard access.** |
| Teacher (approved by an admin; applicants may self-apply) | create drafts; edit **only courses they are attached to**; upload thumbnail/materials; build sections and lessons; submit for review; unpublish own course. Cannot approve, cannot touch other teachers' courses |
| Admin | everything: review queue, approve/reject (reason required), unpublish, edit any course, categories, users. Cannot demote or deactivate themselves or the last admin |

## Publishing workflow
`draft → pending_review → published` · admin may `reject` (note shown to the teacher; teacher edits and resubmits) · `published → unpublished → edit → resubmit`.
Teachers cannot edit a course while it is pending or published (unpublish first). Set `REQUIRE_APPROVAL=0` to let teachers publish directly.

## Becoming a teacher
Anyone can open `/dashboard.html#apply` (or choose **Become an instructor** on the dashboard login screen) and submit their name, email, password, teaching expertise, and motivation. Applications remain pending until an administrator reviews them. Approval creates a teacher account (or promotes an existing student account); rejection does not grant access. The applicant's password is stored only as a password hash. Admins can review applications under **Instructor applications** in the dashboard. Public registration never accepts a role, so applicants cannot grant themselves teacher or admin access.

Admins can still create teacher accounts manually from **Users** if needed.

## API used by the dashboard
Auth: `POST /api/auth/login|logout|register`, `GET /api/auth/me`.
Courses: `GET|POST /api/manage/courses`, `GET|PATCH|DELETE /api/manage/courses/{id}`, `POST .../thumbnail`, `POST .../materials`, `DELETE /api/manage/materials/{id}`, `POST .../sections`, `PATCH|DELETE /api/manage/sections/{id}`, `POST /api/manage/sections/{id}/lessons`, `PATCH|DELETE /api/manage/lessons/{id}`, `POST .../submit`, `POST .../unpublish`.
Teacher applications: `POST /api/teacher-applications`, admin `GET /api/admin/teacher-applications`, `POST /api/admin/teacher-applications/{id}/approve|reject`.
Admin: `GET /api/admin/review-queue`, `POST /api/admin/courses/{id}/approve|reject`, `GET|POST /api/admin/users`, `PATCH /api/admin/users/{id}`, `GET|POST /api/admin/categories`, `PATCH /api/admin/categories/{id}`.
Public: `GET /api/categories`, `GET /api/courses`, `GET /api/courses/{id-or-slug}`, `.../curriculum`, `.../thumbnail`.
Every state-changing request must send `X-Requested-With: saba` (CSRF defence); sessions are HttpOnly cookies.

## Tests
```
pip install pytest httpx
pytest -q test_app.py          # backend: permissions, workflow, uploads, sessions, search/pagination (16 tests)
npm install jsdom
node test_ui.js               # drives the real dashboard + website login in a simulated browser against a live server (39 checks)
```

## Not built yet
Course Details page, lesson player, quizzes, paid checkout (paid enrolment returns 402), password reset and email, teacher invitations by email, audit log, real-browser (Playwright) tests, PostgreSQL run-through, object storage for uploads.

## Before production
PostgreSQL (`schema.sql`), HTTPS with `COOKIE_SECURE=1`, object storage instead of local `uploads/`, a reverse proxy, backups, rate limiting that survives restarts and multiple workers.


## Student learning journey and test commands

The student journey uses the existing course, enrollment, lesson, and progress tables. Run backend tests and the browser-simulation integration suite before deploying:

```bash
python -m pip install -r requirements-dev.txt
pytest -q test_app.py
npm install --no-save jsdom
node test_ui.js
```

GitHub Actions runs these checks on pushes to `main` and pull requests. A green CI run verifies only the tested code paths in CI; it does not prove that a production host, HTTPS, PostgreSQL, backups, or real browsers are configured correctly.

## Production environment

**Do not launch with the development defaults.** Configure the host's secret/environment settings before starting the app:

- `APP_ENV=production`
- `DATABASE_URL` — PostgreSQL connection string; production mode refuses a missing URL or SQLite.
- `COOKIE_SECURE=1` — required in production; serve the site over HTTPS.
- `UPLOAD_DIR` — persistent private directory/storage for uploaded files; do not mount it as public static content.
- `ADMIN_EMAIL` and a strong, unique `ADMIN_PASSWORD` — supply through the host's secret manager, not source code.
- `REQUIRE_APPROVAL=1` — keep instructor publishing behind admin review.

The app adds an HSTS response header in production and sets session cookies with `Secure`, `HttpOnly`, and `SameSite=Lax` (the Secure flag requires HTTPS). TLS certificates, HTTP-to-HTTPS redirects, firewall rules, persistent storage, PostgreSQL backups, and backup restoration must be configured and verified at the hosting provider.

## Launch gates

Follow [LAUNCH_CHECKLIST.md](LAUNCH_CHECKLIST.md) for the end-to-end student journey, private material access, PostgreSQL staging verification, secrets, HTTPS, backup-and-restore testing, accessibility, and the consent-based pilot with a small number of real courses. Paid enrollment is intentionally rejected until a real payment integration is implemented; do not represent it as available.
