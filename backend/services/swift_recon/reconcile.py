# -*- coding: utf-8 -*-
"""
reconcile.py
------------
Logic đối chiếu thuần (không phụ thuộc Tkinter / openpyxl) để dễ test độc lập.

Khái niệm:
- "side_a" / "side_b": 2 DataFrame đã được parsers.py chuẩn hoá, đều có cột
  _key, _msg_type, _time, _source, _direction.
- match(): ghép các bản ghi có cùng _key giữa 2 bên theo nguyên tắc 1-1
  (nếu 1 khoá xuất hiện nhiều lần ở 1 bên, ghép theo thứ tự xuất hiện, dư ra
  thì coi là lệch / không khớp).
"""
from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from typing import List

import pandas as pd


@dataclass
class MatchResult:
    matched_pairs: List[tuple]       # list of (idx_a, idx_b)
    only_a: List[int]                # index (trong df_a) chỉ có ở A
    only_b: List[int]                # index (trong df_b) chỉ có ở B


def match_by_key(df_a: pd.DataFrame, df_b: pd.DataFrame) -> MatchResult:
    """Ghép cặp theo cột _key. df_a / df_b phải có cột '_key'."""
    bucket_b = defaultdict(list)
    for idx, key in df_b["_key"].items():
        bucket_b[key].append(idx)

    matched_pairs = []
    only_a = []
    used_b = set()

    for idx, key in df_a["_key"].items():
        candidates = bucket_b.get(key, [])
        # lấy candidate đầu tiên chưa dùng
        pos = None
        for i, cand_idx in enumerate(candidates):
            if cand_idx not in used_b:
                pos = i
                break
        if pos is None:
            only_a.append(idx)
        else:
            b_idx = candidates[pos]
            used_b.add(b_idx)
            matched_pairs.append((idx, b_idx))

    only_b = [idx for idx in df_b.index if idx not in used_b]

    return MatchResult(matched_pairs=matched_pairs, only_a=only_a, only_b=only_b)


def _ack_ok(ack_check: dict, ra, rb) -> bool:
    """Kiểm tra 1 cặp bản ghi đã khớp khoá có đang ở trạng thái "Ack" hay
    không, dựa vào field + danh sách giá trị coi là OK ở MỖI bên (2 field
    này được người dùng xác nhận là cùng đề cập đến trạng thái Ack, nên chỉ
    cần 1 trong 2 bên báo Ack là coi như OK)."""
    a_field = ack_check.get("a_field")
    b_field = ack_check.get("b_field")
    a_ok_values = {v.strip().lower() for v in ack_check.get("a_ok_values", set())}
    b_ok_values = {v.strip().lower() for v in ack_check.get("b_ok_values", set())}
    a_val = str(ra.get(a_field, "")).strip().lower() if a_field else ""
    b_val = str(rb.get(b_field, "")).strip().lower() if b_field else ""
    return (a_val in a_ok_values) or (b_val in b_ok_values)


def build_merged_view(
    df_a: pd.DataFrame,
    df_b: pd.DataFrame,
    label_a: str,
    label_b: str,
    ack_check: dict | None = None,
) -> pd.DataFrame:
    """Tạo 1 DataFrame "view" để hiển thị lên giao diện / Treeview:
    - Các bản ghi khớp (matched) hiển thị 1 dòng, có dữ liệu cả 2 bên.
    - Các bản ghi không khớp hiển thị riêng, dữ liệu bên kia để trống.
    - matched luôn được xếp lên TRÊN CÙNG (đúng yêu cầu), unmatched xếp dưới.

    ack_check (tuỳ chọn, dùng riêng cho ĐIỆN ĐI): dict dạng
        {"a_field": "ACK/NAK", "a_ok_values": {"ACK"},
         "b_field": "Netw. Status", "b_ok_values": {"Network Ack"}}
    Nếu được truyền vào: với các bản ghi ĐÃ KHỚP KHOÁ ở cả 2 hệ thống, vẫn
    kiểm tra thêm trạng thái Ack. Nếu KHÔNG bên nào báo Ack (ví dụ NAK, lỗi,
    hoặc chưa có trạng thái), bản ghi đó sẽ bị tính là CHÊNH LỆCH (status
    "MATCHED_NOT_ACK") để giao dịch viên kiểm tra thủ công lại tình trạng
    thực tế của điện, dù khoá đối chiếu đã khớp.

    Cột trả về:
        _key, _msg_type, _direction, _matched (bool), _status
            ("MATCHED" / "MATCHED_NOT_ACK" / "ONLY_A" / "ONLY_B"),
        _key_a, _key_b       : khoá đối chiếu RIÊNG của mỗi bên (chỉ có giá
                                trị khi bên đó thực sự có bản ghi, để khi
                                hiển thị không bị hiểu nhầm là "có ở 2 bên")
        _msgtype_a, _msgtype_b : loại điện RIÊNG của mỗi bên (cùng lý do)
        _time_a, _time_b, _time (effective = a nếu có, else b)
        a__<cột gốc...>  (toàn bộ cột gốc của df_a, tiền tố theo label_a)
        b__<cột gốc...>  (toàn bộ cột gốc của df_b, tiền tố theo label_b)
    """
    mr = match_by_key(df_a, df_b)

    cols_a = [c for c in df_a.columns if not c.startswith("_")]
    cols_b = [c for c in df_b.columns if not c.startswith("_")]

    rows = []

    def empty_a():
        return {f"{label_a}__{c}": "" for c in cols_a}

    def empty_b():
        return {f"{label_b}__{c}": "" for c in cols_b}

    def row_a(idx):
        r = df_a.loc[idx]
        return {f"{label_a}__{c}": r[c] for c in cols_a}

    def row_b(idx):
        r = df_b.loc[idx]
        return {f"{label_b}__{c}": r[c] for c in cols_b}

    direction = None
    if len(df_a) > 0:
        direction = df_a["_direction"].iloc[0]
    elif len(df_b) > 0:
        direction = df_b["_direction"].iloc[0]

    # 1) matched lên trước
    for idx_a, idx_b in mr.matched_pairs:
        ra = df_a.loc[idx_a]
        rb = df_b.loc[idx_b]

        is_ack_ok = _ack_ok(ack_check, ra, rb) if ack_check else True
        rec = {
            "_key": ra["_key"],
            "_msg_type": ra["_msg_type"] or rb["_msg_type"],
            "_direction": direction,
            "_matched": is_ack_ok,
            "_status": "MATCHED" if is_ack_ok else "MATCHED_NOT_ACK",
            "_key_a": ra["_key"],
            "_key_b": rb["_key"],
            "_msgtype_a": ra["_msg_type"],
            "_msgtype_b": rb["_msg_type"],
            "_time_a": ra["_time"],
            "_time_b": rb["_time"],
        }
        rec["_time"] = ra["_time"] or rb["_time"]
        rec.update(row_a(idx_a))
        rec.update(row_b(idx_b))
        rows.append(rec)

    # 2) chỉ có ở A
    for idx_a in mr.only_a:
        ra = df_a.loc[idx_a]
        rec = {
            "_key": ra["_key"],
            "_msg_type": ra["_msg_type"],
            "_direction": direction,
            "_matched": False,
            "_status": "ONLY_A",
            "_key_a": ra["_key"],
            "_key_b": "",
            "_msgtype_a": ra["_msg_type"],
            "_msgtype_b": "",
            "_time_a": ra["_time"],
            "_time_b": None,
            "_time": ra["_time"],
        }
        rec.update(row_a(idx_a))
        rec.update(empty_b())
        rows.append(rec)

    # 3) chỉ có ở B
    for idx_b in mr.only_b:
        rb = df_b.loc[idx_b]
        rec = {
            "_key": rb["_key"],
            "_msg_type": rb["_msg_type"],
            "_direction": direction,
            "_matched": False,
            "_status": "ONLY_B",
            "_key_a": "",
            "_key_b": rb["_key"],
            "_msgtype_a": "",
            "_msgtype_b": rb["_msg_type"],
            "_time_a": None,
            "_time_b": rb["_time"],
            "_time": rb["_time"],
        }
        rec.update(empty_a())
        rec.update(row_b(idx_b))
        rows.append(rec)

    if not rows:
        cols = ["_key", "_msg_type", "_direction", "_matched", "_status",
                 "_key_a", "_key_b", "_msgtype_a", "_msgtype_b",
                 "_time_a", "_time_b", "_time"]
        cols += [f"{label_a}__{c}" for c in cols_a] + [f"{label_b}__{c}" for c in cols_b]
        return pd.DataFrame(columns=cols)

    out = pd.DataFrame(rows)
    # matched (True) lên trước -> sort theo _matched giảm dần, giữ nguyên thứ tự bên trong
    out["_sort_matched"] = out["_matched"].apply(lambda x: 0 if x else 1)
    out = out.sort_values(by=["_sort_matched"], kind="stable").drop(columns=["_sort_matched"])
    out = out.reset_index(drop=True)
    return out


def summarize_counts(df_a: pd.DataFrame, df_b: pd.DataFrame, label_a: str, label_b: str) -> pd.DataFrame:
    """Tổng hợp số lượng điện theo từng loại điện (_msg_type) ở 2 hệ thống."""
    count_a = df_a.groupby("_msg_type").size().rename(label_a)
    count_b = df_b.groupby("_msg_type").size().rename(label_b)
    merged = pd.concat([count_a, count_b], axis=1).fillna(0).astype(int)
    merged = merged.reset_index().rename(columns={"_msg_type": "Loại điện"})
    merged["Chênh lệch"] = merged[label_a] - merged[label_b]
    merged = merged.sort_values(by="Loại điện").reset_index(drop=True)

    total_row = {
        "Loại điện": "TỔNG",
        label_a: int(merged[label_a].sum()),
        label_b: int(merged[label_b].sum()),
        "Chênh lệch": int(merged["Chênh lệch"].sum()),
    }
    merged = pd.concat([merged, pd.DataFrame([total_row])], ignore_index=True)
    return merged


def extract_matched_not_ack(merged_df: pd.DataFrame, label_a: str, label_b: str) -> pd.DataFrame:
    """Lấy ra các bản ghi đã khớp khoá nhưng KHÔNG bên nào báo trạng thái Ack
    (status == "MATCHED_NOT_ACK") từ kết quả build_merged_view, giữ đầy đủ
    cột gốc của cả 2 bên (đổi tên "A__cot" -> "[A] cot" cho dễ đọc) để xuất
    Excel cho giao dịch viên tra cứu / điều tra thủ công."""
    if merged_df is None or "_status" not in merged_df.columns:
        return pd.DataFrame()
    sub = merged_df[merged_df["_status"] == "MATCHED_NOT_ACK"].copy()
    if sub.empty:
        return sub
    raw_cols = [c for c in sub.columns if not c.startswith("_")]
    sub = sub[raw_cols]
    sub.columns = [f"[{c.split('__', 1)[0]}] {c.split('__', 1)[1]}" if "__" in c else c for c in sub.columns]
    return sub.reset_index(drop=True)


def diff_only_a(df_a: pd.DataFrame, df_b: pd.DataFrame) -> pd.DataFrame:
    """Trả về các bản ghi gốc (đầy đủ cột) của df_a không có ở df_b (theo _key)."""
    mr = match_by_key(df_a, df_b)
    cols = [c for c in df_a.columns if not c.startswith("_")]
    return df_a.loc[mr.only_a, cols].reset_index(drop=True)


def diff_only_b(df_a: pd.DataFrame, df_b: pd.DataFrame) -> pd.DataFrame:
    """Trả về các bản ghi gốc (đầy đủ cột) của df_b không có ở df_a (theo _key)."""
    mr = match_by_key(df_a, df_b)
    cols = [c for c in df_b.columns if not c.startswith("_")]
    return df_b.loc[mr.only_b, cols].reset_index(drop=True)
