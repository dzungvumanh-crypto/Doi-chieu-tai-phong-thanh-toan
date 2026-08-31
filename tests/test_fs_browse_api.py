"""Test API liệt kê thư mục cho dialog chọn thư mục (backend/api/fs.py).

Nhánh này chỉ cham459901.py dùng open_folder_picker() — xem docstring
backend/api/fs.py. Feature-code duy nhất là menu.cham_459901.

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


@pytest.fixture
def client_chi_co_menu_ach():
    """Chốt ranh giới phạm vi: menu.cham_ach KHÔNG được lọt — module này trên
    nhánh này không dùng folder-picker (xem docstring backend/api/fs.py)."""
    yield _client_voi_quyen(['menu.cham_ach'])
    app.dependency_overrides.clear()


class TestFsBrowseQuyenTruyCap:
    def test_khong_co_menu_nao_bi_tu_choi(self, client_khong_co_menu_nao):
        r = client_khong_co_menu_nao.get('/api/fs/browse')
        assert r.status_code == 403

    def test_chi_co_menu_ach_van_bi_tu_choi(self, client_chi_co_menu_ach):
        r = client_chi_co_menu_ach.get('/api/fs/browse')
        assert r.status_code == 403

    def test_co_menu_459901_duoc_qua(self, client_co_menu_459901):
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

    def test_list_dir_with_subfolders(self, admin_client, tmp_path):
        (tmp_path / 'ngay16').mkdir()
        (tmp_path / 'ngay17').mkdir()
        (tmp_path / 'somefile.txt').write_text('x')

        r = admin_client.get('/api/fs/browse', params={'path': str(tmp_path)})
        assert r.status_code == 200
        body = r.json()
        names = [e['name'] for e in body['entries']]
        assert 'ngay16' in names and 'ngay17' in names
        assert 'somefile.txt' not in names

    def test_nonexistent_path_returns_400(self, admin_client, tmp_path):
        r = admin_client.get('/api/fs/browse', params={'path': str(tmp_path / 'khong_ton_tai')})
        assert r.status_code == 400


class TestFolderPickerRoots:
    def test_khong_cau_hinh_thi_van_khong_gioi_han_nhu_cu(self, admin_client, tmp_path):
        r = admin_client.get('/api/fs/browse', params={'path': str(tmp_path)})
        assert r.status_code == 200

    def test_duyet_ngoai_pham_vi_bi_tu_choi_403(self, admin_client, tmp_path, monkeypatch):
        from backend.core.config import settings

        root = tmp_path / 'goc_cho_phep'
        root.mkdir()
        ngoai_pham_vi = tmp_path / 'noi_khac'
        ngoai_pham_vi.mkdir()
        monkeypatch.setattr(settings, 'FOLDER_PICKER_ROOTS', [str(root)])

        r = admin_client.get('/api/fs/browse', params={'path': str(ngoai_pham_vi)})
        assert r.status_code == 403

    def test_duyet_trong_pham_vi_duoc_phep(self, admin_client, tmp_path, monkeypatch):
        from backend.core.config import settings

        root = tmp_path / 'goc_cho_phep'
        root.mkdir()
        monkeypatch.setattr(settings, 'FOLDER_PICKER_ROOTS', [str(root)])

        r = admin_client.get('/api/fs/browse', params={'path': str(root)})
        assert r.status_code == 200
