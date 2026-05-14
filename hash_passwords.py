import hashlib
from database import SessionLocal
from models import User

db = SessionLocal()

users = db.query(User).all()

for u in users:
    # skip already hashed passwords
    if len(u.Password) == 64:
        continue

    hashed = hashlib.sha256(u.Password.encode()).hexdigest()
    print(u.Email, "->", hashed)

    u.Password = hashed

db.commit()
print("All passwords hashed successfully")