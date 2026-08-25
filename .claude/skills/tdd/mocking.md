# When to Mock

Mock at **system boundaries** only:

- External APIs (email, SMS, dịch vụ ngoài, ...)
- Databases (đôi khi — ưu tiên DB test/tmp thật hơn mock)
- Time/randomness
- File system (đôi khi)

Don't mock:

- Module/hàm nội bộ của chính dự án
- Internal collaborators
- Anything you control

> **Ngoại lệ của dự án này — module đối chiếu tài chính (`doi-chieu` skill):** với I/O đọc file
> nguồn (CSV/xlsx/zip) của các module ACH, ILO1000, 459901, Đối chiếu Song phương — **không mock**,
> kể cả khi nó là "boundary". Dùng file thu nhỏ thật (tổng hợp nhỏ, đúng format thật). Mock I/O ở
> đây từng che giấu lỗi format thật (xem `feedback_check_data_loading_before_algorithm`). Quy tắc
> "mock ở boundary" bên dưới áp dụng cho phần còn lại của codebase, không áp dụng cho nhóm module này.

## Designing for Mockability

At system boundaries, design interfaces that are easy to mock:

**1. Use dependency injection**

Pass external dependencies in rather than creating them internally:

```python
# Easy to mock — DB session truyền vào qua tham số/dependency
def get_active_staff(db: Session):
    return db.query(UserTTTT).filter(UserTTTT.is_active == True).all()

# Hard to mock — tự tạo session bên trong hàm
def get_active_staff():
    db = SessionLocal()
    return db.query(UserTTTT).filter(UserTTTT.is_active == True).all()
```

`admin_client` trong `tests/conftest.py` áp dụng đúng nguyên tắc này: override `get_db`/`get_current_staff`
qua FastAPI dependency injection, không patch thẳng vào module.

**2. Prefer SDK-style interfaces over generic fetchers**

Create specific functions for each external operation instead of one generic function with conditional logic:

```python
# GOOD: Each function is independently mockable
class PaymentGatewayClient:
    def get_status(self, ref: str) -> dict: ...
    def submit(self, payload: dict) -> dict: ...

# BAD: Mocking requires conditional logic inside the mock
class GenericClient:
    def call(self, endpoint: str, method: str, payload: dict | None = None) -> dict: ...
```

The SDK approach means:
- Each mock returns one specific shape
- No conditional logic in test setup
- Easier to see which endpoints a test exercises
- Type hints per endpoint, not per generic payload
