from fastapi import FastAPI
from fastapi.templating import Jinja2Templates

from app.routes import api, pages

app = FastAPI(title="Fitness Tracker")
app.state.templates = Jinja2Templates(directory="app/templates")

app.include_router(pages.router)
app.include_router(api.router)

