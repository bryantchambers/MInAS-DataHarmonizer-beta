"""Serve the built editor and lookup API on one beta preview port."""

import os
from pathlib import Path

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from lookup.triad_mvp_api import app as lookup_app

repository = Path(__file__).resolve().parents[2]
web_directory = Path(os.getenv("TRIAD_WEB_DIRECTORY", str(repository / "web/dist")))
app = FastAPI(title="MInAS DataHarmonizer beta", docs_url=None, redoc_url=None)
app.mount("/api", lookup_app)
app.mount("/", StaticFiles(directory=web_directory, html=True))
