"""Router registry — thêm router mới vào đây, không cần sửa main.py.

Quy trình thêm router mới:
1. Tạo file backend/api/<tên>.py với router = APIRouter(...)
2. Thêm import bên dưới
3. Thêm 1 tuple vào _ROUTERS
4. Tạo PR riêng, Người 1 approve
"""
from fastapi import FastAPI

from backend.api.auth import router as auth_router
from backend.api.groups import router as groups_router
from backend.api.bundles import router as bundle_router
from backend.api.dashboard import router as dashboard_router
from backend.api.delegations import router as delegations_router
from backend.api.departments import dept_router
from backend.api.handovers import router as handover_router
from backend.api.handover_reports import router as handover_reports_router
from backend.api.holidays import router as holidays_router
from backend.api.leaves import router as leaves_router
from backend.api.logs import router as logs_router
from backend.api.reports import router as reports_router
from backend.api.staff import router as staff_router
from backend.api.th_reports import router as th_reports_router
from backend.api.duty_staff import router as duty_staff_router
from backend.api.duty_constraints import router as duty_constraints_router
from backend.api.duty_schedule import router as duty_schedule_router
from backend.api.duty_stats import router as duty_stats_router
from backend.api.duty_export import router as duty_export_router
from backend.api.cham459901 import router as cham459901_router
from backend.api.doi_chieu_song_phuong import router as doi_chieu_song_phuong_router
from backend.api.swift_recon import router as swift_recon_router
from backend.api.doi_chieu_citad import router as doi_chieu_citad_router
from backend.api.doi_soat_citad import router as doi_soat_citad_router
from backend.api.ttqt_branches import router as ttqt_branches_router

# Thêm router mới: 1 dòng import ở trên + 1 tuple ở đây
# Format: (router_object, {"prefix": "/api/...", "tags": ["..."]})
# Nếu prefix/tags đã khai báo trong router file thì dùng {} rỗng
_ROUTERS = [
    (auth_router,        {}),
    (staff_router,       {}),
    (dept_router,        {}),
    (handover_router,    {}),
    (bundle_router,      {}),
    (leaves_router,      {"prefix": "/api/leaves",         "tags": ["leaves"]}),
    (delegations_router, {"prefix": "/api/delegations",    "tags": ["delegations"]}),
    (logs_router,        {"prefix": "/api/admin/logs",     "tags": ["admin-logs"]}),
    (dashboard_router,   {"prefix": "/api/dashboard",      "tags": ["dashboard"]}),
    (holidays_router,    {"prefix": "/api/admin/holidays", "tags": ["holidays"]}),
    (reports_router,     {}),
    (handover_reports_router, {}),
    (th_reports_router,  {}),
    (groups_router,          {}),
    (duty_staff_router,      {}),
    (duty_constraints_router, {}),
    (duty_schedule_router,   {}),
    (duty_stats_router,      {}),
    (duty_export_router,     {}),
    (cham459901_router,      {}),
    (doi_chieu_song_phuong_router, {}),
    (swift_recon_router, {}),
    (doi_chieu_citad_router, {}),
    (doi_soat_citad_router, {}),
    (ttqt_branches_router, {}),
]


def apply_routers(app: FastAPI) -> None:
    for router, kwargs in _ROUTERS:
        app.include_router(router, **kwargs)
