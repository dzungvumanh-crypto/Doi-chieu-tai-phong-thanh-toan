"""FastAPI Application Entry Point"""
import os
import sys

# Thêm root vào path
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import text
from backend.database import engine, Base
from backend.api.auth import router as auth_router
from backend.api.staff import router as staff_router
from backend.api.departments import dept_router, user_router
from backend.api.handovers import router as handover_router
from backend.api.bundles import router as bundle_router

# Tạo tables
Base.metadata.create_all(bind=engine)


def _ensure_indexes():
    """Tạo index và migrate schema trên DB hiện tại (idempotent)."""
    stmts = [
        # Schema migration – thêm cột mới nếu chưa có (SQLite không hỗ trợ IF NOT EXISTS cho ADD COLUMN)
        # Bọc trong try/except ở Python để bỏ qua lỗi "duplicate column"
    ]
    schema_migrations = [
        "ALTER TABLE bundles ADD COLUMN cover_units TEXT",
        # Cột mới cho KSNBStaff (chuyên viên)
        "ALTER TABLE ksnb_staff ADD COLUMN department_id INTEGER REFERENCES departments(id)",
        # Cột mới cho DocumentEntry
        "ALTER TABLE document_entries ADD COLUMN entry_status TEXT DEFAULT 'confirmed'",
        "ALTER TABLE document_entries ADD COLUMN entered_by_id INTEGER REFERENCES ksnb_staff(id)",
        "ALTER TABLE document_entries ADD COLUMN confirmed_by_id INTEGER REFERENCES ksnb_staff(id)",
        "ALTER TABLE document_entries ADD COLUMN confirmed_at DATETIME",
        "ALTER TABLE document_entries ADD COLUMN borrowed_at DATETIME",
    ]
    with engine.connect() as conn:
        for s in schema_migrations:
            try:
                conn.execute(text(s))
                conn.commit()
            except Exception:
                conn.rollback()   # cột đã tồn tại → bỏ qua

    stmts = [
        "CREATE INDEX IF NOT EXISTS ix_source_users_dept      ON source_users(department_id)",
        "CREATE INDEX IF NOT EXISTS ix_doc_entries_user        ON document_entries(source_user_id)",
        "CREATE INDEX IF NOT EXISTS ix_doc_entries_handover    ON document_entries(handover_id)",
        "CREATE INDEX IF NOT EXISTS ix_doc_entries_date        ON document_entries(transaction_date)",
        "CREATE INDEX IF NOT EXISTS ix_handovers_dept          ON handovers(department_id)",
        "CREATE INDEX IF NOT EXISTS ix_handovers_recv          ON handovers(received_by_id)",
        "CREATE INDEX IF NOT EXISTS ix_bundle_groups_dept      ON bundle_groups(department_id)",
        "CREATE INDEX IF NOT EXISTS ix_bundle_groups_creator   ON bundle_groups(created_by_id)",
        "CREATE INDEX IF NOT EXISTS ix_bundles_group           ON bundles(group_id)",
        "CREATE INDEX IF NOT EXISTS ix_bundles_custodian       ON bundles(custodian_id)",
        "CREATE INDEX IF NOT EXISTS ix_bundle_items_bundle     ON bundle_items(bundle_id)",
        "CREATE INDEX IF NOT EXISTS ix_bundle_items_entry      ON bundle_items(entry_id)",
        "CREATE INDEX IF NOT EXISTS ix_leave_records_staff     ON leave_records(staff_id)",
        # Indexes mới
        "CREATE INDEX IF NOT EXISTS ix_ksnb_staff_dept         ON ksnb_staff(department_id)",
        "CREATE INDEX IF NOT EXISTS ix_doc_entries_status      ON document_entries(entry_status)",
        "CREATE INDEX IF NOT EXISTS ix_entry_change_logs_entry ON entry_change_logs(entry_id)",
        "CREATE INDEX IF NOT EXISTS ix_entry_change_logs_actor ON entry_change_logs(performed_by_id)",
    ]
    with engine.connect() as conn:
        for s in stmts:
            conn.execute(text(s))
        conn.commit()

_ensure_indexes()

app = FastAPI(
    title="KSNB&HTVH – Agribank",
    description="Hệ thống quản lý nhân sự và chứng từ hậu kiểm",
    version="1.0.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Register routers
app.include_router(auth_router)
app.include_router(staff_router)
app.include_router(dept_router)
app.include_router(user_router)
app.include_router(handover_router)
app.include_router(bundle_router)


@app.get("/")
def root():
    return {"message": "KSNB&HTVH API đang chạy", "docs": "/docs"}
