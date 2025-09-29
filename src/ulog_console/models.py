from sqlalchemy import Column, Integer, String, Float, ForeignKey, BLOB, DateTime, Text
from sqlalchemy.orm import declarative_base, relationship
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
from sqlalchemy.orm import sessionmaker

Base = declarative_base()

class Session(Base):
    __tablename__ = "sessions"
    id = Column(Integer, primary_key=True)
    elf_path = Column(Text)
    elf_hash = Column(String(64))
    start_time = Column(DateTime)
    end_time = Column(DateTime, nullable=True)
    status = Column(String)
    record_count = Column(Integer, default=0)
    logs = relationship("LogEntry", back_populates="session")

class LogEntry(Base):
    __tablename__ = "log_entries"
    log_id = Column(Integer, primary_key=True)
    file = Column(Text)
    line = Column(Integer)
    level = Column(String)
    message_template = Column(Text)
    vars = relationship("VarDef", back_populates="logdef")

class VarDef(Base):
    __tablename__ = "var_defs"
    id = Column(Integer, primary_key=True)
    log_id = Column(Integer, ForeignKey("log_entries.log_id"))
    name = Column(Text)
    type = Column(String)
    formatter = Column(String)
    position = Column(Integer)
    logentry = relationship("LogEntry", back_populates="vars")

class Log(Base):
    __tablename__ = "logs"
    id = Column(Integer, primary_key=True)
    ts = Column(Float)
    log_id = Column(Integer, ForeignKey("log_entries.log_id"))
    session_id = Column(Integer, ForeignKey("sessions.id"))
    raw_payload = Column(BLOB)
    session = relationship("Session", back_populates="logs")
    vars = relationship("VarValue", back_populates="log")

class VarValue(Base):
    __tablename__ = "var_values"
    id = Column(Integer, primary_key=True)
    log_id = Column(Integer, ForeignKey("logs.id"))
    var_def_id = Column(Integer, ForeignKey("var_defs.id"))
    value_blob = Column(BLOB)
    value_int = Column(Integer, nullable=True)
    value_real = Column(Float, nullable=True)
    log = relationship("Log", back_populates="vars")
