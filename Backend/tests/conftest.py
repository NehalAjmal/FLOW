# tests/conftest.py
# pytest runs this file before any test file is imported.
# config.py refuses to load without these four values, but tests never
# need real secrets or the real MySQL database, so give them dummy ones.
import os

os.environ.setdefault("DATABASE_URL", "sqlite://")
os.environ.setdefault("JWT_SECRET_KEY", "test-only-secret")
os.environ.setdefault("GEMINI_API_KEY", "test-only")
os.environ.setdefault("GOOGLE_CLIENT_ID", "test-only")