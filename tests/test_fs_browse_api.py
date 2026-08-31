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
        for tham_so in ({}, {'path': 'C:\\'}):
            r = client_khong_co_menu_nao.get('/api/fs/browse', params=tham_so)
            assert r.status_code == 403

    def test_co_menu_459901_duoc_qua(self, client_co_menu_459901):
        """Chỉ cần MỘT trong 4 menu — không bắt phải có cả 4 (quan hệ HOẶC)."""
        r = client_co_menu_459901.get('/api/fs/browse')
        assert r.status_code == 200


class TestBrowse:
    def test_list_drives_when_path_empty(self, admin_client):
        r = admin_client.get('/api/fs/browse')
        assert r.status_code == 200
        body = r.json()
        assert body['path'] is None
        assert body['parent'] is None
        assert isinstance(body['entries'], list) and len(body['entries']) > 0
        assert all(e['name'].endswith(':\\') for e in body['entries'])

    def test_list_dir_with_subfolders(self, admin_client, tmp_path):
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
        assert body['parent'] is not None  # tmp_path không phải gốc ổ đĩa

    def test_empty_dir_returns_empty_entries(self, admin_client, tmp_path):
        empty_dir = tmp_path / 'empty'
        empty_dir.mkdir()
        r = admin_client.get('/api/fs/browse', params={'path': str(empty_dir)})
        assert r.status_code == 200
        assert r.json()['entries'] == []

    def test_nonexistent_path_returns_400(self, admin_client, tmp_path):
        r = admin_client.get('/api/fs/browse', params={'path': str(tmp_path / 'khong_ton_tai')})
        assert r.status_code == 400

    def test_drive_root_parent_is_none(self, admin_client, tmp_path):
        drive = str(tmp_path)[:3]  # vd 'C:\\'
        r = admin_client.get('/api/fs/browse', params={'path': drive})
        assert r.status_code == 200
        assert r.json()['parent'] is None

    def test_breadcrumbs_di_tu_o_dia_toi_thu_muc_hien_tai(self, admin_client, tmp_path):
        """Breadcrumb (thanh điều hướng kiểu Explorer) phải liệt kê đủ từ ổ đĩa
        tới thư mục đang mở, mỗi đoạn có path để bấm nhảy thẳng tới đó."""
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

    def test_breadcrumbs_tai_goc_o_dia_chi_co_1_doan(self, admin_client, tmp_path):
        drive = str(tmp_path)[:3]
        r = admin_client.get('/api/fs/browse', params={'path': drive})
        assert r.status_code == 200
        crumbs = r.json()['breadcrumbs']
        assert len(crumbs) == 1
        assert crumbs[0]['name'].endswith(':\\')

    def test_permission_denied_returns_403(self, admin_client, tmp_path, monkeypatch):
        import backend.api.fs as fs_mod

        def _raise(_path):
            raise PermissionError('Access denied')

        monkeypatch.setattr(fs_mod.os, 'scandir', _raise)
        r = admin_client.get('/api/fs/browse', params={'path': str(tmp_path)})
        assert r.status_code == 403


# ── FOLDER_PICKER_ROOTS — giới hạn phạm vi duyệt (review PR#68, khanhbq693 mục 2) ──
# Trước fix: require_any_feature() siết ĐƯỢC AI vào, nhưng _list_dir() nhận path tuỳ
# ý, không có gốc giới hạn — một chuyên viên chỉ có menu.cham_ach vẫn duyệt được
# C:\Users, ổ mạng đã map, toàn bộ cây thư mục máy chủ.

class TestFolderPickerRoots:
    def test_khong_cau_hinh_thi_van_khong_gioi_han_nhu_cu(self, admin_client, tmp_path):
        """FOLDER_PICKER_ROOTS rỗng (mặc định, chưa ai cấu hình) — giữ hành vi cũ,
        không chặn nhầm khi chưa biết cấu trúc thư mục thật trên server production."""
        r = admin_client.get('/api/fs/browse', params={'path': str(tmp_path)})
        assert r.status_code == 200

    def test_duyet_trong_pham_vi_goc_duoc_phep(self, admin_client, tmp_path, monkeypatch):
        import backend.api.fs as fs_mod

        root = tmp_path / 'goc_cho_phep'
        root.mkdir()
        (root / 'con').mkdir()
        monkeypatch.setattr(fs_mod.settings, 'FOLDER_PICKER_ROOTS', [str(root)])

        r = admin_client.get('/api/fs/browse', params={'path': str(root)})
        assert r.status_code == 200
        assert any(e['name'] == 'con' for e in r.json()['entries'])

        r2 = admin_client.get('/api/fs/browse', params={'path': str(root / 'con')})
        assert r2.status_code == 200

    def test_duyet_ngoai_pham_vi_bi_tu_choi_403(self, admin_client, tmp_path, monkeypatch):
        import backend.api.fs as fs_mod

        root = tmp_path / 'goc_cho_phep'
        root.mkdir()
        ngoai_pham_vi = tmp_path / 'noi_khac'
        ngoai_pham_vi.mkdir()
        monkeypatch.setattr(fs_mod.settings, 'FOLDER_PICKER_ROOTS', [str(root)])

        r = admin_client.get('/api/fs/browse', params={'path': str(ngoai_pham_vi)})
        assert r.status_code == 403

    def test_khoi_dau_chi_hien_danh_sach_goc_khong_phai_o_dia(self, admin_client, tmp_path, monkeypatch):
        import backend.api.fs as fs_mod

        root = tmp_path / 'goc_cho_phep'
        root.mkdir()
        monkeypatch.setattr(fs_mod.settings, 'FOLDER_PICKER_ROOTS', [str(root)])

        r = admin_client.get('/api/fs/browse')
        assert r.status_code == 200
        body = r.json()
        assert body['path'] is None
        assert [e['path'] for e in body['entries']] == [str(root)]

    def test_len_1_cap_tai_goc_dung_lai_khong_lo_thu_muc_cha_that(self, admin_client, tmp_path, monkeypatch):
        """'Lên 1 cấp' tại đúng thư mục gốc phải dừng (parent=None) — không lộ ra
        thư mục cha thật của gốc (VD gốc nằm trong G:\\, không được lộ G:\\)."""
        import backend.api.fs as fs_mod

        root = tmp_path / 'goc_cho_phep'
        root.mkdir()
        monkeypatch.setattr(fs_mod.settings, 'FOLDER_PICKER_ROOTS', [str(root)])

        r = admin_client.get('/api/fs/browse', params={'path': str(root)})
        assert r.status_code == 200
        assert r.json()['parent'] is None

    def test_path_traversal_tu_ben_trong_goc_bi_chan(self, admin_client, tmp_path, monkeypatch):
        import backend.api.fs as fs_mod

        root = tmp_path / 'goc_cho_phep'
        root.mkdir()
        monkeypatch.setattr(fs_mod.settings, 'FOLDER_PICKER_ROOTS', [str(root)])

        r = admin_client.get('/api/fs/browse', params={'path': str(root / '..')})
        assert r.status_code == 403
