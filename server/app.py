"""Comic Studio AI API - initial single-workspace MVP.

The v0.1 server is intentionally single-user. Do not expose it to the Internet.
"""
from __future__ import annotations

import base64
from datetime import datetime, timezone
from hashlib import sha256
from html import escape
from io import BytesIO
import json
import math
import os
from pathlib import Path
from uuid import uuid4

import cairosvg
from fastapi import FastAPI, File, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import Response
from PIL import Image, UnidentifiedImageError
from providers import MockImageProvider, provider_manifest
import ai_pipeline
from pydantic import BaseModel, Field
from sqlalchemy import ForeignKey, Integer, String, Text, create_engine, select, UniqueConstraint, func
from sqlalchemy.orm import DeclarativeBase, Mapped, Session, mapped_column, sessionmaker

DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///./comic_studio.db")
ASSET_DIR = Path(os.getenv("ASSET_DIR", "./assets")).resolve()
ASSET_DIR.mkdir(parents=True, exist_ok=True)
engine = create_engine(DATABASE_URL, connect_args={"check_same_thread": False} if DATABASE_URL.startswith("sqlite") else {}, pool_pre_ping=True)
SessionLocal = sessionmaker(engine, expire_on_commit=False)

class Base(DeclarativeBase):
    pass

class Project(Base):
    __tablename__ = "projects"
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    title: Mapped[str] = mapped_column(String(160))
    premise: Mapped[str] = mapped_column(Text, default="")
    style: Mapped[str] = mapped_column(String(120), default="3D动画电影风")
    panel_count: Mapped[int] = mapped_column(Integer, default=4)
    outline: Mapped[str] = mapped_column(Text, default="")
    updated_at: Mapped[str] = mapped_column(String(40))

class Character(Base):
    __tablename__ = "characters"
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    project_id: Mapped[str] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"))
    name: Mapped[str] = mapped_column(String(100))
    appearance: Mapped[str] = mapped_column(Text, default="")
    personality: Mapped[str] = mapped_column(Text, default="")
    reference_asset_id: Mapped[str | None] = mapped_column(String(36), nullable=True)

class Panel(Base):
    __tablename__ = "panels"
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    project_id: Mapped[str] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"))
    sequence: Mapped[int] = mapped_column(Integer)
    scene: Mapped[str] = mapped_column(Text, default="")
    camera: Mapped[str] = mapped_column(String(80), default="中景")
    approved_asset_id: Mapped[str | None] = mapped_column(String(36), nullable=True)

class Dialogue(Base):
    __tablename__ = "dialogues"
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    panel_id: Mapped[str] = mapped_column(ForeignKey("panels.id", ondelete="CASCADE"))
    speaker_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    text: Mapped[str] = mapped_column(Text)
    locked: Mapped[bool] = mapped_column(default=False)
    version: Mapped[int] = mapped_column(Integer, default=1)
    x: Mapped[float] = mapped_column(default=.06)
    y: Mapped[float] = mapped_column(default=.06)
    w: Mapped[float] = mapped_column(default=.84)
    h: Mapped[float] = mapped_column(default=.25)

class Asset(Base):
    __tablename__ = "assets"
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    project_id: Mapped[str] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"))
    panel_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    path: Mapped[str] = mapped_column(String(300))
    content_hash: Mapped[str] = mapped_column(String(64))
    mime: Mapped[str] = mapped_column(String(50), default="image/png")
    created_at: Mapped[str] = mapped_column(String(40))

class StoryDraft(Base):
    __tablename__ = "story_drafts"
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    project_id: Mapped[str] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"))
    status: Mapped[str] = mapped_column(String(20), default="pending")
    payload: Mapped[str] = mapped_column(Text)
    created_at: Mapped[str] = mapped_column(String(40))


class CharacterReference(Base):
    """Versioned references; never overwrite an earlier image, including after selecting a new active asset."""
    __tablename__ = "character_references"
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    character_id: Mapped[str] = mapped_column(ForeignKey("characters.id", ondelete="CASCADE"))
    asset_id: Mapped[str] = mapped_column(ForeignKey("assets.id"))
    angle: Mapped[str] = mapped_column(String(24))
    note: Mapped[str] = mapped_column(String(300), default="")
    created_at: Mapped[str] = mapped_column(String(40))


class GenerationJob(Base):
    """Durable jobs. One worker leases one job using SELECT FOR UPDATE SKIP LOCKED on PostgreSQL."""
    __tablename__ = "generation_jobs"
    __table_args__ = (UniqueConstraint("project_id","request_key",name="uq_job_project_key"),)
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    project_id: Mapped[str] = mapped_column(ForeignKey("projects.id",ondelete="CASCADE"))
    panel_id: Mapped[str] = mapped_column(ForeignKey("panels.id",ondelete="CASCADE"))
    status: Mapped[str] = mapped_column(String(24),default="queued")
    provider: Mapped[str] = mapped_column(String(24),default="mock")
    prompt: Mapped[str] = mapped_column(Text)
    references: Mapped[str] = mapped_column(Text,default="[]")
    request_key: Mapped[str] = mapped_column(String(100))
    attempt: Mapped[int] = mapped_column(Integer,default=0)
    max_attempts: Mapped[int] = mapped_column(Integer,default=2)
    candidate_asset_id: Mapped[str|None] = mapped_column(String(36),nullable=True)
    error_code: Mapped[str|None] = mapped_column(String(100),nullable=True)
    created_at: Mapped[str] = mapped_column(String(40))
    updated_at: Mapped[str] = mapped_column(String(40))


class QueueImageIn(BaseModel):
    provider: str = "mock"
    character_ids: list[str] = Field(default_factory=list,max_length=8)
    prompt_override: str = Field(default="",max_length=2000)
    request_key: str|None = Field(default=None,min_length=1,max_length=100)


class ReferenceMeta(BaseModel):
    angle: str = "front"
    note: str = Field(default="",max_length=300)


class ImageGenerateIn(BaseModel):
    character_ids: list[str] = Field(default_factory=list, max_length=8)
    prompt_override: str = Field(default="", max_length=2000)


class ProjectIn(BaseModel):
    title: str = Field(min_length=1, max_length=160)
    premise: str = ""
    style: str = "3D动画电影风"
    panel_count: int = Field(default=4)

class CharacterIn(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    appearance: str = ""
    personality: str = ""

class PanelUpdate(BaseModel):
    scene: str | None = None
    camera: str | None = None

class DialogueIn(BaseModel):
    text: str = Field(min_length=1, max_length=300)
    speaker_id: str | None = None
    x: float = .06
    y: float = .06
    w: float = .84
    h: float = .25

class DialogueUpdate(BaseModel):
    text: str | None = Field(default=None, min_length=1, max_length=300)
    speaker_id: str | None = None
    x: float | None = None
    y: float | None = None
    w: float | None = None
    h: float | None = None

app = FastAPI(title="Comic Studio AI", version="0.1.0")
app.add_middleware(CORSMiddleware, allow_origins=[os.getenv("WEB_ORIGIN", "http://localhost:5173")], allow_credentials=False, allow_methods=["*"], allow_headers=["*"])

@app.on_event("startup")
def initialize():
    Base.metadata.create_all(engine)  # v0.1 bootstrap; replace with Alembic migrations

def now() -> str:
    return datetime.now(timezone.utc).isoformat()

def require(db: Session, cls, pk):
    o = db.get(cls, pk)
    if o is None:
        raise HTTPException(404, f"{cls.__name__} not found")
    return o

def row_project(p: Project):
    return {"id":p.id,"title":p.title,"premise":p.premise,"style":p.style,"panel_count":p.panel_count,"outline":p.outline,"updated_at":p.updated_at}

def row_character(c: Character):
    return {"id":c.id,"project_id":c.project_id,"name":c.name,"appearance":c.appearance,"personality":c.personality,"reference_asset_id":c.reference_asset_id}

def row_dialogue(d: Dialogue):
    return {"id":d.id,"panel_id":d.panel_id,"speaker_id":d.speaker_id,"text":d.text,"locked":d.locked,"version":d.version,"x":d.x,"y":d.y,"w":d.w,"h":d.h}

def row_panel(p: Panel, db: Session):
    ds=db.scalars(select(Dialogue).where(Dialogue.panel_id==p.id).order_by(Dialogue.id)).all()
    return {"id":p.id,"project_id":p.project_id,"sequence":p.sequence,"scene":p.scene,"camera":p.camera,"approved_asset_id":p.approved_asset_id,"dialogues":[row_dialogue(d) for d in ds]}

def snapshot(db: Session, project_id: str):
    p=require(db, Project, project_id)
    cs=db.scalars(select(Character).where(Character.project_id==p.id).order_by(Character.name)).all()
    ps=db.scalars(select(Panel).where(Panel.project_id==p.id).order_by(Panel.sequence)).all()
    return {"project":row_project(p),"characters":[row_character(c) for c in cs],"panels":[row_panel(panel,db) for panel in ps]}

@app.get("/api/providers")
def list_providers():
    return provider_manifest()

def row_reference(r:CharacterReference):
    return {"id":r.id,"character_id":r.character_id,"asset_id":r.asset_id,
            "angle":r.angle,"note":r.note,"created_at":r.created_at}


def row_job(j:GenerationJob):
    return {"id":j.id,"project_id":j.project_id,"panel_id":j.panel_id,
            "status":j.status,"provider":j.provider,"attempt":j.attempt,
            "max_attempts":j.max_attempts,"candidate_asset_id":j.candidate_asset_id,
            "error_code":j.error_code,"created_at":j.created_at,"updated_at":j.updated_at}


@app.get("/api/ai/status")
def get_ai_status():
    return ai_pipeline.capability_status()


@app.post("/api/projects/{project_id}/story:ai", status_code=201)
def generate_story_draft(project_id: str):
    """Generate a reviewable draft; never overwrite any existing project content."""
    with SessionLocal() as db:
        p=require(db,Project,project_id)
        cast=db.scalars(select(Character).where(Character.project_id==p.id).order_by(Character.name)).all()
        req=(p.title,p.premise,p.style,p.panel_count,[
            {"name":c.name,"appearance":c.appearance,"personality":c.personality} for c in cast
        ])
    try:
        draft=ai_pipeline.story_draft(*req)
    except ai_pipeline.AIProviderError as exc:
        raise HTTPException(502,str(exc)) from exc
    with SessionLocal.begin() as db:
        require(db,Project,project_id)
        record=StoryDraft(id=str(uuid4()),project_id=project_id,payload=json.dumps(draft,ensure_ascii=False),
                          created_at=now(),status="pending")
        db.add(record)
        return {"id":record.id,"project_id":project_id,"status":record.status,"draft":draft}


@app.get("/api/projects/{project_id}/story-drafts")
def get_story_drafts(project_id: str):
    with SessionLocal() as db:
        require(db,Project,project_id)
        drafts=db.scalars(select(StoryDraft).where(StoryDraft.project_id==project_id).order_by(StoryDraft.created_at.desc())).all()
        return [{"id":d.id,"status":d.status,"created_at":d.created_at,"draft":json.loads(d.payload)} for d in drafts]


@app.post("/api/story-drafts/{draft_id}/apply")
def apply_story_draft(draft_id: str):
    """Atomic approval. Prevent accidental loss of user/Mock scripts."""
    with SessionLocal.begin() as db:
        draft=require(db,StoryDraft,draft_id)
        project=require(db,Project,draft.project_id)
        if draft.status!="pending":
            raise HTTPException(409,"Story draft already applied")
        panels=db.scalars(select(Panel).where(Panel.project_id==project.id).order_by(Panel.sequence)).all()
        if len(panels)!=project.panel_count:
            raise HTTPException(409,"Project panel count changed")
        existing=db.scalars(select(Dialogue).where(Dialogue.panel_id.in_([p.id for p in panels]))).all()
        if existing:
            raise HTTPException(409,"Project has existing dialogue; use a new project to apply AI draft without data loss")
        if project.outline.strip() or any(p.scene != f"第{p.sequence}格：待设计" or p.camera != "中景" for p in panels):
            raise HTTPException(409,"Project has manually planned story content; refusing to overwrite it")
        payload=json.loads(draft.payload)
        cast=db.scalars(select(Character).where(Character.project_id==project.id)).all()
        name_to_id={c.name:c.id for c in cast}
        for panel,proposed in zip(panels,payload["panels"]):
            if panel.sequence!=proposed["sequence"]:
                raise HTTPException(409,"Panel sequence mismatch")
            panel.scene=proposed["scene"]
            panel.camera=proposed["camera"]
            for j,line in enumerate(proposed["dialogues"]):
                speaker_name=line["speaker_name"]
                if speaker_name is not None and speaker_name not in name_to_id:
                    raise HTTPException(409,"Character roster changed since draft generation")
                # 2 bubbles in distinct upper/lower slots without overlap.
                db.add(Dialogue(id=str(uuid4()),panel_id=panel.id,speaker_id=name_to_id.get(speaker_name),
                                text=line["text"],y=.06+j*.30))
        project.outline=payload["outline"]
        project.updated_at=now()
        draft.status="applied"
        return {"project_id":project.id,"draft_id":draft.id,"status":draft.status}


@app.post("/api/characters/{character_id}/reference",status_code=201)
async def set_character_reference(character_id: str,file:UploadFile=File(...)):
    with SessionLocal() as db:
        character=require(db,Character,character_id)
        project_id=character.project_id
    raw=await file.read(ai_pipeline.MAX_IMAGE_BYTES+1)
    try:
        normalized=ai_pipeline.normalize_png(raw)
    except ai_pipeline.AIProviderError as exc:
        raise HTTPException(415,str(exc)) from exc
    asset_id=str(uuid4())
    filename=f"{asset_id}.png"
    (ASSET_DIR/filename).write_bytes(normalized)
    with SessionLocal.begin() as db:
        character=require(db,Character,character_id)
        if character.project_id!=project_id:
            raise HTTPException(409,"Character changed project")
        db.add(Asset(id=asset_id,project_id=project_id,panel_id=None,path=filename,
                     content_hash=sha256(normalized).hexdigest(),created_at=now()))
        character.reference_asset_id=asset_id
        return {"character_id":character_id,"reference_asset_id":asset_id}


@app.get("/api/characters/{character_id}/references")
def get_character_references(character_id:str):
    with SessionLocal() as db:
        require(db,Character,character_id)
        refs=db.scalars(select(CharacterReference).where(CharacterReference.character_id==character_id).order_by(CharacterReference.created_at.desc(),CharacterReference.id.desc())).all()
        return [row_reference(ref) for ref in refs]


@app.post("/api/characters/{character_id}/references",status_code=201)
async def upload_character_reference_version(character_id:str,file:UploadFile=File(...),angle:str="front",note:str=""):
    if angle not in {"front","side","back","expression","outfit"}:
        raise HTTPException(422,"angle must be front, side, back, expression or outfit")
    if len(note)>300:raise HTTPException(422,"note too long")
    with SessionLocal() as db:
        c=require(db,Character,character_id)
        project_id=c.project_id
    try:
        raw=await file.read(ai_pipeline.MAX_IMAGE_BYTES+1)
        normalized=ai_pipeline.normalize_png(raw)
    except ai_pipeline.AIProviderError as exc:
        raise HTTPException(415,str(exc)) from exc
    aid=str(uuid4());filename=f"{aid}.png"
    (ASSET_DIR/filename).write_bytes(normalized)
    with SessionLocal.begin() as db:
        character=require(db,Character,character_id)
        db.add(Asset(id=aid,project_id=project_id,panel_id=None,path=filename,content_hash=sha256(normalized).hexdigest(),created_at=now()))
        ref=CharacterReference(id=str(uuid4()),character_id=character.id,asset_id=aid,angle=angle,note=note,created_at=now())
        db.add(ref)
        if not character.reference_asset_id:character.reference_asset_id=aid
        db.flush()
        return row_reference(ref)


@app.post("/api/characters/{character_id}/references/{reference_id}/activate")
def activate_character_reference(character_id:str,reference_id:str):
    with SessionLocal.begin() as db:
        character=require(db,Character,character_id)
        ref=require(db,CharacterReference,reference_id)
        if ref.character_id!=character.id:raise HTTPException(422,"reference belongs to another character")
        asset=require(db,Asset,ref.asset_id)
        if asset.project_id!=character.project_id or asset.panel_id is not None:
            raise HTTPException(422,"reference asset ownership mismatch")
        character.reference_asset_id=ref.asset_id
        return {"character_id":character_id,"reference_asset_id":ref.asset_id,"reference_id":ref.id}


def build_job_payload(db:Session, panel:Panel, data:QueueImageIn):
    project=require(db,Project,panel.project_id)
    if len(set(data.character_ids))!=len(data.character_ids):raise HTTPException(422,"duplicate character ids")
    if data.character_ids:
        characters=[require(db,Character,cid) for cid in data.character_ids]
        if any(c.project_id!=project.id for c in characters):raise HTTPException(422,"character from another project")
    else:
        characters=db.scalars(select(Character).where(Character.project_id==project.id).order_by(Character.name)).all()
    cast=[{"name":c.name,"appearance":c.appearance,"personality":c.personality} for c in characters]
    prompt=ai_pipeline.build_panel_prompt(panel.scene,panel.camera,project.style,cast,data.prompt_override)
    refs=[]
    if data.provider=="ai" and ai_pipeline.reference_mode()=="edits":
        for c in characters:
            if c.reference_asset_id:
                asset=require(db,Asset,c.reference_asset_id)
                if asset.project_id!=project.id or asset.panel_id is not None:
                    raise HTTPException(422,"invalid character reference")
                refs.append(asset.id)
        if len(refs)>3:raise HTTPException(422,"maximum 3 reference images")
    return prompt,refs


@app.post("/api/panels/{panel_id}/jobs",status_code=202)
def enqueue_image_job(panel_id:str,data:QueueImageIn):
    if data.provider not in ("mock","ai"):raise HTTPException(422,"provider must be mock or ai")
    if data.provider=="ai" and not ai_pipeline.capability_status()["image"]["ready"]:
        raise HTTPException(422,"image provider not configured")
    request_key=data.request_key or str(uuid4())
    with SessionLocal.begin() as db:
        panel=require(db,Panel,panel_id)
        existing=db.scalars(select(GenerationJob).where(GenerationJob.project_id==panel.project_id,GenerationJob.request_key==request_key)).first()
        if existing:
            if existing.panel_id!=panel.id or existing.provider!=data.provider:
                raise HTTPException(409,"request key reused for another job")
            return row_job(existing)
        pending=db.scalar(select(func.count()).select_from(GenerationJob).where(
            GenerationJob.project_id==panel.project_id,
            GenerationJob.status.in_(["queued","running"])))
        if pending is not None and pending>=32:raise HTTPException(429,"project pending job quota reached")
        prompt,refs=build_job_payload(db,panel,data)
        job=GenerationJob(id=str(uuid4()),project_id=panel.project_id,panel_id=panel.id,
                          status="queued",provider=data.provider,prompt=prompt,references=json.dumps(refs),
                          request_key=request_key,created_at=now(),updated_at=now())
        db.add(job);db.flush()
        return row_job(job)


@app.get("/api/projects/{project_id}/jobs")
def list_generation_jobs(project_id:str):
    with SessionLocal() as db:
        require(db,Project,project_id)
        jobs=db.scalars(select(GenerationJob).where(GenerationJob.project_id==project_id).order_by(GenerationJob.created_at.desc())).all()
        return [row_job(job) for job in jobs[:100]]


@app.get("/api/jobs/{job_id}")
def get_generation_job(job_id:str):
    with SessionLocal() as db:
        return row_job(require(db,GenerationJob,job_id))


@app.post("/api/jobs/{job_id}/cancel")
def cancel_generation_job(job_id:str):
    with SessionLocal.begin() as db:
        job=require(db,GenerationJob,job_id)
        if job.status in ("queued","running"):
            job.status="cancelled";job.updated_at=now()
        return row_job(job)


@app.post("/api/jobs/{job_id}/retry")
def retry_generation_job(job_id:str):
    with SessionLocal.begin() as db:
        job=require(db,GenerationJob,job_id)
        if job.status!="failed":raise HTTPException(409,"only failed jobs may be retried")
        if job.attempt>=job.max_attempts:raise HTTPException(409,"maximum attempts reached")
        job.status="queued";job.error_code=None;job.updated_at=now()
        return row_job(job)


@app.get("/api/panels/{panel_id}/candidates")
def get_panel_candidates(panel_id: str):
    with SessionLocal() as db:
        panel=require(db,Panel,panel_id)
        assets=db.scalars(select(Asset).where(Asset.panel_id==panel.id).order_by(Asset.created_at.desc())).all()
        return [{"id":a.id,"url":f"/api/assets/{a.id}",
                 "approved":a.id==panel.approved_asset_id,"created_at":a.created_at} for a in assets]


@app.post("/api/panels/{panel_id}/generate:ai",status_code=201)
def generate_ai_panel(panel_id: str, data:ImageGenerateIn):
    """Generate a candidate only. Approval is always explicit."""
    with SessionLocal() as db:
        panel=require(db,Panel,panel_id)
        project=require(db,Project,panel.project_id)
        if len(set(data.character_ids))!=len(data.character_ids):
            raise HTTPException(422,"Duplicate character IDs")
        if data.character_ids:
            characters=[require(db,Character,cid) for cid in data.character_ids]
            if any(c.project_id!=project.id for c in characters):
                raise HTTPException(422,"Character from another project")
        else:
            characters=db.scalars(select(Character).where(Character.project_id==project.id).order_by(Character.name)).all()
        cast=[{"name":c.name,"appearance":c.appearance,"personality":c.personality} for c in characters]
        refs=[]
        if ai_pipeline.reference_mode()=="edits":
            for c in characters:
                if c.reference_asset_id:
                    asset=require(db,Asset,c.reference_asset_id)
                    if asset.project_id!=project.id or asset.panel_id is not None:
                        raise HTTPException(422,"Invalid character reference")
                    image_path=ASSET_DIR/asset.path
                    if not image_path.is_file():
                        raise HTTPException(422,"Character reference file is missing")
                    refs.append(image_path.read_bytes())
            if len(refs)>3:
                raise HTTPException(422,"Maximum 3 character reference images per request")
        prompt=ai_pipeline.build_panel_prompt(panel.scene,panel.camera,project.style,cast,data.prompt_override)
        project_id=project.id
    try:
        image_bytes=ai_pipeline.image_candidate(prompt,refs)
    except ai_pipeline.AIProviderError as exc:
        raise HTTPException(502,str(exc)) from exc
    asset_id=str(uuid4())
    filename=f"{asset_id}.png"
    (ASSET_DIR/filename).write_bytes(image_bytes)
    with SessionLocal.begin() as db:
        require(db,Panel,panel_id)
        db.add(Asset(id=asset_id,project_id=project_id,panel_id=panel_id,path=filename,
                     content_hash=sha256(image_bytes).hexdigest(),created_at=now()))
    return {"id":asset_id,"panel_id":panel_id,"approved":False,
            "reference_count":len(refs),"provider":"image-api"}


@app.get("/api/health")
def health():
    return {"status":"ok","version":"0.1.0"}

@app.get("/api/projects")
def list_projects():
    with SessionLocal() as db:
        return [row_project(p) for p in db.scalars(select(Project).order_by(Project.updated_at.desc())).all()]

@app.post("/api/projects", status_code=201)
def create_project(data: ProjectIn):
    if data.panel_count not in (4,6,8,12):
        raise HTTPException(422,"panel_count must be 4, 6, 8, or 12")
    with SessionLocal.begin() as db:
        p=Project(id=str(uuid4()),title=data.title,premise=data.premise,style=data.style,panel_count=data.panel_count,updated_at=now())
        db.add(p)
        db.flush()
        for i in range(data.panel_count):
            db.add(Panel(id=str(uuid4()),project_id=p.id,sequence=i+1,scene=f"第{i+1}格：待设计",camera="中景"))
        return row_project(p)

@app.get("/api/projects/{project_id}")
def get_project(project_id: str):
    with SessionLocal() as db:
        return snapshot(db,project_id)

@app.post("/api/projects/{project_id}/characters",status_code=201)
def add_character(project_id: str, data: CharacterIn):
    with SessionLocal.begin() as db:
        require(db,Project,project_id)
        c=Character(id=str(uuid4()),project_id=project_id,**data.model_dump())
        db.add(c)
        db.flush()
        return row_character(c)

@app.patch("/api/characters/{character_id}")
def edit_character(character_id: str, data: CharacterIn):
    with SessionLocal.begin() as db:
        c=require(db,Character,character_id)
        for k,v in data.model_dump().items():setattr(c,k,v)
        return row_character(c)

@app.post("/api/projects/{project_id}/story:mock")
def mock_story(project_id: str):
    """Deterministic offline storyboard plan. No calls to any model provider."""
    with SessionLocal.begin() as db:
        p=require(db,Project,project_id)
        p.outline=f"围绕「{p.premise or p.title}」展开：起因、发展、冲突、结局。"
        panels=db.scalars(select(Panel).where(Panel.project_id==p.id).order_by(Panel.sequence)).all()
        arcs=["交代人物与故事背景","人物产生互动","矛盾逐渐升级","转折并完成结局"]
        demo_lines=["今天又要开始新任务了！","我已经做好准备了！","等等，怎么会这样？","原来是个误会，解决了！"]
        cast=db.scalars(select(Character).where(Character.project_id==p.id).order_by(Character.name)).all()
        for i,panel in enumerate(panels):
            panel.scene=f"{arcs[min(3,math.floor(i*4/len(panels)))]}；主题：{p.premise or p.title}"
            exists=db.scalars(select(Dialogue).where(Dialogue.panel_id==panel.id)).first()
            if not exists:
                speaker=cast[i%len(cast)].id if cast else None
                db.add(Dialogue(id=str(uuid4()),panel_id=panel.id,speaker_id=speaker,text=demo_lines[min(3,math.floor(i*4/len(panels)))]))
        return snapshot(db,project_id)

@app.patch("/api/panels/{panel_id}")
def edit_panel(panel_id: str,data:PanelUpdate):
    with SessionLocal.begin() as db:
        p=require(db,Panel,panel_id)
        for k,v in data.model_dump(exclude_none=True).items():setattr(p,k,v)
        return row_panel(p,db)

def check_geometry(d):
    if not all(math.isfinite(v) for v in (d.x,d.y,d.w,d.h)) or d.x<0 or d.y<0 or d.w<=0 or d.h<=0 or d.x+d.w>1.00001 or d.y+d.h>1.00001:
        raise HTTPException(422,"bubble coordinates must fit within panel (0..1)")

@app.post("/api/panels/{panel_id}/dialogues",status_code=201)
def add_dialogue(panel_id: str,data:DialogueIn):
    with SessionLocal.begin() as db:
        p=require(db,Panel,panel_id)
        if "y" not in data.model_fields_set:
            existing=db.scalars(select(Dialogue).where(Dialogue.panel_id==panel_id)).all()
            data.y=.06+.30*len(existing)
        check_geometry(data)
        if data.speaker_id:
            c=require(db,Character,data.speaker_id)
            if c.project_id!=p.project_id:raise HTTPException(422,"speaker from different project")
        d=Dialogue(id=str(uuid4()),panel_id=panel_id,**data.model_dump())
        db.add(d);db.flush()
        return row_dialogue(d)

@app.patch("/api/dialogues/{dialogue_id}")
def edit_dialogue(dialogue_id: str,data:DialogueUpdate):
    with SessionLocal.begin() as db:
        d=require(db,Dialogue,dialogue_id)
        changed=data.model_dump(exclude_unset=True)
        if d.locked and ("text" in changed or "speaker_id" in changed):
            raise HTTPException(409,"locked dialogue text or speaker cannot be edited")
        for k,v in changed.items():setattr(d,k,v)
        if not d.text or len(d.text)>300:raise HTTPException(422,"invalid dialogue")
        check_geometry(d)
        if d.speaker_id:
            c=require(db,Character,d.speaker_id)
            p=require(db,Panel,d.panel_id)
            if c.project_id!=p.project_id:raise HTTPException(422,"speaker from different project")
        if changed:d.version+=1
        return row_dialogue(d)

@app.post("/api/dialogues/{dialogue_id}/lock")
def lock_dialogue(dialogue_id: str):
    with SessionLocal.begin() as db:
        d=require(db,Dialogue,dialogue_id);d.locked=True;return row_dialogue(d)

@app.post("/api/dialogues/{dialogue_id}/unlock")
def unlock_dialogue(dialogue_id: str):
    with SessionLocal.begin() as db:
        d=require(db,Dialogue,dialogue_id);d.locked=False;return row_dialogue(d)

@app.post("/api/panels/{panel_id}/assets",status_code=201)
async def upload_panel_image(panel_id: str, file: UploadFile = File(...)):
    with SessionLocal() as db:
        p=require(db,Panel,panel_id)
        project_id=p.project_id
    raw=await file.read(12*1024*1024+1)
    if len(raw)>12*1024*1024:raise HTTPException(413,"image too large (12MB limit)")
    try:
        with Image.open(BytesIO(raw)) as img:
            img.load()
            if img.width*img.height>30_000_000:raise HTTPException(413,"image dimensions too large")
            image=img.convert("RGB")
            bio=BytesIO();image.save(bio,format="PNG",optimize=True)
            normalized=bio.getvalue()
    except (UnidentifiedImageError,OSError,ValueError) as ex:
        raise HTTPException(415,"invalid raster image") from ex
    aid=str(uuid4());name=f"{aid}.png"; path=ASSET_DIR/name
    path.write_bytes(normalized)
    with SessionLocal.begin() as db:
        asset=Asset(id=aid,project_id=project_id,panel_id=panel_id,path=name,content_hash=sha256(normalized).hexdigest(),created_at=now())
        db.add(asset)
    return {"id":aid,"panel_id":panel_id,"sha256":asset.content_hash}

@app.post("/api/panels/{panel_id}/generate:mock",status_code=201)
def generate_mock_panel(panel_id: str):
    """Offline illustrative Mock image. Creates a candidate, not an approval."""
    with SessionLocal() as db:
        panel=require(db,Panel,panel_id)
        project=require(db,Project,panel.project_id)
        project_id=project.id
        sequence=panel.sequence
        count=project.panel_count
    generated=MockImageProvider().generate(sequence,count,panel_id)
    aid=str(uuid4())
    filename=f"{aid}.png"
    (ASSET_DIR/filename).write_bytes(generated)
    with SessionLocal.begin() as db:
        db.add(Asset(id=aid,project_id=project_id,panel_id=panel_id,path=filename,content_hash=sha256(generated).hexdigest(),created_at=now()))
    return {"id":aid,"panel_id":panel_id,"mock":True}

@app.post("/api/panels/{panel_id}/approve/{asset_id}")
def approve_asset(panel_id: str,asset_id: str):
    with SessionLocal.begin() as db:
        p=require(db,Panel,panel_id)
        a=require(db,Asset,asset_id)
        if a.panel_id!=p.id or a.project_id!=p.project_id:raise HTTPException(422,"asset not owned by panel")
        p.approved_asset_id=a.id
        return {"panel_id":p.id,"approved_asset_id":a.id}

@app.get("/api/assets/{asset_id}")
def get_asset(asset_id: str):
    with SessionLocal() as db:
        a=require(db,Asset,asset_id)
        path=ASSET_DIR/a.path
        if not path.is_file():raise HTTPException(404,"asset data missing")
        return Response(path.read_bytes(),media_type="image/png")

# Typography: Unicode width is estimated conservatively; overflow rejects rather than clipping.
def split_zh(text:str, limit:int)->list[str]:
    result=[];part="";units=0
    for char in text:
        size=1 if ord(char)<128 else 2
        if units+size>limit and part:
            result.append(part);part="";units=0
        part+=char;units+=size
    if part:result.append(part)
    return result

def render(project_id:str,db:Session,validate:bool=True):
    data=snapshot(db,project_id)
    p=data["project"]; panels=data["panels"]
    columns={4:2,6:3,8:4,12:4}[p["panel_count"]]
    rows=math.ceil(p["panel_count"]/columns)
    W,H=1920,1080; pad=30;top=108; gap=16
    pw=(W-2*pad-(columns-1)*gap)/columns
    ph=(H-top-pad-(rows-1)*gap)/rows
    svg=[f'<svg xmlns="http://www.w3.org/2000/svg" xmlns:xlink="http://www.w3.org/1999/xlink" width="{W}" height="{H}" viewBox="0 0 {W} {H}">',
         '<rect width="1920" height="1080" fill="#eaf0f7"/>',
         f'<text x="{W/2}" y="69" font-size="44" text-anchor="middle" fill="#162c4b" font-family="Noto Sans CJK SC,sans-serif" font-weight="700">{escape(p["title"])}</text>']
    errors=[]
    for i,panel in enumerate(panels):
        x=pad+(i%columns)*(pw+gap);y=top+(i//columns)*(ph+gap)
        svg.append(f'<rect x="{x:.2f}" y="{y:.2f}" width="{pw:.2f}" height="{ph:.2f}" rx="10" fill="#ffffff" stroke="#6b87ad" stroke-width="3"/>')
        if panel["approved_asset_id"]:
            asset=db.get(Asset,panel["approved_asset_id"])
            if not asset or asset.panel_id!=panel["id"]:errors.append(f'第{i+1}格：关联图片无效')
            elif not (ASSET_DIR/asset.path).is_file():errors.append(f'第{i+1}格：图片文件缺失')
            else:
                payload=base64.b64encode((ASSET_DIR/asset.path).read_bytes()).decode()
                svg.append(f'<svg x="{x+3:.2f}" y="{y+3:.2f}" width="{pw-6:.2f}" height="{ph-6:.2f}" viewBox="0 0 1000 1000" preserveAspectRatio="xMidYMid slice"><image width="1000" height="1000" preserveAspectRatio="xMidYMid slice" href="data:image/png;base64,{payload}"/></svg>')
        else:
            svg.append(f'<text x="{x+pw/2:.2f}" y="{y+ph/2:.2f}" text-anchor="middle" fill="#9daaba" font-size="28" font-family="Noto Sans CJK SC,sans-serif">{i+1} / 待上传画面</text>')
        boxes=[]
        for j,d in enumerate(panel["dialogues"]):
            bx=x+d["x"]*pw;by=y+d["y"]*ph;bw=d["w"]*pw;bh=d["h"]*ph
            fs=min(30,max(17,round(min(pw,ph)*.067)))
            line_height=fs*1.35;limit=max(1,math.floor((bw-34)/fs*2))
            lines=split_zh(d["text"],limit)
            if 18+len(lines)*line_height>bh:errors.append(f'第{i+1}格第{j+1}气泡：中文文字超框')
            if bx<x-0.001 or by<y-0.001 or bx+bw>x+pw+0.001 or by+bh>y+ph+0.001:errors.append(f'第{i+1}格第{j+1}气泡：位置越界')
            for prev in boxes:
                if bx<prev[0]+prev[2] and bx+bw>prev[0] and by<prev[1]+prev[3] and by+bh>prev[1]:errors.append(f'第{i+1}格第{j+1}气泡：与其他气泡重叠')
            boxes.append((bx,by,bw,bh))
            svg.append(f'<rect x="{bx:.2f}" y="{by:.2f}" width="{bw:.2f}" height="{bh:.2f}" rx="19" fill="#ffffff" fill-opacity=".96" stroke="#1a2945" stroke-width="3"/>')
            for k,line in enumerate(lines):
                ly=by+18+fs+(k*line_height)
                svg.append(f'<text x="{bx+17:.2f}" y="{ly:.2f}" font-family="Noto Sans CJK SC,sans-serif" font-size="{fs}" fill="#17243a">{escape(line)}</text>')
    svg.append('</svg>')
    if validate and errors:raise HTTPException(422,{"errors":errors})
    return "".join(svg),errors

@app.get("/api/projects/{project_id}/validate")
def validate_composition(project_id:str):
    with SessionLocal() as db:
        _,errors=render(project_id,db,validate=False)
    return {"valid":not bool(errors),"errors":errors}

@app.get("/api/projects/{project_id}/export.svg")
def export_svg(project_id:str):
    with SessionLocal() as db: svg,_=render(project_id,db)
    return Response(svg,media_type="image/svg+xml",headers={"Content-Disposition":"attachment; filename=comic.svg"})

@app.get("/api/projects/{project_id}/export.png")
def export_png(project_id:str):
    with SessionLocal() as db: svg,_=render(project_id,db)
    try: png=cairosvg.svg2png(bytestring=svg.encode("utf-8"))
    except Exception as ex:raise HTTPException(500,"PNG rendering failed") from ex
    return Response(png,media_type="image/png",headers={"Content-Disposition":"attachment; filename=comic.png"})

@app.get("/api/projects/{project_id}/export.json")
def export_json(project_id:str):
    with SessionLocal() as db: data=snapshot(db,project_id)
    return Response(json.dumps(data,ensure_ascii=False,indent=2),media_type="application/json",headers={"Content-Disposition":"attachment; filename=comic.json"})
