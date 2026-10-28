import os, tempfile
T = tempfile.mkdtemp()
os.environ.update(DATABASE_URL=f"sqlite:///{T}/t.db", UPLOAD_DIR=f"{T}/up", ADMIN_EMAIL="admin@saba.com", ADMIN_PASSWORD="AdminPass123", REQUIRE_APPROVAL="1")
import pytest
from fastapi.testclient import TestClient
import app as A
H = {"X-Requested-With": "saba"}
PNG = b"\x89PNG\r\n\x1a\n" + b"0" * 200

@pytest.fixture(scope="module")
def anon():
    with TestClient(A.app, headers=H) as c: yield c
def client():
    return TestClient(A.app, headers=H)
def login(email, pw):
    c = client(); r = c.post("/api/auth/login", json={"email": email, "password": pw}); assert r.status_code == 200, r.text; return c
@pytest.fixture(scope="module")
def world(anon):
    adm = login("admin@saba.com", "AdminPass123")
    for em, role in (("t1@saba.com", "teacher"), ("t2@saba.com", "teacher"), ("s1@saba.com", "student")):
        assert adm.post("/api/admin/users", json={"email": em, "name": em.split("@")[0], "password": "Passw0rd!!", "role": role}).status_code == 201
    return dict(adm=adm, t1=login("t1@saba.com", "Passw0rd!!"), t2=login("t2@saba.com", "Passw0rd!!"), s1=login("s1@saba.com", "Passw0rd!!"))

def make_course(c, title="Intro to Python", price=0, publish_as_admin=False, preview=False, cat=1, level="Beginner"):
    r = c.post("/api/manage/courses", json={"title_en": title, "summary_en": "Short summary", "category_id": cat, "price": price, "level": level}); assert r.status_code == 201, r.text
    cid = r.json()["id"]; s = c.post(f"/api/manage/courses/{cid}/sections", json={"title_en": "Part 1"}).json()["id"]
    l1 = c.post(f"/api/manage/sections/{s}/lessons", json={"title_en": "Welcome", "kind": "text", "content_text": "Hello", "duration_minutes": 5, "is_preview": preview}).json()["id"]
    c.post(f"/api/manage/sections/{s}/lessons", json={"title_en": "Video", "kind": "video", "video_url": "https://example.com/v.mp4", "duration_minutes": 10})
    assert c.post(f"/api/manage/courses/{cid}/thumbnail", files={"file": ("t.png", PNG, "image/png")}).status_code == 200
    return cid, l1

def test_seeded_categories_and_empty_catalogue(anon):
    assert len(anon.get("/api/categories").json()) == 10
    j = anon.get("/api/courses").json(); assert j["total"] == 0 and j["items"] == []

def test_auth_basics(anon):
    assert anon.post("/api/auth/register", json={"email": "x@y.com", "name": "X", "password": "short"}).status_code == 422
    r = anon.post("/api/auth/register", json={"email": "new@saba.com", "name": "New", "password": "Passw0rd!!", "role": "admin"}); assert r.status_code == 201 and r.json()["role"] == "student"
    assert anon.post("/api/auth/register", json={"email": "NEW@saba.com", "name": "N", "password": "Passw0rd!!"}).status_code == 409
    assert anon.get("/api/auth/me").json()["email"] == "new@saba.com"
    anon.post("/api/auth/logout"); assert anon.get("/api/auth/me").status_code == 401
    assert TestClient(A.app).post("/api/auth/login", json={"email": "a@b.com", "password": "x"}).status_code == 403   # no CSRF header
    bad = client()
    for _ in range(8): assert bad.post("/api/auth/login", json={"email": "new@saba.com", "password": "wrong"}).status_code == 401
    assert bad.post("/api/auth/login", json={"email": "new@saba.com", "password": "Passw0rd!!"}).status_code == 429   # brute-force throttle

def test_roles_enforced_on_server(world, anon):
    assert anon.post("/api/manage/courses", json={"title_en": "abc", "category_id": 1}).status_code == 401
    assert world["s1"].post("/api/manage/courses", json={"title_en": "abc", "category_id": 1}).status_code == 403
    assert world["s1"].get("/api/admin/users").status_code == 403 and world["t1"].get("/api/admin/users").status_code == 403
    assert world["t1"].get("/api/admin/review-queue").status_code == 403

def test_full_publishing_workflow_and_visibility(world, anon):
    t1, t2, adm, s1 = world["t1"], world["t2"], world["adm"], world["s1"]
    cid, lesson = make_course(t1, "Workflow Course", preview=True)
    pub = lambda c: [x["id"] for x in c.get("/api/courses?page_size=50").json()["items"]]
    assert cid not in pub(anon) and anon.get(f"/api/courses/{cid}").status_code == 404 and s1.get(f"/api/courses/{cid}").status_code == 404   # draft hidden
    assert t1.get(f"/api/courses/{cid}").status_code == 200                                             # owner sees draft
    assert t2.patch(f"/api/manage/courses/{cid}", json={"title_en": "Hijack"}).status_code == 403       # other teacher blocked
    assert t2.get(f"/api/manage/courses/{cid}").status_code == 403 and cid not in [x["id"] for x in t2.get("/api/manage/courses").json()]
    assert t1.patch(f"/api/manage/courses/{cid}", json={"price": 0, "title_en": "Workflow Course v2"}).status_code == 200
    r = t1.post(f"/api/manage/courses/{cid}/submit"); assert r.json()["status"] == "pending_review"
    assert cid not in pub(anon) and anon.get(f"/api/courses/{cid}").status_code == 404                   # pending hidden
    assert t1.patch(f"/api/manage/courses/{cid}", json={"title_en": "Edit while pending"}).status_code == 409   # locked in review
    assert t1.post(f"/api/admin/courses/{cid}/approve").status_code == 403                               # teacher cannot self-approve
    assert any(x["id"] == cid for x in adm.get("/api/admin/review-queue").json())
    assert adm.post(f"/api/admin/courses/{cid}/reject", json={"note": "Please add a longer summary"}).json()["status"] == "rejected"
    assert t1.get(f"/api/manage/courses/{cid}").json()["review_note"].startswith("Please") and cid not in pub(anon)
    assert t1.post(f"/api/manage/courses/{cid}/submit").json()["status"] == "pending_review"
    assert adm.post(f"/api/admin/courses/{cid}/approve").json()["status"] == "published"
    assert cid in pub(anon)                                                                               # appears with NO code change
    c = anon.get(f"/api/courses/{cid}").json(); assert c["lesson_count"] == 2 and c["duration_minutes"] == 15 and c["thumbnail_url"]
    assert anon.get(f"/api/courses/{c['slug']}").json()["id"] == cid                                      # slug lookup
    assert anon.get(c["thumbnail_url"]).status_code == 200
    # curriculum gating
    cur = anon.get(f"/api/courses/{cid}/curriculum").json(); ls = cur["sections"][0]["lessons"]
    assert ls[0]["locked"] is False and "content_text" in ls[0] and ls[1]["locked"] is True and "video_url" not in ls[1]
    assert s1.post(f"/api/lessons/{lesson}/complete").status_code == 403                                  # must enrol first
    assert s1.post(f"/api/courses/{cid}/enroll").json()["enrolled"] is True
    cur = s1.get(f"/api/courses/{cid}/curriculum").json(); assert cur["has_access"] and cur["sections"][0]["lessons"][1]["video_url"]
    assert s1.post(f"/api/lessons/{lesson}/complete").json() == {"completed_lessons": 1, "lesson_count": 2}
    assert s1.post(f"/api/lessons/{lesson}/complete").json()["completed_lessons"] == 1                    # idempotent
    saved = s1.get(f"/api/courses/{cid}/curriculum").json()["sections"][0]["lessons"]
    assert saved[0]["completed"] is True and saved[1]["completed"] is False  # completion survives a fresh request
    assert anon.get(f"/api/courses/{cid}/curriculum").json()["sections"][0]["lessons"][0]["completed"] is False  # no progress leakage
    other = client(); other.post("/api/auth/register", json={"email": "other-student@saba.com", "name": "Other", "password": "Passw0rd!!"})
    other.post(f"/api/courses/{cid}/enroll")
    assert other.get(f"/api/courses/{cid}/curriculum").json()["sections"][0]["lessons"][0]["completed"] is False
    assert s1.get("/api/me/enrollments").json()[0]["completed_lessons"] == 1
    assert t1.post(f"/api/manage/courses/{cid}/unpublish").json()["status"] == "unpublished"
    assert cid not in pub(anon) and anon.get(f"/api/courses/{cid}").status_code == 404
    assert t1.delete(f"/api/manage/courses/{cid}").status_code == 409                                      # has a student

def test_validation_and_upload_safety(world):
    t1 = world["t1"]; cid = t1.post("/api/manage/courses", json={"title_en": "Upload Test", "category_id": 2}).json()["id"]
    assert t1.post(f"/api/manage/courses/{cid}/thumbnail", files={"file": ("evil.png", b"<html><script>alert(1)</script>", "image/png")}).status_code == 415
    assert t1.post(f"/api/manage/courses/{cid}/thumbnail", files={"file": ("big.png", PNG + b"0" * (3 * 1024 * 1024), "image/png")}).status_code == 413
    assert t1.post(f"/api/manage/courses/{cid}/materials", files={"file": ("x.exe", b"MZ\x90\x00\x03\x00\x00\x00", "application/octet-stream")}).status_code == 415
    assert t1.post(f"/api/manage/courses/{cid}/materials", files={"file": ("n.txt", b"notes", "text/plain")}).status_code == 201
    assert t1.post("/api/manage/courses", json={"title_en": "ab", "category_id": 1}).status_code == 422
    assert t1.post("/api/manage/courses", json={"title_en": "Valid title", "category_id": 999}).status_code == 422
    assert t1.post("/api/manage/courses", json={"title_en": "Valid title", "category_id": 1, "price": -5}).status_code == 422
    s = t1.post(f"/api/manage/courses/{cid}/sections", json={"title_en": "S"}).json()["id"]
    assert t1.post(f"/api/manage/sections/{s}/lessons", json={"title_en": "L", "kind": "video", "video_url": "javascript:alert(1)"}).status_code == 422
    r = t1.post(f"/api/manage/courses/{cid}/submit"); assert r.status_code == 422 and r.json()["detail"]["problems"]   # incomplete course rejected

def test_materials_need_enrolment(world):
    t1, s1, adm = world["t1"], world["s1"], world["adm"]; cid, _ = make_course(t1, "Materials Course")
    mid = t1.post(f"/api/manage/courses/{cid}/materials", files={"file": ("guide.pdf", b"%PDF-1.4 test", "application/pdf")}).json()["id"]
    t1.post(f"/api/manage/courses/{cid}/submit"); adm.post(f"/api/admin/courses/{cid}/approve")
    assert s1.get(f"/api/materials/{mid}").status_code == 403
    s1.post(f"/api/courses/{cid}/enroll"); assert s1.get(f"/api/materials/{mid}").status_code == 200

def test_paid_course_not_faked(world):
    t1, s1, adm = world["t1"], world["s1"], world["adm"]; cid, _ = make_course(t1, "Paid Course", price=1500)
    t1.post(f"/api/manage/courses/{cid}/submit"); adm.post(f"/api/admin/courses/{cid}/approve")
    assert s1.post(f"/api/courses/{cid}/enroll").status_code == 402

def test_search_filter_sort_pagination_on_real_data(world, anon):
    adm = world["adm"]
    for i in range(25):
        cid, _ = make_course(adm, f"Bulk Course {i:02d}", price=0 if i % 2 == 0 else 100 + i, cat=1 + i % 3, level=["Beginner", "Intermediate", "Advanced"][i % 3])
        assert adm.post(f"/api/manage/courses/{cid}/submit").json()["status"] == "published"                       # admin publishes directly
    j = anon.get("/api/courses?q=bulk&page_size=10").json(); assert j["total"] == 25 and j["pages"] == 3 and len(j["items"]) == 10
    assert len(anon.get("/api/courses?q=bulk&page_size=10&page=3").json()["items"]) == 5
    ids = {x["id"] for p in (1, 2, 3) for x in anon.get(f"/api/courses?q=bulk&page_size=10&page={p}&sort=az").json()["items"]}; assert len(ids) == 25   # no duplicates across pages
    free = anon.get("/api/courses?q=bulk&price=free&page_size=50").json(); assert free["total"] == 13 and all(x["price"] == 0 for x in free["items"])
    assert anon.get("/api/courses?q=bulk&price=paid&page_size=50").json()["total"] == 12
    adv = anon.get("/api/courses?q=bulk&level=Advanced&page_size=50").json(); assert adv["total"] == 8 and all(x["level"] == "Advanced" for x in adv["items"])
    pl = [x["price"] for x in anon.get("/api/courses?q=bulk&sort=plow&page_size=50").json()["items"]]; assert pl == sorted(pl)
    az = [x["title_en"] for x in anon.get("/api/courses?q=bulk&sort=az&page_size=50").json()["items"]]; assert az == sorted(az)
    assert anon.get("/api/courses?category=cybersecurity&q=bulk").json()["total"] == 8
    assert anon.get("/api/courses?q=zzzz-nothing").json()["total"] == 0
    assert anon.get("/api/courses?q=%25").json()["total"] == 0 and anon.get("/api/courses?q='; DROP TABLE courses;--").status_code == 200   # LIKE wildcards and SQL are inert
    assert anon.get("/api/courses?page_size=999").status_code == 422
    assert all(x["category"]["slug"] for x in anon.get("/api/courses").json()["items"])

def test_admin_safeguards_and_new_category(world, anon):
    adm = world["adm"]; me = adm.get("/api/auth/me").json()["id"]
    assert adm.patch(f"/api/admin/users/{me}", json={"role": "student"}).status_code == 400
    uid_ = next(u["id"] for u in adm.get("/api/admin/users").json() if u["email"] == "s1@saba.com")
    assert adm.patch(f"/api/admin/users/{uid_}", json={"is_active": False}).status_code == 200
    assert world["s1"].get("/api/auth/me").status_code == 401                                              # deactivation kills sessions
    r = adm.post("/api/admin/categories", json={"slug": "photography", "name_en": "Photography", "name_am": "ፎቶግራፊ"}); assert r.status_code == 201
    assert any(c["slug"] == "photography" for c in anon.get("/api/categories").json())                   # new discipline, zero code change

# ======================= Teacher / admin dashboard workflows =======================
def test_teacher_sees_only_own_courses_and_full_editor_flow(world):
    t1, t2 = world["t1"], world["t2"]
    a, _ = make_course(t1, "Dash A Course"); b, _ = make_course(t2, "Dash B Course")
    mine = [c["id"] for c in t1.get("/api/manage/courses").json()]; assert a in mine and b not in mine
    assert b in [c["id"] for c in world["adm"].get("/api/manage/courses").json()]                         # admin sees everything
    assert t1.get("/api/manage/courses?status=draft").json() and all(c["status"] == "draft" for c in t1.get("/api/manage/courses?status=draft").json())
    # edit every supported field
    r = t1.patch(f"/api/manage/courses/{a}", json={"title_en": "Dash A Edited", "title_am": "አማርኛ", "summary_en": "s", "summary_am": "ሀ", "description_en": "d", "description_am": "ሐ",
                                                  "category_id": 3, "level": "Advanced", "language": "both", "course_type": "video", "price": 900}); assert r.status_code == 200
    d = t1.get(f"/api/manage/courses/{a}").json(); assert (d["title_en"], d["level"], d["language"], d["course_type"], d["price"], d["category"]["id"]) == ("Dash A Edited", "Advanced", "both", "video", 900, 3)
    # materials: listed, downloadable by the owner, deletable
    mid = t1.post(f"/api/manage/courses/{a}/materials", files={"file": ("slides.pdf", b"%PDF-1.4 x", "application/pdf")}).json()["id"]
    assert [m["filename"] for m in t1.get(f"/api/manage/courses/{a}").json()["materials"]] == ["slides.pdf"]
    assert t1.get(f"/api/materials/{mid}").status_code == 200
    assert t2.delete(f"/api/manage/materials/{mid}").status_code == 403                                  # other teacher cannot delete it
    assert t1.delete(f"/api/manage/materials/{mid}").status_code == 200 and t1.get(f"/api/manage/courses/{a}").json()["materials"] == []
    # curriculum organisation: reorder sections and lessons, edit and delete
    s2 = t1.post(f"/api/manage/courses/{a}/sections", json={"title_en": "Part 2"}).json()
    secs = t1.get(f"/api/manage/courses/{a}").json()["sections"]; p1, p2 = secs[0], secs[1]; assert p1["position"] < p2["position"]
    t1.patch(f"/api/manage/sections/{p1['id']}", json={"position": p2["position"]}); t1.patch(f"/api/manage/sections/{p2['id']}", json={"position": p1["position"]})
    assert [s["title_en"] for s in t1.get(f"/api/manage/courses/{a}").json()["sections"]] == ["Part 2", "Part 1"]
    l = t1.get(f"/api/manage/courses/{a}").json()["sections"][1]["lessons"][0]
    assert t1.patch(f"/api/manage/lessons/{l['id']}", json={"title_en": "Renamed", "duration_minutes": 20, "is_preview": True}).status_code == 200
    assert t1.get(f"/api/manage/courses/{a}").json()["duration_minutes"] == 30
    assert t1.delete(f"/api/manage/sections/{s2['id']}").status_code == 200

def test_teacher_a_cannot_touch_teacher_b(world):
    t1, t2 = world["t1"], world["t2"]; b, lb = make_course(t2, "Private B Course")
    sec = t2.get(f"/api/manage/courses/{b}").json()["sections"][0]["id"]
    for method, url, kw in [("patch", f"/api/manage/courses/{b}", {"json": {"title_en": "Hijacked"}}), ("delete", f"/api/manage/courses/{b}", {}), ("post", f"/api/manage/courses/{b}/submit", {}),
                            ("post", f"/api/manage/courses/{b}/unpublish", {}), ("post", f"/api/manage/courses/{b}/sections", {"json": {"title_en": "x"}}),
                            ("patch", f"/api/manage/sections/{sec}", {"json": {"title_en": "x"}}), ("delete", f"/api/manage/sections/{sec}", {}),
                            ("post", f"/api/manage/sections/{sec}/lessons", {"json": {"title_en": "x"}}), ("patch", f"/api/manage/lessons/{lb}", {"json": {"title_en": "x"}}),
                            ("delete", f"/api/manage/lessons/{lb}", {}), ("get", f"/api/manage/courses/{b}", {}),
                            ("post", f"/api/manage/courses/{b}/thumbnail", {"files": {"file": ("t.png", PNG, "image/png")}}), ("post", f"/api/manage/courses/{b}/materials", {"files": {"file": ("n.txt", b"x", "text/plain")}})]:
        assert getattr(t1, method)(url, **kw).status_code == 403, (method, url)
    assert t2.get(f"/api/manage/courses/{b}").json()["title_en"] == "Private B Course"                   # untouched

def test_teacher_cannot_approve_own_course_and_admin_review_flow(world, anon):
    t1, adm = world["t1"], world["adm"]; cid, _ = make_course(t1, "Review Flow Course")
    mid = t1.post(f"/api/manage/courses/{cid}/materials", files={"file": ("notes.txt", b"hello", "text/plain")}).json()["id"]
    assert t1.post(f"/api/manage/courses/{cid}/submit").json()["status"] == "pending_review"
    for url in (f"/api/admin/courses/{cid}/approve", f"/api/admin/courses/{cid}/reject"):
        assert t1.post(url, json={"note": "no"}).status_code == 403                                      # teachers can never approve or reject
    assert t1.get("/api/admin/review-queue").status_code == 403
    q = adm.get("/api/admin/review-queue").json(); assert cid in [c["id"] for c in q]
    d = adm.get(f"/api/manage/courses/{cid}").json(); assert d["materials"][0]["filename"] == "notes.txt" and d["sections"][0]["lessons"][0]["content_text"] == "Hello"   # admin can inspect everything
    assert adm.get(f"/api/materials/{mid}").status_code == 200
    assert adm.post(f"/api/admin/courses/{cid}/reject", json={"note": ""}).status_code == 422             # reason is mandatory
    assert adm.post(f"/api/admin/courses/{cid}/reject", json={"note": "Needs more detail in lesson 1"}).json()["status"] == "rejected"
    assert adm.post(f"/api/admin/courses/{cid}/approve").status_code == 409                               # cannot approve a rejected course directly
    mine = next(c for c in t1.get("/api/manage/courses").json() if c["id"] == cid); assert mine["status"] == "rejected" and mine["review_note"] == "Needs more detail in lesson 1"
    assert t1.patch(f"/api/manage/courses/{cid}", json={"summary_en": "Improved summary"}).status_code == 200   # rejected courses are editable
    assert t1.post(f"/api/manage/courses/{cid}/submit").json()["status"] == "pending_review"             # resubmission
    assert t1.get(f"/api/manage/courses/{cid}").json()["review_note"] == ""                               # old note cleared
    assert adm.post(f"/api/admin/courses/{cid}/approve").json()["status"] == "published"
    assert anon.get(f"/api/courses/{cid}").status_code == 200
    assert t1.patch(f"/api/manage/courses/{cid}", json={"title_en": "Edit live"}).status_code == 409      # published = locked for teachers

def test_category_management_by_admin_only(world, anon):
    adm, t1 = world["adm"], world["t1"]
    assert t1.get("/api/admin/categories").status_code == 403 and t1.post("/api/admin/categories", json={"slug": "xx", "name_en": "XX"}).status_code == 403
    cid = adm.post("/api/admin/categories", json={"slug": "robotics", "name_en": "Robotics", "name_am": "ሮቦቲክስ"}).json()["id"]
    assert adm.post("/api/admin/categories", json={"slug": "robotics", "name_en": "Dup"}).status_code == 409
    assert adm.post("/api/admin/categories", json={"slug": "Bad Slug!", "name_en": "Bad"}).status_code == 422
    first = adm.get("/api/admin/categories").json()[0]
    assert adm.patch(f"/api/admin/categories/{cid}", json={"slug": first["slug"], "name_en": "Robotics"}).status_code == 409   # slug clash is a clean 409, not a 500
    assert adm.patch(f"/api/admin/categories/{cid}", json={"slug": "robotics", "name_en": "Robotics", "is_active": False}).status_code == 200
    assert "robotics" not in [c["slug"] for c in anon.get("/api/categories").json()] and "robotics" in [c["slug"] for c in adm.get("/api/admin/categories").json()]

def test_validation_errors_are_clean(world):
    t1 = world["t1"]
    assert t1.post("/api/manage/courses", json={}).status_code == 422
    cid, _ = make_course(t1, "Validation Course")
    assert t1.patch(f"/api/manage/courses/{cid}", json={"level": "Expert"}).status_code == 422
    assert t1.patch(f"/api/manage/courses/{cid}", json={"price": "free"}).status_code == 422
    assert t1.patch(f"/api/manage/courses/{cid}", json={"language": "fr"}).status_code == 422
    assert t1.post(f"/api/manage/courses/{cid}/sections", json={"title_en": ""}).status_code == 422
    s = t1.get(f"/api/manage/courses/{cid}").json()["sections"][0]["id"]
    assert t1.post(f"/api/manage/sections/{s}/lessons", json={"title_en": "L", "duration_minutes": 5000}).status_code == 422
    assert t1.post(f"/api/manage/courses/{cid}/thumbnail").status_code == 422                              # missing file
    assert t1.get("/api/manage/courses/not-a-real-id").status_code == 404

def test_sessions_logout_expiry_and_unauthorised_access(world, anon):
    from sqlalchemy import update
    c = login("t1@saba.com", "Passw0rd!!"); token = c.cookies.get("saba_session")
    assert c.get("/api/manage/courses").status_code == 200
    stolen = client(); stolen.cookies.set("saba_session", token)
    c.post("/api/auth/logout"); assert c.get("/api/manage/courses").status_code == 401
    assert stolen.get("/api/manage/courses").status_code == 401                                           # logout kills the server-side session, not just the cookie
    c2 = login("t1@saba.com", "Passw0rd!!")
    with A.SessionLocal() as db:
        db.execute(update(A.SessionRow).where(A.SessionRow.token_hash == A.sha(c2.cookies.get("saba_session"))).values(expires_at=A.now() - A.dt.timedelta(seconds=1))); db.commit()
    assert c2.get("/api/auth/me").status_code == 401 and c2.get("/api/manage/courses").status_code == 401   # expired session
    bogus = client(); bogus.cookies.set("saba_session", "forged-token")
    assert bogus.get("/api/manage/courses").status_code == 401 and bogus.get("/api/admin/users").status_code == 401
    assert anon.get("/api/admin/categories").status_code in (401, 403) and anon.get("/api/admin/review-queue").status_code == 401

def test_students_blocked_from_every_staff_and_admin_endpoint(world):
    s = client()
    em = "stu2@saba.com"; assert s.post("/api/auth/register", json={"email": em, "name": "Stu", "password": "Passw0rd!!"}).status_code == 201
    cid, _ = make_course(world["t1"], "Student Block Course")
    for method, url, kw in [("get", "/api/manage/courses", {}), ("post", "/api/manage/courses", {"json": {"title_en": "abc", "category_id": 1}}), ("get", f"/api/manage/courses/{cid}", {}),
                            ("get", "/api/admin/users", {}), ("get", "/api/admin/review-queue", {}), ("get", "/api/admin/categories", {}), ("post", f"/api/admin/courses/{cid}/approve", {}),
                            ("post", "/api/admin/users", {"json": {"email": "q@q.com", "name": "q", "password": "Passw0rd!!", "role": "admin"}})]:
        assert getattr(s, method)(url, **kw).status_code == 403, url
    me_id = s.get("/api/auth/me").json()["id"]; assert s.patch(f"/api/admin/users/{me_id}", json={"role": "admin"}).status_code == 403   # no self-promotion


def test_teacher_application_requires_admin_approval_and_never_self_assigns(world, anon):
    r = anon.post("/api/teacher-applications", json={
        "name": "Applicant Example", "email": "applicant@saba.com", "password": "SecurePass123!",
        "expertise": "Web development", "motivation": "I want to teach practical web development to beginners.", "role": "admin"
    })
    assert r.status_code == 201, r.text
    aid = r.json()["id"]
    assert r.json()["status"] == "pending"
    assert anon.get("/api/auth/me").status_code == 401
    assert anon.get("/api/manage/courses").status_code == 401
    assert anon.post("/api/teacher-applications", json={
        "name": "Applicant Example", "email": "applicant@saba.com", "password": "SecurePass123!",
        "expertise": "Web development", "motivation": "I want to teach practical web development to beginners."
    }).status_code == 409
    assert world["t1"].get("/api/admin/teacher-applications").status_code == 403
    item = next(x for x in world["adm"].get("/api/admin/teacher-applications").json() if x["id"] == aid)
    assert item["email"] == "applicant@saba.com" and item["status"] == "pending"
    assert "password" not in item and "password_hash" not in item
    approved = world["adm"].post(f"/api/admin/teacher-applications/{aid}/approve")
    assert approved.status_code == 200, approved.text
    assert approved.json()["status"] == "approved"
    teacher = login("applicant@saba.com", "SecurePass123!")
    assert teacher.get("/api/auth/me").json()["role"] == "teacher"
    assert teacher.get("/api/manage/courses").status_code == 200
    assert world["adm"].post(f"/api/admin/teacher-applications/{aid}/approve").status_code == 409

def test_teacher_application_rejection_and_validation(world, anon):
    bad = anon.post("/api/teacher-applications", json={
        "name": "Rejected Example", "email": "reject@saba.com", "password": "SecurePass123!",
        "expertise": "Design", "motivation": "too short"
    })
    assert bad.status_code == 422
    r = anon.post("/api/teacher-applications", json={
        "name": "Rejected Example", "email": "reject@saba.com", "password": "SecurePass123!",
        "expertise": "Design", "motivation": "I can teach practical design skills to new learners."
    })
    assert r.status_code == 201, r.text
    aid = r.json()["id"]
    assert world["adm"].post(f"/api/admin/teacher-applications/{aid}/reject", json={"note": "Please provide more teaching examples."}).json()["status"] == "rejected"
    again = anon.post("/api/teacher-applications", json={
        "name": "Rejected Example", "email": "reject@saba.com", "password": "SecurePass123!",
        "expertise": "Design", "motivation": "I can teach practical design skills to new learners."
    })
    assert again.status_code == 201 and again.json()["status"] == "pending"
    assert anon.get("/api/auth/me").status_code == 401
