from sqlalchemy import create_engine, Column, Integer, String, Text, ForeignKey
from sqlalchemy.orm import declarative_base, sessionmaker, relationship
from sqlalchemy.pool import StaticPool
import json
import os

DATABASE_URL = "sqlite:///./assistive_vision.db"

# ConnectArgs needed for SQLite to allow multi-thread access in FastAPI
engine = create_engine(
    DATABASE_URL, 
    connect_args={"check_same_thread": False},
    poolclass=StaticPool
)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()

class User(Base):
    __tablename__ = "users"

    id = Column(Integer, primary_key=True, index=True)
    google_id = Column(String, unique=True, index=True, nullable=True)
    email = Column(String, unique=True, index=True)
    name = Column(String)
    avatar_url = Column(String, nullable=True)
    hashed_password = Column(String, nullable=True)
    
    # Store user-specific settings as a JSON string
    settings_json = Column(Text, default=json.dumps({"show_overlays": True}))

    faces = relationship("ReferenceFace", back_populates="owner", cascade="all, delete-orphan")

class ReferenceFace(Base):
    __tablename__ = "reference_faces"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"))
    name = Column(String)
    file_path = Column(String) # Path to the image file on disk

    owner = relationship("User", back_populates="faces")

def init_db():
    Base.metadata.create_all(bind=engine)
    # Ensure user-specific face directories exist
    os.makedirs("src/faces", exist_ok=True)

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
