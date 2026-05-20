import io
import os
import uuid
from typing import Annotated, List, Optional

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from PIL import Image as PilImage
from pydantic import BaseModel
from sqlalchemy.orm import Session, joinedload

import models
import auth
from database import SessionLocal

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------
UPLOAD_DIR    = "uploads/data"       # original full-size images
THUMBNAIL_DIR = "thumbnails"    # resized copies
THUMBNAIL_SIZE = (320, 320)     # max width × max height (aspect ratio preserved)
ALLOWED_TYPES = {"image/jpeg", "image/png", "image/gif", "image/webp"}
MAX_FILE_SIZE = 10 * 1024 * 1024   # 10 MB

os.makedirs(UPLOAD_DIR, exist_ok=True)
os.makedirs(THUMBNAIL_DIR, exist_ok=True)

# ---------------------------------------------------------------------------
# Router
# ---------------------------------------------------------------------------
router = APIRouter(
    prefix="/images",
    tags=["images"],
)

# ---------------------------------------------------------------------------
# Schemas
# ---------------------------------------------------------------------------
class UploaderInfo(BaseModel):
    id: int
    name: str
    email: str

    class Config:
        from_attributes = True

class ImageResponse(BaseModel):
    id: int
    url: str
    thumbnail_url: str
    description: Optional[str] = None
    user_id: int
    uploader: UploaderInfo

    class Config:
        from_attributes = True

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
user_dependency = Annotated[dict, Depends(auth.get_current_user)]

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def _save_file(upload: UploadFile) -> tuple[str, bytes]:
    """
    Validate and stream the uploaded file to disk.

    Returns:
        (disk_path, raw_bytes) — raw_bytes is kept in memory so Pillow
        can generate the thumbnail without a second disk read.
    Raises:
        HTTPException 415 for unsupported content type.
        HTTPException 413 when the file exceeds MAX_FILE_SIZE.
    """
    if upload.content_type not in ALLOWED_TYPES:
        raise HTTPException(
            status_code=415,
            detail=f"Unsupported media type '{upload.content_type}'. "
                   f"Allowed: {', '.join(ALLOWED_TYPES)}",
        )

    ext = upload.filename.rsplit(".", 1)[-1] if "." in upload.filename else "bin"
    filename = f"{uuid.uuid4().hex}.{ext}"
    dest = os.path.join(UPLOAD_DIR, filename)

    chunks: list[bytes] = []
    size = 0
    while chunk := upload.file.read(1024 * 64):   # 64 KB chunks
        size += len(chunk)
        if size > MAX_FILE_SIZE:
            raise HTTPException(
                status_code=413,
                detail=f"File too large. Maximum allowed size is {MAX_FILE_SIZE // (1024 * 1024)} MB.",
            )
        chunks.append(chunk)

    raw = b"".join(chunks)
    with open(dest, "wb") as f:
        f.write(raw)

    return dest, raw   # e.g. ("uploads/abc123.jpg", b"...")


def _generate_thumbnail(raw: bytes, stem: str) -> str:
    """
    Create a resized copy of the image and save it to THUMBNAIL_DIR.

    - Preserves aspect ratio (thumbnail_copy fits inside THUMBNAIL_SIZE box).
    - GIF: only the first frame is thumbnailed and saved as JPEG.
    - Output is always JPEG for consistency and smaller file size.

    Args:
        raw:  Raw bytes of the original image.
        stem: Base filename without extension (shared with the original).

    Returns:
        Relative disk path of the thumbnail, e.g. "thumbnails/abc123.jpg".
    """
    thumb_filename = f"{stem}.jpg"
    thumb_path = os.path.join(THUMBNAIL_DIR, thumb_filename)

    with PilImage.open(io.BytesIO(raw)) as img:
        # For animated GIFs, use only the first frame
        if getattr(img, "is_animated", False):
            img.seek(0)

        # Convert palette/transparency modes to RGB so JPEG save works
        if img.mode in ("RGBA", "P", "LA"):
            img = img.convert("RGB")
        elif img.mode != "RGB":
            img = img.convert("RGB")

        img.thumbnail(THUMBNAIL_SIZE, PilImage.LANCZOS)
        img.save(thumb_path, format="JPEG", quality=85, optimize=True)

    return thumb_path   # e.g. "thumbnails/abc123.jpg"

# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------
@router.post("/upload", response_model=ImageResponse, status_code=201)
async def upload_image(
    current_user: user_dependency,
    db: db_dependency,
    file: UploadFile = File(...),
    description: Optional[str] = None,
):
    """
    Upload an image file.

    - Saves the original to ``uploads/``
    - Generates a resized thumbnail (max 320×320 JPEG) in ``thumbnails/``
    - Records both paths and the authenticated user's ID in the database.

    **Auth**: Bearer token required (login via ``POST /auth/login``).
    """
    file_path, raw = _save_file(file)

    # Derive a shared stem (UUID without extension) for the thumbnail filename
    stem = os.path.splitext(os.path.basename(file_path))[0]

    try:
        thumb_path = _generate_thumbnail(raw, stem)
    except Exception as e:
        # Thumbnail failure is non-fatal — log and fall back to original
        import logging
        logging.warning(f"Thumbnail generation failed for {file_path}: {e}")
        thumb_path = file_path

    # Build public-facing URL strings.
    # In production replace this prefix with your actual base URL or CDN.
    base_url  = f"/{file_path}"    # e.g. /uploads/abc123.jpg
    thumb_url = f"/{thumb_path}"   # e.g. /thumbnails/abc123.jpg

    db_image = models.Images(
        url=base_url,
        thumbnail_url=thumb_url,
        description=description,
        user_id=current_user["user_id"],
    )
    db.add(db_image)
    db.commit()
    db.refresh(db_image)
    return db_image


@router.get("/", response_model=List[ImageResponse])
async def list_my_images(
    current_user: user_dependency,
    db: db_dependency,
    skip: int = 0,
    limit: int = 50,
):
    """
    Return all images uploaded by the currently authenticated user.

    Supports basic pagination via ``skip`` and ``limit`` query params.
    """
    images = (
        db.query(models.Images)
        .options(joinedload(models.Images.uploader))
        .filter(models.Images.user_id == current_user["user_id"])
        .offset(skip)
        .limit(limit)
        .all()
    )
    return images


@router.get("/{image_id}", response_model=ImageResponse)
async def get_image(
    image_id: int,
    current_user: user_dependency,
    db: db_dependency,
):
    """
    Fetch a single image by ID.
    Only the owning user can access the record.
    """
    image = (
        db.query(models.Images)
        .options(joinedload(models.Images.uploader))
        .filter(models.Images.id == image_id)
        .first()
    )
    if image is None:
        raise HTTPException(status_code=404, detail="Image not found")
    if image.user_id != current_user["user_id"]:
        raise HTTPException(status_code=403, detail="Not authorised to access this image")
    return image


@router.delete("/{image_id}", status_code=204)
async def delete_image(
    image_id: int,
    current_user: user_dependency,
    db: db_dependency,
):
    """
    Delete an image record *and* remove the file from disk.
    Only the owning user may delete their images.
    """
    image = db.query(models.Images).filter(models.Images.id == image_id).first()
    if image is None:
        raise HTTPException(status_code=404, detail="Image not found")
    if image.user_id != current_user["user_id"]:
        raise HTTPException(status_code=403, detail="Not authorised to delete this image")

    # Remove original and thumbnail from disk (best-effort)
    for url_field in (image.url, image.thumbnail_url):
        disk_path = url_field.lstrip("/")
        if os.path.exists(disk_path):
            os.remove(disk_path)

    db.delete(image)
    db.commit()