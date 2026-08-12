"""Test API liệt kê thư mục cho dialog chọn thư mục (backend/api/fs.py).
Chạy: .venv\\Scripts\\python.exe -m pytest tests/test_fs_browse_api.py -v
"""


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

    def test_duong_dan_cua_1_file_thi_mo_thu_muc_chua_no(self, admin_client, tmp_path):
        """Người dùng hay copy đường dẫn của FILE thay vì thư mục — mở thư mục
        chứa nó thay vì báo 'Thư mục không tồn tại' rồi bế tắc (2026-08-12)."""
        (tmp_path / 'con_a').mkdir()
        f = tmp_path / 'QT đi 10.08.xlsx'
        f.write_text('x', encoding='utf-8')

        r = admin_client.get('/api/fs/browse', params={'path': str(f)})
        assert r.status_code == 200
        data = r.json()
        assert data['path'] == str(tmp_path)
        assert [e['name'] for e in data['entries']] == ['con_a']

    def test_duong_dan_boc_trong_dau_nhay_kep_van_mo_duoc(self, admin_client, tmp_path):
        """Windows "Copy as path" trả về đường dẫn bọc trong dấu nháy kép."""
        (tmp_path / 'con_b').mkdir()
        r = admin_client.get('/api/fs/browse', params={'path': f'"{tmp_path}"'})
        assert r.status_code == 200
        assert [e['name'] for e in r.json()['entries']] == ['con_b']
