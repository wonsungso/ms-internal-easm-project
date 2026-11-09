# 프로젝트 개발 규칙

- Python 3.11, 타입 힌트, Pydantic, pytest, Ruff를 사용합니다. 의존성은 pyproject.toml에 선언합니다.
- 수집기는 DefaultAzureCredential과 구독 Reader 중심으로 실행하며 Azure 쓰기/삭제/배포/비밀 조회 API를 호출하지 않습니다.
- 관리자 전용 scripts/(setup.sh, setup_account.py) 및 demo만 승인된 배포·역할·일회성 인증 준비를 수행합니다. 수집기가 이 모듈을 import하지 않게 합니다.
- 환경 식별자는 config/CLI/로컬 실행 결과로 받습니다. 기본 수집 범위는 지정 테넌트의 접근 가능한 모든 구독입니다.
- 미확인 API/필드를 추측하지 않습니다. 공식 버전·근거·한계는 docs/api-notes.md에 기록합니다.
- 수집 불가는 null과 permission_denied/feature_unavailable/license_missing/not_found/error로 기록합니다. 조회 실패를 L1이나 0으로 바꾸지 않습니다.
- API 지표·분모·증거·한계·임계값은 config/criteria.yaml의 grading_profile=api_configuration_v1에서 읽고 설치본 기본값도 패키지에 포함합니다. 별도 기준은 --criteria로 지정하며 config/custom-config.yaml은 workers·tags·projects 등 수집 기술 설정만 예시합니다.
- 22개 수집 항목은 API 구성·기록 충족률로 평가합니다. L1=0%, L2=0% 초과~80% 미만, L3=80% 이상~90% 미만, L4=90% 이상~100% 미만, L5=100%입니다. 조회 실패·필수 필드 미확인·빈 분모는 null과 사유를 유지하며 L1이나 0으로 바꾸지 않습니다.
- policy_facts·허용 모델·내부 기준 등 과거 Settings 필드는 기존 로컬 설정 로딩 호환용이며 등급을 결정하지 않습니다. 구성 존재만으로 정책 승인·실효성·자동화 동작을 추론하거나 별도 L2 기본등급을 부여하지 않습니다.
- API 증적은 evidence/<timestamp>/에 저장하기 전에 비밀·토큰·연결문자열·개인 식별 정보를 마스킹합니다.
- 구독별 병렬 실행, 페이지 처리, 429/일시 오류 재시도 및 부분 실패 기록을 유지합니다.
- M365/Purview/Power Platform/Agent 365의 범위 밖 9개 항목은 진단하지 않습니다. Entra는 Agent ID·Blueprint·소유자·후원자·앱 역할의 명시된 읽기 범위만 포함합니다. 관리자 셋업은 진단 범위와 구분합니다.
- 문서는 한국어, 표 중심으로 짧게 작성합니다. 문서·스크립트의 문장부호에는 ASCII 하이픈을 사용합니다.
- 실제 화면 캡처는 클릭 위치를 빨간 네모로 표시하고 식별자를 가립니다. 실제로 실행하지 않은 인증·배포를 완료했다고 표시하지 않습니다.
