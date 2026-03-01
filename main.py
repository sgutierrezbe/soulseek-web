from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from fastapi.requests import Request
from routers import search, downloads, library, covers, setup

app = FastAPI(title="Soulseek Web")
app.include_router(search.router, prefix="/api/search")
app.include_router(downloads.router, prefix="/api/downloads")
app.include_router(library.router, prefix="/api/library")
app.include_router(covers.router, prefix="/api/covers")
app.include_router(setup.router, prefix="/api/setup")

app.mount("/static", StaticFiles(directory="static"), name="static")
templates = Jinja2Templates(directory="templates")

@app.get("/")
async def index(request: Request):
    return templates.TemplateResponse("index.html", {"request": request})