"""Test tiêu chí xoá backup cũ (đổi 18/08/2026).

Luật cũ: `sorted(glob("ksnb_*.db"))[:-7]` — sắp theo TÊN và vơ cả file người
đặt tay. Ba hậu quả được khoá lại ở đây.

Chạy: .venv/Scripts/python.exe -m pytest tests/test_backup_rotation.py -v
"""

import pytest

from backend.services import backup_service as bs


def _tao(thu_muc, *ten):
    for t in ten:
        (thu_muc / t).write_bytes(b"gia-lap-file-db")


def _con_lai(thu_muc):
    return sorted(p.name for p in thu_muc.glob("*.db"))


class TestKhongDungFileNguoiDatTay:
    """Bản đặt tay trước khi làm việc nguy hiểm là thứ CẦN nhất khi có sự cố —
    và là thứ duy nhất không tự tạo lại được."""

    def test_giu_nguyen_ban_dat_tay_du_rat_cu(self, tmp_path):
        _tao(tmp_path,
             "ksnb_truoc_nhomA_20260728.db",
             "ksnb_before_cleanup_537_20260720_134609.db")
        # thêm thật nhiều bản tự sinh mới hơn để ép rotate phải xoá
        _tao(tmp_path, *[f"ksnb_2026{8:02d}{ngay:02d}_1000.db" for ngay in range(1, 26)])
        bs._rotate(tmp_path)
        con = _con_lai(tmp_path)
        assert "ksnb_truoc_nhomA_20260728.db" in con
        assert "ksnb_before_cleanup_537_20260720_134609.db" in con

    def test_khong_dung_file_khac_duoi_db(self, tmp_path):
        _tao(tmp_path, "ghi_chu.db", "ksnb.db")
        bs._rotate(tmp_path)
        assert set(_con_lai(tmp_path)) == {"ghi_chu.db", "ksnb.db"}


class TestKhoiDongLaiNhieuLanKhongCuonTroiLichSu:
    """Kịch bản thật: run.py tự khởi động lại tới 5 lần khi gặp sự cố, mỗi lần
    start_scheduler() backup ngay. Luật cũ (giữ 7 file mới nhất) làm cả tuần
    lịch sử bị thay bằng 5 bản chụp cách nhau vài giây."""

    def test_lich_su_bay_ngay_van_con(self, tmp_path):
        # 7 ngày trước đó, mỗi ngày 1 bản
        _tao(tmp_path, *[f"ksnb_202608{ngay:02d}_0900.db" for ngay in range(11, 18)])
        # hôm nay khởi động lại 6 lần trong vài phút
        _tao(tmp_path, *[f"ksnb_20260818_09{phut:02d}.db" for phut in (1, 2, 3, 4, 5, 6)])

        bs._rotate(tmp_path)
        con = _con_lai(tmp_path)

        # Mỗi ngày cũ vẫn còn đúng bản của ngày đó
        for ngay in range(12, 18):
            assert f"ksnb_202608{ngay:02d}_0900.db" in con, f"mất lịch sử ngày {ngay}"
        # Bản chụp mới nhất hôm nay chắc chắn còn
        assert "ksnb_20260818_0906.db" in con

    def test_mot_ngay_nhieu_ban_thi_ban_cu_trong_ngay_bi_don(self, tmp_path):
        """Không giữ vô hạn: bản cũ TRONG NGÀY vượt quá _GIU_GAN_NHAT thì dọn."""
        _tao(tmp_path, *[f"ksnb_20260818_09{phut:02d}.db" for phut in range(1, 21)])
        bs._rotate(tmp_path)
        con = _con_lai(tmp_path)
        assert len(con) == bs._GIU_GAN_NHAT
        assert "ksnb_20260818_0920.db" in con
        assert "ksnb_20260818_0901.db" not in con


class TestGiuDungSoNgay:

    def test_qua_han_ngay_thi_xoa(self, tmp_path):
        # 20 ngày liên tiếp, mỗi ngày 1 bản
        _tao(tmp_path, *[f"ksnb_202608{ngay:02d}_0900.db" for ngay in range(1, 21)])
        bs._rotate(tmp_path)
        con = _con_lai(tmp_path)
        # _GIU_NGAY và _GIU_GAN_NHAT chồng lên nhau khi mỗi ngày chỉ 1 bản
        assert len(con) == max(bs._GIU_NGAY, bs._GIU_GAN_NHAT)
        assert "ksnb_20260820_0900.db" in con      # mới nhất
        assert "ksnb_20260801_0900.db" not in con  # cũ nhất

    def test_thu_muc_rong_khong_no(self, tmp_path):
        bs._rotate(tmp_path)          # không được ném lỗi
        assert _con_lai(tmp_path) == []


class TestBaoDungNgayChoManHinhAdmin:
    """Trước bản vá, `sorted()[-1]` trả bản đặt tay (`'t' > '2'`) nên Admin báo
    'Backup gần nhất: 28/07' trong khi vừa có bản của hôm nay — người vận hành
    tưởng backup đã chết ba tuần."""

    @pytest.fixture
    def thu_muc(self, tmp_path, monkeypatch):
        monkeypatch.setattr(bs, "_BACKUP_DIR", tmp_path)
        return tmp_path

    def test_lay_dung_ban_moi_nhat(self, thu_muc):
        _tao(thu_muc,
             "ksnb_20260814_1529.db",
             "ksnb_20260818_0917.db",
             "ksnb_truoc_nhomA_20260728.db")
        tt = bs.last_backup_info()
        assert tt["exists"] is True
        assert tt["time"] == "09:17 18/08/2026"
        assert tt["count"] == 2            # chỉ đếm bản tự động
        assert tt["count_thu_cong"] == 1

    def test_chi_co_ban_dat_tay_thi_bao_chua_co_backup_tu_dong(self, thu_muc):
        _tao(thu_muc, "ksnb_truoc_nhomA_20260728.db")
        tt = bs.last_backup_info()
        assert tt["exists"] is False
        assert tt["count_thu_cong"] == 1

    def test_thu_muc_chua_ton_tai(self, tmp_path, monkeypatch):
        monkeypatch.setattr(bs, "_BACKUP_DIR", tmp_path / "chua-co")
        assert bs.last_backup_info()["exists"] is False
