import os
from pathlib import Path

os.environ["CATALOG_PATH"] = str(
    Path(__file__).resolve().parents[1] / "data/catalog.sqlite"
)
os.environ["SESSION_SIGNING_SECRET"] = "test-signing-secret"
os.environ["OPENAI_API_KEY"] = "placeholder-test"
