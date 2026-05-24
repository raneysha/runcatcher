import os
import shutil
import tempfile
from typing import Annotated, List, Optional
from urllib.parse import urlparse

import pandas as pd
from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from pydantic import BaseModel
from sqlalchemy.orm import Session

import models
from database import SessionLocal, URL_DATABASE

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------
# DeepFace.search() queries a backend DB — no local directory needed.
# Images must be pre-registered via DeepFace.register().
# Reference: https://sefiks.com/2026/01/01/introducing-brand-new-face-recognition-in-deepface/
THUMBNAIL_DIR = "thumbnails"

# Parse once at startup instead of on every request
_u = urlparse(URL_DATABASE)
_CONNECTION_DETAILS = {
    "host":     _u.hostname,
    "port":     _u.port or 5432,
    "user":     _u.username,
    "password": _u.password,
    "dbname":   _u.path.lstrip("/"),
}

# ---------------------------------------------------------------------------
# Router
# ---------------------------------------------------------------------------
router = APIRouter(prefix="/faces", tags=["faces"])

# ---------------------------------------------------------------------------
# Schemas
# ---------------------------------------------------------------------------
class FaceSearchResult(BaseModel):
    distance: float
    file_path: str
    thumbnail_path: str

class FaceSearchResponse(BaseModel):
    results: List[FaceSearchResult]
    total: int

# ---------------------------------------------------------------------------
# Dependencies
# ---------------------------------------------------------------------------
def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

db_dependency = Annotated[Session, Depends(get_db)]

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def _lookup_thumbnail(db: Session, file_url: str) -> Optional[str]:
    """Return thumbnail_url from DB matching the given file URL, or None."""
    image = db.query(models.Images).filter(models.Images.url == file_url).first()
    return image.thumbnail_url if image else None

# ---------------------------------------------------------------------------
# Endpoint
# ---------------------------------------------------------------------------
@router.post("/search", response_model=FaceSearchResponse)
async def search_faces(
    db: db_dependency,
    file: UploadFile = File(...),
    model_name: str = "VGG-Face",
    distance_metric: str = "cosine",
    database_type: str = "postgres",
    detector_backend: str = "opencv",
    align: bool = True,
    l2_normalize: bool = True,
    limit: int = 10,
):
    """
    Search for matching faces using **DeepFace.search()** (stateless, DB-backed).

    Requires images to have been pre-registered via ``DeepFace.register()``.

    **Reference**: https://sefiks.com/2026/01/01/introducing-brand-new-face-recognition-in-deepface/

    **IMPORTANT**: ``model_name``, ``detector_backend``, ``align``, and ``l2_normalize``
    must exactly match the values used when calling ``DeepFace.register()``.

    - `model_name`: VGG-Face (default), Facenet, Facenet512, ArcFace, SFace, GhostFaceNet …
    - `distance_metric`: cosine (default), euclidean, euclidean_l2
    - `database_type`: postgres (default), pgvector, mongo, neo4j, pinecone, weaviate
    - `detector_backend`: opencv (default), retinaface, mtcnn, ssd, dlib …
    - `align`: whether alignment was applied during register (default True)
    - `l2_normalize`: whether embeddings were L2-normalised during register (default True)
    - `limit`: max results to return (default 10)
    """
    try:
        from deepface import DeepFace
    except ImportError:
        raise HTTPException(
            status_code=500,
            detail="deepface is not installed. Run: pip install deepface",
        )

    suffix = os.path.splitext(file.filename or "query.jpg")[-1] or ".jpg"
    with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp:
        shutil.copyfileobj(file.file, tmp)
        tmp_path = tmp.name

    try:
        dfs = DeepFace.search(
            img=tmp_path,
            model_name=model_name,
            distance_metric=distance_metric,
            database_type=database_type,
            connection_details=_CONNECTION_DETAILS,
            detector_backend=detector_backend,
            align=align,
            l2_normalize=l2_normalize,
            enforce_detection=False,
        )
    except Exception as e:
        raise HTTPException(status_code=422, detail=f"DeepFace search failed: {e}")
    finally:
        os.unlink(tmp_path)

    if not dfs:
        return FaceSearchResponse(results=[], total=0)

    df = pd.concat(dfs, ignore_index=True)

    if df.empty:
        return FaceSearchResponse(results=[], total=0)

    df = df.sort_values("distance").head(limit)

    results: List[FaceSearchResult] = []
    for _, row in df.iterrows():
        raw_path: str = row["img_name"]
        file_url = "/" + raw_path.replace("\\", "/").lstrip("/")

        thumb_url = _lookup_thumbnail(db, file_url)
        if thumb_url is None:
            thumb_url = f"/{THUMBNAIL_DIR}/{os.path.basename(raw_path)}"

        results.append(FaceSearchResult(
            distance=round(float(row["distance"]), 6),
            file_path=file_url,
            thumbnail_path=thumb_url,
        ))

    return FaceSearchResponse(results=results, total=len(results))