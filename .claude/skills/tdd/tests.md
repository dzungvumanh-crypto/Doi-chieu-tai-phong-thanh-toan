# Good and Bad Tests

## Good Tests

**Integration-style**: Test through real interfaces, not mocks of internal parts.

```python
# GOOD: Tests observable behavior, through the public function
def test_gd02_khop_khi_so_tien_va_msgref_trung():
    df_mis = pd.DataFrame({"MSGREF": ["M1"], "SO_TIEN": [1_000_000]})
    df_gw = pd.DataFrame({"MSGREF": ["M1"], "SO_TIEN": [1_000_000]})
    result = khop_voi_gw(df_mis, df_gw)
    assert result.loc[0, "TRANG_THAI"] == "Đã khớp"
```

Characteristics:

- Tests behavior callers care about (input DataFrame in → classified DataFrame out)
- Uses public function only, no reaching into private helpers
- Survives internal refactors
- Describes WHAT (nghiệp vụ được kiểm tra), not HOW
- One logical assertion per test

## Bad Tests

**Implementation-detail tests**: Coupled to internal structure.

```python
# BAD: Asserts on an internal helper call instead of the observable result
def test_khop_voi_gw_calls_internal_merge(monkeypatch):
    called = {}
    monkeypatch.setattr(pipeline, "_merge_by_msgref", lambda *a: called.setdefault("hit", True))
    khop_voi_gw(df_mis, df_gw)
    assert called["hit"]
```

Red flags:

- Mocking internal collaborators (ở đây: mock thẳng hàm nội bộ `_merge_by_msgref`)
- Testing private methods (tên bắt đầu bằng `_`)
- Asserting on call counts/order thay vì kết quả
- Test breaks when refactoring without behavior change
- Test name describes HOW not WHAT
- Verifying through external means instead of the interface

```python
# BAD: Bypasses interface to verify — đọc thẳng DB thay vì gọi lại qua API
def test_process_creates_batch(admin_client):
    admin_client.post("/api/ilo1000/process", json={"batch_id": "B1"})
    row = db.execute("SELECT * FROM ilo1000_batch WHERE id = 'B1'").fetchone()
    assert row is not None

# GOOD: Verifies through the interface the caller actually uses
def test_process_creates_batch(admin_client):
    admin_client.post("/api/ilo1000/process", json={"batch_id": "B1"})
    resp = admin_client.get("/api/ilo1000/batch/B1")
    assert resp.status_code == 200
```

**Tautological tests**: Expected value restates the implementation, so the test passes by construction.

```python
# BAD: Expected value is recomputed the way the code computes it
def test_tong_no_bang_tong_co():
    rows = [{"no": 10, "co": 0}, {"no": 0, "co": 10}]
    expected = sum(r["no"] for r in rows)  # tính lại y hệt logic bên trong
    assert tinh_tong_no(rows) == expected

# GOOD: Expected value is an independent, known literal from a worked example
def test_tong_no_bang_tong_co():
    rows = [{"no": 10, "co": 0}, {"no": 0, "co": 10}]
    assert tinh_tong_no(rows) == 10
```
