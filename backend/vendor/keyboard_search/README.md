# keyboard_search 재사용 경계

사용자가 지정한 로컬 `keyboard_search` MCP의 Python 검색 모듈을 가져왔습니다. 원본 파일 SHA-256은 `UPSTREAM.json`에 있습니다. 기존 review-catalog-platform 소스는 복사하지 않았습니다.

변경점:
- `experience/repository.py`: 통합 SQLite의 읽기 전용 연결과 메타데이터 사용. 전체 파일 SHA 검증은 `demo.catalog`에서 수행.
- `engine.py`: 상세 문서를 SQLite `documents`에서 조회. 문서 키워드 검색 알고리즘은 동일.
- FastMCP 서버/stdio 프로세스는 Lambda에서 실행하지 않음. `demo/tool_schemas.json`과 `demo/tools.py`에서 기존 8개 도구를 Responses function calling으로 연결.

`policy.py`, 조건 판정·표시, 원래 속성/상태 탐색, 리뷰 집계, 점수와 증거 로직은 원본 계약을 유지합니다. 원본 리뷰/정규화 결과는 동일 MCP의 SQLite에서 가져옵니다.
