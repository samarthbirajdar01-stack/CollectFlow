import os
from datetime import date, datetime

from dotenv import load_dotenv
from sqlalchemy import Date, DateTime, create_engine, event, inspect, text
from sqlalchemy.orm import declarative_base, sessionmaker

load_dotenv()

DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///./collectflow.db")
connect_args = {"check_same_thread": False} if DATABASE_URL.startswith("sqlite") else {}
engine = create_engine(DATABASE_URL, connect_args=connect_args)

if DATABASE_URL.startswith("sqlite"):
    @event.listens_for(engine, "connect")
    def enable_sqlite_foreign_keys(connection, _record):
        cursor = connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def migrate_followup_statuses(target_engine=engine):
    if target_engine.dialect.name != "sqlite":
        return
    inspector = inspect(target_engine)
    if "followups" not in inspector.get_table_names():
        return
    checks = inspector.get_check_constraints("followups")
    columns = {column["name"] for column in inspector.get_columns("followups")}
    allows_missed = any("MISSED" in (check.get("sqltext") or "") for check in checks)
    if allows_missed and "promise_id" in columns:
        return

    from models import FollowUp

    with target_engine.begin() as connection:
        rows = connection.execute(text("SELECT * FROM followups")).mappings().all()
        connection.exec_driver_sql("DROP TABLE followups")
        FollowUp.__table__.create(connection)
        valid_columns = {column.name for column in FollowUp.__table__.columns}
        for row in rows:
            values = {}
            for key, value in row.items():
                if key not in valid_columns:
                    continue
                column_type = FollowUp.__table__.c[key].type
                if isinstance(value, str) and isinstance(column_type, DateTime):
                    value = datetime.fromisoformat(value)
                elif isinstance(value, str) and isinstance(column_type, Date):
                    value = date.fromisoformat(value)
                values[key] = value
            connection.execute(FollowUp.__table__.insert().values(**values))
