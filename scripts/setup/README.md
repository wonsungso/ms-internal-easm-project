# 진단 계정 준비 - 관리자용

- 수집 대상: Microsoft Foundry, Azure 자체 호스팅 Agent, Azure Monitor, 비용·보안 권고.
- 일반 수집 절차는 [고객 실행 안내](../../README.md)를 사용합니다.
- 이 폴더는 관리자 계정·읽기 역할·인증 준비 전용입니다. 수집기가 import하지 않습니다.

## 입력

- `config/setup.example.json`을 `output/setup.json`으로 복사합니다.
- 고객 테넌트 ID·허용 구독 목록·계정 이름을 입력합니다.
- 계정 유형은 `user` 또는 `service-principal`입니다.
- 기존 계정은 재사용합니다. 새 SP가 필요할 때만 `--create-principal`을 사용합니다.
- 새 사용자는 고객 관리 절차로 먼저 준비합니다.
- 설정·적용 결과는 Git에 포함하지 않습니다.

## 실행

```bash
bash scripts/setup/manage.sh login
bash scripts/setup/manage.sh plan --create-principal
bash scripts/setup/manage.sh apply --create-principal
```

- `login`
  - 관리자의 디바이스 코드 로그인입니다. SP 인증을 대신하지 않습니다.
- `plan`
  - 변경 계획만 표시합니다. Azure API를 호출하지 않습니다.
- `apply`
  - 계정 재사용·필요한 읽기 역할 할당·재조회를 수행합니다.
  - 같은 계정·역할은 중복 생성하지 않습니다.
  - 실패하면 원인을 해결한 뒤 같은 명령으로 이어갑니다.
- `verify`
  - 별도 진단 주체로 API 접근을 읽기만 확인합니다.

## 추가 역할

- 실제 거부 원인을 확인한 뒤 필요한 옵션만 선택합니다.
  - `--cost-reader`: Cost Management Reader.
  - `--monitoring-reader`: Monitoring Reader.
  - `--log-analytics-reader`: Log Analytics Reader.
  - `--security-reader`: Azure Security Reader.
  - `--foundry-project-scopes '<project-resource-id>' --create-foundry-read-role`: 지정 프로젝트의 읽기 역할.
- Foundry 사용자 지정 역할은 agents/read·evaluations/read·assets/read를 사용합니다.
- 기존 승인 역할은 `--foundry-read-role-id '<role-id>'`로 지정할 수 있습니다.
- Foundry User의 키 조회·쓰기 작업을 진단 계정에 허용하지 않습니다.
- 역할의 서비스 권한 단위·한계는 [읽기 권한](../../docs/rbac.md)을 참고하세요.

## 인증과 접근 확인

- [공개 인증서·연합 인증 화면](../../docs/sp-authentication.md)을 참고하세요.
- 인증서 개인키는 Codespaces 저장소 밖의 보호 경로에 둡니다.

```bash
bash scripts/setup/manage.sh verify \
  --certificate-path "$HOME/.config/wasm-agent/diagnostic.pem"
```

- 결과
  - `output/permissions.json`.
  - `output/permissions.md`.
- 인증서/연합 설정이 없으면 관리자 로그인으로 대신하지 않고 중단합니다.
- 사람은 디바이스 코드로, SP는 인증서/연합 인증으로 로그인합니다.
- 관리자는 구독 역할 할당·앱/SP 준비 권한이 필요합니다.
- 진단 주체에는 관리 그룹·테넌트 루트·Owner·Contributor·User Access Administrator를 부여하지 않습니다.
- 접근 성공은 데이터 완전성·성숙도 보장이 아닙니다.
