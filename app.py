"""쇼핑 리스트 앱 (Streamlit)."""

import re
import time

import streamlit as st
from streamlit.runtime.scriptrunner import get_script_run_ctx

import storage
from storage import MAX_QUANTITY, StorageError

MAX_NAME_LEN = 50
DOUBLE_SUBMIT_SEC = 1.5  # 추가 직후 이 시간 안의 빈 제출은 더블클릭으로 보고 무시

st.set_page_config(page_title="쇼핑 리스트", page_icon="🛒", layout="centered")


# ---------------------------------------------------------------------------
# 스타일 (커스텀 CSS는 여기 한 곳에만)
# ---------------------------------------------------------------------------
def inject_css() -> None:
    st.markdown(
        """
        <style>
        /* 메인 영역 폭 제한 → PC에서도 카드 앱처럼 보이게 */
        .block-container { max-width: 680px; padding-top: 2.5rem; padding-bottom: 3rem; }

        /* 요약 카드 */
        .summary { display: flex; gap: .6rem; margin: .25rem 0 .75rem; }
        .summary .card {
            flex: 1; background: #fff; border: 1px solid #e5e7eb; border-radius: 12px;
            padding: .6rem .75rem; text-align: center;
        }
        .summary .num { font-size: 1.5rem; font-weight: 700; line-height: 1.2; }
        .summary .label { font-size: .8rem; color: #6b7280; }
        .summary .card.left .num { color: #ea580c; }
        .summary .card.done .num { color: #16a34a; }

        /* 아이템 카드 배경 */
        [class*="st-key-row_"] { background: #fff; }

        /* 아이템 행: 모바일에서도 열이 세로로 쌓이지 않게 고정 */
        [class*="st-key-row_"] [data-testid="stHorizontalBlock"] {
            flex-wrap: nowrap !important; gap: .4rem !important; align-items: center;
        }
        [class*="st-key-row_"] [data-testid="stColumn"] {
            min-width: 0 !important; width: auto !important;
        }
        [class*="st-key-row_"] [data-testid="stColumn"]:nth-child(1),
        [class*="st-key-row_"] [data-testid="stColumn"]:nth-child(3),
        [class*="st-key-row_"] [data-testid="stColumn"]:nth-child(4) {
            flex: 0 0 auto !important;
        }
        [class*="st-key-row_"] [data-testid="stColumn"]:nth-child(2) {
            flex: 1 1 auto !important; overflow-wrap: anywhere;
        }
        [class*="st-key-row_"] { padding: .3rem .5rem .3rem .85rem !important; }
        /* markdown의 음수 margin 때문에 이름이 체크박스보다 아래로 처지는 것 보정 */
        [class*="st-key-row_"] [data-testid="stMarkdownContainer"],
        [class*="st-key-row_"] [data-testid="stMarkdown"] { margin-bottom: 0 !important; }
        [class*="st-key-row_"] p { margin-bottom: 0; }

        /* 입력 줄: 모바일에서도 한 줄 유지 (이름은 넓게, 수량·버튼은 좁게) */
        .st-key-add_row [data-testid="stHorizontalBlock"] { flex-wrap: nowrap !important; gap: .4rem !important; }
        .st-key-add_row [data-testid="stColumn"] { min-width: 0 !important; width: auto !important; }
        .st-key-add_row [data-testid="stColumn"]:nth-child(1) { flex: 1 1 auto !important; }
        .st-key-add_row [data-testid="stColumn"]:nth-child(2) { flex: 0 0 5.5rem !important; }
        .st-key-add_row [data-testid="stColumn"]:nth-child(3) { flex: 0 0 auto !important; }

        /* 편집 모드의 저장/취소 버튼은 모바일에서도 나란히 */
        [class*="st-key-editbtns_"] [data-testid="stHorizontalBlock"] { flex-wrap: nowrap !important; }
        [class*="st-key-editbtns_"] [data-testid="stColumn"] { min-width: 0 !important; flex: 1 1 0 !important; }

        /* 손가락으로 누르기 쉬운 크기 (버튼·체크박스 모두 40px 이상) */
        [class*="st-key-row_"] button { min-height: 2.5rem; min-width: 2.5rem; padding: 0 .4rem; }
        [class*="st-key-row_"] [data-testid="stCheckbox"] label {
            min-height: 2.5rem; min-width: 2.5rem; align-items: center; justify-content: center;
        }
        [class*="st-key-row_"] [data-testid="stCheckbox"] label > span:first-child { transform: scale(1.25); }

        /* 삭제 버튼은 눈에 덜 띄게, 마우스를 올리면 빨간색 */
        [class*="st-key-del_"] button { opacity: .55; }
        [class*="st-key-del_"] button:hover { opacity: 1; color: #dc2626; }
        </style>
        """,
        unsafe_allow_html=True,
    )


# ---------------------------------------------------------------------------
# 메시지 helpers
# ---------------------------------------------------------------------------
def flash(target: str, level: str, message: str) -> None:
    """다음 렌더링 때 target 위치에 표시할 메시지. target: 'top', 'add' 또는 아이템 id."""
    st.session_state["flash"] = {"target": target, "level": level, "message": message}


def show_flash(target: str) -> None:
    msg = st.session_state.get("flash")
    if msg and msg["target"] == target:
        getattr(st, msg["level"])(msg["message"])
        del st.session_state["flash"]


def toast(message: str, icon: str) -> None:
    """콜백 안에서 호출 → 다음 렌더링 때 st.toast로 표시."""
    st.session_state["toast"] = (message, icon)


def show_toast() -> None:
    if "toast" in st.session_state:
        message, icon = st.session_state.pop("toast")
        st.toast(message, icon=icon)


def safe_text(text: str) -> str:
    """사용자 입력을 markdown/HTML로 해석되지 않게 만든다.

    - markdown 특수문자는 백슬래시 이스케이프 (HTML 엔티티는 Streamlit에서 일부가 그대로 노출되므로 쓰지 않음)
    - URL·이메일 자동 링크는 이스케이프로 막히지 않으므로 보이지 않는 문자(U+2060)를 끼워 넣어 끊는다
    """
    text = re.sub(r"([\\`*_{}\[\]()#+\-.!|~<>&:$])", r"\\\1", text)
    text = re.sub(r"(?i)(\\:)(//)", "\\1\u2060\\2", text)  # http:// 등
    text = re.sub(r"(?i)\b(www)(\\\.)", "\\1\u2060\\2", text)  # www.
    return text.replace("@", "@\u2060")  # 이메일


def storage_failed(target: str, error: Exception) -> None:
    # 자세한 원인(파일 경로 등)은 서버 로그에만 남기고 화면에는 짧게 안내
    print(f"[storage error] {error}", flush=True)
    flash(target, "error", "저장에 실패했어요. 잠시 후 다시 시도해 주세요.")


def validate_quantity(raw, target: str) -> int | None:
    """1 ~ MAX_QUANTITY 정수만 허용. 범위 밖이면 경고를 남기고 None."""
    try:
        quantity = int(raw)
    except (TypeError, ValueError):
        quantity = 0
    if not 1 <= quantity <= MAX_QUANTITY:
        flash(target, "warning", f"수량은 1 ~ {MAX_QUANTITY} 사이로 입력해 주세요.")
        return None
    return quantity


@st.cache_resource(show_spinner=False)
def _last_add_times() -> dict[str, float]:
    """세션별 마지막 추가 시각 (프로세스 공용, 재실행 사이에도 유지).

    더블클릭으로 두 제출이 몇 ms 간격으로 오면 두 번째 요청이 첫 실행을 중단시키고,
    첫 실행에서 바꾼 st.session_state 값은 두 번째 콜백에서 보이지 않는다.
    그래서 session_state 대신 이 dict를 쓰고, 콜백 안에서는 Streamlit 호출 없이
    모듈 전역 LAST_ADD_TIMES로만 접근한다 (Streamlit 호출 지점에서 실행이 중단될 수 있음).
    """
    return {}


LAST_ADD_TIMES = _last_add_times()


def _session_id() -> str:
    ctx = get_script_run_ctx()
    return ctx.session_id if ctx else ""


# ---------------------------------------------------------------------------
# 데이터 변경 (모두 콜백에서 호출, 저장 성공 후에만 화면 상태를 바꿈)
# ---------------------------------------------------------------------------
def add_item() -> None:
    """F-01 ~ F-04"""
    name = st.session_state.get("new_name", "").strip()
    session_id = _session_id()
    if not name:
        # 추가 버튼 더블클릭 시 두 번째 (빈) 제출은 조용히 무시
        if time.monotonic() - LAST_ADD_TIMES.get(session_id, 0.0) > DOUBLE_SUBMIT_SEC:
            flash("add", "warning", "아이템 이름을 입력해 주세요.")
        return
    quantity = validate_quantity(st.session_state.get("new_qty"), "add")
    if quantity is None:
        return
    # 저장보다 먼저 기록: 두 번째 제출이 첫 콜백 도중에 끼어들어도 이미 보이도록
    LAST_ADD_TIMES[session_id] = time.monotonic()
    try:
        storage.insert_item(name, quantity)
    except StorageError as e:
        storage_failed("add", e)
        return
    toast(f"'{safe_text(name)}' 추가했어요", "✅")


def clear_edit_state(item_id: str) -> None:
    for key in (f"edit_name_{item_id}", f"edit_qty_{item_id}"):
        st.session_state.pop(key, None)


def start_edit(item_id: str, name: str, quantity: int) -> None:
    """F-09: 해당 행을 편집 모드로 전환하고 현재 값을 입력창에 채운다."""
    previous = st.session_state.get("editing_id")
    if previous:
        clear_edit_state(previous)
    st.session_state["editing_id"] = item_id
    st.session_state[f"edit_name_{item_id}"] = name
    st.session_state[f"edit_qty_{item_id}"] = quantity


def cancel_edit() -> None:
    item_id = st.session_state.get("editing_id")
    if item_id:
        clear_edit_state(item_id)
    st.session_state["editing_id"] = None


def save_edit(item_id: str) -> None:
    """F-10, F-11"""
    name = st.session_state.get(f"edit_name_{item_id}", "").strip()
    if not name:
        flash(item_id, "warning", "이름은 비워둘 수 없어요.")
        return
    quantity = validate_quantity(st.session_state.get(f"edit_qty_{item_id}"), item_id)
    if quantity is None:
        return
    try:
        updated = storage.update_item(item_id, name=name, quantity=quantity)
    except StorageError as e:
        storage_failed(item_id, e)
        return
    cancel_edit()
    if updated is None:
        flash("top", "warning", "다른 곳에서 이미 삭제된 아이템이에요.")
    else:
        toast("수정했어요", "✏️")


def delete_item(item_id: str) -> None:
    """F-12"""
    try:
        deleted = storage.delete_item(item_id)
    except StorageError as e:
        storage_failed("top", e)
        return
    if st.session_state.get("editing_id") == item_id:
        cancel_edit()
    if deleted is not None:
        toast(f"'{safe_text(deleted['name'])}' 삭제했어요", "🗑️")


def toggle_item(item_id: str) -> None:
    """F-14, F-15"""
    checked = bool(st.session_state[f"chk_{item_id}"])
    try:
        updated = storage.update_item(item_id, checked=checked)
    except StorageError as e:
        storage_failed("top", e)
        return
    if updated is None:
        flash("top", "warning", "다른 곳에서 이미 삭제된 아이템이에요.")


def clear_checked() -> None:
    """F-13"""
    try:
        removed = storage.delete_checked()
    except StorageError as e:
        storage_failed("top", e)
        return
    cancel_edit()
    toast(f"완료 항목 {removed}개 삭제했어요", "🧹")


# ---------------------------------------------------------------------------
# 화면 조각
# ---------------------------------------------------------------------------
def render_summary(total: int, done: int) -> None:
    left = total - done
    st.markdown(
        f"""
        <div class="summary">
          <div class="card"><div class="num">{total}</div><div class="label">전체</div></div>
          <div class="card left"><div class="num">{left}</div><div class="label">남은 항목</div></div>
          <div class="card done"><div class="num">{done}</div><div class="label">완료</div></div>
        </div>
        """,
        unsafe_allow_html=True,
    )
    if total:
        st.progress(done / total, text=f"진행률 {round(done / total * 100)}%")
    if total and done == total:
        st.success("🎉 장보기 완료!")


def render_add_form() -> None:
    """F-01 ~ F-04: form → Enter로 제출, 제출 후 입력창 초기화.

    수량 입력에 min/max를 걸면 범위 밖 값일 때 Streamlit이 폼 제출을 말없이 막으므로,
    범위 검사는 콜백(validate_quantity)에서 하고 경고를 보여준다.
    """
    with st.form("add_form", clear_on_submit=True, border=False):
        with st.container(key="add_row"):
            c_name, c_qty, c_btn = st.columns([4, 1, 1], vertical_alignment="bottom")
            with c_name:
                st.text_input("아이템 이름", key="new_name", max_chars=MAX_NAME_LEN,
                              placeholder="예: 우유, 계란, 사과...")
            with c_qty:
                st.number_input("수량", value=1, step=1, key="new_qty")
            with c_btn:
                st.form_submit_button("추가", on_click=add_item, type="primary",
                                      use_container_width=True)
    show_flash("add")


def render_edit_row(item: dict) -> None:
    """F-09 ~ F-11: 편집 모드 (모바일에서도 보기 좋게 두 줄 구성)."""
    item_id = item["id"]
    with st.container(border=True, key=f"edit_{item_id}_box"):
        c_name, c_qty = st.columns([4, 1.3])
        with c_name:
            st.text_input("이름 수정", key=f"edit_name_{item_id}", max_chars=MAX_NAME_LEN)
        with c_qty:
            st.number_input("수량", step=1, key=f"edit_qty_{item_id}")
        with st.container(key=f"editbtns_{item_id}"):
            c_save, c_cancel = st.columns(2)
            with c_save:
                st.button("저장", key=f"save_{item_id}", on_click=save_edit,
                          args=(item_id,), type="primary", use_container_width=True)
            with c_cancel:
                st.button("취소", key=f"cancel_{item_id}", on_click=cancel_edit,
                          use_container_width=True)
        show_flash(item_id)


def render_item_row(item: dict) -> None:
    """F-05, F-06, F-12, F-14: 체크박스 | 이름·수량 | ✏️ | 🗑️"""
    item_id = item["id"]
    if st.session_state["editing_id"] == item_id:
        render_edit_row(item)
        return

    name = safe_text(item["name"])
    # 다른 탭/기기에서 바뀐 체크 상태를 반영 (위젯 생성 전에 상태를 맞춤)
    st.session_state[f"chk_{item_id}"] = item["checked"]

    with st.container(border=True, key=f"row_{item_id}"):
        c_chk, c_name, c_edit, c_del = st.columns(
            [0.6, 6, 0.8, 0.8], vertical_alignment="center", gap="small"
        )
        with c_chk:
            # 라벨은 숨김 처리되고 스크린리더는 input의 aria-label(=이 문자열 그대로)을 읽으므로
            # 이스케이프하지 않은 원래 이름을 쓴다. (이스케이프하면 "\." 같은 백슬래시를 읽음)
            st.checkbox(
                f"{item['name']} 완료",
                key=f"chk_{item_id}",
                on_change=toggle_item,
                args=(item_id,),
                label_visibility="collapsed",
            )
        with c_name:
            qty = f":gray[×{item['quantity']}]"
            if item["checked"]:
                st.markdown(f":gray[~~{name}~~] {qty}")
            else:
                st.markdown(f"**{name}** {qty}")
        with c_edit:
            st.button("✏️", key=f"edit_{item_id}", on_click=start_edit,
                      args=(item_id, item["name"], item["quantity"]),
                      type="tertiary", help="수정")
        with c_del:
            st.button("🗑️", key=f"del_{item_id}", on_click=delete_item,
                      args=(item_id,), type="tertiary", help="삭제")


# ---------------------------------------------------------------------------
# 데이터 불러오기: 매 실행마다 파일에서 새로 읽어 다른 탭/기기의 변경을 반영
# ---------------------------------------------------------------------------
st.session_state.setdefault("editing_id", None)
try:
    items, load_warnings = storage.load_items()
except StorageError as e:
    print(f"[storage error] {e}", flush=True)
    items, load_warnings = [], []
    flash("top", "error", "데이터를 불러오지 못했어요. 잠시 후 새로고침해 주세요.")

# 편집 중이던 아이템이 다른 곳에서 삭제됐으면 편집 모드 해제
if st.session_state["editing_id"] and all(it["id"] != st.session_state["editing_id"] for it in items):
    cancel_edit()
    flash("top", "warning", "다른 곳에서 이미 삭제된 아이템이에요.")

active = [it for it in items if not it["checked"]]
completed = [it for it in items if it["checked"]]

# ---------------------------------------------------------------------------
# 화면
# ---------------------------------------------------------------------------
inject_css()
show_toast()

st.title("🛒 쇼핑 리스트")
for message in load_warnings:
    st.warning(message)
show_flash("top")
render_summary(len(items), len(completed))
render_add_form()

st.write("")

if not items:
    st.info("쇼핑 리스트가 비어 있어요. 위에서 아이템을 추가해 보세요.")
else:
    # 미완료 항목 먼저
    if active:
        for item in active:
            render_item_row(item)
    else:
        st.caption("남은 항목이 없어요.")

    # 완료 항목은 아래 별도 섹션 (F-06)
    if completed:
        with st.expander(f"완료된 항목 ({len(completed)})", expanded=True):
            for item in completed:
                render_item_row(item)

    # 일괄 삭제는 하단 (F-13)
    st.button(
        f"🧹 완료 항목 모두 삭제 ({len(completed)})",
        key="clear_checked",
        on_click=clear_checked,
        disabled=not completed,
        use_container_width=True,
    )
