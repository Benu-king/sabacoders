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
| Teacher (created by an admin) | create drafts; edit **only courses they are attached to**; upload thumbnail/materials; build sections and lessons; submit for review; unpublish own course. Cannot approve, cannot touch other teachers' courses |
| Admin | everything: review queue, approve/reject (reason required), unpublish, edit any course, categories, users. Cannot demote or deactivate themselves or the last admin |

## Publishing workflow
`draft → pending_review → published` · admin may `reject` (note shown to the teacher; teacher edits and resubmits) · `published → unpublished → edit → resubmit`.
Teachers cannot edit a course while it is pending or published (unpublish first). Set `REQUIRE_APPROVAL=0` to let teachers publish directly.

## Creating the first teacher
Log in to the dashboard as admin → **Users** → *Create account* with role *Teacher*. The teacher logs in at `/dashboard.html`.

## API used by the dashboard
Auth: `POST /api/auth/login|logout|register`, `GET /api/auth/me`.
Courses: `GET|POST /api/manage/courses`, `GET|PATCH|DELETE /api/manage/courses/{id}`, `POST .../thumbnail`, `POST .../materials`, `DELETE /api/manage/materials/{id}`, `POST .../sections`, `PATCH|DELETE /api/manage/sections/{id}`, `POST /api/manage/sections/{id}/lessons`, `PATCH|DELETE /api/manage/lessons/{id}`, `POST .../submit`, `POST .../unpublish`.
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
