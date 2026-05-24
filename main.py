from fastapi import FastAPI, HTTPException, Depends
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from typing import List, Optional, Annotated
import models
from database import SessionLocal, engine
from sqlalchemy.orm import Session
from sqlalchemy.exc import IntegrityError
import auth
import images as images_router   # ← new
from face_search import router as face_search_router
from fastapi.middleware.cors import CORSMiddleware



app = FastAPI()

# Routers
app.include_router(auth.router)
app.include_router(images_router.router)   # ← new: mounts at /images
app.include_router(face_search_router)     # ← new: mounts at /faces

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# Serve uploaded files as static assets
app.mount("/uploads",    StaticFiles(directory="uploads"),    name="uploads")
app.mount("/thumbnails", StaticFiles(directory="thumbnails"), name="thumbnails")

models.Base.metadata.create_all(bind=engine)

# ------------------------------------------------------------------
# Schemas
# ------------------------------------------------------------------
class UsersCreate(BaseModel):
    name: str
    email: str
    role: Optional[str] = None
    password: Optional[str] = None

class UsersResponse(BaseModel):
    id: int
    name: str
    email: str
    role: Optional[str] = None

class Images(BaseModel):
    id: int
    url: str
    thumbnail_url: str
    description: Optional[str] = None
    user_id: int

# ------------------------------------------------------------------
# Dependencies
# ------------------------------------------------------------------
def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

db_dependency = Annotated[Session, Depends(get_db)]
user_dependency = Annotated[dict, Depends(auth.get_current_user)]

# ------------------------------------------------------------------
# Existing endpoints
# ------------------------------------------------------------------
@app.get("/user")
async def read_user(user: user_dependency, db: db_dependency):
    if user is None:
        raise HTTPException(status_code=401, detail="Unauthorized")
    return {"User": user}