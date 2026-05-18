from datetime import datetime, timedelta
from fastapi import APIRouter, HTTPException, Depends
from pydantic import BaseModel
from typing import Annotated
import models
from database import SessionLocal
from sqlalchemy.orm import Session
from sqlalchemy.exc import IntegrityError
from passlib.context import CryptContext
from fastapi.security import OAuth2PasswordBearer, OAuth2PasswordRequestForm
from jose import JWTError, jwt

# Secret key for JWT encoding/decoding (use a secure method to store this in production)
SECRET_KEY = "97562be3103cf0ecfa589cfa109f47b9c7d66ddc5911e2394ffd57658a56ff11"
ALGORITHM = "HS256"

router = APIRouter(
    prefix="/auth",
    tags=["auth"]
)

bcrypt_context = CryptContext(schemes=["bcrypt"], deprecated="auto")
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="auth/login")

class CreateUserRequest(BaseModel):
    name: str
    email: str
    password: str

class CreateUserResponse(BaseModel):
    id: int
    name: str
    email: str

class Token(BaseModel):
    access_token: str
    token_type: str

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

db_dependency = Annotated[Session, Depends(get_db)]

@router.post("/register", status_code=201, response_model=CreateUserResponse)
async def create_user(user: CreateUserRequest, db: db_dependency):
    try:
        hashed_password = bcrypt_context.hash(user.password)
        db_user = models.Users(
            name=user.name,
            email=user.email,
            password=hashed_password
        )
        db.add(db_user)
        db.commit()
        db.refresh(db_user)
        return db_user

    except IntegrityError as e:
        db.rollback()
        raise HTTPException(status_code=409, detail=str(e.orig))

    except HTTPException:
        raise

    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=str(e))

@router.post("/login", response_model=Token)
async def login_for_access_token(form_data: Annotated[OAuth2PasswordRequestForm, Depends()], db: db_dependency):
    user = authenticate_user(db, form_data.username, form_data.password)
    if not user:
        raise HTTPException(status_code=401, detail="Incorrect email or password")
    token = create_access_token(user.email, user.id, timedelta(minutes=30))
    return {"access_token": token, "token_type": "bearer"}
    

def authenticate_user(db, email: str, password: str):
    user = db.query(models.Users).filter(models.Users.email == email).first()
    if not user:
        return False
    if not bcrypt_context.verify(password, user.password):
        return False
    return user

def create_access_token(username: str, user_id: int, expires_delta: timedelta):
    encode = {"sub": username, "user_id": user_id}
    expire = datetime.utcnow() + expires_delta
    encode.update({"exp": expire})
    return jwt.encode(encode, SECRET_KEY, algorithm=ALGORITHM)

async def get_current_user(token: Annotated[str, Depends(oauth2_scheme)]):
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        email: str = payload.get("sub")
        user_id: int = payload.get("user_id")
        if email is None or user_id is None:
            raise HTTPException(status_code=401, detail="Invalid token")
        return {"email": email, "user_id": user_id}
    except JWTError:
        raise HTTPException(status_code=401, detail="Invalid token")