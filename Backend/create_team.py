"""
Make a real team, instead of the old seeded demo team.

    python create_team.py "Team name"

Prints the company code and a one-time admin key. Give both to the person
who will be the team's admin: they register with account type "admin",
the company code and the admin key. Only a hash of the key is stored, so
it can't be shown again; run this again for a new team if it's lost.
"""
import secrets
import string
import sys

from auth.utils import get_password_hash
from db_models.base import SessionLocal
import db_models  # noqa: registers every table
from db_models.team import Team

CODE_CHARS = string.ascii_uppercase + string.digits


def create_team(db, name: str):
    while True:
        code = "".join(secrets.choice(CODE_CHARS) for _ in range(6))
        if not db.query(Team).filter(Team.company_code == code).first():
            break
    admin_key = f"{secrets.randbelow(10**6):06d}"
    team = Team(name=name, company_code=code, admin_key=get_password_hash(admin_key))
    db.add(team)
    db.commit()
    return team, admin_key


if __name__ == "__main__":
    if len(sys.argv) != 2 or not sys.argv[1].strip():
        print('Usage: python create_team.py "Team name"')
        sys.exit(1)
    db = SessionLocal()
    try:
        team, key = create_team(db, sys.argv[1].strip())
        print(f"Team:         {team.name}")
        print(f"Company code: {team.company_code}")
        print(f"Admin key:    {key}   (shown once, not stored)")
    finally:
        db.close()
