from datetime import datetime

from sqlalchemy import create_engine, text

from database import migrate_followup_statuses
from models import FollowUp


def test_legacy_followups_are_preserved_and_allow_missed_status(tmp_path):
    engine = create_engine(f"sqlite:///{(tmp_path / 'legacy.db').as_posix()}")
    try:
        with engine.begin() as connection:
            connection.exec_driver_sql("CREATE TABLE agents (id INTEGER PRIMARY KEY)")
            connection.exec_driver_sql("CREATE TABLE loans (id INTEGER PRIMARY KEY)")
            connection.exec_driver_sql("CREATE TABLE payment_promises (id INTEGER PRIMARY KEY)")
            connection.exec_driver_sql("""
                CREATE TABLE followups (
                    id INTEGER PRIMARY KEY,
                    loan_id INTEGER NOT NULL REFERENCES loans(id),
                    agent_id INTEGER NOT NULL REFERENCES agents(id),
                    due_at DATETIME NOT NULL,
                    kind VARCHAR(40) NOT NULL,
                    notes TEXT NOT NULL,
                    status VARCHAR(20) NOT NULL CHECK (status IN ('OPEN', 'COMPLETED', 'CANCELLED')),
                    created_at DATETIME NOT NULL
                )
            """)
            connection.exec_driver_sql("INSERT INTO agents (id) VALUES (1)")
            connection.exec_driver_sql("INSERT INTO loans (id) VALUES (1)")
            connection.execute(text("""
                INSERT INTO followups (id, loan_id, agent_id, due_at, kind, notes, status, created_at)
                VALUES (1, 1, 1, :due_at, 'CALL', 'Existing synthetic task', 'OPEN', :created_at)
            """), {"due_at": "2026-01-02 00:00:00", "created_at": "2026-01-01 00:00:00"})

        migrate_followup_statuses(engine)

        with engine.begin() as connection:
            saved = connection.execute(text("SELECT id, notes, status FROM followups WHERE id = 1")).one()
            assert tuple(saved) == (1, "Existing synthetic task", "OPEN")
            connection.execute(FollowUp.__table__.insert().values(
                loan_id=1,
                agent_id=1,
                due_at=datetime(2026, 1, 3),
                kind="PROMISE_CHECK",
                notes="Missed synthetic promise",
                status="MISSED",
                created_at=datetime(2026, 1, 1),
            ))
            assert connection.execute(text("SELECT COUNT(*) FROM followups WHERE status = 'MISSED'")).scalar_one() == 1
    finally:
        engine.dispose()
