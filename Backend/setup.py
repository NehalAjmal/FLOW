"""
FLOW — Database Setup Script
Team Error 011 | Hacknovate 7.0

Run once after cloning:
    python setup_db.py
"""

import sys
import re
import os
import urllib.request
from pathlib import Path
from dotenv import find_dotenv, load_dotenv

load_dotenv(find_dotenv())

# ── ML MODEL DOWNLOAD ────────────────────────────────────────────────────────
_ML_MODELS_DIR = Path(__file__).parent / "ml_models"
_FACE_LANDMARKER = _ML_MODELS_DIR / "face_landmarker.task"
_FACE_LANDMARKER_URL = (
    "https://storage.googleapis.com/mediapipe-models/"
    "face_landmarker/face_landmarker/float16/latest/face_landmarker.task"
)


def download_ml_models():
    """Download large binary models that are not stored in git."""
    if _FACE_LANDMARKER.exists():
        print("   face_landmarker.task already present — skipping download")
        return
    _ML_MODELS_DIR.mkdir(parents=True, exist_ok=True)
    print(f"   Downloading face_landmarker.task (~4 MB)...")
    try:
        urllib.request.urlretrieve(_FACE_LANDMARKER_URL, _FACE_LANDMARKER)
        print(f"   Saved to {_FACE_LANDMARKER}")
    except Exception as e:
        print(f"   Download failed: {e}")
        print("   → You can manually download it from:")
        print(f"     {_FACE_LANDMARKER_URL}")
        print(f"     and place it at: {_FACE_LANDMARKER}")



DATABASE_URL = os.getenv("DATABASE_URL")
if not DATABASE_URL:
    print(" DATABASE_URL not found in .env")
    print("  → Copy .env.example to .env and fill in your MySQL password")
    sys.exit(1)


def get_db_name(url: str) -> str:
    match = re.search(r"/([^/?]+)(\?|$)", url)
    if not match:
        raise ValueError(f"Could not parse database name from URL: {url}")
    return match.group(1)


def get_root_url(url: str, db_name: str) -> str:
    return url.replace(f"/{db_name}", "/")


def create_database(url: str, db_name: str):
    from sqlalchemy import create_engine, text
    root_url = get_root_url(url, db_name)
    engine = create_engine(root_url)
    with engine.connect() as conn:
        conn.execute(text(
            f"CREATE DATABASE IF NOT EXISTS `{db_name}` "
            f"CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci"
        ))
        conn.commit()
    engine.dispose()
    print(f"   Database `{db_name}` ready")


def create_tables():
    from sqlalchemy import create_engine
    from db_models.base import Base
    import db_models.user            # noqa
    import db_models.team            # noqa
    import db_models.session         # noqa
    import db_models.biometric       # noqa
    import db_models.breaks          # noqa
    import db_models.calendar_cache  # noqa
    import db_models.llm_cache       # noqa
    import db_models.refresh_token   # noqa
    import db_models.intervention    # noqa
    import db_models.user_settings   # noqa
    import db_models.rating          # noqa
    import db_models.data_export     # noqa
    import db_models.schedule        # noqa
    import db_models.invite          # noqa
    import db_models.refresh_token   # noqa
    import db_models.consent         # noqa
    import db_models.audit_log       # noqa

    engine = create_engine(DATABASE_URL)
    Base.metadata.create_all(bind=engine)
    engine.dispose()
    print("   All tables created (or already exist)")


def main():
    print("\n FLOW — Setup\n")

    print("[1/4] Downloading ML models...")
    download_ml_models()

    db_name = get_db_name(DATABASE_URL)

    print(f"[2/4] Creating database `{db_name}`...")
    try:
        create_database(DATABASE_URL, db_name)
    except Exception as e:
        print(f"   Failed: {e}")
        print("  → Check your DATABASE_URL in .env and make sure MySQL is running")
        sys.exit(1)

    print("[3/4] Creating tables...")
    try:
        create_tables()
    except Exception as e:
        print(f"   Failed: {e}")
        sys.exit(1)

    # No demo team any more: its admin key was public, so anyone could become its admin.
    print("[4/4] Make your team with:  python create_team.py \"Your team name\"")

    print("\n Setup complete! Run the server with:\n")
    print("   uvicorn main:app --reload\n")


if __name__ == "__main__":
    main()