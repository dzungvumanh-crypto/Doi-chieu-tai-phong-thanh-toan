"""Test migration cấp bù cham_ach.process cho nhóm đã có menu.cham_ach (review PR#54).

cham_ach.process khai trong FEATURES từ trước nhưng chưa từng được enforce — PR#54 bắt
đầu enforce ở /start /continue /cancel. Nhóm nào chỉ có menu.cham_ach trong DB thật sẽ mất
nút "Chạy" ngay khi deploy nếu không cấp bù. Migration trong _ensure_indexes() phải tự cấp.

Chạy: .venv\\Scripts\\python.exe -m pytest tests/test_migrations_ach_process_grant.py -v
"""
import sqlite3

import backend.db.migrations as migrations


def _fresh_db(path: str) -> sqlite3.Connection:
    migrations._create_tables(path)
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    return conn


class TestCapBuChamAchProcess:
    def test_nhom_co_menu_cham_ach_duoc_cap_bu_process(self, tmp_path, monkeypatch):
        db_path = str(tmp_path / 'test.db')
        conn = _fresh_db(db_path)
        conn.execute("INSERT INTO user_groups (id, name, is_active) VALUES (1, 'Nhom ACH', 1)")
        conn.execute("INSERT INTO group_features (group_id, feature_code) VALUES (1, 'menu.cham_ach')")
        conn.commit()
        conn.close()

        monkeypatch.setattr(migrations, 'DB_PATH', db_path)
        migrations._ensure_indexes()

        conn = sqlite3.connect(db_path)
        codes = {r[0] for r in conn.execute(
            "SELECT feature_code FROM group_features WHERE group_id = 1"
        )}
        conn.close()
        assert 'menu.cham_ach' in codes
        assert 'cham_ach.process' in codes

    def test_nhom_khong_co_menu_cham_ach_khong_bi_cap_nham(self, tmp_path, monkeypatch):
        db_path = str(tmp_path / 'test.db')
        conn = _fresh_db(db_path)
        conn.execute("INSERT INTO user_groups (id, name, is_active) VALUES (1, 'Nhom Khac', 1)")
        conn.execute("INSERT INTO group_features (group_id, feature_code) VALUES (1, 'menu.cham_459901')")
        conn.commit()
        conn.close()

        monkeypatch.setattr(migrations, 'DB_PATH', db_path)
        migrations._ensure_indexes()

        conn = sqlite3.connect(db_path)
        codes = {r[0] for r in conn.execute(
            "SELECT feature_code FROM group_features WHERE group_id = 1"
        )}
        conn.close()
        assert 'cham_ach.process' not in codes

    def test_chay_lai_lan_2_khong_loi_khong_trung(self, tmp_path, monkeypatch):
        """Idempotent — INSERT OR IGNORE trên PRIMARY KEY (group_id, feature_code)."""
        db_path = str(tmp_path / 'test.db')
        conn = _fresh_db(db_path)
        conn.execute("INSERT INTO user_groups (id, name, is_active) VALUES (1, 'Nhom ACH', 1)")
        conn.execute("INSERT INTO group_features (group_id, feature_code) VALUES (1, 'menu.cham_ach')")
        conn.commit()
        conn.close()

        monkeypatch.setattr(migrations, 'DB_PATH', db_path)
        migrations._ensure_indexes()
        migrations._ensure_indexes()  # chạy lại — không được lỗi/trùng dòng

        conn = sqlite3.connect(db_path)
        n = conn.execute(
            "SELECT COUNT(*) FROM group_features WHERE group_id = 1 AND feature_code = 'cham_ach.process'"
        ).fetchone()[0]
        conn.close()
        assert n == 1

    def test_nhom_da_co_san_process_khong_bi_dong_gi(self, tmp_path, monkeypatch):
        """Nhóm đã tách quyền đúng từ trước (có cả 2 mã) — migration không được xoá gì."""
        db_path = str(tmp_path / 'test.db')
        conn = _fresh_db(db_path)
        conn.execute("INSERT INTO user_groups (id, name, is_active) VALUES (1, 'Nhom Chi Xem', 1)")
        conn.execute("INSERT INTO group_features (group_id, feature_code) VALUES (1, 'menu.cham_ach')")
        conn.commit()
        conn.close()

        monkeypatch.setattr(migrations, 'DB_PATH', db_path)
        migrations._ensure_indexes()

        conn = sqlite3.connect(db_path)
        codes = {r[0] for r in conn.execute(
            "SELECT feature_code FROM group_features WHERE group_id = 1"
        )}
        conn.close()
        # Cấp bù process — không xoá menu.cham_ach gốc
        assert codes == {'menu.cham_ach', 'cham_ach.process'}
