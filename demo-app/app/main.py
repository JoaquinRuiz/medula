from contextlib import asynccontextmanager

from fastapi import FastAPI

from app import db, routes_auth, routes_consulta, routes_reservas


@asynccontextmanager
async def lifespan(_: FastAPI):
    db.init_db()
    yield


app = FastAPI(title="Reservas de salas", lifespan=lifespan)
app.include_router(routes_auth.router)
app.include_router(routes_reservas.router)
app.include_router(routes_consulta.router)
