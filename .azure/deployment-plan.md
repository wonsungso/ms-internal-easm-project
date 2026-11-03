# 거버넌스 수집기 샘플 배포 계획

## 삭제 후 재구성 E2E - 2026-11-03 승인

- 승인: 소유 태그 확인된 lab 리소스 그룹만 삭제. 진단 SP·읽기 역할·로그인 앱 등록·Codespaces 유지.
- 기존 보고서·증적 보존. 삭제 완료를 재조회한 후 같은 Korea Central·소형 모델로 재배포.
- 새 프로젝트 생성과 기존 로컬 평가 영수증을 구분하고 새 실제 평가를 실행.
- 새 generation의 로그인 앱과 정확한 새 MI subject로 연합 신뢰를 구성. 기존 앱·신뢰는 임의 삭제·덮어쓰기하지 않음.
- 검증: 새 Agent 10개·평가·웹 로그인·읽기 진단·전체 구독 열거·XLSX·ZIP·Codespaces.
- 삭제된 Foundry 계정의 soft-delete 보존과 재생성을 혼동하지 않도록 generation을 변경하여 새 계정·호스트 이름을 사용. 지역·구독·구성·예산은 유지.
- 평가 영수증은 lab_id별 폴더에 분리하여 삭제 전 완료 기록을 새 평가로 재사용하지 않음.
- 추가 기능: --all-subscriptions는 설정 구독 목록을 무시하고 지정 테넌트의 접근 가능한 활성 구독을 열거.
- 재배포 전 검증: 199개 테스트·Ruff·Bicep·새 generation의 ARM validate/what-if·정책 조회 통과.
- 기존 소유 그룹 삭제 후 부재 재조회 완료. 이후 아래 배포는 새 리소스 생성이며 기존 완료 기록을 재사용하지 않음.

- Status: Validated

## 챗봇 확장 - 2026-11-03

- **사용자 승인**
  - 승인·계획: Azure 웹 챗봇, Entra 로그인 보호, 기존 호스팅 재사용·총 10개·일부 실제 평가
- **환경**
  - 승인·계획: 기존 동일 테넌트·대상 구독·Korea Central·gpt-4.1-nano·USD 100 검증 범위 유지
- **구성**
  - 승인·계획: 기존 Foundry 프로젝트 논리 Agent 8개 + 기존 LangChain 호스트 2개. 신규 B1 플랜 없음
- **차이**
  - 승인·계획: 평가 완료/미수행, 역할별 프롬프트, 도구 사용, 운영/테스트 표시. 실제 증거 없는 상태는 만들지 않음
- **웹 접근**
  - 승인·계획: 두 기존 웹 앱에 단일 테넌트 Entra 인증. 비인증 추론 금지, 입력·출력·호출량 제한
- **비밀**
  - 승인·계획: 공식 App Service MI 연합 인증. 앱별 전용 User Assigned MI 1개·로그인 앱 등록 1개, client secret 생성 없음
- **진단 경계**
  - 승인·계획: 챗봇 추론용 앱 MI와 Reader 진단 SP 분리. 관리자 인증 준비·평가·배포는 scripts/lab만
- **고객 문서**
  - 승인·계획: README 개발 Step 제거, 준비·인증·수집·보고서 읽기 순서. 수집 항목 목록 확대
- **출력**
  - 승인·계획: 기계용 JSON 계약 보존. 사용자용 한글 표·사유·근거 파일·개선 방법 추가
- **확인**
  - 승인·계획: 실제 10개 인벤토리·로그인 차단·대화·평가 조회·보고서·스크린샷

- 인증은 공식 `OVERRIDE_USE_MI_FIC_ASSERTION_CLIENTID` 설정과 MI 연합 자격증명을 사용합니다. 허용 사용자는 현재 승인된 관리자 Object ID로 제한하고 동일 테넌트 issuer를 검증합니다. 인증 준비는 관리자 셋업이며 Entra 진단 기능을 추가하는 것이 아닙니다. 합성 3문항의 실제 Agent 응답을 Foundry string_check 평가로 기록합니다. 기본 원칙 정확 일치 검사이며 포괄적 안전성/업무 품질 인증으로 표현하지 않습니다. 평가하지 않은 Agent에는 실행 기록을 만들지 않습니다. 기존 Python 3.11·B1·Linux wheel 사전 패키징을 유지하고 신규 플랜·모델 배포를 만들지 않습니다. 한도: 입력 2,000자/대화 8,000자·10개 메시지·응답 256토큰, 호스트당 일 100회·사용자당 분 10회. 호출은 한 번에 1개이며 로그에는 질문/답변을 기록하지 않습니다.

## 승인 범위

- **지역**
  - 승인 내용: koreacentral. 다른 지역으로 임의 변경하지 않음
- **예산**
  - 승인 내용: 이번 검증 USD 100. 비용 추정·쿼터 확인 후 확정, 하드 청구 상한 보장 아님
- **구독**
  - 승인 내용: 기존 로컬 셋업 결과의 동일 테넌트 대상 구독
- **샘플**
  - 승인 내용: 최소 Foundry 계정·프로젝트·Agent·소형 모델, LangChain 호스팅, 모니터링
- **인증**
  - 승인 내용: 자동 임시 인증서. 공개키만 앱 등록, 개인키는 저장소 밖 사용자 전용 임시 경로에서 사용 후 삭제
- **역할 분리**
  - 승인 내용: 관리자 bootstrap이 배포/인증 준비, 진단 SP는 Reader 및 승인된 제한적 읽기 역할만 사용
- **종료 후**
  - 승인 내용: 샘플 리소스 유지. 비용·리소스 목록과 명시적 정리 명령 제공
- **비밀**
  - 승인 내용: client secret 금지. 개인키·토큰·비밀값을 코드/증적/로그/스크린샷에 남기지 않음

## 확정 제안

- **셋업 결과의 첫 번째 구독**
  - 신규 샘플: Foundry 계정 1, 프로젝트 1, prompt Agent 1, 모델 배포 1, Log Analytics 1
  - 구성: Korea Central, 신규 Agents API, gpt-4.1-nano 2025-04-14 GlobalStandard 최소 용량
- **두 번째 구독**
  - 신규 샘플: LangChain 웹 앱 1, Linux B1 플랜 1, 앱 Managed Identity
  - 구성: Korea Central, 첫 번째 구독의 모델 사용
- **세 번째 구독**
  - 신규 샘플: LangChain 웹 앱 1, Linux B1 플랜 1, 앱 Managed Identity
  - 구성: Korea Central, 첫 번째 구독의 모델 사용

- 각 구독의 별도 `rg-seagent-lab-01/02/03` 안에만 샘플을 생성합니다. 동명 그룹이 이미 존재하면 소유 태그를 검증하며 기존 임의 리소스를 재사용·변경하지 않습니다. Foundry 계정의 전역 고유 이름은 실행 시 생성해 로컬 배포 결과에 기록합니다. 기존 앱/SP 및 Reader 할당은 재사용합니다.

- Recipe: AZCLI with Bicep. 기존 Bash/Azure CLI 셋업과 통합하고, 실제 생성에 사용하는 infra/main.bicep 및 모듈을 배포 전 validate/what-if로 검증합니다. 관리자 bootstrap과 진단 수집을 분리합니다. 새 샘플 LangChain 앱에는 외부에서 과금을 유발하는 공개 모델 실행 경로를 만들지 않습니다. 관리자 bootstrap이 합성 입력으로 제한된 smoke 호출만 수행합니다. 비밀키 대신 앱 Managed Identity를 사용합니다.

## 사전 조사 결과 (2026-11-03)

- **신규 Foundry Agent Service**
  - 결과: 공식 지역 표에서 Korea Central 지원 확인
- **기존 클래식 Agents**
  - 결과: 지역 표에 Korea Central이 없어 신규 Agents API를 기준으로 설계
- **첫 번째 구독 모델**
  - 결과: gpt-4o-mini 2024-07-18, GlobalStandard 사용 가능, usage 0 / limit 2000 응답
- **신규 배포 검증 결과**
  - 결과: 위 gpt-4o-mini는 ServiceModelDeprecating으로 신규 배포 거부. 실제로 생성하지 않음
- **대체 소형 모델**
  - 결과: gpt-4.1-nano 2025-04-14, GlobalStandard quota 0/5000. 동일 Korea Central의 실제 ARM validate 통과
- **다른 2개 구독 모델 쿼터**
  - 결과: CognitiveServices 미등록으로 usage 목록이 비어 있음. 0 또는 무제한으로 해석하지 않음
- **모델 배치 대안**
  - 결과: 모델은 쿼터가 확인된 첫 번째 구독에만 배치하고 다른 2개 구독은 자체 호스팅 Agent로 분산
- **Container Apps 쿼터**
  - 결과: Microsoft.Quota 미등록 오류. Container Apps 대신 요금이 확인된 App Service Linux B1 제안
- **공급자 등록**
  - 결과: 다른 2개 구독의 Microsoft.Web 등 필요한 공급자는 bootstrap에서 등록 후 재검증
- **Linux B1 공개 소매 요금**
  - 결과: Korea Central, USD 0.018 / hour / plan. 2개면 USD 0.036 / hour, USD 0.864 / day

- 요금 출처: Azure Retail Prices API. 필터는 Korea Central 및 Azure App Service로 조회한 뒤 `Azure App Service Basic Plan - Linux`, `B1`, `Consumption` 행을 확인했습니다. 모델 토큰·로그 수집·저장 비용은 위 B1 요금에 포함되지 않습니다. USD 100은 이번 검증의 승인 예산이며 샘플 유지 기간 전체의 하드 청구 상한은 아닙니다. 유지되는 B1 2개만으로 30일 기준 약 USD 25.92가 발생하며 다른 비용·세금·환율·계약 할인은 별도입니다.

## 남은 승인 항목

- GlobalStandard는 리소스 위치가 Korea Central이어도 모델 추론 처리가 다른 지역에서 수행될 수 있습니다. 이번 샘플은 합성 데이터만 사용합니다. 이 처리 방식 허용 여부를 최종 확인한 뒤 배포합니다. 국내 처리만 허용한다면 모델·배포 유형을 다시 확인하며 다른 지역으로 임의 전환하지 않습니다.

- 사용자가 합성 데이터의 GlobalStandard 처리와 위 배포 계획을 승인했습니다. 모델은 승인된 소형·저비용 범위 안에서 신규 배포가 실제 검증된 gpt-4.1-nano로 대체했습니다.

## 구현 상태

- **Step 1~2**
  - 상태: 패키지·설정·공통 모델·설계 구현
- **Step 3~6**
  - 상태: 인벤토리·Foundry 신규 v1·LangChain·비용/로그/메트릭/보안 읽기 수집기 구현
- **Step 7~8**
  - 상태: 6개 SE 초안 판정·수동 등록·인터뷰 괴리·개선 후보·JSON/CSV/Markdown/HTML 보고서 구현
- **Step 9**
  - 상태: 전체 123개 mock 테스트·Ruff 통과, 실제 배포·smoke·SP 실측·스크린샷 완료
- **실행 환경**
  - 상태: Python 3.11.18 전용 .venv, 고객 환경과 분리된 패키지 설치
- **실제 샘플**
  - 상태: 대상 구독의 Foundry 1 + LangChain 2 동작 확인, 샘플 유지

## All validation checks pass

- [x] Python 3.11.18 및 전체 mock 테스트 109개
- [x] Ruff, 컴파일, Bash 구문
- [x] 실제 생성에 사용하는 Bicep 컴파일
- [x] 대상 구독 ARM validate
- [x] 대상 구독 what-if 및 삭제 미포함
- [x] 정책 조회 및 공급자 등록 확인
- [x] 역할 정적 확인: 진단 SP는 Reader/프로젝트 read 전용. 샘플 앱 추론 역할은 해당 모델 계정 범위로 제한

## 7. Validation Proof

- 챗봇 확장 전 검증: `python -m scripts.lab.run validate` 성공. 155개 테스트·Ruff·Bicep 컴파일·대상 구독 ARM validate/what-if·정책 조회 통과. 새 웹 인증 설정은 공식 authsettingsV2 스키마와 단위 테스트로 확인했으며, 관리자 DefaultAzureCredential의 ARM/Graph 토큰 취득과 동일 테넌트를 확인했습니다. 실제 Entra 로그인·웹 대화·평가 결과는 배포 후 별도로 검증합니다.

- 배포 전 `.venv/Scripts/python.exe -m pytest -q`: 109 passed. 최종 구현은 123 passed. `ruff check src scripts samples tests`, Python compileall, Bash `-n` 통과. `az bicep build --file infra/main.bicep --stdout` 통과. gpt-4o-mini 배포 전 validate 실패 및 동일 지역 gpt-4.1-nano validate 성공 확인. `bash scripts/lab/manage.sh validate --prepare-providers` 최종 실행 성공. 2026-11-03T01:54:26Z에 `.azure/validation.json`의 passed=true 확인. 대상 구독 모두 ARM validate·what-if 성공, 삭제 미포함. 조회한 정책 할당은 각각 6/3/3건입니다. 위 기록은 배포 전 검증입니다. 아래 최종 실측 기록과 구분합니다.

- 첫 실제 배포에서 Foundry 계정의 프로젝트 생성과 모델 배포가 동시에 진행되어 RequestConflict가 발생했습니다. 계정·워크스페이스 등 생성된 샘플은 유지하고, 모델이 프로젝트 생성 완료 후 실행되도록 실제 Bicep 의존성을 추가했습니다. 변경된 템플릿으로 다시 validate/what-if 후 재시도합니다. 다른 구독으로 범위를 확대하지 않습니다. 의존성 수정 후 `bash scripts/lab/manage.sh validate --prepare-providers`를 재실행해 109개 테스트·린트 및 대상 구독 validate/what-if·정책 조회가 모두 다시 통과했습니다.

- 실제 대상 구독 인프라와 첫 LangChain 앱의 모델 smoke는 확인됐으나, Azure CLI의 Linux 시작 추적이 실패를 반환했습니다. Kudu status=4/complete=true와 실제 /health smoke_status=completed를 별도 확인했습니다. 샘플의 루트 readiness 경로를 추가하고, CLI 추적 대신 Kudu 완료와 명시적 health를 검증하도록 수정했습니다. 재배포에서 Foundry 계정 업데이트에 PublicNetworkAccess 필드가 필요해, 기존 샘플의 의도된 공개/AAD 전용 설정을 Enabled로 명시했습니다. 변경 후 재검증합니다. 해당 변경 후에도 109개 테스트·린트·대상 구독 ARM validate/what-if·정책 조회가 모두 통과했습니다.

## 최종 실측 (2026-11-03)

- **실제 Agent**
  - 결과: Foundry 1 + LangChain 2, 모델 배포 1
- **기능**
  - 결과: Foundry 모델 응답 및 LangChain 도구 Agent 2개의 smoke 완료, 두 health HTTP 200
- **진단 SP 역할 재조회**
  - 결과: 구독 Reader 3, 프로젝트 Foundry 읽기 v1/v2, 샘플 workspace Log Analytics Reader
- **금지 권한**
  - 결과: 진단 SP에 Owner/Contributor/User Access Administrator 없음, 관리자 수집 fallback 없음
- **인증 정리**
  - 결과: 공개 인증서 0건 재조회, 일회성 개인키 정리
- **실제 수집**
  - 결과: 대상 구독 완료, Agent 3건. 비용 not_found 3 + 중앙 로그 permission_denied 3 + AI 권고 feature_unavailable 3
- **판정**
  - 결과: DS-SY-06은 샘플 허용 목록 기준 L3 초안. 나머지 5개는 증거·범위 부족 N/A
- **상태**
  - 결과: 자동화·기능 검증 완료. 증거 가용성 partial, 종료 코드 2
- **결과**
  - 결과: [실행 결과와 실제 캡처](../docs/runthrough.md), 로컬 `output/verification.json`

- 인증서 작업은 Azure CLI의 오래된 Graph 정책 토큰 문제를 확인한 뒤, 같은 관리자 DefaultAzureCredential의 공식 Graph GET/PATCH로 변경했습니다. 기존 공개키를 보존하고 이번 실행의 임시 key ID만 제거합니다. 진단 수집 권한을 확대하지 않습니다.

## 수행 순서

- 공식 API·koreacentral 지원·대상 구독 쿼터·예상 비용 조사.
- 실제 지원 범위를 바탕으로 샘플 배치와 배포 명령 확정.
- Step 1~9 구현 및 mock 테스트.
- 배포 전 검증, 관리자 bootstrap으로 승인된 샘플 생성.
- 임시 인증서로 진단 SP 실행, 통합 인벤토리·판정 초안·리포트 생성.
- 실제 화면·명령 실행 결과 캡처 및 문서 연결.
- 공개 인증서 등록/로컬 개인키 등 일회성 인증 재료 정리, 샘플은 유지.

## 검증 및 안전 경계

- 실제 30일 비용/90일 사용 이력은 신규 샘플에서 즉시 확보할 수 없음. 수집 공백을 수치로 꾸미지 않음.
- 신규 Agent/Evaluation API의 정확한 버전·응답 형태를 공식 SDK/문서로 확인한 뒤 코드화.
- 읽기 진단 SP에는 필요한 프로젝트 데이터 read 역할만 추가. bootstrap/샘플 앱의 쓰기·추론 역할은 진단 SP에 부여하지 않음.
- 임시 인증서의 공개키 등록과 정확한 해당 키 삭제만 허용. 기존 인증서/시크릿을 초기화하지 않음.
- 개인키는 실행 중 사용자 전용 ACL의 저장소 밖 임시 폴더에서만 사용. 종료 시 해당 파일만 삭제.
- bootstrap 요청 성공과 진단 SP 수집 성공은 별도 검증. 읽기 전용 계정 실패 시 관리자 수집으로 대체하지 않음.
- 배포 전 azure-validate, 배포 시 azure-deploy 절차를 적용했으며 실제 배포·동작 확인을 완료함.
- 영구 리소스 삭제는 승인되지 않음. 일회성 인증서 정리는 승인 범위에 포함.
- 명시적 정리 스크립트는 생성된 리소스 ID 목록만 대상으로 하며, 이번 실행은 샘플 유지.

## 공식 근거

- [Foundry 프로젝트 지역](https://learn.microsoft.com/azure/foundry/reference/region-support)
- [신규 Agent Service 지역](https://learn.microsoft.com/azure/foundry/agents/concepts/limits-quotas-regions#supported-regions)
- [클래식 Agent Service 지역](https://learn.microsoft.com/azure/foundry-classic/agents/concepts/model-region-support)
- [공개 소매 요금 API](https://learn.microsoft.com/rest/api/cost-management/retail-prices/azure-retail-prices)
