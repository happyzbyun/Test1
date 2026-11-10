"""쇼핑 리스트 데이터 저장/불러오기 (data.json).

모든 변경은 행(아이템) 단위로 처리한다: 잠금 → 파일을 새로 읽음 → 해당 변경만 적용 → 원자적 저장.
이렇게 해야 여러 탭/기기가 동시에 써도 서로의 변경을 덮어쓰지 않는다.
"""

import json
import os
import shutil
import tempfile
import threading
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path

DATA_FILE = Path(__file__).parent / "data.json"
MAX_QUANTITY = 999

# Streamlit은 한 프로세스에서 세션마다 스레드를 쓰므로 프로세스 내 잠금으로 충분하다.
_lock = threading.RLock()
# 쓰기 도중 발견한 파일 문제도 다음 load_items() 때 화면에 보여주기 위해 모아 둔다.
_pending_warnings: list[str] = []


class StorageError(Exception):
    """저장소 읽기/쓰기 실패."""


# ---------------------------------------------------------------------------
# 내부 helpers
# ---------------------------------------------------------------------------
def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _backup_path(reason: str) -> Path:
    """data.json.<reason>-<시각> 형식의 겹치지 않는 백업 경로 (같은 초에 여러 번 생겨도 덮어쓰지 않음)."""
    base = f"{DATA_FILE.name}.{reason}-{datetime.now().strftime('%Y%m%d-%H%M%S')}"
    path, n = DATA_FILE.with_name(base), 1
    while path.exists():
        path = DATA_FILE.with_name(f"{base}-{n}")
        n += 1
    return path


def _backup(reason: str) -> Path:
    """현재 data.json을 백업 경로로 복사해 둔다."""
    backup = _backup_path(reason)
    shutil.copy2(DATA_FILE, backup)
    return backup


def normalize_item(raw) -> dict | None:
    """저장된 아이템 하나를 검증·정규화한다. 쓸 수 없으면 None."""
    if not isinstance(raw, dict):
        return None
    item_id = raw.get("id")
    name = raw.get("name")
    if not isinstance(item_id, str) or not item_id.strip():
        return None
    if not isinstance(name, str) or not name.strip():
        return None
    try:
        quantity = int(raw.get("quantity", 1))
    except (TypeError, ValueError):
        quantity = 1
    checked = raw.get("checked", False)
    created_at = raw.get("created_at")
    return {
        "id": item_id,
        "name": name.strip(),
        "quantity": min(max(quantity, 1), MAX_QUANTITY),
        "checked": checked if isinstance(checked, bool) else str(checked).lower() == "true",
        "created_at": created_at if isinstance(created_at, str) else _now_iso(),
    }


def _write(items: list[dict]) -> None:
    """임시 파일에 쓴 뒤 교체하는 원자적 쓰기. 도중에 실패해도 기존 파일은 손상되지 않는다."""
    fd, tmp = tempfile.mkstemp(dir=DATA_FILE.parent, prefix=".data-", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(items, f, ensure_ascii=False, indent=2)
            f.flush()
            os.fsync(f.fileno())
        # Windows에서는 다른 스레드가 파일을 읽는 순간 교체가 잠깐 실패할 수 있어 재시도한다.
        for attempt in range(5):
            try:
                os.replace(tmp, DATA_FILE)
                return
            except PermissionError:
                if attempt == 4:
                    raise
                time.sleep(0.05)
    except OSError as e:
        raise StorageError(f"data.json 저장 실패: {e}") from e
    finally:
        if os.path.exists(tmp):
            os.remove(tmp)


def _read() -> list[dict]:
    """파일을 읽어 정규화한다. 문제가 있으면 원본을 백업하고 _pending_warnings에 사유를 남긴다."""
    warnings = _pending_warnings
    if not DATA_FILE.exists():
        return []
    try:
        with DATA_FILE.open(encoding="utf-8") as f:
            data = json.load(f)
    except (json.JSONDecodeError, UnicodeDecodeError):
        # 손상된 파일은 덮어쓰기 전에 다른 이름으로 옮겨 원본을 보존한다.
        backup = _backup_path("corrupt")
        os.replace(DATA_FILE, backup)
        warnings.append(
            f"저장 파일이 손상되어 빈 리스트로 시작해요. 원본은 `{backup.name}`에 보관했어요."
        )
        return []
    except OSError as e:
        raise StorageError(f"data.json 읽기 실패: {e}") from e

    if not isinstance(data, list):
        backup = _backup("invalid")
        _write([])
        warnings.append(
            f"저장 파일 형식이 올바르지 않아 빈 리스트로 시작해요. 원본은 `{backup.name}`에 보관했어요."
        )
        return []

    items, seen = [], set()
    for raw in data:
        item = normalize_item(raw)
        if item is None or item["id"] in seen:
            continue
        seen.add(item["id"])
        items.append(item)

    if items != data:
        # 잘못된 항목이 있었다면 원본을 백업하고 정리된 내용으로 한 번만 다시 저장한다.
        skipped = len(data) - len(items)
        backup = _backup("invalid")
        _write(items)
        if skipped:
            warnings.append(
                f"읽을 수 없는 아이템 {skipped}개를 건너뛰었어요. 원본은 `{backup.name}`에 보관했어요."
            )
    return items


# ---------------------------------------------------------------------------
# 공개 인터페이스
# ---------------------------------------------------------------------------
def load_items() -> tuple[list[dict], list[str]]:
    """(아이템 목록, 사용자에게 보여줄 경고 목록)을 반환한다."""
    with _lock:
        items = _read()
        warnings = _pending_warnings.copy()
        _pending_warnings.clear()
        return items, warnings


def insert_item(name: str, quantity: int) -> dict:
    item = {
        "id": uuid.uuid4().hex,
        "name": name,
        "quantity": quantity,
        "checked": False,
        "created_at": _now_iso(),
    }
    with _lock:
        items = _read()
        items.append(item)
        _write(items)
    return item


def update_item(item_id: str, **fields) -> dict | None:
    """name / quantity / checked 중 주어진 필드만 바꾼다. 아이템이 없으면 None."""
    allowed = {k: v for k, v in fields.items() if k in ("name", "quantity", "checked")}
    with _lock:
        items = _read()
        for item in items:
            if item["id"] == item_id:
                item.update(allowed)
                _write(items)
                return item
    return None


def delete_item(item_id: str) -> dict | None:
    """삭제한 아이템을 반환한다. 이미 없으면 None."""
    with _lock:
        items = _read()
        target = next((it for it in items if it["id"] == item_id), None)
        if target is not None:
            _write([it for it in items if it["id"] != item_id])
        return target


def delete_checked() -> int:
    """체크된 아이템을 모두 삭제하고 삭제 개수를 반환한다."""
    with _lock:
        items = _read()
        remaining = [it for it in items if not it["checked"]]
        removed = len(items) - len(remaining)
        if removed:
            _write(remaining)
        return removed
