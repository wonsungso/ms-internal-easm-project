# 프로젝트 개발 규칙

- Python 3.11, 타입 힌트, Pydantic, pytest, Ruff를 사용합니다. 의존성은 pyproject.toml에 선언합니다.
- 수집기는 DefaultAzureCredential과 구독 Reader 중심으로 실행하며 Azure 쓰기/삭제/배포/비밀 조회 API를 호출하지 않습니다.
- 관리자 전용 scripts/(setup.sh, setup_account.py) 및 demo만 승인된 배포·역할·일회성 인증 준비를 수행합니다. 수집기가 이 모듈을 import하지 않게 합니다.
- 환경 식별자는 config/CLI/로컬 실행 결과로 받습니다. 기본 수집 범위는 지정 테넌트의 접근 가능한 모든 구독입니다.
- 미확인 API/필드를 추측하지 않습니다. 공식 버전·근거·한계는 docs/api-notes.md에 기록합니다.
- 수집 불가는 null과 permission_denied/feature_unavailable/license_missing/not_found/error로 기록합니다. 조회 실패를 L1이나 0으로 바꾸지 않습니다.
- 임계값은 config/criteria.yaml에서 읽고(설치본 기본값도 패키지에 포함), 고객 정책 값(허용 모델·내부 기준·정성 조건)은 선택 입력인 config/custom-config.yaml로 받습니다. 별도 기준은 --criteria로 지정합니다. L4/L5는 비율뿐 아니라 해당 정책·자동화 증거를 요구합니다.
- API 증적은 evidence/<timestamp>/에 저장하기 전에 비밀·토큰·연결문자열·개인 식별 정보를 마스킹합니다.
- 구독별 병렬 실행, 페이지 처리, 429/일시 오류 재시도 및 부분 실패 기록을 유지합니다.
- M365/Entra/Purview/Power Platform/Agent 365 진단은 구현하지 않습니다. 관리자 셋업은 진단 범위와 구분합니다.
- 문서는 한국어, 표 중심으로 짧게 작성합니다. 문서·스크립트의 문장부호에는 ASCII 하이픈을 사용합니다.
- 실제 화면 캡처는 클릭 위치를 빨간 네모로 표시하고 식별자를 가립니다. 실제로 실행하지 않은 인증·배포를 완료했다고 표시하지 않습니다.
