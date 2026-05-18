from fastapi import FastAPI, HTTPException, Depends
from pydantic import BaseModel
from typing import List, Optional, Annotated
import models
from database import SessionLocal, engine
from sqlalchemy.orm import Session
from sqlalchemy.exc import IntegrityError
import auth

app = FastAPI()
app.include_router(auth.router)
models.Base.metadata.create_all(bind=engine)

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

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

db_dependency = Annotated[Session, Depends(get_db)]
user_dependency = Annotated[dict, Depends(auth.get_current_user)]


@app.get("/user")
async def read_user(user: user_dependency, db: db_dependency):
    if user is None:
        raise HTTPException(status_code=401, detail="Unauthorized")
    return {"User": user}