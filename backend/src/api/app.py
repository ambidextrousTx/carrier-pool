from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from psycopg_pool import ConnectionPool

from .config import POOL_MAX_SIZE, POOL_MIN_SIZE, RUNTIME_DSN
from .routes import router


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    # One pool for the process, opened at startup and closed at shutdown
    # -- not a lazy global, so a broken DB connection fails fast at boot
    # instead of on someone's first request. psycopg_pool.ConnectionPool
    # is thread-safe, which is what makes sync path functions safe here:
    # FastAPI runs `def` (non-async) routes in a threadpool automatically,
    # and each thread checks out its own connection from the same pool.
    pool = ConnectionPool(RUNTIME_DSN, min_size=POOL_MIN_SIZE, max_size=POOL_MAX_SIZE, open=True)
    app.state.pool = pool
    yield
    pool.close()


app = FastAPI(title="Carrier Recommendation API", lifespan=lifespan)

# Permissive for local dev only (no real auth in front of this demo
# anyway -- see handoff §8.8) -- tighten if this ever runs anywhere
# other than a laptop next to `docker compose up`.
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
    allow_methods=["GET"],
    allow_headers=["*"],
)

app.include_router(router)
