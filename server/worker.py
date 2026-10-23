"""Separate worker process for generation_jobs.

Run with python worker.py. PostgreSQL row locks provide worker exclusivity;
SQLite is supported for serial local tests only.
"""
from __future__ import annotations

from datetime import datetime, timezone, timedelta
from hashlib import sha256
import json
import logging
import os
import time
from uuid import uuid4

from sqlalchemy import select

import ai_pipeline
from app import ASSET_DIR, Asset, Base, GenerationJob, Panel, Project, SessionLocal, engine, now
from providers import MockImageProvider

logging.basicConfig(level=logging.INFO)
log=logging.getLogger("comic-worker")


def claim_one() -> str | None:
    # PostgreSQL SKIP LOCKED stops concurrent workers taking the same job.
    # SQLite is for single-process tests and is not concurrency-safe.
    with SessionLocal.begin() as db:
        stale=(datetime.now(timezone.utc)-timedelta(minutes=10)).isoformat()
        query=select(GenerationJob).where(
            (GenerationJob.status=="queued") |
            ((GenerationJob.status=="running") & (GenerationJob.updated_at<stale))
        ).order_by(GenerationJob.created_at,GenerationJob.id).with_for_update(skip_locked=True)
        job=db.scalars(query).first()
        if job is None:return None
        if job.attempt>=job.max_attempts:
            job.status="failed"
            job.error_code="expired_attempt_limit"
            job.updated_at=now()
            return None
        job.status="running"
        job.attempt+=1
        job.error_code=None
        job.updated_at=now()
        return job.id


def run_one(job_id:str) -> dict:
    # Prompt and references are frozen at queue submission.
    with SessionLocal() as db:
        job=db.get(GenerationJob,job_id)
        if job is None:return {"job_id":job_id,"status":"missing"}
        if job.status!="running":return {"job_id":job_id,"status":job.status}
        provider=job.provider
        prompt=job.prompt
        refs=json.loads(job.references)
        project_id=job.project_id
        panel_id=job.panel_id
        if provider=="mock":
            panel=db.get(Panel,panel_id)
            project=db.get(Project,project_id)
            if not panel or not project:raise RuntimeError("job target no longer exists")
            count=project.panel_count;sequence=panel.sequence
        else:
            payload=[]
            for aid in refs:
                asset=db.get(Asset,aid)
                if asset is None or asset.project_id!=project_id or asset.panel_id is not None:
                    raise RuntimeError("reference mismatch")
                path=ASSET_DIR/asset.path
                if not path.is_file():raise RuntimeError("reference missing")
                payload.append(path.read_bytes())
    try:
        if provider=="mock":
            generated=MockImageProvider().generate(sequence,count,job_id)
        elif provider=="ai":
            generated=ai_pipeline.image_candidate(prompt,payload)
        else:
            raise RuntimeError("unknown job provider")
        normalized=ai_pipeline.normalize_png(generated)
    except Exception as exc:
        log.warning("job %s failed: %s",job_id,type(exc).__name__)
        with SessionLocal.begin() as db:
            job=db.get(GenerationJob,job_id)
            if job and job.status=="running":
                job.status="failed"
                job.error_code=type(exc).__name__[:100]
                job.updated_at=now()
        return {"job_id":job_id,"status":"failed"}

    aid=str(uuid4());filename=aid+".png"
    with SessionLocal.begin() as db:
        job=db.get(GenerationJob,job_id,with_for_update=True)
        if job is None or job.status!="running":
            return {"job_id":job_id,"status":"cancelled"}
        path=ASSET_DIR/filename
        path.write_bytes(normalized)
        db.add(Asset(id=aid,project_id=project_id,panel_id=panel_id,
                     path=filename,content_hash=sha256(normalized).hexdigest(),created_at=now()))
        job.status="succeeded"
        job.candidate_asset_id=aid
        job.updated_at=now()
    return {"job_id":job_id,"status":"succeeded","candidate_asset_id":aid}


def process_one() -> dict | None:
    jid=claim_one()
    if jid is None:return None
    try:return run_one(jid)
    except Exception as exc:
        log.exception("unhandled worker failure for %s",jid)
        with SessionLocal.begin() as db:
            job=db.get(GenerationJob,jid)
            if job is not None and job.status=="running":
                job.status="failed"
                job.error_code=type(exc).__name__[:100]
                job.updated_at=now()
        return {"job_id":jid,"status":"failed"}


def main():
    Base.metadata.create_all(engine)  # bootstrapping only; Alembic is needed for production
    interval=float(os.getenv("WORKER_POLL_SECONDS","2"))
    if not (0.5<=interval<=30):raise ValueError("WORKER_POLL_SECONDS must be between 0.5 and 30")
    log.info("Comic Studio worker ready")
    while True:
        try:
            result=process_one()
            if result:log.info("job %s => %s",result["job_id"],result["status"])
            else:time.sleep(interval)
        except KeyboardInterrupt:
            break
        except Exception:
            log.exception("worker poll failed")
            time.sleep(interval)


if __name__=="__main__":
    main()
