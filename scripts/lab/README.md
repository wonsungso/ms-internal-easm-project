# 샘플 생성부터 실측까지 - Bash

- **고객 진단만 실행하려면 [고객 실행 안내](../../README.md)를 사용하세요.** 여기는 관리자용 합성 샘플 배포 문서입니다. 고객 환경 진단에 샘플 배포가 필요한 것은 아닙니다. [10개 챗봇 구성·로그인·질문 예시](../../docs/chatbot-samples.md)도 참고하세요.

- **설정**
  - 내용: [config/lab.yaml](../../config/lab.yaml), Git 제외 `output/setup.json`
- **승인**
  - 내용: Korea Central, 검증 USD 100, 합성 입력의 GlobalStandard 처리, 샘플 유지
- **배포**
  - 내용: 별도 소유 태그가 있는 데모 리소스 그룹. Foundry와 자체 호스팅 Agent를 분리
- **권한**
  - 내용: 관리자 bootstrap이 배포, 진단 SP는 Reader 및 필요한 제한적 읽기 역할만
- **인증**
  - 내용: 비밀번호 없이 4시간 임시 인증서. 공개 인증서만 앱 등록, 개인키는 사용자 전용 임시 폴더
- **정리**
  - 내용: 실행 종료 시 새 인증서만 삭제. 기존 인증서는 보존, 샘플 리소스는 유지

```bash
export WASM_AGENT_PYTHON=python
bash scripts/lab/manage.sh plan
bash scripts/lab/manage.sh test
bash scripts/lab/manage.sh validate --prepare-providers
bash scripts/lab/manage.sh all --apply
# 이미 생성된 샘플을 로그인 보호 챗봇 10개로 확장:
python -m scripts.lab.expand --apply
# 인프라는 재사용하고 앱 배포·진단만 재검증:
bash scripts/lab/manage.sh all --apply --reuse-infrastructure
# 샘플을 유지한 채 다시 실측:
bash scripts/lab/manage.sh collect
# 실제 결과를 독립 재검증하고 대시보드 갱신:
python -m scripts.lab.summarize
```

- `all --apply` 전에는 `.azure/validation.json`의 passed=true 배포 전 검증이 필요합니다. validate는 Python 테스트·린트, 실제 Bicep 컴파일, 대상 구독의 ARM validate/what-if와 정책 조회를 실행합니다. --prepare-providers는 승인된 샘플에 필요한 공급자 등록만 수행하며 샘플 리소스를 배포하지 않습니다. 관리자 로그인이 만료되면 `bash scripts/setup/manage.sh login`의 디바이스 코드를 사용합니다. 수집기는 관리자 로그인으로 대체하지 않으며 DefaultAzureCredential의 SP 인증서 인증을 사용합니다.

## 자동 처리

- 전체 mock 테스트와 fixture Run-through.
- 필요한 공급자 등록, 샘플 그룹·Foundry·모델·웹 앱·로그 설정 생성/재사용.
- 샘플 앱 Managed Identity로 합성 모델 호출. 공개 과금 유발 엔드포인트는 만들지 않음.
- 진단 SP 임시 인증, 실제 대상 구독 병렬 수집, JSON/CSV/Markdown/HTML 보고서.
- 실제 접근 거부가 있을 때만 Cost Management Reader 또는 워크스페이스 Log Analytics Reader 추가 후 재수집.
- 새 공개 인증서·개인키 삭제. 실패 시에도 정리하며 강제 프로세스 종료는 별도 점검.

- `auto_grant_needed_read_roles: false`로 추가 읽기 역할 자동 부여를 끌 수 있습니다. 이전 거부 결과는 `output/before-additional-read-roles/`에 보존합니다. Foundry 프로젝트에는 agents/read·evaluations/read·assets/read v2 사용자 지정 역할을 진단 SP에 부여합니다. 신규 평가 API가 assets/read를 실제로 요구해 v2를 추가했으며 기존 v1 역할은 임의 수정·삭제하지 않습니다. 샘플 생성용 관리자·서비스 Managed Identity의 쓰기/추론 역할은 진단 주체와 구분합니다.

- App Service에는 Python 3.11 Linux x86_64 wheel을 사전 패키징해 배포합니다. 17개 Linux ELF 확장과 ZIP CRC를 검증했으며 Windows 바이너리를 올리지 않습니다. 원격 Oryx 플랫폼 설치나 CLI의 시작 추적을 성공 근거로 삼지 않고, 이 실행에서 생성된 새 Kudu 배포 ID의 완료와 실제 Agent health를 각각 확인합니다.

## 결과 및 주의

- **`output/mock/`**
  - 설명: 가짜 fixture 테스트. 실제 Azure 증적 아님
- **`output/lab.json`**
  - 설명: 실제 생성 리소스·endpoint·smoke 결과·추가 읽기 역할
- **`output/runthrough.json`**
  - 설명: 성공/부분 성공/실패와 일회성 인증 정리 상태
- **`output/runthrough.html`, `verification.json`**
  - 설명: 최종 테스트·실제 역할·HTTP health·공개 인증서 잔여 수 재검증
- **`output/inventory.json`, `.csv`**
  - 설명: 플랫폼 공통 Agent 스키마
- **`output/collection.json`**
  - 설명: 모델·평가·비용·보안·로그·수집 이슈
- **`output/report.md`, `.html`, `summary.csv`**
  - 설명: SE 판정 초안·null 사유·개선 후보·인터뷰 괴리
- **`output/customer_summary.csv`, `customer_inventory.csv`**
  - 설명: 사람이 읽는 한글 요약·Agent 목록
- **`output/chatbot-expansion/`**
  - 설명: 실제 평가 문항·Agent 답변·서비스 실행 ID·개별 결과와 확장 상태
- **`evidence/<timestamp>/`**
  - 설명: 마스킹된 API 응답

- 유지되는 B1 2개는 합계 USD 0.036/시간이며 모델·로그 비용은 별도입니다. USD 100은 검증 승인 예산이지 영구 하드 과금 상한이 아닙니다. 실제 30일 비용/90일 관측 기간은 신규 리소스 생성으로 만들어지지 않습니다. 미지원 API·권한 부족·로그 유입 지연은 null과 사유로 남깁니다.

- [완료된 실제 실행과 화면](../../docs/runthrough.md)을 참고하세요. `summarize`는 기존 샘플 결과를 읽고 테스트와 읽기 검증만 수행합니다. 배포·추론·역할 변경은 하지 않습니다. 현재 진단 앱의 인증서가 0건이고 실제 smoke가 완료됐는지 확인한 뒤 결과를 생성합니다. `collect`의 종료 코드 2는 일부 증거를 확보하지 못했다는 뜻이며, 해당 사유는 보고서에 남습니다.

## 나중에 샘플을 정리하려면

- 이번 실행에서는 **샘플을 삭제하지 않습니다.** 다음은 목록 확인만 하는 dry-run입니다.

```bash
python -m scripts.lab.cleanup
```

- 실제 삭제는 별도 승인 후 `--apply --confirm-lab-id '<lab_id>'`를 명시해야 합니다. 설정에서 계산한 그룹의 테넌트·소유 태그를 모두 검사한 뒤 해당 샘플 그룹만 삭제합니다. 기존 앱/SP·역할 정의와 다른 고객 리소스는 삭제하지 않습니다.
