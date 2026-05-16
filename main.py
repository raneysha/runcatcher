from fastapi import FastAPI, HTTPException, Depends
from pydantic import BaseModel
from typing import List, Optional, Annotated
import models
from database import SessionLocal, engine
from sqlalchemy.orm import Session
from sqlalchemy.exc import IntegrityError


app = FastAPI()
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

@app.post("/users/", response_model=UsersResponse)
async def create_user(user: UsersCreate, db: db_dependency):
    try:
        db_user = models.Users(name=user.name, email=user.email, role=user.role, password=user.password)
        db.add(db_user)
        db.commit()
        db.refresh(db_user)
        return db_user

    except IntegrityError as e:
        db.rollback()
        raise HTTPException(
            status_code=409,
            detail=str(e.orig)
        )