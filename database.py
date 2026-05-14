# import urllib.parse
# from sqlalchemy import create_engine
# from sqlalchemy.ext.declarative import declarative_base
# from sqlalchemy.orm import sessionmaker

# # Database Configuration 
# DB_NAME = "HMS_DB"
# DB_USER = "postgres"
# # URL-encoding handles special characters like '@' in 'K@rim3214s' to prevent connection errors
# DB_PASS = urllib.parse.quote_plus("K@rim3214s")
# DB_HOST = "localhost"
# DB_PORT = "5432"

# # Constructing the Database URL 
# DATABASE_URL = f"postgresql://{DB_USER}:{DB_PASS}@{DB_HOST}:{DB_PORT}/{DB_NAME}"

# # SQLAlchemy engine with connection pooling for efficient database usage [cite: 7932, 7949]
# engine = create_engine(DATABASE_URL, pool_pre_ping=True)

# # Creating a session factory for handling transactions 
# SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

# # Base class for declarative models [cite: 7949, 7950]
# Base = declarative_base()

# # Dependency to get a DB session for route operations 
# def get_db():
#     db = SessionLocal()
#     try:
#         yield db
#     finally:
#         db.close()

# from contextlib import contextmanager

# @contextmanager
# def get_db_ctx():
#     db = SessionLocal()
#     try:
#         yield db
#     finally:
#         db.close()

import urllib.parse
from flask_sqlalchemy import SQLAlchemy
from contextlib import contextmanager

# create db
db = SQLAlchemy()

# Database Configuration
DB_NAME = "HMS_DB"
DB_USER = "postgres"
DB_PASS = urllib.parse.quote_plus("K@rim3214s")
DB_HOST = "localhost"
DB_PORT = "5432"

DATABASE_URL = f"postgresql://{DB_USER}:{DB_PASS}@{DB_HOST}:{DB_PORT}/{DB_NAME}"


def get_db():
    try:
        yield db.session
    finally:
        db.session.close()


@contextmanager
def get_db_ctx():
    try:
        yield db.session
    finally:
        db.session.close()