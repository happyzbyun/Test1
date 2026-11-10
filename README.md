# 🛒 쇼핑 리스트

아이템 추가 · 수정 · 삭제 · 체크 기능이 있는 간단한 Streamlit 쇼핑 리스트 앱입니다.
자세한 요구사항은 [PRD.md](PRD.md)를 참고하세요.

## 설치

```bash
python -m venv .venv
# Windows
.venv\Scripts\activate
# macOS / Linux
source .venv/bin/activate

pip install -r requirements.txt
```

## 실행

```bash
streamlit run app.py
```

브라우저에서 http://localhost:8501 로 접속합니다.

## 데이터 저장

아이템은 프로젝트 폴더의 `data.json`에 저장됩니다 (git에는 포함되지 않음).
여러 탭이나 기기에서 동시에 써도 서로의 변경을 덮어쓰지 않습니다.

- 아이템 이름은 최대 50자, 수량은 1 ~ 999까지 입력할 수 있습니다.
- `data.json`이 손상되면 원본을 `data.json.corrupt-<날짜시각>`으로 옮겨 보관하고 빈 리스트로 시작합니다.
- 읽을 수 없는 아이템이 섞여 있으면 원본을 `data.json.invalid-<날짜시각>`에 백업한 뒤 해당 아이템만 건너뜁니다.
- 두 경우 모두 앱 화면에 경고가 표시됩니다. 백업 파일도 git에는 포함되지 않습니다.

> Streamlit Community Cloud에 배포하면 앱 재시작·재배포 시 데이터가 초기화됩니다.
> (클라우드 DB 연동은 [PRD.md](PRD.md) 4.6장 참고 — 현재 보류 중)
