# 배포 및 검증 기록

검증일: 2026-10-11 (Asia/Seoul)

## 배포

- GitHub Pages: https://experience-driven-product-catalog.github.io/review-catalog-platform-demo/
- API Gateway: https://mbtxcknt19.execute-api.ap-northeast-2.amazonaws.com/prod
- `review-catalog-platform-demo-report`, `review-catalog-platform-demo-chat`: Python 3.12, 512MB, 최대 300초
- `review-catalog-platform-demo` / `review-catalog-platform-demo-storage`: CloudFormation 배포 완료
- S3 카탈로그 SHA-256: `b630d444743d6a107a0ec976363f187025e2445ed63d98c610f3a8e394bd746e`
- 카탈로그: keyboard_search SQLite 원본, 9개 상품 / 1,609개 리뷰 / 4,828개 Opinion Units

## 확인한 결과

- Python 테스트 10개 통과: 읽기 전용 연결, Exact-match, 미상/혼합 감성, Wilson 구간, 보고서 비저장, 도구 조회, 세션 서명/만료, 이전 응답 연결, 추출 원문 검증, 입력 제한.
- TypeScript 및 Vite 프로덕션 빌드 성공, Python Ruff 검사 통과.
- 기존 MCP와 객관 필터·0건·속성 탐색·상품 비교·상세·문서 검색 대표 7건의 출력 일치. 상세 문서의 로컬 경로만 식별용 파일명으로 바뀜.
- 실제 OpenAI API와 배포된 AWS에서 Luna high 리뷰 추출 및 보고서, Sol medium 2턴 채팅 성공. `scripts/smoke.py --live` 통과.
- 공개 브라우저에서 ‘빛샘 없음’ 리뷰 검색: 일치 상품 6개, 원래 상태 ‘거의 없음’을 기타로 구분하고 상반 리뷰 수·원문 표시.
- 이어서 ‘앞선 조건 유지 + 27형’: 빛샘 조건을 유지한 상품 2개 및 적용 조건 표시.
- 새 대화 확인 후 화면 메시지 0개·조건 0개, localStorage/sessionStorage 빈 상태 확인.
- 새 대화에서 ‘100형 이상, 조건 완화 금지’: 이전 빛샘 조건 없이 검색하여 0건과 명시적인 무결과 안내 확인.
- 390px 모바일에서 가로 페이지 넘침 없음. 데스크톱·모바일의 입력/응답/초기화 UI 확인.
- Frontend 빌드 산출물에 실제 API 키가 포함되지 않음을 확인. `.env`, `deployment.json`, `.build`, Frontend 로컬 환경 파일은 Git 제외.

실제 모델 출력은 비결정적이므로 위 결과는 해당 실행의 확인 결과입니다. 앱은 사용자 입력과 응답을 DB에 저장하지 않으며, 검증 기록에도 응답 ID·세션 토큰·키를 기록하지 않았습니다. OpenAI 측 채팅 응답 저장은 이전 응답 참조를 위해 사용합니다.
