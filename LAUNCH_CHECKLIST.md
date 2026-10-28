# Saba Coders pre-launch checklist

Do not announce a public launch until every **blocker** below is verified in the deployed environment. Repository code and a passing CI run are not substitutes for live checks.

## 1. Student journey — blocker

- [ ] Visitor can discover a **published** course from Home and Explore; drafts and pending-review courses never appear publicly.
- [ ] View Course while signed out opens the real login/create-account dialog and preserves the selected course.
- [ ] Successful login **and** successful account creation return to that course; failed authentication shows a clear error and does not navigate.
- [ ] Enroll in a free course succeeds once; repeat enrollment is safe and does not create duplicate rows.
- [ ] Enrolled student can open non-preview lesson text/video and permitted course materials; another account and a signed-out visitor cannot access private materials.
- [ ] Completing a lesson saves progress to the database. Refresh, log out/in, and use a second browser session: progress remains for the same student and is not exposed to another student.
- [ ] Course progress totals and empty/loading/error states are sensible on desktop and mobile; test English and Amharic.
- [ ] Paid courses clearly remain unavailable for enrollment until a real payment integration exists. Do not simulate payment success.

## 2. Production configuration — blocker

- [ ] Set `APP_ENV=production`, `DATABASE_URL` to a managed PostgreSQL connection string, `COOKIE_SECURE=1`, `UPLOAD_DIR` to durable private storage, and `REQUIRE_APPROVAL=1`.
- [ ] Set `ADMIN_EMAIL` and a unique strong `ADMIN_PASSWORD` using the host's secret manager. Never commit `.env`, credentials, database dumps, API keys, or session tokens.
- [ ] Deploy behind a platform-managed HTTPS certificate; force HTTP-to-HTTPS redirects at the hosting/proxy layer and verify login cookies include `Secure`, `HttpOnly`, and `SameSite=Lax` in a real HTTPS browser.
- [ ] Verify the application refuses to start in production without PostgreSQL or with `COOKIE_SECURE=0`.
- [ ] Verify upload directories are not publicly mounted. Thumbnails are public only through the course thumbnail endpoint; course materials require an authorized owner/teacher/admin or enrolled student. Test unauthorized direct material URLs.
- [ ] Confirm the host limits request size and rate, restricts database network access, and provides process restarts and logs without exposing passwords/tokens.
- [ ] Run database migrations/schema initialization on a **staging** PostgreSQL database first. Test unique constraints, foreign keys, transactions, restart persistence, and concurrent enrollment/progress writes.
- [ ] Configure automated encrypted PostgreSQL backups and retention with the hosting provider. Perform a restore into a separate database and verify users, courses, enrollments, progress, and relationships. Back up uploaded files separately; a database backup does not contain files.
- [ ] Test recovery procedures and document who can access backups. Do not store backups in the public web directory or the same unprotected disk as production.

## 3. Quality and security checks — blocker

- [ ] GitHub Actions backend tests and UI integration tests pass on the exact commit to be deployed.
- [ ] Run a clean deployment smoke test after deploy: health endpoint, register, login, browse, enroll, lesson access, progress save/read, logout, and unauthorized access denial.
- [ ] Verify admin-only routes, teacher ownership boundaries, student access boundaries, CSRF header rejection, login throttling, file type/size checks, and session expiry.
- [ ] Review dependency/security alerts and rotate any credential that was ever committed or shared. Removing a secret from the latest commit is not sufficient; revoke/rotate it.
- [ ] Test keyboard-only navigation, focus visibility, labels, contrast, mobile layout, and English/Amharic text with real browsers.

## 4. Small real-course pilot — blocker

- [ ] Publish 2–3 complete, reviewed courses with instructor permission, accurate descriptions, clear outcomes, and useful first lessons. Use original or properly licensed media and materials.
- [ ] Invite a small group of consenting pilot learners; explain what feedback/data is collected, avoid collecting unnecessary personal data, and provide a way to report problems.
- [ ] Observe learners completing the full discovery-to-progress journey. Record device/browser, issue, severity, reproducible steps, and expected behavior without recording passwords or private lesson content.
- [ ] Fix the highest-impact blockers first (cannot sign in, cannot enroll, cannot open lesson, progress lost, privacy/access leak), rerun CI, and repeat the pilot before expanding.
- [ ] Confirm support contact, privacy notice, terms, course ownership/licensing, incident contact, and backup/restore owner before public promotion.

## Launch decision

- **GO:** all blockers above have evidence, current CI passes, backup restore has been tested, and pilot learners can finish the core journey without critical errors.
- **NO-GO:** any unverified production security control, failed restore, cross-user access leak, lost progress, or broken authentication/enrollment/lesson flow.
