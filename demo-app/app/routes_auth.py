from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from app.auth import AuthError, login

router = APIRouter()


class LoginIn(BaseModel):
    username: str
    password: str


@router.post("/login")
def post_login(body: LoginIn) -> dict:
    try:
        session = login(body.username, body.password)
    except AuthError:
        raise HTTPException(status_code=401, detail="credenciales invalidas")
    return {"token": session.token}
