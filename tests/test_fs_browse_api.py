"""Test API liệt kê thư mục cho dialog chọn thư mục (backend/api/fs.py).
Chạy: .venv\\Scripts\\python.exe -m pytest tests/test_fs_browse_api.py -v
"""

import sqlite3

import pytest
from fastapi.testclient import TestClient

from backend.core.deps import get_current_staff
from backend.core.enums import StaffRole
from backend.database import get_db
from backend.main import app

_STAFF_ID = 7


def _client_voi_quyen(codes: list[str]) -> TestClient:
    """TestClient đăng nhập bằng chuyên viên thuộc 1 nhóm được cấp đúng `codes`
    (không phải admin — admin bypass mọi feature check, không chạm được lớp
    phân quyền đang test)."""
    conn = sqlite3.connect(':memory:', check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.executescript(
        """CREATE TABLE user_groups (id INTEGER PRIMARY KEY, name TEXT, is_active BOOLEAN DEFAULT 1);
           CREATE TABLE group_members (group_id INTEGER, staff_id INTEGER);
           CREATE TABLE group_features (group_id INTEGER, feature_code TEXT);
           INSERT INTO user_groups (id, name, is_active) VALUES (1, 'Nhom test', 1);"""
    )
    conn.execute('INSERT INTO group_members (group_id, staff_id) VALUES (1, ?)', (_STAFF_ID,))
    conn.executemany(
        'INSERT INTO group_features (group_id, feature_code) VALUES (1, ?)',
        [(c,) for c in codes],
    )
    conn.commit()

    app.dependency_overrides[get_current_staff] = lambda: {
        'id': _STAFF_ID, 'role': StaffRole.CHUYEN_VIEN,
        'username': 'test-cv', 'full_name': 'Test Chuyen Vien',
    }
    def _db():
        yield conn

    app.dependency_overrides[get_db] = _db
    return TestClient(app)


@pytest.fixture
def client_khong_co_menu_nao():
    yield _client_voi_quyen([])
    app.dependency_overrides.clear()


@pytest.fixture
def client_co_menu_459901():
    yield _client_voi_quyen(['menu.cham_459901'])
    app.dependency_overrides.clear()


class TestFsBrowseChanUserKhongLienQuan:
    """Review PR#68 (khanhbq693): trước fix, /api/fs/browse chỉ gắn
    get_current_staff — BẤT KỲ ai đã đăng nhập, kể cả chuyên viên không có menu
    nào trong 4 module dùng folder-picker, liệt kê được toàn bộ ổ đĩa/thư mục
    trên máy chủ. Nay dùng require_any_feature() — cùng cách PR54 (nhánh
    ach-chi-tim-timeout) đã cài sẵn sentinel test yêu cầu đúng giải pháp này."""

    def test_khong_co_menu_nao_bi_tu_choi(self, client_khong_co_menu_nao):
        # Không cần cấu hình FOLDER_PICKER_ROOTS — require_any_feature() chặn TRƯỚC khi route
        # kịp đọc tới cấu hình đó.
        for tham_so in ({}, {'path': 'C:\\'}):
            r = client_khong_co_menu_nao.get('/api/fs/browse', params=tham_so)
            assert r.status_code == 403

    def test_co_menu_459901_duoc_qua(self, client_co_menu_459901, tmp_path, monkeypatch):
        """Chỉ cần MỘT trong 4 menu — không bắt phải có cả 4 (quan hệ HOẶC)."""
        monkeypatch.setenv('FOLDER_PICKER_ROOTS', str(tmp_path))
        r = client_co_menu_459901.get('/api/fs/browse')
        assert r.status_code == 200


class TestBrowse:
    """Mọi test dùng `admin_client` (bypass RBAC) — luôn cấu hình FOLDER_PICKER_ROOTS trỏ vào
    `tmp_path` để mô phỏng "đã cấu hình đúng cách" (2026-09-01, đổi sang fail-closed — xem
    `TestFolderPickerRoots`)."""

    def test_list_dir_with_subfolders(self, admin_client, tmp_path, monkeypatch):
        monkeypatch.setenv('FOLDER_PICKER_ROOTS', str(tmp_path))
        (tmp_path / 'ngay16').mkdir()
        (tmp_path / 'ngay17').mkdir()
        (tmp_path / 'somefile.txt').write_text('x')  # file — không được lọt vào entries

        r = admin_client.get('/api/fs/browse', params={'path': str(tmp_path)})
        assert r.status_code == 200
        body = r.json()
        names = [e['name'] for e in body['entries']]
        assert names == sorted(names, key=str.lower)
        assert 'ngay16' in names and 'ngay17' in names
        assert 'somefile.txt' not in names

    def test_empty_dir_returns_empty_entries(self, admin_client, tmp_path, monkeypatch):
        monkeypatch.setenv('FOLDER_PICKER_ROOTS', str(tmp_path))
        empty_dir = tmp_path / 'empty'
        empty_dir.mkdir()
        r = admin_client.get('/api/fs/browse', params={'path': str(empty_dir)})
        assert r.status_code == 200
        assert r.json()['entries'] == []

    def test_nonexistent_path_returns_400(self, admin_client, tmp_path, monkeypatch):
        monkeypatch.setenv('FOLDER_PICKER_ROOTS', str(tmp_path))
        r = admin_client.get('/api/fs/browse', params={'path': str(tmp_path / 'khong_ton_tai')})
        assert r.status_code == 400

    def test_breadcrumbs_di_tu_goc_toi_thu_muc_hien_tai(self, admin_client, tmp_path, monkeypatch):
        """Breadcrumb (thanh điều hướng kiểu Explorer) phải liệt kê đủ từ ổ đĩa
        tới thư mục đang mở, mỗi đoạn có path để bấm nhảy thẳng tới đó."""
        monkeypatch.setenv('FOLDER_PICKER_ROOTS', str(tmp_path))
        nested = tmp_path / 'ACH' / '28.07'
        nested.mkdir(parents=True)
        r = admin_client.get('/api/fs/browse', params={'path': str(nested)})
        assert r.status_code == 200
        crumbs = r.json()['breadcrumbs']
        names = [c['name'] for c in crumbs]
        assert names[0].endswith(':\\')  # đoạn đầu luôn là ổ đĩa
        assert names[-2:] == ['ACH', '28.07']
        # Đoạn cuối cùng phải trỏ đúng thư mục đang mở
        assert crumbs[-1]['path'] == str(nested)

    def test_permission_denied_returns_403(self, admin_client, tmp_path, monkeypatch):
        monkeypatch.setenv('FOLDER_PICKER_ROOTS', str(tmp_path))
        import backend.api.fs as fs_mod

        def _raise(_path):
            raise PermissionError('Access denied')

        monkeypatch.setattr(fs_mod.os, 'scandir', _raise)
        r = admin_client.get('/api/fs/browse', params={'path': str(tmp_path)})
        assert r.status_code == 403


# ── FOLDER_PICKER_ROOTS — fail-closed (2026-09-01, review PR#68 khanhbq693 mục B2) ──
# Trước: rỗng/chưa cấu hình = liệt kê được TOÀN BỘ ổ đĩa/thư mục máy chủ cho bất kỳ ai
# qua được require_any_feature() — không phải kiểm soát bảo mật thật, chỉ là 1 dòng
# WARNING không ai đọc. Nay: chưa cấu hình = route báo lỗi rõ ràng (400), giống hệt
# `cham459901_folder_roots()` đã áp dụng trước đó cho "Chấm 459901 → Chọn thư mục server".

class TestFolderPickerRoots:
    def test_chua_cau_hinh_thi_bi_khoa(self, admin_client, tmp_path):
        """FOLDER_PICKER_ROOTS chưa đặt trong .env (mặc định môi trường test, không set biến
        này) — route phải báo lỗi rõ ràng, KHÔNG mặc định liệt kê toàn bộ ổ đĩa như trước."""
        r = admin_client.get('/api/fs/browse', params={'path': str(tmp_path)})
        assert r.status_code == 400
        assert 'FOLDER_PICKER_ROOTS' in r.json()['detail']

    def test_duyet_trong_pham_vi_goc_duoc_phep(self, admin_client, tmp_path, monkeypatch):
        root = tmp_path / 'goc_cho_phep'
        root.mkdir()
        (root / 'con').mkdir()
        monkeypatch.setenv('FOLDER_PICKER_ROOTS', str(root))

        r = admin_client.get('/api/fs/browse', params={'path': str(root)})
        assert r.status_code == 200
        assert any(e['name'] == 'con' for e in r.json()['entries'])

        r2 = admin_client.get('/api/fs/browse', params={'path': str(root / 'con')})
        assert r2.status_code == 200

    def test_duyet_ngoai_pham_vi_bi_tu_choi_403(self, admin_client, tmp_path, monkeypatch):
        root = tmp_path / 'goc_cho_phep'
        root.mkdir()
        ngoai_pham_vi = tmp_path / 'noi_khac'
        ngoai_pham_vi.mkdir()
        monkeypatch.setenv('FOLDER_PICKER_ROOTS', str(root))

        r = admin_client.get('/api/fs/browse', params={'path': str(ngoai_pham_vi)})
        assert r.status_code == 403

    def test_khoi_dau_chi_hien_danh_sach_goc_khong_phai_o_dia(self, admin_client, tmp_path, monkeypatch):
        root = tmp_path / 'goc_cho_phep'
        root.mkdir()
        monkeypatch.setenv('FOLDER_PICKER_ROOTS', str(root))

        r = admin_client.get('/api/fs/browse')
        assert r.status_code == 200
        body = r.json()
        assert body['path'] is None
        assert [e['path'] for e in body['entries']] == [str(root)]

    def test_len_1_cap_tai_goc_dung_lai_khong_lo_thu_muc_cha_that(self, admin_client, tmp_path, monkeypatch):
        """'Lên 1 cấp' tại đúng thư mục gốc phải dừng (parent=None) — không lộ ra
        thư mục cha thật của gốc (VD gốc nằm trong G:\\, không được lộ G:\\)."""
        root = tmp_path / 'goc_cho_phep'
        root.mkdir()
        monkeypatch.setenv('FOLDER_PICKER_ROOTS', str(root))

        r = admin_client.get('/api/fs/browse', params={'path': str(root)})
        assert r.status_code == 200
        assert r.json()['parent'] is None

    def test_path_traversal_tu_ben_trong_goc_bi_chan(self, admin_client, tmp_path, monkeypatch):
        root = tmp_path / 'goc_cho_phep'
        root.mkdir()
        monkeypatch.setenv('FOLDER_PICKER_ROOTS', str(root))

        r = admin_client.get('/api/fs/browse', params={'path': str(root / '..')})
        assert r.status_code == 403

    def test_nhieu_goc_ngan_boi_dau_cham_phay(self, admin_client, tmp_path, monkeypatch):
        """Nhiều thư mục gốc ngăn bằng dấu ';' (quy ước Windows, giống CHAM459901_FOLDER_ROOTS)."""
        root1 = tmp_path / 'goc1'
        root2 = tmp_path / 'goc2'
        root1.mkdir()
        root2.mkdir()
        monkeypatch.setenv('FOLDER_PICKER_ROOTS', f'{root1};{root2}')

        r = admin_client.get('/api/fs/browse')
        assert r.status_code == 200
        paths = {e['path'] for e in r.json()['entries']}
        assert paths == {str(root1), str(root2)}
