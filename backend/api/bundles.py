"""Bundle management endpoints"""
import json
from datetime import date as date_type
from typing import List, Optional, Tuple
from collections import defaultdict
from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import Response
from sqlalchemy.orm import Session, joinedload
from backend.database import get_db
from backend.models import (
    Bundle, BundleGroup, BundleItem, DocumentEntry,
    Department, Handover, KSNBStaff, SourceUser
)
from backend.schemas import (
    BundleGroupOut, BundleUpdateRequest, BundleGenerateRequest,
    StorageViewRow, StorageViewResponse,
    ArchiveRecord, HandoverArchiveResponse,
)
from backend.core.deps import get_current_staff, require_controller, require_ksnb
from backend.services.bundle_service import generate_bundles_for_entries, EntryUnit
from backend.services.cover_service import generate_covers_docx


def _get_dates_for_bundle(b: Bundle):
    """Lấy tập hợp ngày GD của 1 tập — ưu tiên cover_units, fallback BundleItems."""
    if b.cover_units:
        try:
            data = json.loads(b.cover_units)
            return frozenset(date_type.fromisoformat(u["date"]) for u in data)
        except Exception:
            pass
    return frozenset(
        item.entry.transaction_date
        for item in b.items
        if item.entry
    )


def _units_from_bundle(bundle: Bundle) -> List[EntryUnit]:
    """Build EntryUnit list for cover from cover_units JSON if set, else from BundleItems."""
    if bundle.cover_units:
        try:
            data = json.loads(bundle.cover_units)
            return [
                EntryUnit(
                    entry_ids=[],
                    source_user_id=0,
                    user_code=u["user_code"],
                    full_name=u.get("full_name"),
                    transaction_date=date_type.fromisoformat(u["date"]),
                    sheet_count=u["sheet_count"],
                    is_large=u.get("is_large", False),
                )
                for u in data
            ]
        except Exception:
            pass
    # Fallback: đọc từ BundleItems (trường hợp không có cover_units)
    units = []
    for item in bundle.items:
        e = item.entry
        if e and e.source_user:
            units.append(EntryUnit(
                entry_ids=[e.id],
                source_user_id=e.source_user_id,
                user_code=e.source_user.user_code,
                full_name=e.source_user.full_name,
                transaction_date=e.transaction_date,
                sheet_count=e.sheet_count,
            ))
    return units


def _get_bundle_label(bundle: Bundle, group_bundles) -> Tuple[int, int]:
    """
    Tính (label_seq, label_total) cho bìa của 1 tập.
    - Tập bị chia từ 1 ngày vượt 350: đánh số cục bộ (I/II, II/II, ...)
    - Tập gom nhiều ngày hoặc tập đơn: luôn là I/I
    """
    bundle_dates = {b.id: _get_dates_for_bundle(b) for b in group_bundles}

    # Nhóm các tập có cùng 1 ngày duy nhất (= các tập bị chia)
    single_date_groups: dict = defaultdict(list)
    for b in group_bundles:
        dates = bundle_dates[b.id]
        if len(dates) == 1:
            single_date_groups[next(iter(dates))].append(b)

    my_dates = bundle_dates.get(bundle.id, frozenset())
    if len(my_dates) == 1:
        day = next(iter(my_dates))
        same = sorted(single_date_groups[day], key=lambda b: b.sequence)
        if len(same) > 1:
            idx = next(i + 1 for i, b in enumerate(same) if b.id == bundle.id)
            return idx, len(same)
    return 1, 1

router = APIRouter(prefix="/api/bundles", tags=["Bundles"])


def _load_bundle_group(db: Session, group_id: int) -> BundleGroup:
    g = db.query(BundleGroup).options(
        joinedload(BundleGroup.department),
        joinedload(BundleGroup.bundles).joinedload(Bundle.custodian_staff),
        joinedload(BundleGroup.bundles).joinedload(Bundle.items).joinedload(
            BundleItem.entry
        ).joinedload(DocumentEntry.source_user)
    ).filter(BundleGroup.id == group_id).first()
    if not g:
        raise HTTPException(404, "Không tìm thấy nhóm tập")
    return g


@router.get("/groups", response_model=List[BundleGroupOut])
def list_groups(
    department_id: Optional[int] = None,
    month: Optional[int] = None,
    year: Optional[int] = None,
    db: Session = Depends(get_db),
    _: KSNBStaff = Depends(require_ksnb)
):
    q = db.query(BundleGroup).options(
        joinedload(BundleGroup.department),
        joinedload(BundleGroup.created_by_staff),
        joinedload(BundleGroup.bundles).joinedload(Bundle.items)
    )
    if department_id:
        q = q.filter(BundleGroup.department_id == department_id)
    if month:
        q = q.filter(BundleGroup.notes.like(f"Tháng {month:02d}/%"))
    if year:
        q = q.filter(BundleGroup.notes.like(f"%/{year}"))
    return q.order_by(BundleGroup.created_at.desc()).all()


@router.get("/groups/{group_id}", response_model=BundleGroupOut)
def get_group(
    group_id: int,
    db: Session = Depends(get_db),
    _: KSNBStaff = Depends(require_ksnb)
):
    return _load_bundle_group(db, group_id)


@router.post("/generate", response_model=BundleGroupOut)
def generate_bundles(
    req: BundleGenerateRequest,
    db: Session = Depends(get_db),
    current: KSNBStaff = Depends(require_controller)
):
    """Tự động gom tập từ danh sách entry IDs"""
    dept = db.query(Department).get(req.department_id)
    if not dept:
        raise HTTPException(404, "Không tìm thấy phòng")

    entry_ids = list(dict.fromkeys(req.entry_ids))
    if not entry_ids:
        raise HTTPException(400, "Không có chứng từ để gom")

    # Lấy entries và kiểm tra phạm vi phòng
    entries = db.query(DocumentEntry).options(
        joinedload(DocumentEntry.source_user),
        joinedload(DocumentEntry.handover)
    ).filter(DocumentEntry.id.in_(entry_ids)).all()

    if not entries:
        raise HTTPException(400, "Không có chứng từ để gom")

    non_confirmed = [e for e in entries if e.entry_status != "confirmed"]
    if non_confirmed:
        raise HTTPException(400, f"{len(non_confirmed)} chứng từ chưa được xác nhận, không thể gom tập")

    found_ids = {e.id for e in entries}
    missing_ids = set(entry_ids) - found_ids
    if missing_ids:
        raise HTTPException(400, "Có chứng từ không tồn tại")

    invalid_entries = [
        e.id for e in entries
        if not e.handover
        or e.handover.department_id != req.department_id
    ]
    if invalid_entries:
        raise HTTPException(
            400,
            "Có chứng từ không thuộc phòng đã chọn"
        )

    # Chuẩn bị data cho thuật toán
    entries_data = []
    for e in entries:
        entries_data.append({
            "id": e.id,
            "source_user_id": e.source_user_id,
            "user_code": e.source_user.user_code if e.source_user else str(e.source_user_id),
            "full_name": e.source_user.full_name if e.source_user else None,
            "transaction_date": e.transaction_date,
            "sheet_count": e.sheet_count,
        })

    # Chạy thuật toán gom tập
    bundle_results = generate_bundles_for_entries(entries_data)

    if not bundle_results:
        raise HTTPException(400, "Không thể gom tập")

    # Lưu vào DB
    group = BundleGroup(
        department_id=req.department_id,
        total_bundles=len(bundle_results),
        created_by_id=current.id,
        notes=req.notes,
    )
    db.add(group)
    db.flush()

    for br in bundle_results:
        cover_units_json = json.dumps([
            {
                "user_code": unit.user_code,
                "full_name": unit.full_name,
                "date": unit.transaction_date.isoformat(),
                "sheet_count": unit.sheet_count,
                "is_large": unit.is_large,
            }
            for unit in br.units
        ], ensure_ascii=False)

        bundle = Bundle(
            group_id=group.id,
            sequence=br.sequence,
            total_sheets=br.total_sheets,
            custodian_id=req.custodian_id,
            status="pending",
            cover_units=cover_units_json,
        )
        db.add(bundle)
        db.flush()

        for unit in br.units:
            for entry_id in unit.entry_ids:
                item = BundleItem(bundle_id=bundle.id, entry_id=entry_id)
                db.add(item)

    db.commit()
    return _load_bundle_group(db, group.id)


@router.put("/{bundle_id}", response_model=BundleGroupOut)
def update_bundle(
    bundle_id: int,
    req: BundleUpdateRequest,
    db: Session = Depends(get_db),
    _: KSNBStaff = Depends(require_controller)
):
    bundle = db.query(Bundle).get(bundle_id)
    if not bundle:
        raise HTTPException(404, "Không tìm thấy tập")
    for field, val in req.dict(exclude_none=True).items():
        setattr(bundle, field, val)
    db.commit()
    return _load_bundle_group(db, bundle.group_id)


@router.get("/{bundle_id}/cover")
def download_cover(
    bundle_id: int,
    custodian_id: Optional[int] = None,
    db: Session = Depends(get_db),
    _: KSNBStaff = Depends(get_current_staff)
):
    """Tải bìa .docx cho 1 tập cụ thể"""
    bundle = db.query(Bundle).options(
        joinedload(Bundle.group).joinedload(BundleGroup.department),
        joinedload(Bundle.items).joinedload(BundleItem.entry).joinedload(
            DocumentEntry.source_user
        ),
        joinedload(Bundle.custodian_staff)
    ).filter(Bundle.id == bundle_id).first()

    if not bundle:
        raise HTTPException(404, "Không tìm thấy tập")

    # Load toàn bộ group để tính nhãn cục bộ
    group = _load_bundle_group(db, bundle.group_id)
    label_seq, label_total = _get_bundle_label(bundle, group.bundles)

    # Tìm custodian
    cust_name = "..."
    cid = custodian_id or bundle.custodian_id
    if cid:
        staff = db.query(KSNBStaff).get(cid)
        if staff:
            cust_name = staff.full_name

    # Build bundle result
    from backend.services.bundle_service import BundleResult
    units = _units_from_bundle(bundle)

    br = BundleResult(
        sequence=bundle.sequence,
        total_bundles_in_group=bundle.group.total_bundles,
        total_sheets=bundle.total_sheets,
        units=units,
        label_seq=label_seq,
        label_total=label_total,
        custodian_name=cust_name,
    )

    dept_name = bundle.group.department.name if bundle.group.department else "Phòng"
    docx_bytes = generate_covers_docx(dept_name, [br])

    filename = f"bia_tap_{bundle.sequence}.docx"
    return Response(
        content=docx_bytes,
        media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        headers={"Content-Disposition": f"attachment; filename={filename}"}
    )


@router.get("/groups/{group_id}/cover-all")
def download_all_covers(
    group_id: int,
    db: Session = Depends(get_db),
    _: KSNBStaff = Depends(require_ksnb)
):
    """Tải tất cả bìa của 1 nhóm tập trong 1 file .docx"""
    group = _load_bundle_group(db, group_id)

    from backend.services.bundle_service import BundleResult
    bundle_results = []

    for bundle in sorted(group.bundles, key=lambda b: b.sequence):
        cust_name = "..."
        if bundle.custodian_staff:
            cust_name = bundle.custodian_staff.full_name
        elif bundle.custodian_id:
            staff = db.query(KSNBStaff).get(bundle.custodian_id)
            if staff:
                cust_name = staff.full_name

        label_seq, label_total = _get_bundle_label(bundle, group.bundles)

        br = BundleResult(
            sequence=bundle.sequence,
            total_bundles_in_group=group.total_bundles,
            total_sheets=bundle.total_sheets,
            units=_units_from_bundle(bundle),
            label_seq=label_seq,
            label_total=label_total,
            custodian_name=cust_name,
        )
        bundle_results.append(br)

    dept_name = group.department.name if group.department else "Phòng"
    docx_bytes = generate_covers_docx(dept_name, bundle_results)

    filename = f"bia_tat_ca_tap_{group_id}.docx"
    return Response(
        content=docx_bytes,
        media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        headers={"Content-Disposition": f"attachment; filename={filename}"}
    )


@router.post("/{bundle_id}/mark-printed", response_model=BundleGroupOut)
def mark_bundle_printed(
    bundle_id: int,
    db: Session = Depends(get_db),
    _: KSNBStaff = Depends(require_controller)
):
    """Đánh dấu 1 tập là đã in bìa thực tế"""
    bundle = db.query(Bundle).get(bundle_id)
    if not bundle:
        raise HTTPException(404, "Không tìm thấy tập")

    from datetime import datetime
    bundle.cover_printed_at = datetime.utcnow()
    bundle.status = "printed"
    db.commit()
    return _load_bundle_group(db, bundle.group_id)


@router.post("/groups/{group_id}/mark-printed", response_model=BundleGroupOut)
def mark_group_printed(
    group_id: int,
    db: Session = Depends(get_db),
    _: KSNBStaff = Depends(require_controller)
):
    """Đánh dấu tất cả tập trong nhóm là đã in bìa thực tế"""
    group = _load_bundle_group(db, group_id)

    from datetime import datetime
    now = datetime.utcnow()
    for bundle in group.bundles:
        bundle.cover_printed_at = now
        bundle.status = "printed"

    db.commit()
    return _load_bundle_group(db, group_id)


@router.get("/cover-bulk")
def download_bulk_covers(
    department_id: int,
    db: Session = Depends(get_db),
    _: KSNBStaff = Depends(require_ksnb)
):
    """Tải tất cả bìa của 1 phòng (gom tất cả groups) vào 1 file .docx"""
    from backend.services.bundle_service import BundleResult

    dept = db.query(Department).get(department_id)
    if not dept:
        raise HTTPException(404, "Không tìm thấy phòng")

    groups = db.query(BundleGroup).options(
        joinedload(BundleGroup.bundles).joinedload(Bundle.custodian_staff),
        joinedload(BundleGroup.bundles).joinedload(Bundle.items).joinedload(
            BundleItem.entry
        ).joinedload(DocumentEntry.source_user)
    ).filter(BundleGroup.department_id == department_id).order_by(BundleGroup.created_at.asc()).all()

    if not groups:
        raise HTTPException(404, "Không có nhóm tập nào cho phòng này")

    all_bundle_results = []

    for group in groups:
        for bundle in sorted(group.bundles, key=lambda b: b.sequence):
            cust_name = "..."
            if bundle.custodian_staff:
                cust_name = bundle.custodian_staff.full_name
            elif bundle.custodian_id:
                staff = db.query(KSNBStaff).get(bundle.custodian_id)
                if staff:
                    cust_name = staff.full_name

            label_seq, label_total = _get_bundle_label(bundle, group.bundles)

            br = BundleResult(
                sequence=bundle.sequence,
                total_bundles_in_group=group.total_bundles,
                total_sheets=bundle.total_sheets,
                units=_units_from_bundle(bundle),
                label_seq=label_seq,
                label_total=label_total,
                custodian_name=cust_name,
            )
            all_bundle_results.append(br)

    if not all_bundle_results:
        raise HTTPException(404, "Không có tập nào để tải bìa")

    docx_bytes = generate_covers_docx(dept.name, all_bundle_results)
    filename = f"bia_phong_{department_id}.docx"
    return Response(
        content=docx_bytes,
        media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        headers={"Content-Disposition": f"attachment; filename={filename}"}
    )


def _get_storage_rows_for_month(
    db: Session, department_id: int, year: int, month: int
) -> tuple:
    """Returns (dept_name, rows: list[StorageViewRow]) for one month."""
    notes_key = f"Tháng {month:02d}/{year}"
    groups = (
        db.query(BundleGroup)
        .options(
            joinedload(BundleGroup.department),
            joinedload(BundleGroup.bundles)
            .joinedload(Bundle.items)
            .joinedload(BundleItem.entry),
        )
        .filter(
            BundleGroup.department_id == department_id,
            BundleGroup.notes == notes_key,
        )
        .order_by(BundleGroup.created_at)
        .all()
    )

    dept_name = ""
    if groups and groups[0].department:
        dept_name = groups[0].department.name
    else:
        d = db.query(Department).filter(Department.id == department_id).first()
        if d:
            dept_name = d.name

    all_rows: list = []
    for g in groups:
        bundles = sorted(g.bundles, key=lambda b: b.sequence)
        bundle_dates: dict = {}
        for b in bundles:
            bundle_dates[b.id] = sorted(_get_dates_for_bundle(b))

        single_day: dict = defaultdict(list)
        multi_day: list = []
        for b in bundles:
            dates = bundle_dates[b.id]
            if len(dates) == 1:
                single_day[dates[0]].append(b)
            elif len(dates) > 1:
                multi_day.append((dates, b))

        group_rows: list = []
        for dates, b in multi_day:
            group_rows.append(StorageViewRow(
                days=sorted(d.day for d in dates),
                bundle_sheets=[b.total_sheets],
                n_bundles=1,
            ))
        for date, date_bundles in single_day.items():
            date_bundles = sorted(date_bundles, key=lambda b: b.sequence)
            group_rows.append(StorageViewRow(
                days=[date.day],
                bundle_sheets=[b.total_sheets for b in date_bundles],
                n_bundles=len(date_bundles),
            ))
        group_rows.sort(key=lambda r: min(r.days) if r.days else 0)
        all_rows.extend(group_rows)

    return dept_name, all_rows


def _generate_archive_records(
    db: Session, department_id: int, year: int, tieu_de_dau: str, tu_tap: str
) -> list:
    """Build archive record list for a whole year — 1 DB query for all 12 months."""
    dept = db.query(Department).filter(Department.id == department_id).first()
    dept_name = dept.name if dept else str(department_id)

    # 1 query duy nhất cho cả năm (LIKE "Tháng %/YYYY")
    groups = (
        db.query(BundleGroup)
        .options(
            joinedload(BundleGroup.department),
            joinedload(BundleGroup.bundles)
            .joinedload(Bundle.items)
            .joinedload(BundleItem.entry),
        )
        .filter(
            BundleGroup.department_id == department_id,
            BundleGroup.notes.like(f"Tháng %/{year}"),
        )
        .order_by(BundleGroup.created_at)
        .all()
    )

    if groups and groups[0].department:
        dept_name = groups[0].department.name

    # Phân nhóm theo tháng trong Python
    by_month: dict = defaultdict(list)
    for g in groups:
        try:
            month = int((g.notes or "").split("/")[0].split(" ")[1])
        except (IndexError, ValueError):
            continue
        by_month[month].append(g)

    records = []
    for month in range(1, 13):
        month_groups = by_month.get(month, [])
        if not month_groups:
            continue

        # Dùng lại logic decompose từ _get_storage_rows_for_month
        all_rows: list = []
        for g in month_groups:
            bundles = sorted(g.bundles, key=lambda b: b.sequence)
            bundle_dates: dict = {}
            for b in bundles:
                bundle_dates[b.id] = sorted(_get_dates_for_bundle(b))
            single_day: dict = defaultdict(list)
            multi_day: list = []
            for b in bundles:
                dates = bundle_dates[b.id]
                if len(dates) == 1:
                    single_day[dates[0]].append(b)
                elif len(dates) > 1:
                    multi_day.append((dates, b))
            group_rows: list = []
            for dates, b in multi_day:
                group_rows.append(StorageViewRow(
                    days=sorted(d.day for d in dates),
                    bundle_sheets=[b.total_sheets],
                    n_bundles=1,
                ))
            for date, date_bundles in single_day.items():
                date_bundles = sorted(date_bundles, key=lambda b: b.sequence)
                group_rows.append(StorageViewRow(
                    days=[date.day],
                    bundle_sheets=[b.total_sheets for b in date_bundles],
                    n_bundles=len(date_bundles),
                ))
            group_rows.sort(key=lambda r: min(r.days) if r.days else 0)
            all_rows.extend(group_rows)

        tieu_de_cuoi = f"{dept_name} tháng {month:02d}/{year}"
        for r in all_rows:
            days = r.days
            ds_ngay_full = ", ".join(f"{d:02d}/{month:02d}/{year}" for d in days)
            ngay_mo = f"{min(days):02d}/{month:02d}/{year}"
            ngay_kt = f"{max(days):02d}/{month:02d}/{year}"
            for stt in range(1, r.n_bundles + 1):
                if r.n_bundles == 1:
                    tieu_de = f"{tieu_de_dau} {ds_ngay_full} {tieu_de_cuoi}"
                else:
                    tieu_de = f"{tieu_de_dau} {ds_ngay_full} {tieu_de_cuoi} {tu_tap} {stt}/{r.n_bundles}"
                records.append(ArchiveRecord(ngay_mo=ngay_mo, ngay_kt=ngay_kt, tieu_de=tieu_de))
    return records


@router.get("/storage-view", response_model=StorageViewResponse)
def storage_view(
    department_id: int,
    year: int,
    month: int,
    db: Session = Depends(get_db),
    _: KSNBStaff = Depends(require_ksnb),
):
    """
    Mỗi hàng = 1 "tập lớn":
    - Bundle nhiều ngày → 1 hàng, số tập = 1.
    - Nhiều bundle cùng 1 ngày (I/II, II/II...) → 1 hàng, số tập = n.
    """
    dept_name, all_rows = _get_storage_rows_for_month(db, department_id, year, month)
    notes_key = f"Tháng {month:02d}/{year}"
    return StorageViewResponse(
        department_name=dept_name,
        period=notes_key,
        rows=all_rows,
        total_sheets=sum(sum(r.bundle_sheets) for r in all_rows),
        total_bundles=sum(r.n_bundles for r in all_rows),
    )


@router.get("/handover-archive", response_model=HandoverArchiveResponse)
def handover_archive_preview(
    department_id: int,
    year: int,
    tieu_de_dau: str = "Hồ sơ ngày",
    tu_tap: str = "tập",
    db: Session = Depends(get_db),
    _: KSNBStaff = Depends(get_current_staff),
):
    records = _generate_archive_records(db, department_id, year, tieu_de_dau, tu_tap)
    return HandoverArchiveResponse(records=records, total=len(records))


@router.get("/handover-archive-excel")
def handover_archive_excel(
    department_id: int,
    year: int,
    tieu_de_dau: str = "Hồ sơ ngày",
    tu_tap: str = "tập",
    db: Session = Depends(get_db),
    _: KSNBStaff = Depends(get_current_staff),
):
    import io
    import openpyxl
    from openpyxl.styles import Alignment, Border, Font, Side

    records = _generate_archive_records(db, department_id, year, tieu_de_dau, tu_tap)

    dept = db.query(Department).filter(Department.id == department_id).first()
    dept_name = dept.name if dept else str(department_id)

    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Bàn giao lưu trữ"

    thin = Side(style="thin")
    border = Border(left=thin, right=thin, top=thin, bottom=thin)
    font_h = Font(name="Times New Roman", size=11, bold=True)
    font_d = Font(name="Times New Roman", size=11)
    align_c = Alignment(horizontal="center", vertical="center")
    align_l = Alignment(horizontal="left", vertical="center", wrap_text=True)

    for col, hdr in enumerate(["NGAY_MO_HS", "NGAY_KT_HS", "TIEUDE_HS"], 1):
        cell = ws.cell(row=1, column=col, value=hdr)
        cell.font = font_h
        cell.border = border
        cell.alignment = align_c

    ws.column_dimensions["A"].width = 14
    ws.column_dimensions["B"].width = 14
    ws.column_dimensions["C"].width = 75

    for row_i, rec in enumerate(records, 2):
        for col, (val, aln) in enumerate(
            [(rec.ngay_mo, align_c), (rec.ngay_kt, align_c), (rec.tieu_de, align_l)], 1
        ):
            cell = ws.cell(row=row_i, column=col, value=val)
            cell.font = font_d
            cell.border = border
            cell.alignment = aln

    buf = io.BytesIO()
    wb.save(buf)
    buf.seek(0)

    safe_name = dept_name.replace("/", "-").replace("\\", "-")
    filename = f"ban_giao_luu_tru_{safe_name}_{year}.xlsx"
    return Response(
        content=buf.read(),
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f"attachment; filename={filename}"},
    )


@router.delete("/groups/{group_id}")
def delete_group(
    group_id: int,
    db: Session = Depends(get_db),
    _: KSNBStaff = Depends(require_controller)
):
    g = db.query(BundleGroup).get(group_id)
    if not g:
        raise HTTPException(404, "Không tìm thấy nhóm tập")
    db.delete(g)
    db.commit()
    return {"message": "Đã xóa nhóm tập"}
