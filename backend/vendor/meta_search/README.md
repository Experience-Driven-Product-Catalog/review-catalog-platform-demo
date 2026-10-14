# meta-search 재사용 경계

원본 `meta-search/src/meta_search`의 읽기 전용 검색 모듈을 사용합니다. `UPSTREAM.json`은 각 원본 파일의 SHA-256을 기록합니다. 원본 meta-search 프로젝트는 수정하지 않습니다.

- `db.py`: 공개된 카탈로그 SQLite만 `mode=ro&immutable=1`, `query_only=ON`으로 읽습니다.
- `errors.py`: MCP ToolError를 Responses 함수 호출의 ValueError로 전달하는 경량 어댑터입니다. FastMCP 서버 프로세스를 실행하지 않습니다.
- `search/service.py`: 가이드/상품 상세의 top-aspect 요약은 기존 데모 정책에 따라 원래 표현으로 집계합니다. 나머지 검색·비교·판매·체감 로직을 보존합니다.
- `demo/tools.py`: 고정 9개 모니터 범위, 군집 전체 자동 선택 금지, 가상 판매 정보 표시, 기존 조건 카드 출력 호환 필드를 적용합니다.
- 등록·작업 관리·수집·재군집화·임베딩 코드 및 ML 의존성은 배포하지 않습니다.

재동기화는 원본 프로젝트 환경의 Python으로 `scripts/sync_meta_search.py`를 실행합니다. 서버 모듈을 import하지 않아 원본 DB/작업 상태를 변경하지 않습니다.
