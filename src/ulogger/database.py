from sqlalchemy import create_engine
from sqlalchemy import Integer, SmallInteger, Text, Float
from sqlalchemy import ForeignKey, Index
from sqlalchemy.orm import DeclarativeBase, Mapped
from sqlalchemy.orm import mapped_column, relationship, sessionmaker
from typing import Optional, List

class Base(DeclarativeBase):
    pass

class DebugSession(Base):
    __tablename__ = 'debug_sessions'

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    start_ts: Mapped[float] = mapped_column(Float, comment="Timestamp when debug session started (Unix epoch in seconds)")
    elf_path: Mapped[Optional[str]] = mapped_column(Text, comment="Absolute path to the ELF file of the application being debugged")
    elf_sha256: Mapped[bytes] = mapped_column(Text, comment="SHA256 digest of the ELF file")

class VarTrait(Base):
    __tablename__ = 'var_traits'

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(Text, unique=True)


class LogLevel(Base):
    __tablename__ = 'log_levels'

    level: Mapped[int] = mapped_column(SmallInteger, primary_key=True)
    name: Mapped[str] = mapped_column(Text, unique=True)
    color: Mapped[str] = mapped_column(Text)

class SourceFile(Base):
    """
    List of the source files that contains ulog statements
    """
    __tablename__ = 'source_files'

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    fullpath: Mapped[str] = mapped_column(Text, unique=True)
    repr: Mapped[str] = mapped_column(Text, unique=True)

    # Relationship
    log_defs: Mapped[List["LogDef"]] = relationship("LogDef", back_populates="file_ref")

class LogDef(Base):
    __tablename__ = 'log_defs'

    id: Mapped[int] = mapped_column(SmallInteger, primary_key=True)
    source_file: Mapped[Optional[int]] = mapped_column(Integer, ForeignKey('source_files.id'))
    line: Mapped[Optional[int]] = mapped_column(Integer)
    level: Mapped[int] = mapped_column(SmallInteger, ForeignKey('log_levels.level'))
    format: Mapped[str] = mapped_column(Text)

    # Relationships
    file_ref: Mapped[Optional["SourceFile"]] = relationship("SourceFile", back_populates="log_defs")
    var_defs: Mapped[List["VarDef"]] = relationship("VarDef", back_populates="log_def")
    logs: Mapped[List["Log"]] = relationship("Log", back_populates="log_def")

class VarDef(Base):
    __tablename__ = 'var_defs'

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    log_id: Mapped[int] = mapped_column(Integer, ForeignKey('log_defs.id'))
    name: Mapped[str] = mapped_column(Text)
    trait: Mapped[int] = mapped_column(SmallInteger, ForeignKey('var_traits.id'))

    # Relationships
    log_def: Mapped["LogDef"] = relationship("LogDef", back_populates="var_defs")
    var_values: Mapped[List["VarValue"]] = relationship("VarValue", back_populates="var_def")

class Log(Base):
    __tablename__ = 'logs'

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    ts: Mapped[float] = mapped_column(Float)
    log_id: Mapped[int] = mapped_column(Integer, ForeignKey('log_defs.id'))

    # Relationships
    log_def: Mapped["LogDef"] = relationship(
        "LogDef", back_populates="logs")

    # one-to-many: User -> Posts
    var_values: Mapped[List["VarValue"]] = relationship(
        "VarValue", back_populates="log_ref", cascade="all, delete-orphan")

class VarValue(Base):
    __tablename__ = 'var_values'

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    log_id: Mapped[int] = mapped_column(Integer, ForeignKey('logs.id'))
    var_def_id: Mapped[int] = mapped_column(Integer, ForeignKey('var_defs.id'))
    value_int: Mapped[Optional[int]] = mapped_column(Integer)
    value_real: Mapped[Optional[float]] = mapped_column(Float)

    # Relationships
    log_ref: Mapped["Log"] = relationship("Log", back_populates="var_values")
    var_def: Mapped["VarDef"] = relationship("VarDef", back_populates="var_values")

# Indexes
Index('idx_logs_ts', Log.ts)                                 # range queries, scrolling UI
Index('idx_logs_log_id', Log.log_id)                         # filter by type/definition
Index('idx_logs_log_id_ts', Log.log_id, Log.ts)              # WHERE log_id=? ORDER BY ts
Index('idx_var_values_log_id', VarValue.log_id)              # fetch vars for log
Index('idx_var_values_var_def_id', VarValue.var_def_id)      # filter by variable type

def populate_initial_data(connection):
    """Populate initial data after all tables are created"""

    # Insert var traits
    connection.execute(
        VarTrait.__table__.insert(),
        [
            {"id": 0x00, "name": "none"},
            {"id": 0x10, "name": "uint8"},
            {"id": 0x11, "name": "int8"},
            {"id": 0x12, "name": "bool"},
            {"id": 0x20, "name": "uint16"},
            {"id": 0x21, "name": "int16"},
            {"id": 0x22, "name": "pointer"},
            {"id": 0x40, "name": "uint32"},
            {"id": 0x41, "name": "int32"},
            {"id": 0x42, "name": "float32"},
            {"id": 0x43, "name": "string4"},
        ],
    )

    # Insert log levels
    connection.execute(
        LogLevel.__table__.insert(),
        [
            {"level": 0, "name": "ERROR",  "color": "red"    },
            {"level": 1, "name": "WARN",   "color": "orange" },
            {"level": 2, "name": "MILE",   "color": "yellow" },
            {"level": 3, "name": "INFO",   "color": "green"  },
            {"level": 4, "name": "TRACE",  "color": "blue"   },
            {"level": 5, "name": "DEBUG0", "color": "purple" },
            {"level": 6, "name": "DEBUG1", "color": "pink"   },
            {"level": 7, "name": "DEBUG2", "color": "cyan"   },
            {"level": 8, "name": "DEBUG3", "color": "magenta"},
        ],
    )

    # Insert the two internal log definitions
    connection.execute(
        LogDef.__table__.insert(),
        [
            {
                "id": 255,
                "source_file": None,
                "line": None,
                "level": 0,       # ERROR
                "format": "OVERRUN: lost {} logs"
            },
            {
                "id": 254,
                "source_file": None,
                "line": None,
                "level": 0,       # ERROR
                "format": "LOGGER STARTED"
            }
        ]
    )

    # Insert related VarDef for the overrun event
    connection.execute(
        VarDef.__table__.insert(),
        [
            {
                "log_id": 255,
                "name": "lost_count",
                "trait": 0x10
            }
        ]
    )

    connection.commit()

def create_database(database_url="sqlite:///ulog.db"):
    """Create the database and return session factory"""
    engine = create_engine(database_url, echo=False)
    Base.metadata.create_all(engine)

    # Populate initial data
    with engine.begin() as connection:
        populate_initial_data(connection)

    Session = sessionmaker(bind=engine)
    return Session

# Usage example:
if __name__ == "__main__":
    SessionFactory = create_database()
    session = SessionFactory()

    # Example query
    log_levels = session.query(LogLevel).all()
    for level in log_levels:
        print(f"Level {level.level}: {level.name}")

    session.close()