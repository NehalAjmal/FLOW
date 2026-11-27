# user/router.py
# The old /user/dashboard and /user/patterns lived here with shapes the app
# doesn't read. They moved to insights/router.py (contract section 5).
from fastapi import APIRouter

router = APIRouter()
