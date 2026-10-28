"""Saba Coders backend: ONE file. FastAPI + SQLAlchemy.
Courses, categories, lessons, users, enrolments and progress live in the database; files live in UPLOAD_DIR.
Run:  python app.py init   (create tables, seed categories, create first admin from env)
      python app.py serve  (http://127.0.0.1:8000 - serves the API and static/index.html)"""
from __future__ import annotations
import os, sys, re, uuid, secrets, hashlib, hmac, time, math, pathlib, datetime as dt
from contextlib import asynccontextmanager
from typing import Optional, Literal
from fastapi import FastAPI, Depends, HTTPException, Request, Response, UploadFile, File, Query
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field
from sqlalchemy import (create_engine, event, String, Integer, Text, Boolean, DateTime, ForeignKey, UniqueConstraint,
                        CheckConstraint, Table, Column, select, func, or_, case)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship, sessionmaker, Session

BASE = pathlib.Path(__file__).parent
DB_URL = os.getenv("DATABASE_URL", f"sqlite:///{BASE / 'saba.db'}")
UPLOADS = pathlib.Path(os.getenv("UPLOAD_DIR", str(BASE / "uploads")))
REQUIRE_APPROVAL = os.getenv("REQUIRE_APPROVAL", "1") == "1"   # teachers need admin approval to publish
COOKIE_SECURE = os.getenv("COOKIE_SECURE", "0") == "1"          # set 1 behind HTTPS
SESSION_DAYS, MAX_THUMB = 14, 3 * 1024 * 1024
MAX_MATERIAL = int(os.getenv("MAX_MATERIAL_MB", "25")) * 1024 * 1024

def uid(): return str(uuid.uuid4())
def now(): return dt.datetime.now(dt.timezone.utc).replace(tzinfo=None)

engine = create_engine(DB_URL, pool_pre_ping=True, connect_args={"check_same_thread": False} if DB_URL.startswith("sqlite") else {})
if DB_URL.startswith("sqlite"):
    @event.listens_for(engine, "connect")
    def _fk(c, _): c.execute("PRAGMA foreign_keys=ON")
SessionLocal = sessionmaker(engine, expire_on_commit=False)

class Base(DeclarativeBase): pass

class User(Base):
    __tablename__ = "users"
    __table_args__ = (CheckConstraint("role in ('student','teacher','admin')", name="ck_user_role"),)
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    email: Mapped[str] = mapped_column(String(255), unique=True, index=True)
    name: Mapped[str] = mapped_column(String(120))
    bio: Mapped[str] = mapped_column(Text, default="")
    password_hash: Mapped[str] = mapped_column(String(255))
    role: Mapped[str] = mapped_column(String(10), default="student")
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[dt.datetime] = mapped_column(DateTime, default=now)

class SessionRow(Base):
    __tablename__ = "sessions"
    token_hash: Mapped[str] = mapped_column(String(64), primary_key=True)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    expires_at: Mapped[dt.datetime] = mapped_column(DateTime)

class TeacherApplication(Base):
    __tablename__ = "teacher_applications"
    __table_args__ = (CheckConstraint("status in ('pending','approved','rejected')", name="ck_teacher_application_status"),)
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    name: Mapped[str] = mapped_column(String(120))
    email: Mapped[str] = mapped_column(String(255), index=True)
    password_hash: Mapped[str] = mapped_column(String(255))
    expertise: Mapped[str] = mapped_column(String(160))
    motivation: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(10), default="pending", index=True)
    review_note: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[dt.datetime] = mapped_column(DateTime, default=now)
    reviewed_at: Mapped[Optional[dt.datetime]] = mapped_column(DateTime)

class Category(Base):
    __tablename__ = "categories"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    slug: Mapped[str] = mapped_column(String(80), unique=True)
    name_en: Mapped[str] = mapped_column(String(160))
    name_am: Mapped[str] = mapped_column(String(160), default="")
    position: Mapped[int] = mapped_column(Integer, default=0)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)

course_teachers = Table("course_teachers", Base.metadata,
    Column("course_id", ForeignKey("courses.id", ondelete="CASCADE"), primary_key=True),
    Column("user_id", ForeignKey("users.id", ondelete="CASCADE"), primary_key=True))

class Course(Base):
    __tablename__ = "courses"
    __table_args__ = (
        CheckConstraint("status in ('draft','pending_review','published','rejected','unpublished')", name="ck_course_status"),
        CheckConstraint("level in ('Beginner','Intermediate','Advanced')", name="ck_course_level"),
        CheckConstraint("language in ('en','am','both')", name="ck_course_lang"),
        CheckConstraint("course_type in ('video','text','mixed')", name="ck_course_type"),
        CheckConstraint("price >= 0", name="ck_course_price"))
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    slug: Mapped[str] = mapped_column(String(180), unique=True, index=True)
    category_id: Mapped[int] = mapped_column(ForeignKey("categories.id"), index=True)
    title_en: Mapped[str] = mapped_column(String(160)); title_am: Mapped[str] = mapped_column(String(160), default="")
    summary_en: Mapped[str] = mapped_column(String(400), default=""); summary_am: Mapped[str] = mapped_column(String(400), default="")
    description_en: Mapped[str] = mapped_column(Text, default=""); description_am: Mapped[str] = mapped_column(Text, default="")
    level: Mapped[str] = mapped_column(String(12), default="Beginner")
    language: Mapped[str] = mapped_column(String(4), default="en")
    course_type: Mapped[str] = mapped_column(String(5), default="mixed")
    price: Mapped[int] = mapped_column(Integer, default=0)       # whole ETB; 0 = free
    thumbnail: Mapped[Optional[str]] = mapped_column(String(120))
    status: Mapped[str] = mapped_column(String(14), default="draft", index=True)
    review_note: Mapped[str] = mapped_column(Text, default="")
    lesson_count: Mapped[int] = mapped_column(Integer, default=0)
    duration_minutes: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[dt.datetime] = mapped_column(DateTime, default=now)
    updated_at: Mapped[dt.datetime] = mapped_column(DateTime, default=now, onupdate=now)
    submitted_at: Mapped[Optional[dt.datetime]] = mapped_column(DateTime)
    published_at: Mapped[Optional[dt.datetime]] = mapped_column(DateTime, index=True)
    category: Mapped[Category] = relationship()
    teachers: Mapped[list[User]] = relationship(secondary=course_teachers)
    sections: Mapped[list["Section"]] = relationship(order_by="Section.position", cascade="all, delete-orphan")
    materials: Mapped[list["Material"]] = relationship(cascade="all, delete-orphan")

class Section(Base):
    __tablename__ = "sections"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    course_id: Mapped[str] = mapped_column(ForeignKey("courses.id", ondelete="CASCADE"), index=True)
    title_en: Mapped[str] = mapped_column(String(160)); title_am: Mapped[str] = mapped_column(String(160), default="")
    position: Mapped[int] = mapped_column(Integer, default=0)
    lessons: Mapped[list["Lesson"]] = relationship(order_by="Lesson.position", cascade="all, delete-orphan")

class Lesson(Base):
    __tablename__ = "lessons"
    __table_args__ = (CheckConstraint("kind in ('video','text')", name="ck_lesson_kind"),)
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    section_id: Mapped[str] = mapped_column(ForeignKey("sections.id", ondelete="CASCADE"), index=True)
    course_id: Mapped[str] = mapped_column(ForeignKey("courses.id", ondelete="CASCADE"), index=True)
    title_en: Mapped[str] = mapped_column(String(160)); title_am: Mapped[str] = mapped_column(String(160), default="")
    kind: Mapped[str] = mapped_column(String(5), default="text")
    content_text: Mapped[str] = mapped_column(Text, default="")
    video_url: Mapped[str] = mapped_column(String(500), default="")
    duration_minutes: Mapped[int] = mapped_column(Integer, default=0)
    position: Mapped[int] = mapped_column(Integer, default=0)
    is_preview: Mapped[bool] = mapped_column(Boolean, default=False)

class Material(Base):
    __tablename__ = "materials"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    course_id: Mapped[str] = mapped_column(ForeignKey("courses.id", ondelete="CASCADE"), index=True)
    filename: Mapped[str] = mapped_column(String(200)); stored: Mapped[str] = mapped_column(String(120))
    content_type: Mapped[str] = mapped_column(String(80)); size: Mapped[int] = mapped_column(Integer)

class Enrollment(Base):
    __tablename__ = "enrollments"
    __table_args__ = (UniqueConstraint("user_id", "course_id"),)
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    course_id: Mapped[str] = mapped_column(ForeignKey("courses.id", ondelete="CASCADE"), index=True)
    created_at: Mapped[dt.datetime] = mapped_column(DateTime, default=now)

class Progress(Base):
    __tablename__ = "lesson_progress"
    __table_args__ = (UniqueConstraint("user_id", "lesson_id"),)
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    lesson_id: Mapped[str] = mapped_column(ForeignKey("lessons.id", ondelete="CASCADE"))
    course_id: Mapped[str] = mapped_column(ForeignKey("courses.id", ondelete="CASCADE"), index=True)
    completed_at: Mapped[dt.datetime] = mapped_column(DateTime, default=now)

SEED = [("programming", "Programming and Software Development", "ፕሮግራሚንግና ሶፍትዌር ልማት"), ("web", "Web Development and Digital Technology", "ዌብ ልማትና ዲጂታል ቴክኖሎጂ"),
 ("cybersecurity", "Cybersecurity", "ሳይበር ደህንነት"), ("forex", "Forex and Financial Markets", "ፎሬክስና የፋይናንስ ገበያዎች"), ("phone-repair", "Phone Repair and Electronics", "የስልክ ጥገናና ኤሌክትሮኒክስ"),
 ("computer-maintenance", "Computer Maintenance and Hardware", "የኮምፒውተር ጥገናና ሃርድዌር"), ("architecture", "Architecture and Built Environment", "አርክቴክቸርና የግንባታ አካባቢ"),
 ("engineering", "Engineering and Technical Skills", "ምህንድስናና ቴክኒካዊ ክህሎቶች"), ("design", "Graphic Design and Creative Skills", "ግራፊክ ዲዛይንና የፈጠራ ክህሎቶች"), ("business", "Business and Professional Development", "ቢዝነስና ሙያዊ ልማት")]

def hash_pw(p):
    s = secrets.token_bytes(16); h = hashlib.scrypt(p.encode(), salt=s, n=2**14, r=8, p=1, dklen=32); return f"scrypt${s.hex()}${h.hex()}"
def check_pw(p, stored):
    try:
        _, s, h = stored.split("$"); x = hashlib.scrypt(p.encode(), salt=bytes.fromhex(s), n=2**14, r=8, p=1, dklen=32)
        return hmac.compare_digest(x.hex(), h)
    except Exception: return False
def sha(t): return hashlib.sha256(t.encode()).hexdigest()

def init_db():
    Base.metadata.create_all(engine); UPLOADS.mkdir(parents=True, exist_ok=True)
    with SessionLocal() as db:
        if not db.scalar(select(func.count()).select_from(Category)):
            for i, (s, en, am) in enumerate(SEED): db.add(Category(slug=s, name_en=en, name_am=am, position=i))
        em, pw = os.getenv("ADMIN_EMAIL", "").lower(), os.getenv("ADMIN_PASSWORD", "")
        if em and len(pw) >= 8 and not db.scalar(select(User).where(User.role == "admin")):
            db.add(User(email=em, name="Administrator", password_hash=hash_pw(pw), role="admin"))
        db.commit()

@asynccontextmanager
async def lifespan(_):
    init_db(); yield

app = FastAPI(title="Saba Coders API", lifespan=lifespan)

@app.middleware("http")
async def guard(request: Request, call_next):
    # CSRF defence: every state-changing API call must carry a custom header a cross-site form cannot set.
    if request.method not in ("GET", "HEAD", "OPTIONS") and request.url.path.startswith("/api/") and request.headers.get("x-requested-with") != "saba":
        return JSONResponse({"detail": "Missing X-Requested-With header"}, 403)
    r = await call_next(request)
    r.headers.update({"X-Content-Type-Options": "nosniff", "Referrer-Policy": "same-origin", "X-Frame-Options": "DENY"}); return r

def get_db():
    with SessionLocal() as s: yield s
def user_opt(request: Request, db: Session = Depends(get_db)):
    tok = request.cookies.get("saba_session")
    row = db.get(SessionRow, sha(tok)) if tok else None
    if not row or row.expires_at < now(): return None
    u = db.get(User, row.user_id); return u if u and u.is_active else None
def user_req(u=Depends(user_opt)):
    if not u: raise HTTPException(401, "Login required")
    return u
def staff(u=Depends(user_req)):
    if u.role not in ("teacher", "admin"): raise HTTPException(403, "Teacher or admin only")
    return u
def admin(u=Depends(user_req)):
    if u.role != "admin": raise HTTPException(403, "Admin only")
    return u

HITS: dict = {}
def throttle_check(key, limit=8, window=300):
    t = time.time(); HITS[key] = [x for x in HITS.get(key, []) if t - x < window]
    if len(HITS[key]) >= limit: raise HTTPException(429, "Too many failed attempts. Try again later.")
def throttle_fail(key): HITS.setdefault(key, []).append(time.time())

EMAIL = re.compile(r"^[^@\s]{1,64}@[^@\s]+\.[^@\s]{2,}$")
class Reg(BaseModel):
    email: str = Field(max_length=255); name: str = Field(min_length=1, max_length=120); password: str = Field(min_length=8, max_length=128)
class TeacherApplicationIn(BaseModel):
    name: str = Field(min_length=2, max_length=120)
    email: str = Field(max_length=255)
    password: str = Field(min_length=8, max_length=128)
    expertise: str = Field(min_length=2, max_length=160)
    motivation: str = Field(min_length=20, max_length=3000)
class ApplicationDecision(BaseModel):
    note: str = Field("", max_length=2000)
class Login(BaseModel): email: str; password: str
class AdminUser(Reg): role: Literal["student", "teacher", "admin"] = "student"
class UserPatch(BaseModel): role: Optional[Literal["student", "teacher", "admin"]] = None; is_active: Optional[bool] = None
Level = Literal["Beginner", "Intermediate", "Advanced"]
class CourseIn(BaseModel):
    title_en: str = Field(min_length=3, max_length=160); title_am: str = Field("", max_length=160)
    summary_en: str = Field("", max_length=400); summary_am: str = Field("", max_length=400)
    description_en: str = Field("", max_length=10000); description_am: str = Field("", max_length=10000)
    category_id: int; level: Level = "Beginner"; language: Literal["en", "am", "both"] = "en"
    course_type: Literal["video", "text", "mixed"] = "mixed"; price: int = Field(0, ge=0, le=10_000_000)
class CoursePatch(BaseModel):
    title_en: Optional[str] = Field(None, min_length=3, max_length=160); title_am: Optional[str] = Field(None, max_length=160)
    summary_en: Optional[str] = Field(None, max_length=400); summary_am: Optional[str] = Field(None, max_length=400)
    description_en: Optional[str] = Field(None, max_length=10000); description_am: Optional[str] = Field(None, max_length=10000)
    category_id: Optional[int] = None; level: Optional[Level] = None; language: Optional[Literal["en", "am", "both"]] = None
    course_type: Optional[Literal["video", "text", "mixed"]] = None; price: Optional[int] = Field(None, ge=0, le=10_000_000)
class SectionIn(BaseModel): title_en: str = Field(min_length=1, max_length=160); title_am: str = Field("", max_length=160); position: Optional[int] = None
class SectionPatch(BaseModel): title_en: Optional[str] = Field(None, min_length=1, max_length=160); title_am: Optional[str] = Field(None, max_length=160); position: Optional[int] = None
class LessonIn(BaseModel):
    title_en: str = Field(min_length=1, max_length=160); title_am: str = Field("", max_length=160); kind: Literal["video", "text"] = "text"
    content_text: str = Field("", max_length=50000); video_url: str = Field("", max_length=500)
    duration_minutes: int = Field(0, ge=0, le=1000); is_preview: bool = False; position: Optional[int] = None
class LessonPatch(BaseModel):
    title_en: Optional[str] = Field(None, min_length=1, max_length=160); title_am: Optional[str] = Field(None, max_length=160)
    kind: Optional[Literal["video", "text"]] = None; content_text: Optional[str] = Field(None, max_length=50000); video_url: Optional[str] = Field(None, max_length=500)
    duration_minutes: Optional[int] = Field(None, ge=0, le=1000); is_preview: Optional[bool] = None; position: Optional[int] = None
class Note(BaseModel): note: str = Field(min_length=3, max_length=2000)
class CatIn(BaseModel): slug: str = Field(pattern=r"^[a-z0-9-]{2,80}$"); name_en: str = Field(min_length=2, max_length=160); name_am: str = Field("", max_length=160); position: int = 0; is_active: bool = True
class TeacherAdd(BaseModel): email: str

def ok_video(url):
    if url and not url.startswith("https://"): raise HTTPException(422, "video_url must start with https://")

# ---------- serialisation ----------
def udict(u): return {"id": u.id, "email": u.email, "name": u.name, "role": u.role}
def cdict(c, full=False):
    d = {"id": c.id, "slug": c.slug, "title_en": c.title_en, "title_am": c.title_am, "summary_en": c.summary_en, "summary_am": c.summary_am,
         "category": {"id": c.category.id, "slug": c.category.slug, "name_en": c.category.name_en, "name_am": c.category.name_am},
         "level": c.level, "language": c.language, "course_type": c.course_type, "price": c.price, "currency": "ETB",
         "thumbnail_url": f"/api/courses/{c.id}/thumbnail" if c.thumbnail else None, "lesson_count": c.lesson_count,
         "duration_minutes": c.duration_minutes, "instructors": [{"id": t.id, "name": t.name, "bio": t.bio} for t in c.teachers],
         "published_at": c.published_at.isoformat() if c.published_at else None}
    if full: d.update(description_en=c.description_en, description_am=c.description_am)
    return d
def mdict(c):
    d = cdict(c, True); d.update(materials=[{"id": m.id, "filename": m.filename, "size": m.size} for m in c.materials], status=c.status, review_note=c.review_note, created_at=c.created_at.isoformat(), sections=[
        {"id": s.id, "title_en": s.title_en, "title_am": s.title_am, "position": s.position, "lessons": [
            {k: getattr(l, k) for k in ("id", "title_en", "title_am", "kind", "content_text", "video_url", "duration_minutes", "position", "is_preview")} for l in s.lessons]} for s in c.sections])
    return d

def get_course(db, ref):
    c = db.scalar(select(Course).where(or_(Course.id == ref, Course.slug == ref)))
    if not c: raise HTTPException(404, "Course not found")
    return c
def can_manage(u, c): return bool(u) and (u.role == "admin" or (u.role == "teacher" and any(t.id == u.id for t in c.teachers)))
def visible(db, ref, u):
    c = get_course(db, ref)
    if c.status != "published" and not can_manage(u, c): raise HTTPException(404, "Course not found")   # drafts are invisible, not "forbidden"
    return c
def for_edit(db, ref, u):
    c = get_course(db, ref)
    if not can_manage(u, c): raise HTTPException(403, "You cannot manage this course")
    if u.role != "admin" and c.status not in ("draft", "rejected", "unpublished"):
        raise HTTPException(409, f"Course is {c.status}; unpublish it (or wait for review) before editing")
    return c
def recalc(db, c):
    db.flush(); ls = db.scalars(select(Lesson).where(Lesson.course_id == c.id)).all()
    c.lesson_count, c.duration_minutes = len(ls), sum(l.duration_minutes for l in ls)
def slugify(db, title):
    base = re.sub(r"[^a-z0-9]+", "-", title.lower()).strip("-")[:60] or "course"; s = base
    while db.scalar(select(Course.id).where(Course.slug == s)): s = f"{base}-{secrets.token_hex(2)}"
    return s
def has_access(db, u, c):
    return bool(u) and (can_manage(u, c) or db.scalar(select(Enrollment.id).where(Enrollment.user_id == u.id, Enrollment.course_id == c.id)) is not None)
def esc(s): return s.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")

# ---------- auth ----------
def start_session(db, u, response):
    tok = secrets.token_urlsafe(32); db.add(SessionRow(token_hash=sha(tok), user_id=u.id, expires_at=now() + dt.timedelta(days=SESSION_DAYS))); db.commit()
    response.set_cookie("saba_session", tok, httponly=True, samesite="lax", secure=COOKIE_SECURE, max_age=SESSION_DAYS * 86400, path="/")
@app.post("/api/auth/register", status_code=201)
def register(b: Reg, response: Response, request: Request, db: Session = Depends(get_db)):
    em = b.email.strip().lower()
    if not EMAIL.match(em): raise HTTPException(422, "Invalid email address")
    if db.scalar(select(User.id).where(User.email == em)): raise HTTPException(409, "Email already registered")
    u = User(email=em, name=b.name.strip(), password_hash=hash_pw(b.password), role="student"); db.add(u); db.commit()  # role is NEVER taken from the client
    start_session(db, u, response); return udict(u)
@app.post("/api/teacher-applications", status_code=201)
def apply_to_teach(b: TeacherApplicationIn, request: Request, db: Session = Depends(get_db)):
    em = b.email.strip().lower()
    if not EMAIL.match(em): raise HTTPException(422, "Invalid email address")
    key = f"teacher-application|{request.client.host if request.client else '?'}"
    throttle_check(key, limit=5, window=3600)
    if db.scalar(select(User.id).where(User.email == em)):
        raise HTTPException(409, "An account already exists for this email. Log in or contact an administrator.")
    if db.scalar(select(TeacherApplication.id).where(TeacherApplication.email == em, TeacherApplication.status == "pending")):
        raise HTTPException(409, "An application for this email is already waiting for review.")
    throttle_fail(key)
    row = TeacherApplication(name=b.name.strip(), email=em, password_hash=hash_pw(b.password),
                             expertise=b.expertise.strip(), motivation=b.motivation.strip())
    db.add(row); db.commit()
    return {"id": row.id, "status": row.status, "message": "Application received. An administrator must approve it before teacher access is granted."}

@app.post("/api/auth/login")
def login(b: Login, response: Response, request: Request, db: Session = Depends(get_db)):
    em = b.email.strip().lower(); key = f"{request.client.host if request.client else '?'}|{em}"; throttle_check(key)
    u = db.scalar(select(User).where(User.email == em)); good = check_pw(b.password, u.password_hash if u else "scrypt$00$00")
    if not (u and good and u.is_active): throttle_fail(key); raise HTTPException(401, "Invalid email or password")
    HITS.pop(key, None); start_session(db, u, response); return udict(u)
@app.post("/api/auth/logout")
def logout(request: Request, response: Response, db: Session = Depends(get_db)):
    tok = request.cookies.get("saba_session"); row = db.get(SessionRow, sha(tok)) if tok else None
    if row: db.delete(row); db.commit()
    response.delete_cookie("saba_session", path="/"); return {"ok": True}
@app.get("/api/auth/me")
def me(u=Depends(user_req)): return udict(u)

# ---------- public catalogue (published only) ----------
@app.get("/api/categories")
def categories(db: Session = Depends(get_db)):
    cnt = dict(db.execute(select(Course.category_id, func.count()).where(Course.status == "published").group_by(Course.category_id)).all())
    return [{"id": c.id, "slug": c.slug, "name_en": c.name_en, "name_am": c.name_am, "course_count": cnt.get(c.id, 0)}
            for c in db.scalars(select(Category).where(Category.is_active).order_by(Category.position, Category.id))]
SORTS = {"newest": lambda: (Course.published_at.desc(),), "az": lambda: (Course.title_en.asc(),), "dshort": lambda: (Course.duration_minutes.asc(),),
         "dlong": lambda: (Course.duration_minutes.desc(),), "plow": lambda: (Course.price.asc(),), "phigh": lambda: (Course.price.desc(),),
         "level": lambda: (case({"Beginner": 0, "Intermediate": 1}, value=Course.level, else_=2), Course.duration_minutes.asc())}
@app.get("/api/courses")
def list_courses(q: str = "", category: str = "", level: str = "", price: str = "", type: str = "", language: str = "", sort: str = "newest",
                 page: int = Query(1, ge=1, le=100000), page_size: int = Query(12, ge=1, le=50), db: Session = Depends(get_db)):
    st = select(Course).join(Category, Course.category_id == Category.id).where(Course.status == "published")
    if q.strip():
        like = f"%{esc(q.strip()[:100])}%"
        st = st.where(or_(*[col.ilike(like, escape="\\") for col in (Course.title_en, Course.title_am, Course.summary_en, Course.summary_am, Category.name_en, Category.name_am)]))
    if category: st = st.where(Category.slug == category)
    if level: st = st.where(Course.level == level)
    if price == "free": st = st.where(Course.price == 0)
    elif price == "paid": st = st.where(Course.price > 0)
    if type: st = st.where(Course.course_type == type)
    if language: st = st.where(or_(Course.language == language, Course.language == "both"))
    total = db.scalar(select(func.count()).select_from(st.subquery()))
    rows = db.scalars(st.order_by(*SORTS.get(sort, SORTS["newest"])(), Course.id).limit(page_size).offset((page - 1) * page_size)).all()
    return {"items": [cdict(c) for c in rows], "total": total, "page": page, "page_size": page_size, "pages": max(1, math.ceil(total / page_size))}
@app.get("/api/courses/{ref}")
def course_detail(ref: str, db: Session = Depends(get_db), u=Depends(user_opt)): return cdict(visible(db, ref, u), True)
@app.get("/api/courses/{ref}/curriculum")
def curriculum(ref: str, db: Session = Depends(get_db), u=Depends(user_opt)):
    c = visible(db, ref, u); acc = has_access(db, u, c); out = []
    for s in c.sections:
        ls = []
        for l in s.lessons:
            d = {"id": l.id, "title_en": l.title_en, "title_am": l.title_am, "kind": l.kind, "duration_minutes": l.duration_minutes, "is_preview": l.is_preview, "locked": not (acc or l.is_preview)}
            if not d["locked"]: d.update(content_text=l.content_text, video_url=l.video_url)
            ls.append(d)
        out.append({"id": s.id, "title_en": s.title_en, "title_am": s.title_am, "lessons": ls})
    mats = [{"id": m.id, "filename": m.filename, "size": m.size} for m in db.scalars(select(Material).where(Material.course_id == c.id))] if acc else []
    return {"course_id": c.id, "has_access": acc, "sections": out, "materials": mats}
MEDIA = {"jpg": "image/jpeg", "png": "image/png", "webp": "image/webp", "pdf": "application/pdf", "zip": "application/zip", "txt": "text/plain; charset=utf-8"}
@app.get("/api/courses/{ref}/thumbnail")
def thumbnail(ref: str, db: Session = Depends(get_db), u=Depends(user_opt)):
    c = visible(db, ref, u); p = UPLOADS / "thumbs" / (c.thumbnail or "none")
    if not c.thumbnail or not p.is_file(): raise HTTPException(404, "No thumbnail")
    return FileResponse(p, media_type=MEDIA[p.suffix[1:]], headers={"Cache-Control": "public, max-age=300"})
@app.get("/api/materials/{mid}")
def material(mid: str, db: Session = Depends(get_db), u=Depends(user_req)):
    m = db.get(Material, mid)
    if not m: raise HTTPException(404, "Not found")
    c = db.get(Course, m.course_id)
    if not (has_access(db, u, c) and (c.status == "published" or can_manage(u, c))): raise HTTPException(403, "Enrol in this course to download materials")
    return FileResponse(UPLOADS / "materials" / m.stored, media_type=m.content_type, filename=m.filename)

# ---------- student: enrolment & progress ----------
@app.post("/api/courses/{ref}/enroll")
def enroll(ref: str, db: Session = Depends(get_db), u=Depends(user_req)):
    c = visible(db, ref, u)
    if c.status != "published": raise HTTPException(409, "Course is not published")
    if c.price > 0: raise HTTPException(402, "Paid enrolment is not available yet: payment integration is not built")
    if not db.scalar(select(Enrollment.id).where(Enrollment.user_id == u.id, Enrollment.course_id == c.id)): db.add(Enrollment(user_id=u.id, course_id=c.id)); db.commit()
    return {"enrolled": True}
@app.get("/api/me/enrollments")
def my_enrollments(db: Session = Depends(get_db), u=Depends(user_req)):
    out = []
    for c in db.scalars(select(Course).join(Enrollment, Enrollment.course_id == Course.id).where(Enrollment.user_id == u.id, Course.status == "published")):
        done = db.scalar(select(func.count()).select_from(Progress).where(Progress.user_id == u.id, Progress.course_id == c.id))
        out.append({**cdict(c), "completed_lessons": done})
    return out
@app.post("/api/lessons/{lid}/complete")
def complete(lid: str, db: Session = Depends(get_db), u=Depends(user_req)):
    l = db.get(Lesson, lid); c = db.get(Course, l.course_id) if l else None
    if not c or c.status != "published": raise HTTPException(404, "Lesson not found")
    if not db.scalar(select(Enrollment.id).where(Enrollment.user_id == u.id, Enrollment.course_id == c.id)): raise HTTPException(403, "Enrol first")
    if not db.scalar(select(Progress.id).where(Progress.user_id == u.id, Progress.lesson_id == lid)): db.add(Progress(user_id=u.id, lesson_id=lid, course_id=c.id)); db.commit()
    done = db.scalar(select(func.count()).select_from(Progress).where(Progress.user_id == u.id, Progress.course_id == c.id))
    return {"completed_lessons": done, "lesson_count": c.lesson_count}

# ---------- teacher / admin management ----------
@app.get("/api/manage/courses")
def manage_list(status: str = "", db: Session = Depends(get_db), u=Depends(staff)):
    st = select(Course).order_by(Course.updated_at.desc())
    if u.role != "admin": st = st.join(course_teachers, course_teachers.c.course_id == Course.id).where(course_teachers.c.user_id == u.id)
    if status: st = st.where(Course.status == status)
    return [{**cdict(c), "status": c.status, "review_note": c.review_note} for c in db.scalars(st)]
@app.post("/api/manage/courses", status_code=201)
def manage_create(b: CourseIn, db: Session = Depends(get_db), u=Depends(staff)):
    if not db.get(Category, b.category_id): raise HTTPException(422, "Unknown category")
    c = Course(slug=slugify(db, b.title_en), status="draft", **b.model_dump())
    if u.role == "teacher": c.teachers.append(u)
    db.add(c); db.commit(); return mdict(c)
@app.get("/api/manage/courses/{cid}")
def manage_get(cid: str, db: Session = Depends(get_db), u=Depends(staff)):
    c = get_course(db, cid)
    if not can_manage(u, c): raise HTTPException(403, "You cannot manage this course")
    return mdict(c)
@app.patch("/api/manage/courses/{cid}")
def manage_patch(cid: str, b: CoursePatch, db: Session = Depends(get_db), u=Depends(staff)):
    c = for_edit(db, cid, u); data = b.model_dump(exclude_unset=True)
    if "category_id" in data and not db.get(Category, data["category_id"]): raise HTTPException(422, "Unknown category")
    for k, v in data.items():
        if v is not None: setattr(c, k, v)
    db.commit(); return mdict(c)
@app.delete("/api/manage/courses/{cid}")
def manage_delete(cid: str, db: Session = Depends(get_db), u=Depends(staff)):
    c = for_edit(db, cid, u)
    if c.status == "published" or db.scalar(select(Enrollment.id).where(Enrollment.course_id == c.id)): raise HTTPException(409, "Courses with students cannot be deleted; unpublish instead")
    for m in c.materials: (UPLOADS / "materials" / m.stored).unlink(missing_ok=True)
    if c.thumbnail: (UPLOADS / "thumbs" / c.thumbnail).unlink(missing_ok=True)
    db.delete(c); db.commit(); return {"ok": True}

async def read_limited(f: UploadFile, limit: int):
    data = await f.read(limit + 1)
    if len(data) > limit: raise HTTPException(413, "File too large")
    return data
def sniff(d: bytes):
    if d[:3] == b"\xff\xd8\xff": return "jpg"
    if d[:8] == b"\x89PNG\r\n\x1a\n": return "png"
    if d[:4] == b"RIFF" and d[8:12] == b"WEBP": return "webp"
    if d[:5] == b"%PDF-": return "pdf"
    if d[:4] == b"PK\x03\x04": return "zip"
    try:
        if b"\x00" not in d: d.decode("utf-8"); return "txt"
    except UnicodeDecodeError: pass
    return None
@app.post("/api/manage/courses/{cid}/thumbnail")
async def upload_thumb(cid: str, file: UploadFile = File(...), db: Session = Depends(get_db), u=Depends(staff)):
    c = for_edit(db, cid, u); data = await read_limited(file, MAX_THUMB); kind = sniff(data)
    if kind not in ("jpg", "png", "webp"): raise HTTPException(415, "Thumbnail must be a JPEG, PNG or WebP image")
    (UPLOADS / "thumbs").mkdir(parents=True, exist_ok=True); name = f"{uid()}.{kind}"; (UPLOADS / "thumbs" / name).write_bytes(data)
    if c.thumbnail: (UPLOADS / "thumbs" / c.thumbnail).unlink(missing_ok=True)
    c.thumbnail = name; db.commit(); return {"thumbnail_url": f"/api/courses/{c.id}/thumbnail"}
@app.post("/api/manage/courses/{cid}/materials", status_code=201)
async def upload_material(cid: str, file: UploadFile = File(...), db: Session = Depends(get_db), u=Depends(staff)):
    c = for_edit(db, cid, u); data = await read_limited(file, MAX_MATERIAL); kind = sniff(data)
    if kind is None: raise HTTPException(415, "Allowed: PDF, ZIP, PNG, JPEG, WebP, plain text")
    (UPLOADS / "materials").mkdir(parents=True, exist_ok=True); name = f"{uid()}.{kind}"; (UPLOADS / "materials" / name).write_bytes(data)
    m = Material(course_id=c.id, filename=re.sub(r"[^\w.\- ]", "_", os.path.basename(file.filename or "file"))[:150], stored=name, content_type=MEDIA[kind].split(";")[0], size=len(data))
    db.add(m); db.commit(); return {"id": m.id, "filename": m.filename, "size": m.size}

@app.delete("/api/manage/materials/{mid}")
def delete_material(mid: str, db: Session = Depends(get_db), u=Depends(staff)):
    m = db.get(Material, mid)
    if not m: raise HTTPException(404, "Material not found")
    for_edit(db, m.course_id, u); (UPLOADS / "materials" / m.stored).unlink(missing_ok=True); db.delete(m); db.commit(); return {"ok": True}

def next_pos(db, model, col, val):
    return (db.scalar(select(func.max(model.position)).where(col == val)) or 0) + 1
@app.post("/api/manage/courses/{cid}/sections", status_code=201)
def add_section(cid: str, b: SectionIn, db: Session = Depends(get_db), u=Depends(staff)):
    c = for_edit(db, cid, u); s = Section(course_id=c.id, title_en=b.title_en, title_am=b.title_am, position=b.position or next_pos(db, Section, Section.course_id, c.id))
    db.add(s); db.commit(); return {"id": s.id, "position": s.position}
def own_section(db, sid, u):
    s = db.get(Section, sid)
    if not s: raise HTTPException(404, "Section not found")
    return s, for_edit(db, s.course_id, u)
@app.patch("/api/manage/sections/{sid}")
def patch_section(sid: str, b: SectionPatch, db: Session = Depends(get_db), u=Depends(staff)):
    s, _ = own_section(db, sid, u)
    for k, v in b.model_dump(exclude_unset=True).items():
        if v is not None: setattr(s, k, v)
    db.commit(); return {"ok": True}
@app.delete("/api/manage/sections/{sid}")
def del_section(sid: str, db: Session = Depends(get_db), u=Depends(staff)):
    s, c = own_section(db, sid, u); db.delete(s); db.flush(); db.expire(c); recalc(db, c); db.commit(); return {"ok": True}
@app.post("/api/manage/sections/{sid}/lessons", status_code=201)
def add_lesson(sid: str, b: LessonIn, db: Session = Depends(get_db), u=Depends(staff)):
    s, c = own_section(db, sid, u); ok_video(b.video_url); d = b.model_dump(); pos = d.pop("position")
    l = Lesson(section_id=s.id, course_id=c.id, position=pos or next_pos(db, Lesson, Lesson.section_id, s.id), **d); db.add(l); recalc(db, c); db.commit(); return {"id": l.id, "position": l.position}
def own_lesson(db, lid, u):
    l = db.get(Lesson, lid)
    if not l: raise HTTPException(404, "Lesson not found")
    return l, for_edit(db, l.course_id, u)
@app.patch("/api/manage/lessons/{lid}")
def patch_lesson(lid: str, b: LessonPatch, db: Session = Depends(get_db), u=Depends(staff)):
    l, c = own_lesson(db, lid, u); data = b.model_dump(exclude_unset=True); ok_video(data.get("video_url") or "")
    for k, v in data.items():
        if v is not None: setattr(l, k, v)
    recalc(db, c); db.commit(); return {"ok": True}
@app.delete("/api/manage/lessons/{lid}")
def del_lesson(lid: str, db: Session = Depends(get_db), u=Depends(staff)):
    l, c = own_lesson(db, lid, u); db.delete(l); recalc(db, c); db.commit(); return {"ok": True}

# ---------- publishing workflow: draft -> pending_review -> published | rejected ; published -> unpublished -> (edit) -> resubmit ----------
def problems(c):
    p = []
    if not c.thumbnail: p.append("A thumbnail is required")
    if not any(s.lessons for s in c.sections): p.append("Add at least one section with one lesson")
    if not c.summary_en.strip(): p.append("A short English summary is required")
    for s in c.sections:
        for l in s.lessons:
            if l.kind == "video" and not l.video_url: p.append(f"Video lesson '{l.title_en}' has no video link")
            if l.kind == "text" and not l.content_text.strip(): p.append(f"Text lesson '{l.title_en}' has no content")
    return p
@app.post("/api/manage/courses/{cid}/submit")
def submit(cid: str, db: Session = Depends(get_db), u=Depends(staff)):
    c = for_edit(db, cid, u)
    if c.status not in ("draft", "rejected", "unpublished"): raise HTTPException(409, f"Cannot submit a {c.status} course")
    p = problems(c)
    if p: raise HTTPException(422, {"message": "Course is not ready", "problems": p})
    c.submitted_at = now()
    if u.role == "admin" or not REQUIRE_APPROVAL: c.status, c.published_at = "published", now()
    else: c.status = "pending_review"
    c.review_note = ""; db.commit(); return {"status": c.status}
@app.post("/api/manage/courses/{cid}/unpublish")
def unpublish(cid: str, db: Session = Depends(get_db), u=Depends(staff)):
    c = get_course(db, cid)
    if not can_manage(u, c): raise HTTPException(403, "You cannot manage this course")
    if c.status not in ("published", "pending_review"): raise HTTPException(409, f"Cannot unpublish a {c.status} course")
    c.status = "unpublished"; db.commit(); return {"status": c.status}
@app.get("/api/admin/review-queue")
def queue(db: Session = Depends(get_db), u=Depends(admin)):
    return [{**cdict(c), "status": c.status, "submitted_at": c.submitted_at.isoformat() if c.submitted_at else None} for c in db.scalars(select(Course).where(Course.status == "pending_review").order_by(Course.submitted_at))]
@app.post("/api/admin/courses/{cid}/approve")
def approve(cid: str, db: Session = Depends(get_db), u=Depends(admin)):
    c = get_course(db, cid)
    if c.status not in ("pending_review", "unpublished"): raise HTTPException(409, f"Cannot approve a {c.status} course")
    if problems(c): raise HTTPException(422, {"message": "Course is not ready", "problems": problems(c)})
    c.status, c.published_at, c.review_note = "published", now(), ""; db.commit(); return {"status": c.status}
@app.post("/api/admin/courses/{cid}/reject")
def reject(cid: str, b: Note, db: Session = Depends(get_db), u=Depends(admin)):
    c = get_course(db, cid)
    if c.status != "pending_review": raise HTTPException(409, "Only courses pending review can be rejected")
    c.status, c.review_note = "rejected", b.note; db.commit(); return {"status": c.status}
@app.post("/api/admin/courses/{cid}/teachers")
def add_teacher(cid: str, b: TeacherAdd, db: Session = Depends(get_db), u=Depends(admin)):
    c = get_course(db, cid); t = db.scalar(select(User).where(User.email == b.email.strip().lower(), User.role == "teacher"))
    if not t: raise HTTPException(404, "No teacher with that email")
    if t not in c.teachers: c.teachers.append(t); db.commit()
    return {"ok": True}

# ---------- admin: teacher applications ----------
def application_dict(x):
    return {"id": x.id, "name": x.name, "email": x.email, "expertise": x.expertise,
            "motivation": x.motivation, "status": x.status, "review_note": x.review_note,
            "created_at": x.created_at.isoformat(), "reviewed_at": x.reviewed_at.isoformat() if x.reviewed_at else None}

@app.get("/api/admin/teacher-applications")
def teacher_applications(db: Session = Depends(get_db), u=Depends(admin)):
    return [application_dict(x) for x in db.scalars(select(TeacherApplication).order_by(TeacherApplication.created_at.desc()))]

@app.post("/api/admin/teacher-applications/{application_id}/approve")
def approve_teacher_application(application_id: str, db: Session = Depends(get_db), u=Depends(admin)):
    x = db.get(TeacherApplication, application_id)
    if not x: raise HTTPException(404, "Application not found")
    if x.status != "pending": raise HTTPException(409, f"Application is already {x.status}")
    existing = db.scalar(select(User).where(User.email == x.email))
    if existing:
        if existing.role != "student": raise HTTPException(409, "This email already belongs to a staff account.")
        existing.role = "teacher"
        teacher = existing
    else:
        teacher = User(email=x.email, name=x.name, password_hash=x.password_hash, role="teacher")
        db.add(teacher)
    x.status, x.review_note, x.reviewed_at = "approved", "", now()
    db.commit()
    return {"status": x.status, "teacher": udict(teacher)}

@app.post("/api/admin/teacher-applications/{application_id}/reject")
def reject_teacher_application(application_id: str, b: ApplicationDecision, db: Session = Depends(get_db), u=Depends(admin)):
    x = db.get(TeacherApplication, application_id)
    if not x: raise HTTPException(404, "Application not found")
    if x.status != "pending": raise HTTPException(409, f"Application is already {x.status}")
    x.status, x.review_note, x.reviewed_at = "rejected", b.note.strip(), now()
    db.commit()
    return {"status": x.status}

# ---------- admin: users & categories ----------
@app.get("/api/admin/users")
def users(db: Session = Depends(get_db), u=Depends(admin)): return [{**udict(x), "is_active": x.is_active} for x in db.scalars(select(User).order_by(User.created_at))]
@app.post("/api/admin/users", status_code=201)
def admin_create_user(b: AdminUser, db: Session = Depends(get_db), u=Depends(admin)):
    em = b.email.strip().lower()
    if not EMAIL.match(em): raise HTTPException(422, "Invalid email address")
    if db.scalar(select(User.id).where(User.email == em)): raise HTTPException(409, "Email already registered")
    x = User(email=em, name=b.name.strip(), password_hash=hash_pw(b.password), role=b.role); db.add(x); db.commit(); return udict(x)
@app.patch("/api/admin/users/{xid}")
def patch_user(xid: str, b: UserPatch, db: Session = Depends(get_db), u=Depends(admin)):
    x = db.get(User, xid)
    if not x: raise HTTPException(404, "User not found")
    if x.id == u.id: raise HTTPException(400, "You cannot change your own role or status")
    leaving = x.role == "admin" and ((b.role and b.role != "admin") or b.is_active is False)
    if leaving and db.scalar(select(func.count()).select_from(User).where(User.role == "admin", User.is_active)) <= 1: raise HTTPException(400, "Cannot remove the last administrator")
    if b.role: x.role = b.role
    if b.is_active is not None:
        x.is_active = b.is_active
        if not b.is_active: db.execute(SessionRow.__table__.delete().where(SessionRow.user_id == x.id))
    db.commit(); return {**udict(x), "is_active": x.is_active}
@app.get("/api/admin/categories")
def admin_categories(db: Session = Depends(get_db), u=Depends(admin)):
    return [{"id": c.id, "slug": c.slug, "name_en": c.name_en, "name_am": c.name_am, "position": c.position, "is_active": c.is_active}
            for c in db.scalars(select(Category).order_by(Category.position, Category.id))]
@app.post("/api/admin/categories", status_code=201)
def add_cat(b: CatIn, db: Session = Depends(get_db), u=Depends(admin)):
    if db.scalar(select(Category.id).where(Category.slug == b.slug)): raise HTTPException(409, "Slug already exists")
    c = Category(**b.model_dump()); db.add(c); db.commit(); return {"id": c.id}
@app.patch("/api/admin/categories/{cid}")
def patch_cat(cid: int, b: CatIn, db: Session = Depends(get_db), u=Depends(admin)):
    c = db.get(Category, cid)
    if not c: raise HTTPException(404, "Not found")
    if db.scalar(select(Category.id).where(Category.slug == b.slug, Category.id != cid)): raise HTTPException(409, "Slug already exists")
    for k, v in b.model_dump().items(): setattr(c, k, v)
    db.commit(); return {"ok": True}
@app.get("/api/health")
def health(): return {"ok": True}

# Serve the frontend files whether they are in /static or at the repository root.
if (BASE / "static").is_dir():
    app.mount("/", StaticFiles(directory=str(BASE / "static"), html=True), name="static")
else:
    @app.get("/", include_in_schema=False)
    def homepage():
        index = BASE / "index.html"
        if not index.is_file(): raise HTTPException(404, "Website homepage not found")
        return FileResponse(index)

    @app.get("/dashboard.html", include_in_schema=False)
    def dashboard_page():
        dashboard = BASE / "dashboard.html"
        if not dashboard.is_file(): raise HTTPException(404, "Dashboard page not found")
        return FileResponse(dashboard)

    @app.get("/favicon.ico", include_in_schema=False)
    def favicon():
        return Response(status_code=204)

if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else "serve"
    if cmd == "init": init_db(); print("Database ready.")
    else:
        import uvicorn; uvicorn.run(app, host=os.getenv("HOST", "127.0.0.1"), port=int(os.getenv("PORT", "8000")))
