"""Quản lý nhân sự — chuẩn hoá dữ liệu, nhắc lịch, thống kê, tra cứu, phân quyền."""
import sqlite3
from datetime import date, timedelta

import pytest
from fastapi.testclient import TestClient

from backend.core.deps import get_current_staff
from backend.database import get_db
from backend.db.migrations import _create_tables
from backend.main import app
from backend.services import hr_service as hr

HOM_NAY = date(2026, 8, 28)


# ── Fixtures ─────────────────────────────────────────────────────────────────
@pytest.fixture
def db(tmp_path):
    """DB thật dựng bằng chính `_create_tables()` — test cũng canh luôn phần DDL:
    gõ sai một cột trong migrations là các test dưới đây đỏ ngay."""
    duong = tmp_path / "hr.db"
    _create_tables(str(duong))
    conn = sqlite3.connect(duong, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    # Hai cột này chỉ được thêm trong `_ensure_indexes()`, mà hàm đó ghi thẳng
    # vào DB thật (DB_PATH) nên không gọi được ở đây — thêm lại đúng phần cần.
    conn.executescript(
        """
        ALTER TABLE user_tttt ADD COLUMN join_industry_date DATE;
        ALTER TABLE user_tttt ADD COLUMN is_deleted BOOLEAN DEFAULT 0;
        """
    )
    conn.executescript(
        """
        INSERT INTO departments (id, code, name) VALUES
            (1, 'TH',  'Phòng Tổng hợp'),
            (2, 'TT',  'Phòng Thanh toán'),
            (3, 'BGD', 'Ban Giám đốc');
        INSERT INTO user_tttt (id, employee_code, full_name, role, department_id,
                               username, pwd_hash, is_active)
        VALUES (1, 'NS001', 'Nguyễn Văn A', 'chuyen_vien',  1, 'a', 'x', 1),
               (2, 'NS002', 'Trần Thị B',   'truong_phong', 2, 'b', 'x', 1),
               (3, 'NS003', 'Lê Văn C',     'giam_doc',     3, 'c', 'x', 1),
               -- Quản trị viên: tài khoản hệ thống, không thuộc phòng nào
               (9, 'QTV01', 'Quản trị viên', 'admin',     NULL, 'qtv', 'x', 1);
        INSERT INTO hr_profiles (staff_id, gender, dob) VALUES
            (1, 'nam', '1996-05-01'),
            (2, 'nu',  '1980-03-15');
        INSERT INTO user_groups (id, name, is_active) VALUES (1, 'Nhân sự', 1);
        """
    )
    conn.commit()
    yield conn
    conn.close()


def _cap_quyen(db, staff_id: int, *codes: str):
    db.execute("INSERT OR IGNORE INTO group_members (group_id, staff_id) VALUES (1, ?)",
               (staff_id,))
    for c in codes:
        db.execute("INSERT OR IGNORE INTO group_features (group_id, feature_code) VALUES (1, ?)",
                   (c,))
    db.commit()


@pytest.fixture
def client(db):
    """Đăng nhập sẵn là cán bộ id=1 (chuyên viên, KHÔNG phải admin) — mọi test
    quyền dưới đây phải đi qua đúng đường phân quyền theo nhóm."""
    app.dependency_overrides[get_current_staff] = lambda: {
        "id": 1, "role": "chuyen_vien", "username": "a", "full_name": "Nguyễn Văn A"}

    def _db():          # phải là hàm generator: FastAPI nhận diện dependency
        yield db        # kiểu yield bằng inspect.isgeneratorfunction()

    app.dependency_overrides[get_db] = _db
    c = TestClient(app)
    yield c
    app.dependency_overrides.clear()


# ── Chuẩn hoá dữ liệu ────────────────────────────────────────────────────────
def test_chuan_hoa_nhan_ngay_kieu_viet():
    ra = hr.chuan_hoa(hr.SECTIONS["work-history"]["fields"],
                      {"from_date": "01/08/2026", "unit": "Phòng TH"})
    assert ra["from_date"] == "2026-08-01"
    assert ra["at_branch"] == 0          # bool trống → 0, không phải None


def test_chuan_hoa_tu_choi_truong_la():
    with pytest.raises(hr.LoiDuLieu, match="không thuộc phân hệ"):
        hr.chuan_hoa(hr.SECTIONS["degrees"]["fields"],
                     {"kind": "trinh_do", "name": "Đại học", "luong": 99})


def test_chuan_hoa_bat_buoc_va_khoang_nguoc():
    with pytest.raises(hr.LoiDuLieu, match="Thiếu"):
        hr.chuan_hoa(hr.SECTIONS["degrees"]["fields"], {"kind": "trinh_do", "name": ""})
    with pytest.raises(hr.LoiDuLieu, match="không được trước"):
        hr.chuan_hoa(hr.SECTIONS["breaks"]["fields"],
                     {"from_date": "2026-08-10", "to_date": "2026-08-01"})


def test_chuan_hoa_enum_sai_gia_tri():
    with pytest.raises(hr.LoiDuLieu, match="không hợp lệ"):
        hr.chuan_hoa(hr.SECTIONS["degrees"]["fields"],
                     {"kind": "bang_lai", "name": "B2"})


# ── Tiện ích tính toán ───────────────────────────────────────────────────────
@pytest.mark.parametrize("ten,nhan", [
    ("Thạc sĩ Tài chính ngân hàng", "Thạc sĩ"),
    ("thac sy kinh te", "Thạc sĩ"),
    ("Đại học Kinh tế quốc dân", "Đại học"),
    ("Chứng chỉ nghiệp vụ", "Khác"),
])
def test_xep_trinh_do(ten, nhan):
    assert hr.xep_trinh_do(ten)[1] == nhan


def test_cong_thang_ngay_31_sang_thang_ngan():
    assert hr.cong_thang(date(2026, 1, 31), 1) == date(2026, 2, 28)
    assert hr.cong_thang(date(2026, 8, 28), 36) == date(2029, 8, 28)


def test_nhom_tuoi():
    assert hr.nhom_tuoi("1996-05-01", HOM_NAY) == "30 – 39"
    assert hr.nhom_tuoi("2000-12-31", HOM_NAY) == "Dưới 30"
    assert hr.nhom_tuoi(None, HOM_NAY) is None


# ── Nhắc lịch ────────────────────────────────────────────────────────────────
def test_nhac_nang_luong_dung_chu_ky(db):
    # QĐ 01/09/2023 + chu kỳ 36 tháng = 01/09/2026 — trong vòng 1 quý tới
    db.execute("""INSERT INTO hr_salaries (staff_id, grade, decision_date, cycle_months)
                  VALUES (1, 'Bậc 3', '2023-09-01', 36)""")
    # Người 2 vừa nâng lương xong, mốc kế tiếp còn 3 năm nữa → không nhắc
    db.execute("""INSERT INTO hr_salaries (staff_id, grade, decision_date, cycle_months)
                  VALUES (2, 'Bậc 5', '2026-08-01', 36)""")
    db.commit()
    ra = hr.tinh_nhac_lich(db, HOM_NAY)
    assert [(x["loai"], x["staff_id"], x["ngay_moc"]) for x in ra] == [
        ("nang_luong", 1, "2026-09-01")]


def test_nhac_lay_dong_luong_moi_nhat(db):
    db.executemany(
        "INSERT INTO hr_salaries (staff_id, decision_date, cycle_months) VALUES (1,?,36)",
        [("2020-01-01",), ("2023-09-01",)])
    db.commit()
    ra = hr.tinh_nhac_lich(db, HOM_NAY)
    # Chỉ 1 dòng nhắc, tính theo quyết định GẦN NHẤT (2023) chứ không phải mọi dòng
    assert len(ra) == 1 and ra[0]["ngay_moc"] == "2026-09-01"


def test_nhac_bo_nhiem_lai_va_qua_han(db):
    db.execute("""INSERT INTO hr_appointments (staff_id, kind, position, effective_to)
                  VALUES (2, 'bo_nhiem', 'Trưởng phòng', '2026-06-30')""")
    db.execute("""INSERT INTO hr_appointments (staff_id, kind, position, effective_to)
                  VALUES (1, 'quy_hoach', 'Phó phòng', '2026-09-30')""")
    db.commit()
    ra = hr.tinh_nhac_lich(db, HOM_NAY)
    assert len(ra) == 1                      # quy hoạch không nằm trong nhắc bổ nhiệm lại
    assert ra[0]["loai"] == "bo_nhiem_lai" and ra[0]["con_lai"] < 0   # đã quá hạn, vẫn hiện


def test_nhac_cap_cong_cu_bo_qua_do_da_tra(db):
    db.execute("""INSERT INTO hr_tools (staff_id, tool_name, status, next_issue_date)
                  VALUES (1, 'Điện thoại', 'dang_dung', '2026-10-01')""")
    db.execute("""INSERT INTO hr_tools (staff_id, tool_name, status, next_issue_date)
                  VALUES (2, 'Điện thoại cũ', 'da_tra', '2026-09-01')""")
    db.commit()
    ra = hr.tinh_nhac_lich(db, HOM_NAY)
    assert [x["staff_id"] for x in ra] == [1]


# ── Thống kê ─────────────────────────────────────────────────────────────────
def test_thong_ke_trinh_do_cao_nhat_va_qua_chi_nhanh(db):
    db.executemany(
        "INSERT INTO hr_degrees (staff_id, kind, name) VALUES (?,?,?)",
        [(1, "trinh_do", "Đại học Ngoại thương"),
         (1, "trinh_do", "Thạc sĩ Kinh tế"),
         (1, "ngoai_ngu", "IELTS 7.0")])
    db.execute("""INSERT INTO hr_work_history (staff_id, from_date, unit, at_branch)
                  VALUES (1, '2018-01-01', 'CN Hà Nội', 1)""")
    db.commit()
    tk = hr.tinh_thong_ke(db, HOM_NAY)
    bac = {m["nhan"]: m["so_luong"] for m in tk["theo_trinh_do"]}
    assert bac["Thạc sĩ"] == 1 and "Đại học" not in bac    # chỉ tính bằng cao nhất
    assert bac["Chưa khai"] == 2
    assert tk["qua_chi_nhanh"][0]["so_luong"] == 1
    assert tk["tong"] == 3, "quản trị viên không được tính vào tổng số cán bộ"


# ── Tra cứu tại thời điểm ────────────────────────────────────────────────────
def test_tra_cuu_lay_phong_theo_lich_su(db):
    db.executemany(
        """INSERT INTO staff_department_history (staff_id, department_id, effective_from)
           VALUES (?,?,?)""",
        [(1, 2, "2020-01-01"), (1, 1, "2026-07-01")])
    db.commit()
    cu = {r["staff_id"]: r["department"]
          for r in hr.tra_cuu_danh_sach(db, moc=date(2025, 6, 1))}
    moi = {r["staff_id"]: r["department"]
           for r in hr.tra_cuu_danh_sach(db, moc=HOM_NAY)}
    assert cu[1] == "Phòng Thanh toán"
    assert moi[1] == "Phòng Tổng hợp"


def test_tra_cuu_quy_hoach_va_chuc_vu_theo_hieu_luc(db):
    db.execute("""INSERT INTO hr_appointments
                  (staff_id, kind, position, effective_from, effective_to)
                  VALUES (1, 'quy_hoach', 'Phó phòng', '2026-01-01', '2029-01-01')""")
    db.execute("""INSERT INTO hr_appointments
                  (staff_id, kind, position, effective_from, effective_to)
                  VALUES (2, 'bo_nhiem', 'Trưởng phòng', '2022-01-01', '2027-01-01')""")
    db.commit()
    qh = hr.tra_cuu_danh_sach(db, "quy_hoach", HOM_NAY)
    assert [r["staff_id"] for r in qh] == [1]
    # Trước ngày hiệu lực thì chưa vào danh sách quy hoạch
    assert hr.tra_cuu_danh_sach(db, "quy_hoach", date(2025, 1, 1)) == []
    tp = hr.tra_cuu_danh_sach(db, "truong_phong", HOM_NAY)
    assert tp[0]["chuc_vu"] == "Trưởng phòng"


# ── Quản trị viên không có hồ sơ nhân sự ─────────────────────────────────────
def test_thong_ke_va_tra_cuu_bo_qua_quan_tri_vien(db):
    """Tài khoản `admin` / `admin_l2` là tài khoản hệ thống, không thuộc phòng
    nào — lọt vào đây là mọi con số 'tổng số cán bộ' đều lệch."""
    assert hr.tinh_thong_ke(db, HOM_NAY)["tong"] == 3        # 4 tài khoản, 1 là QTV
    ds = hr.tra_cuu_danh_sach(db, moc=HOM_NAY)
    assert 9 not in [r["staff_id"] for r in ds]


def test_nhac_lich_bo_qua_quan_tri_vien(db):
    db.execute("""INSERT INTO hr_salaries (staff_id, decision_date, cycle_months)
                  VALUES (9, '2023-09-01', 36)""")
    db.commit()
    assert hr.tinh_nhac_lich(db, HOM_NAY) == []


def test_danh_sach_ho_so_khong_co_quan_tri_vien(client, db):
    _cap_quyen(db, 1, "menu.hr_profiles", "hr.view_all")
    rows = client.get("/api/hr/profiles").json()
    # Danh sách sắp theo tên phòng rồi tới họ tên, nên so sánh theo tập hợp
    assert sorted(r["staff_id"] for r in rows) == [1, 2, 3]


def test_khong_mo_va_khong_ghi_duoc_ho_so_quan_tri_vien(client, db):
    _cap_quyen(db, 1, "menu.hr_profiles", "hr.view_all", "hr.edit_all")
    r = client.get("/api/hr/profiles/9")
    assert r.status_code == 404 and "quản trị viên" in r.json()["detail"]
    assert client.put("/api/hr/profiles/9", json={"cccd": "001"}).status_code == 404
    assert client.post("/api/hr/sections/degrees/9",
                       json={"kind": "tin_hoc", "name": "IC3"}).status_code == 404


# ── Ngày tuyển dụng = Ngày vào ngành ─────────────────────────────────────────
def test_ngay_tuyen_dung_ghi_vao_user_tttt(client, db):
    """Một mốc, một cột: hồ sơ KHÔNG có `recruit_date` riêng, ô "Ngày tuyển dụng"
    ghi thẳng `user_tttt.join_industry_date`."""
    _cap_quyen(db, 1, "menu.hr_profiles", "hr.edit_all")
    r = client.put("/api/hr/profiles/1", json={"join_industry_date": "01/06/2015"})
    assert r.status_code == 200, r.text
    assert db.execute("SELECT join_industry_date FROM user_tttt WHERE id = 1"
                      ).fetchone()[0] == "2015-06-01"
    assert r.json()["staff"]["join_industry_date"] == "2015-06-01"


def test_khong_con_truong_recruit_date(client, db):
    _cap_quyen(db, 1, "menu.hr_profiles", "hr.edit_all")
    r = client.put("/api/hr/profiles/1", json={"recruit_date": "2015-06-01"})
    assert r.status_code == 400 and "recruit_date" in r.json()["detail"]


def test_can_bo_khong_tu_sua_duoc_ngay_vao_nganh(client, db):
    """Cột này quyết định số ngày phép năm — tự khai được là tự cộng phép cho mình."""
    _cap_quyen(db, 1, "menu.hr_profiles")
    r = client.put("/api/hr/profiles/1", json={"join_industry_date": "2010-01-01"})
    assert r.status_code == 403
    assert db.execute("SELECT join_industry_date FROM user_tttt WHERE id = 1"
                      ).fetchone()[0] is None
    # Phần tự khai vẫn lưu bình thường
    assert client.put("/api/hr/profiles/1", json={"cccd": "001"}).status_code == 200


# ── Thứ tự sắp xếp tiếng Việt ────────────────────────────────────────────────
def test_khoa_ten_sap_theo_ten_khong_theo_ho():
    ten = ["Đào Tiến Thành", "Vũ Văn Ngân", "Bùi Quang Trung", "Hà Phương Thu",
           "Tạ Thị Thúy Hà", "Phan Duy Đạt"]
    assert sorted(ten, key=hr.khoa_ten) == [
        "Phan Duy Đạt", "Tạ Thị Thúy Hà", "Vũ Văn Ngân", "Đào Tiến Thành",
        "Hà Phương Thu", "Bùi Quang Trung"]


def test_ten_co_dau_khong_bi_day_xuong_cuoi(client, db):
    """SQLite ORDER BY so sánh theo mã byte: mọi chữ có dấu nằm sau 'z' nên
    "Đào Tiến Thành" bị dồn xuống cuối danh sách, người tra theo vần tưởng hệ
    thống lấy thiếu người. Đây là lỗi đã xảy ra thật trên dữ liệu thật."""
    _cap_quyen(db, 1, "menu.hr_profiles", "hr.view_all")
    db.executemany(
        """INSERT INTO user_tttt (id, employee_code, full_name, role, department_id,
                                  username, pwd_hash, is_active)
           VALUES (?,?,?,'chuyen_vien',1,?,'x',1)""",
        [(20, "NS020", "Đào Tiến Thành", "u20"),
         (21, "NS021", "Vũ Văn Ngân", "u21"),
         (22, "NS022", "Bùi Quang Trung", "u22")])
    db.commit()
    ten = [r["full_name"] for r in client.get(
        "/api/hr/profiles", params={"department_id": 1}).json()]
    assert ten.index("Đào Tiến Thành") < ten.index("Bùi Quang Trung"), ten
    assert ten.index("Vũ Văn Ngân") < ten.index("Đào Tiến Thành"), ten


def test_tra_cuu_cung_thu_tu_voi_danh_sach_ho_so(db):
    db.executemany(
        """INSERT INTO user_tttt (id, employee_code, full_name, role, department_id,
                                  username, pwd_hash, is_active)
           VALUES (?,?,?,'chuyen_vien',1,?,'x',1)""",
        [(20, "NS020", "Đào Tiến Thành", "u20"), (21, "NS021", "Vũ Văn Ngân", "u21")])
    db.commit()
    ds = [r["full_name"] for r in hr.tra_cuu_danh_sach(db, moc=HOM_NAY)
          if r["staff_id"] in (20, 21)]
    assert ds == ["Vũ Văn Ngân", "Đào Tiến Thành"]      # Ngân trước Thành


def test_trong_mot_phong_lanh_dao_dung_truoc(client, db):
    """Trưởng phòng → Phó phòng → nhân viên (hậu kiểm viên và chuyên viên cùng
    bậc, xếp lẫn theo tên)."""
    _cap_quyen(db, 1, "menu.hr_profiles", "hr.view_all")
    db.executemany(
        """INSERT INTO user_tttt (id, employee_code, full_name, role, department_id,
                                  username, pwd_hash, is_active)
           VALUES (?,?,?,?,1,?,'x',1)""",
        [(30, "NS030", "Vũ Văn Bình", "chuyen_vien", "u30"),
         (31, "NS031", "Đào Tiến Thành", "truong_phong", "u31"),
         (32, "NS032", "Trần Thị An", "pho_phong", "u32"),
         (33, "NS033", "Lê Thị Ánh", "hau_kiem_vien", "u33")])
    db.commit()
    ds = [(r["full_name"], r["role"]) for r in client.get(
        "/api/hr/profiles", params={"department_id": 1}).json()
        if r["staff_id"] in (30, 31, 32, 33)]
    assert ds == [("Đào Tiến Thành", "truong_phong"),
                  ("Trần Thị An", "pho_phong"),
                  ("Lê Thị Ánh", "hau_kiem_vien"),      # cùng bậc nhân viên,
                  ("Vũ Văn Bình", "chuyen_vien")]       # xếp theo tên: Ánh < Bình


def test_thu_tu_chuc_vu_khong_dung_chung_bang_voi_phan_quyen():
    """`ROLE_RANK` (backend/core/enums.py) xếp theo QUYỀN — hậu kiểm viên đứng
    trên trưởng phòng. Dùng chung một bảng thì sửa thứ tự hiển thị là vô tình
    đổi luật chặn leo thang quyền."""
    from backend.core.enums import ROLE_RANK
    assert ROLE_RANK["hau_kiem_vien"] > ROLE_RANK["truong_phong"]
    assert hr.THU_TU_CHUC_VU["hau_kiem_vien"] > hr.THU_TU_CHUC_VU["truong_phong"]


def test_tra_cuu_cung_thu_tu_chuc_vu(db):
    db.executemany(
        """INSERT INTO user_tttt (id, employee_code, full_name, role, department_id,
                                  username, pwd_hash, is_active)
           VALUES (?,?,?,?,1,?,'x',1)""",
        [(30, "NS030", "Vũ Văn Bình", "chuyen_vien", "u30"),
         (31, "NS031", "Đào Tiến Thành", "truong_phong", "u31")])
    db.commit()
    ds = [r["full_name"] for r in hr.tra_cuu_danh_sach(db, moc=HOM_NAY)
          if r["staff_id"] in (30, 31)]
    assert ds == ["Đào Tiến Thành", "Vũ Văn Bình"]


# ── Phân quyền qua API ───────────────────────────────────────────────────────
def test_khong_co_quyen_thi_khong_vao_duoc(client):
    assert client.get("/api/hr/profiles").status_code == 403


def test_chi_thay_ho_so_cua_minh(client, db):
    _cap_quyen(db, 1, "menu.hr_profiles")
    rows = client.get("/api/hr/profiles").json()
    assert [r["staff_id"] for r in rows] == [1]
    assert client.get("/api/hr/profiles/2").status_code == 403


def test_tu_khai_duoc_ho_so_minh_nhung_khong_sua_phan_cong_tac(client, db):
    _cap_quyen(db, 1, "menu.hr_profiles")
    r = client.put("/api/hr/profiles/1", json={"cccd": "001096000111", "dependents": 2})
    assert r.status_code == 200 and r.json()["profile"]["cccd"] == "001096000111"
    assert client.put("/api/hr/profiles/1",
                      json={"contract_type": "Không xác định thời hạn"}).status_code == 403


def test_dien_thoai_ghi_thang_vao_user_tttt(client, db):
    _cap_quyen(db, 1, "menu.hr_profiles")
    client.put("/api/hr/profiles/1", json={"phone": "0912345678"})
    assert db.execute("SELECT phone FROM user_tttt WHERE id = 1").fetchone()[0] == "0912345678"


def test_phan_he_tu_khai_va_phan_he_chi_nhan_su(client, db):
    _cap_quyen(db, 1, "menu.hr_profiles")
    # Bằng cấp: tự khai được
    r = client.post("/api/hr/sections/degrees/1",
                    json={"kind": "trinh_do", "name": "Đại học Ngoại thương"})
    assert r.status_code == 200
    # Quá trình công tác: phải là người làm nhân sự
    r = client.post("/api/hr/sections/work-history/1",
                    json={"from_date": "2020-01-01", "unit": "Phòng TH"})
    assert r.status_code == 403


def test_luong_can_quyen_rieng_ke_ca_ho_so_minh(client, db):
    _cap_quyen(db, 1, "menu.hr_profiles", "hr.edit_all")
    r = client.post("/api/hr/sections/salaries/1", json={"decision_date": "2026-01-01"})
    assert r.status_code == 403, "hr.edit_all không được phép kéo theo quyền sửa lương"
    _cap_quyen(db, 1, "hr.salary_edit")
    assert client.post("/api/hr/sections/salaries/1",
                       json={"decision_date": "2026-01-01", "grade": "Bậc 3"}).status_code == 200


def test_an_han_phan_he_luong_cua_nguoi_khac(client, db):
    _cap_quyen(db, 1, "menu.hr_profiles", "hr.view_all")
    db.execute("INSERT INTO hr_salaries (staff_id, decision_date) VALUES (2, '2026-01-01')")
    db.commit()
    data = client.get("/api/hr/profiles/2").json()
    assert "salaries" not in data["sections"]
    assert client.get("/api/hr/sections/salaries/2").status_code == 403
    # Hồ sơ lương của CHÍNH mình thì luôn xem được
    assert client.get("/api/hr/sections/salaries/1").status_code == 200


# ── Định dạng tệp ────────────────────────────────────────────────────────────
def _them_bang_cap(client) -> int:
    return client.post("/api/hr/sections/degrees/1",
                       json={"kind": "tin_hoc", "name": "IC3"}).json()["id"]


def test_dinh_dang_tep_xet_theo_duoi_file(client, db):
    """Kiểm theo PHẦN MỞ RỘNG, không theo content_type client khai — người dùng
    nhìn thấy đuôi file nên báo lỗi theo đuôi mới hiểu được."""
    _cap_quyen(db, 1, "menu.hr_profiles")
    item = _them_bang_cap(client)
    r = client.post(f"/api/hr/attachments/degrees/{item}",
                    files={"file": ("bang.exe", b"MZ", "application/pdf")})
    assert r.status_code == 400 and ".pdf" in r.json()["detail"]
    r = client.post(f"/api/hr/attachments/degrees/{item}",
                    files={"file": ("bang.pdf", b"%PDF-1.4", "application/pdf")})
    assert r.status_code == 200


def test_mime_luu_lai_khong_lay_tu_client(client, db):
    """content_type là chuỗi client tự khai; lưu lại rồi phát ngược ra là để
    người tải lên chọn kiểu nội dung máy chủ sẽ trả về."""
    _cap_quyen(db, 1, "menu.hr_profiles")
    item = _them_bang_cap(client)
    r = client.post(f"/api/hr/attachments/degrees/{item}",
                    files={"file": ("qd.pdf", b"<script>alert(1)</script>", "text/html")})
    assert r.json()["mime"] == "application/pdf"
    assert db.execute("SELECT mime FROM hr_attachments WHERE id = ?",
                      (r.json()["id"],)).fetchone()[0] == "application/pdf"

    r = client.post("/api/hr/profiles/1/photo",
                    files={"file": ("anh.png", b"\x89PNG", "text/html")})
    assert r.status_code == 200
    assert db.execute("SELECT photo_mime FROM hr_profiles WHERE staff_id = 1"
                      ).fetchone()[0] == "image/png"


def test_anh_the_khong_nhan_pdf(client, db):
    _cap_quyen(db, 1, "menu.hr_profiles")
    r = client.post("/api/hr/profiles/1/photo",
                    files={"file": ("qd.pdf", b"%PDF", "application/pdf")})
    assert r.status_code == 400 and ".png" in r.json()["detail"]


def test_meta_cong_bo_dinh_dang_cho_form(client, db):
    """Ô chọn file ngoài giao diện lấy danh sách đuôi từ đây — khai hai nơi thì
    form cho chọn thứ backend từ chối."""
    _cap_quyen(db, 1, "menu.hr_profiles")
    tep = client.get("/api/hr/meta").json()["tep"]
    assert ".pdf" in tep["file_accept"] and ".pdf" not in tep["anh_accept"]
    assert tep["tran_anh_mb"] == 5 and tep["tran_file_mb"] == 15


def test_xoa_dong_ho_so_xoa_luon_file_dinh_kem(client, db):
    _cap_quyen(db, 1, "menu.hr_profiles")
    item_id = client.post("/api/hr/sections/degrees/1",
                          json={"kind": "tin_hoc", "name": "IC3"}).json()["id"]
    db.execute("""INSERT INTO hr_attachments (section, item_id, filename, content)
                  VALUES ('degrees', ?, 'ic3.pdf', X'25504446')""", (item_id,))
    db.commit()
    assert client.delete(f"/api/hr/items/degrees/{item_id}").status_code == 200
    con_lai = db.execute(
        "SELECT COUNT(*) FROM hr_attachments WHERE section='degrees' AND item_id=?",
        (item_id,)).fetchone()[0]
    assert con_lai == 0, "file đính kèm phải bị xoá theo dòng hồ sơ"


def test_cot_not_null_co_gia_tri_mac_dinh(client, db):
    """`hr_tools.status` là NOT NULL — bỏ trống ô Trạng thái phải rơi về
    'đang sử dụng', không được để API gửi NULL xuống làm vỡ câu INSERT."""
    _cap_quyen(db, 1, "menu.hr_profiles")
    r = client.post("/api/hr/sections/tools/1", json={"tool_name": "Laptop"})
    assert r.status_code == 200, r.text
    assert r.json()["status"] == "dang_dung"
    assert r.json()["quantity"] == 1


def test_nghi_gian_doan_mac_dinh_khong_huong_luong(client, db):
    _cap_quyen(db, 1, "menu.hr_profiles", "hr.edit_all")
    r = client.post("/api/hr/sections/breaks/1",
                    json={"from_date": "2019-01-01", "to_date": "2019-03-31"})
    assert r.json()["unpaid"] == 1
    # Bỏ tích thì phải giữ nguyên 0, không bị mặc định đè lên
    r = client.post("/api/hr/sections/breaks/1",
                    json={"from_date": "2020-01-01", "to_date": "2020-02-01",
                          "unpaid": False})
    assert r.json()["unpaid"] == 0


def test_patch_khong_duoc_xoa_trang_truong_bat_buoc(client, db):
    _cap_quyen(db, 1, "menu.hr_profiles")
    item_id = client.post("/api/hr/sections/degrees/1",
                          json={"kind": "tin_hoc", "name": "IC3"}).json()["id"]
    assert client.patch(f"/api/hr/items/degrees/{item_id}", json={"name": ""}).status_code == 400


def test_nhac_lich_khong_co_view_all_chi_thay_cua_minh(client, db):
    _cap_quyen(db, 1, "menu.hr_reminders")
    db.executemany(
        "INSERT INTO hr_tools (staff_id, tool_name, status, next_issue_date) VALUES (?,?,?,?)",
        [(1, "Điện thoại", "dang_dung", (date.today() + timedelta(days=10)).isoformat()),
         (2, "Điện thoại", "dang_dung", (date.today() + timedelta(days=10)).isoformat())])
    db.commit()
    ra = client.get("/api/hr/reminders").json()
    assert [x["staff_id"] for x in ra] == [1]
