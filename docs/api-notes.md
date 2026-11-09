# 설계, API 계약과 System Evidence 기준

- 기준: [config/criteria.yaml](../config/criteria.yaml)의 `grading_profile: api_configuration_v1` (2026-11-09). 항목명·분모·증거·한계·규칙의 단일 기준입니다.
- 실행·고객 권한 설정·정리는 [README](../README.md), 31개 항목과 확인 화면은 [점검 항목 상세](checklist.md), 샘플 배포는 [개발자 데모](../demo/README.md)를 참고합니다.
- 승인된 기존 원본은 로컬 `source-materials/`(.gitignore 대상)에 별도 보관하며 저장소·Codespaces에 요구하지 않습니다. 과거 19개 원문 Level과 구성 L2 기본등급은 현재 평가 기준으로 사용하지 않습니다.

## 범위 원칙

| 구분 | 범위·처리 |
| --- | --- |
| 수집·평가 | Microsoft Foundry, Azure 자체 호스팅 Agent, Azure Monitor·Log Analytics, 비용·보안 권고, Entra Agent ID의 22개 항목 |
| Entra 필수 조회 | DS-SY-05, DP-SY-19, OE-SY-20~21. 생략 옵션 없이 권한 부족은 항목을 유지하고 `null`과 사유 기록 |
| 범위 밖 9개 | DM-SY-01~03, DS-SY-04, BI-SY-10, DP-SY-17~18, OT-SY-27, OT-SY-30. M365·Power Platform·Agent 365·Purview 통제는 수집·채점하지 않음 |
| 범위 구분 | Azure 인벤토리는 Agent Registry·인사 대사를 대체하지 않으며 Azure 로그는 Purview Audit 증거가 아님 |
| 승인 경계 | 지정 테넌트의 접근 가능한 구독을 기본 열거하고 CLI·설정의 승인 범위를 적용. 외부 workspace·청구 범위 접근을 자동 확대하지 않음 |
| 실행 신원 | 진단 SP의 DefaultAzureCredential. Reader 중심 GET 및 Resource Graph·비용·로그의 읽기 query POST만 허용 |
| 관리자 예외 | `scripts/setup.sh`, `setup_account.py`, 정리 스크립트와 demo만 승인된 배포·역할·일회성 인증 준비 수행. 수집기에서 import 금지 |
| 결과 번호 | `assessment_revision: 5`는 01~31 순번. Demand 01~03, Design 04~09, Build 10~16, Deploy 17~19, Operate 20~26, Optimize 27~31 |
| 호환성 | 이전 revision 4는 항목·점수·증거 귀속을 보존해 한 번 변환. 더 오래된 결과는 위험 Agent·Red team 제거와 구 번호 변환을 먼저 수행 |
| 제외 API | Red team·조건부 접근·위험 Agent 진단 제외. 기존 Graph 추가 권한은 관리자가 회수 가능 |

## 심사기준 검토와 점수 반영 (2026-11-05)

이 절의 링크 주소는 유지하며 내용은 현재 API 평가 기준을 설명합니다. 충족률은 아래 분모 중 API 증거가 조건을 충족한 비율입니다. 비용 항목만 건수가 아닌 금액 비율입니다.

| API 충족률 | Level | 점수 |
| --- | --- | --- |
| 0% | L1 | 1 |
| 0% 초과~80% 미만 | L2 | 2 |
| 80% 이상~90% 미만 | L3 | 3 |
| 90% 이상~100% 미만 | L4 | 4 |
| 100% | L5 | 5 |

| 판정 계약 | 적용 |
| --- | --- |
| 완전성 | 전체 대상 인벤토리·페이지·항목별 관련 조회와 필수 필드를 확인한 뒤 계산. 일부 성공한 응답만으로 전체 비율을 만들지 않음 |
| L1 | 유효한 양수 분모에서 확인된 충족률 0%에만 적용 |
| 판정 불가 | 권한 거부·기능 미제공·라이선스 부족·조회 실패·필수 필드 미확인·빈 분모는 `null`과 `permission_denied/feature_unavailable/license_missing/not_found/error` 사유. L1·0%로 대체하지 않음 |
| 명시적 부재 | 조회가 완료되고 필드가 명시적으로 비어 있거나 조건을 미충족한 경우와 조회 자체가 실패한 경우를 구분 |
| 고객 입력 | `policy_facts`, 외부 승인, `major_type_blueprints_defined`, 허용 모델·내부 기준 등 과거 Settings 필드는 기존 로컬 설정 로딩 호환용이며 현재 등급에 사용하지 않음 |
| 해석 한계 | L4/L5도 아래 API 구성·기록의 비율을 뜻함. 정책의 승인·실효성·자동화 동작·개선 효과를 설정만으로 추론하지 않음 |
| 기준 변경 | 지표·임계값·기간은 `criteria.yaml`, 수집 기술 설정은 선택 `custom-config.yaml`. `--criteria`로 별도 기준 지정. 설치본 기본 기준도 패키지에 포함 |
| 범위 | `partial` 결과는 명시된 Azure 부분 범위의 지표이며 조직 전체 원 통제 충족을 의미하지 않음 |

### 22개 API 지표

| 코드·현재 명칭 | 분모 | 충족 API 증거 | 해석 한계 |
| --- | --- | --- | --- |
| DS-SY-05 Agent ID의 Blueprint 연결 | Graph Agent ID 수 | `applications/microsoft.graph.agentIdentityBlueprint`와 `servicePrincipals/microsoft.graph.agentIdentity`의 `agentIdentityBlueprintId` 대조 | Blueprint 조직 표준 승인·업무 유형 분류 아님 |
| DS-SY-06 모델 배포 버전·업데이트 구성 | 모델 배포 수 | `model.name·version·format`과 기준에 정의된 `versionUpgradeOption` 모두 존재 | 허용 모델 대조·퇴역 대응 완료 아님 |
| DS-SY-07 AI 리소스 인바운드 경계 구성 | AI 계정·자체 Agent 호스트 수 | AI 계정의 `publicNetworkAccess`와 Approved `privateEndpointConnections`, 호스트의 기본 거부 접근 제한 또는 비공개 ingress | 송신 경계·실제 차단 효과 아님. HTTPS·VNet 통합만으로 충족하지 않음 |
| DS-SY-08 MCP 도구 필수 승인 모드 | MCP 도구 선언 수 | 최신 Agent 버전 `definition.tools`의 MCP `require_approval=always`만 충족 | `never`·명시적 객체형 `custom`은 미충족, 값 미확인은 null. 함수·내장 도구 제외. 런타임 승인 우회 방지 검증 아님 |
| DS-SY-09 외부 도구 HTTPS 연결 구성 | 명시적 외부 도구 URL 수 | `server_url·url`의 HTTPS scheme·유효 hostname·userinfo 부재 | 업무 승인·상대 서버 신뢰·인증 성공 아님. 경로·쿼리·인증값 미저장 |
| BI-SY-11 Foundry 프로젝트 평가 실행 이력 | Foundry 프로젝트 수 | `/openai/v1/evals`와 `/evals/{id}/runs`에서 `completed` 또는 `succeeded` 실행 보유 | 프로젝트 이력이며 배포 전 평가·Agent 버전별 품질 통과율 아님 |
| BI-SY-12 AI 리소스 보안 권고 상태 | 적용 가능한 AI 보안 권고 수 | `SecurityResources` assessments의 `resourceDetails.Id` 연결과 `status.code=Healthy`, `NotApplicable` 제외 | 권고 없음은 100% 아님. 구독 보안 점수·권고 나이·조치 SLA 채점 안 함 |
| BI-SY-13 콘텐츠 필터 정책 연결 | 모델 배포 수 | 배포 `raiPolicyName`으로 연결된 실제 `accounts/raiPolicies`를 식별하고 `contentFilters.enabled` 확인 | 필터 값 미확인은 null. 실제 차단 효과·강도 승인 아님. 정책명만으로 충족하지 않음 |
| BI-SY-14 Agent 버전·호스트 런타임 식별 | Foundry Agent·자체 호스트 수 | Agent `version`, `sites/config/web.linuxFxVersion`, Container Apps 이미지 sha256 다이제스트 | 소스·빌드 출처·운영 배포 승인·롤백 기록 아님 |
| BI-SY-15 Agent 책임·환경·비용 메타데이터 | Azure Agent 수 | 같은 Agent의 태그 또는 API metadata에 owner·sponsor·env·cost-center 모두 존재 | 값의 업무 승인·인사 상태 아님 |
| BI-SY-16 AI 리소스 정책 평가 준수 | 정책 평가가 있는 AI 관련 리소스 수 | `PolicyResources` policyStates를 리소스별 대조해 모든 평가가 `Compliant` | `Exempt·Unknown`·평가 없음은 준수 아님. 자동 교정 효과 아님 |
| DP-SY-19 Azure Agent의 Entra Blueprint 귀속 | Azure Agent 수 | Entra Agent ID·Blueprint 전체 조회 완료 후 Blueprint tags의 subscriptionId·accountName·projectName·agentName을 Foundry Agent와 정확 대조하고 실제 Agent ID의 해당 Blueprint 참조 확인 | Blueprint 태그만으로 충족하지 않으며 LangChain 관리 ID를 Entra Agent ID로 대신 간주하지 않음 |
| OE-SY-20 Agent ID 소유자·후원자 연결 | Graph Agent ID 수 | 실제 `owners` 수 > 0 및 `sponsors` 수 > 0 | 기본 Graph 읽기 권한의 사용자 속성 제한 때문에 accountEnabled는 조건에서 제외. 계정 활성 상태·퇴사자 판정·인사 대사 아님. 이름·UPN 미저장 |
| OE-SY-21 Agent ID 앱 역할 읽기 범위 | Graph Agent ID 수 | `appRoleAssignments`와 대상 SP의 `appRoles.value`를 해석해 기준의 쓰기·전체제어 패턴 앱 역할 없음 | ARM·위임·앱 내부 권한 제외 |
| OE-SY-22 Agent 리소스 실행 로그 연결 | AI 계정·자체 Agent 호스트 수 | `diagnosticSettings.logs.enabled`와 `workspaceId` 연결 | 구독 공통 Activity Log 제외. 이벤트 유입·테이블 유효 보존기간 아님 |
| OE-SY-23 관리 ID·키 인증·직접 ARM 역할 구성 | AI 계정·자체 Agent 호스트 수 | `identity.principalId·type` 존재, 동일 구독의 광범위 직접 역할 없음, AI 계정 `disableLocalAuth=true` | 타 구독·상속·데이터 평면 역할과 실제 인증 사용 제외 |
| OE-SY-24 AI 리소스 활성 경보 범위 | AI 계정·자체 Agent 호스트 수 | `metricAlerts·scheduledQueryRules·activityLogAlerts`의 enabled·scopes를 실제 AI 리소스 ID에 대조 | 경보 발생·SLO 충족·trace 유입 아님 |
| OE-SY-25 AI 경보의 작업 그룹·수신자 연결 | AI 대상 경보 수 | 활성 경보의 actionGroupId·actionGroups에 존재하는 작업 그룹과 활성 email·SMS·webhook·armRole·Function·LogicApp·ITSM receivers 연결 | 실제 전달 성공·온콜 대응 시간·복구 시험 아님. 주소·이름 미저장 |
| OE-SY-26 리소스 지역·workspace 보존 구성 | AI 계정·자체 Agent 호스트 수 | `resources.location` 식별·활성 로그의 연결 workspace `retentionInDays` 기준 충족, 기본 90일 | 실제 처리 지역·테이블별 유효 보존·법적 삭제 아님 |
| OT-SY-28 AI 리소스 사용량 관측 범위 | AI 계정·자체 Agent 호스트 수 | `metricDefinitions`와 `metrics.timeseries.data`에 기간 내 숫자 표본, 기본 30일 | 숫자 0도 관측됨. Agent별 사용자 수·90일 미사용 여부 아님 |
| OT-SY-29 AI 비용의 단일 Agent 귀속 | 동일 통화의 양수 AI 비용 금액 | Daily query의 ResourceId·UsageDate·Cost·Currency와 Agent·모델·호스트·플랜 ID 대조. 일자 존재·단일 Agent 귀속 금액, 기본 30일 | 공유 비용 중복 배분 금지. 통화 혼재·음수 조정·분모 0은 산출하지 않음 |
| OT-SY-31 구독 예산·실제·예측 경보 구성 | 승인 구독 수 | 현재 유효한 양수·무필터 `Cost` 예산과 활성 Actual·Forecasted 임계값 경보·수신자 존재 | Agent별 예산·실제 전달 성공·통보 후 자동 조치 아님 |

- DS-SY-06의 기본 업데이트 옵션은 `NoAutoUpgrade`, `OnceNewDefaultVersionAvailable`, `OnceCurrentVersionExpired`입니다. 어느 옵션도 조직의 모델 승인이나 퇴역 대응을 보장하지 않습니다.
- OE-SY-21의 기본 패턴은 `*.ReadWrite.All`, `*.Write.All`, `*FullControl*`이며 `criteria.yaml`에서 관리합니다. 매칭되지 않는 역할을 모든 권한에 대한 최소 권한 인증으로 해석하지 않습니다.
- OE-SY-26의 기본 보존 기준은 `workspace_retention_target_days: 90`, OT-SY-28은 `usage_window_days: 30`, OT-SY-29는 `cost_window_days: 30`입니다. workspace 설정값은 테이블별 유효 보존기간이 아닙니다.
- OT-SY-31은 `amount·category·timePeriod·filter`, 활성 notifications의 `thresholdType·threshold`와 수신자 존재를 함께 확인합니다. 만료·향후 예산, 필터 예산 또는 예측 경보만 있는 예산을 구독 전체 충족으로 간주하지 않습니다.

### 보고서와 기존 결과

| 항목 | 계약 |
| --- | --- |
| 출력 | 실행별 `output/<실행시각-UTC>/`에 `report-<타임스탬프>.xlsx`, `raw-data-<타임스탬프>.json` 2개. JSON은 raw + evidence + meta 통합 |
| 실행 시각 | 마이크로초 포함 UTC·충돌 접미사를 폴더와 새 파일명에 동일 적용. 실제 수집 시각은 `collection.collected_at` 유지 |
| 시트 1~5 | 평가 템플릿의 기존 수식 캐시·메타데이터·사용자 강조·스타일·입력 점수·메모·민감도 라벨 보존. 시트 4 점수 자동 덮어쓰기 안 함 |
| 6. 수집 결과 | 시트 4의 A~F·서식·행 순서를 복사. G 수집 상태, I Level·평가기준, J 수집결과·판정 근거, K 다음조치, L 평가 점수(1~5), M 검토메모. 판정 불가는 L 빈칸 |
| 근거 이동 | 6번 J의 수집결과는 같은 SE 코드의 7번 행으로 이동하는 통합 문서 내부 링크. 외부 URL·파일·사용자 입력을 링크 대상으로 쓰지 않음 |
| 원본·실패 | 7. 수집결과 근거, 8. 수집 Raw 데이터, 9. 수집이슈 Raw 데이터, 10. 필드누락사유. 원래 숫자·불리언·null·JSON 및 evidence_refs 보존 |
| 집계 | 인터뷰 54개·SE 31개 구조 유지. 시트 5 실제 집계는 시트 4 입력 기준이며 빈칸·N/A 제외. 4개 인터뷰 관점·SE 확보 시 영역, 6개 영역 확보 시 종합 산정 |
| 괴리 보정 | 인터뷰 평균 - SE 평균 >= 1.5이면 SE 평균 + 1.0으로 하향 보정, 소수 첫째 자리 반올림. 미확보를 0으로 보간하지 않음 |
| 템플릿 갱신 | `python -m scripts.merge_assessment --source <검토할-xlsx> --output <다른-경로.xlsx>`. 검토 후 사용하며 원본 덮어쓰기 금지. 패키지에도 템플릿 포함, 누락 시 오류 |
| 기존 결과 | `wasm-agent package --output-dir output`은 최신 실행의 Excel만 재생성. 특정 실행 폴더·기존 평면 구조 지원. 기존 파일명·판정 보존, 현재 기준으로 재채점하지 않음 |

## 고객 셋업·정리 계약

- 고객 설정·정리 명령과 화면은 [README Step 1~5](../README.md#진행-순서)를 유지합니다. 실제로 실행하지 않은 인증·배포·삭제를 완료했다고 표시하지 않습니다. 실제 캡처는 클릭 위치를 빨간 네모로 표시하고 식별자를 가립니다.
- 고객에게는 [customer-setup.zip](downloads/customer-setup.zip)의 `setup.sh`, `setup_account.py`, `foundry-reader.json`, `cleanup_account.py` 4개 실행 파일과 고객별 공개 인증서를 별도 전달합니다. ZIP에 setup.json·개인키·인증서·수집기를 포함하지 않습니다.
- `python -m scripts.package_customer_setup`으로 현재 소스에서 ZIP을 다시 만듭니다. LF 줄바꿈·고정 파일 목록을 사용하며 테스트는 ZIP·소스 일치와 압축 해제한 고객 폴더의 다중 구독 plan 실행을 확인합니다.
- 고객은 Python 3.11 이상·Azure CLI가 있는 승인된 Bash 환경에서 `bash setup.sh login/plan/apply`를 사용하고 완료한 `setup.json`만 MS에 반환합니다. Python 표준 라이브러리만 사용하며 저장소·수집기 패키지를 요구하지 않습니다. 고객은 관리자 인증 정보나 개인키를 MS에 전달하지 않습니다.
- 고객 폴더는 같은 위치의 setup.json을 기본 입출력으로 사용하고 저장소 내부는 `.wasm-agent/setup.json`을 유지합니다. `verify`는 별도 진단 모듈·개인키가 필요해 MS 저장소에서만 실행하며 고객 폴더에서는 거부합니다.
- `plan`은 계정 식별자의 실제 존재를 조회하지 않습니다. `apply`는 Client ID로 SP를 조회해 앱 이름·반환 Client ID·SP 개체 ID를 검증합니다. principal_id는 생략 가능하며 잘못된 이전 값은 검증한 ID로 보정 사실을 안내하고 성공 후 저장합니다. Client ID 조회·이름 검증 실패 시 이름 기반 대체·새 SP 생성 없이 쓰기 전 중단합니다. Client ID 없는 기존 명시 SP 방식은 유지합니다.

| 권한 구분 | 관리자 apply 계약 |
| --- | --- |
| Azure 읽기 | 승인 구독마다 Reader·Cost Management Reader·Log Analytics Reader·Security Reader |
| Foundry 읽기 | `WASMAgent Foundry Evidence Reader v2`를 승인 구독에 할당해 기존·이후 프로젝트에 상속. `--foundry-project-scopes`로 승인 프로젝트 제한 가능 |
| Foundry DataActions | `agents/read·evaluations/read·assets/read` 3개만. 역할 생성·할당은 관리자 예외이며 수집기가 수행하지 않음 |
| Graph 앱 읽기 | `AgentIdentity.Read.All`, `AgentIdentityBlueprint.Read.All`, `Application.Read.All` 및 테넌트 관리자 동의 |
| 최소 권한 | 진단 SP에 Owner·Contributor·Foundry User 등 쓰기 역할 부여 금지. Graph 관리자 동의 권한은 구독 역할 할당 권한과 별개 |

- Graph 읽기 권한은 앱의 `requiredResourceAccess`에도 추가한 뒤 동의해 Configured permissions와 실제 appRoleAssignments를 맞춥니다. 기존 다른 API 권한은 보존하고 필요한 `Role`만 추가·동의합니다. [Azure CLI API 권한 추가](https://learn.microsoft.com/en-us/cli/azure/ad/app/permission?view=azure-cli-latest#az-ad-app-permission-add).
- Graph appRoleAssignments POST 실패는 Azure 역할 부여 성공과 별도로 동의 미완료로 표시합니다. 활성 Privileged Role Administrator/Global Administrator 등 동의 권한이 필요하고 Global Reader로는 불가합니다. PIM 활성화 후 `bash setup.sh login --login-resource graph`로 토큰을 갱신하고 재실행합니다. Azure CLI 오류는 승인한 고정 코드만 표시하고 본문·토큰은 출력하지 않습니다. [Graph appRoleAssignment 권한](https://learn.microsoft.com/en-us/graph/api/serviceprincipal-post-approleassignments?view=graph-rest-1.0).
- Step 1은 인증서 경로만 `.wasm-agent/certificate-path`에 기록합니다. Step 4의 `scripts/certificate_path.py`는 이를 재사용합니다. 기록 없는 기존 환경에서는 `auth-*/diagnostic.pem`이 정확히 하나일 때만 선택·기록하며 부재·다중 후보·잘못된 기존 기록은 오류입니다. 개인키 내용은 읽지 않습니다.
- 사전 점검의 대상 AI 리소스 없음·프로젝트 endpoint 미지정은 `NOT_CHECKED/not_found`로 저장하며 OK가 아닙니다. 이 항목만 미점검이면 종료 0으로 수집을 이어가고 실제 DENIED·ERROR·FEATURE_UNAVAILABLE는 종료 2입니다. 정식 수집은 프로젝트를 자동 발견하며 실패·null 계약을 유지합니다.

| 정리 단계 | 안전 계약 |
| --- | --- |
| cleanup-plan | 삭제 없이 실제 대상 조회. 완료된 setup.json의 테넌트·Client ID·SP 개체 ID·진단 전용 앱 이름과 Single tenant/Application 유형 검증 |
| cleanup-apply | 승인 구독의 해당 SP 역할 할당을 먼저 회수. 앱·SP 부재를 재조회한 뒤 정확히 일치하는 진단 사용자 지정 역할만 정리 |
| 역할 보존 | 다른 주체의 활성·PIM 적격 할당 또는 재사용 계획이 있으면 보존. 조회 실패를 미사용으로 간주하지 않음 |
| PIM 조회 | 현재 적격 인스턴스와 향후 적격 예약의 모든 페이지 검사. plan의 `delete_after_target_assignments`는 해당 SP 할당 회수 후에만 삭제 가능하다는 뜻 |
| 삭제 직전·직후 | 삭제 직전 사용 여부 재조회. 역할 DELETE 후 승인 구독 전체의 동일 역할 ID 부재를 최대 6회 확인. 전파 대기 중 DELETE 반복 금지. 조회 실패·지속 존재는 성공 아님 |
| 종료 확인 | SP 삭제만으로 RBAC 제거를 가정하지 않음. 홈 테넌트 앱·SP 잔여와 Graph 동의 철회 확인. Step 5 Delete 캡처는 위치 안내이며 삭제 완료 증거 아님 |
| 로컬 정리 | 인증서·개인키·암호 환경변수·경로 기록·setup.json·CLI 세션·공유 보고서·증적 사본을 승인 보관 정책에 따라 정리. 임시 PIM 종료, 데모 종속 ID 보존 |
| 별도 승인 | 스크립트는 영구 삭제·파일 폐기·데모 삭제 안 함. 삭제 앱은 30일 복원 가능할 수 있으며 완전 폐기는 고객 승인 후 별도 수행 |

공식 근거: [PIM 적격 인스턴스 2020-10-01](https://learn.microsoft.com/en-us/rest/api/authorization/role-eligibility-schedule-instances/list-for-scope?view=rest-authorization-2020-10-01), [향후 적격 예약 2020-10-01](https://learn.microsoft.com/en-us/rest/api/authorization/role-eligibility-schedules/list-for-scope?view=rest-authorization-2020-10-01), [앱 삭제](https://learn.microsoft.com/en-us/entra/identity-platform/howto-remove-app), [복원·영구 삭제](https://learn.microsoft.com/en-us/entra/identity-platform/howto-restore-app), [SP 삭제 후 RBAC](https://learn.microsoft.com/en-us/azure/role-based-access-control/troubleshooting#symptom---role-assignments-with-identity-not-found), [사용자 지정 역할 삭제](https://learn.microsoft.com/en-us/azure/role-based-access-control/custom-roles#delete-a-custom-role).

## 공식 API와 읽기 계약

- 현재 Azure Public Cloud만 지원하며 소버린 클라우드 호스트·audience는 추측하지 않습니다. 실행 의존성은 `pyproject.toml`의 azure-identity·requests이며 아래 SDK 버전은 REST 확인 근거이지 설치 요구가 아닙니다.
- 2026-11-03 승인 샘플에서 신규 API·수집을 검증했습니다(Python 3.11.18, azure-ai-projects 2.4.0, openai 2.54.0). 모든 고객 서비스·버전 지원을 보장하지 않습니다.
- 구독별 병렬 실행·전체 페이지·429/일시 오류 재시도·부분 실패를 유지합니다. API 증거는 `evidence/<timestamp>/`에 저장하기 전에 비밀·토큰·연결문자열·개인 식별 정보를 마스킹합니다.

| 조회 | 경로·버전·근거 | 계약·한계 |
| --- | --- | --- |
| 구독 | GET `/subscriptions`, `2022-12-01`. [List](https://learn.microsoft.com/rest/api/resources/subscriptions/list?view=rest-resources-2022-12-01) | 지정 테넌트 Enabled 구독 |
| 유효 권한 | GET `/subscriptions/{id}/providers/Microsoft.Authorization/permissions`, `2022-04-01`. [List](https://learn.microsoft.com/rest/api/authorization/permissions/list-for-scope?view=rest-authorization-2022-04-01) | 광범위·명시적 쓰기 권한 안전 가드이지 완전한 IAM 감사 아님 |
| 리소스 | GET `/subscriptions/{id}/resources`, `2021-04-01`. [List](https://learn.microsoft.com/rest/api/resources/resources/list?view=rest-resources-2021-04-01) | ARM nextLink 처리·Resource Graph 보완 |
| 프로젝트 ARM | `accounts/projects`, `2025-06-01`. [공식 스펙](https://github.com/Azure/azure-rest-api-specs/blob/main/specification/cognitiveservices/resource-manager/Microsoft.CognitiveServices/CognitiveServices/stable/2025-06-01/cognitiveservices.json) | 관리 평면·데이터 평면 구분 |
| 신규 Agent | project endpoint GET `/agents`, `/agents/{name}/versions`, `api-version=v1`. [SDK 2.4 샘플](https://github.com/Azure/azure-sdk-for-python/blob/azure-ai-projects_2.4.0/sdk/ai/azure-ai-projects/samples/agents/sample_agent_basic.py) | data/last_id/has_more 페이지 처리. 논리 Agent당 1건, 최신 보이는 버전이 운영 배포라고 주장하지 않음 |
| 평가 | GET `/openai/v1/evals`, `/openai/v1/evals/{id}/runs`. [안내](https://learn.microsoft.com/azure/foundry/observability/how-to/evaluate-agent) | 완료 상태의 프로젝트 이력. completed_at 없으면 생성 시각으로 대체하지 않음. 질문·응답·데이터셋 본문 미조회 |
| 모델 배포 | GET `{accountResourceId}/deployments`, `2024-10-01`. [List](https://learn.microsoft.com/rest/api/aiservices/accountmanagement/deployments/list?view=rest-aiservices-accountmanagement-2024-10-01) | model·versionUpgradeOption·raiPolicyName은 구성값. 정책 효과·모델 승인 아님 |
| 콘텐츠 필터 | GET `{account}/raiPolicies`, `2024-10-01`. [List](https://learn.microsoft.com/rest/api/aiservices/accountmanagement/rai-policies/list) | 실제 정책과 필터 활성 대조. 미지정 정책명을 실제 안전 통제 부재라고 단정하지 않음 |
| 호스트 구성 | GET `sites/{name}/config/web`, `2024-04-01`. [Get Configuration](https://learn.microsoft.com/rest/api/appservice/web-apps/get-configuration) | 인바운드 기본 제한·런타임. 앱 설정 list는 비밀 반환 가능해 호출하지 않음 |
| ARM 역할 | GET `/subscriptions/{id}/providers/Microsoft.Authorization/roleAssignments`, `2022-04-01`. [List](https://learn.microsoft.com/rest/api/authorization/role-assignments/list-for-subscription) | 관리 ID의 동일 구독 직접 할당과 Graph 앱 역할 구분 |
| Resource Graph | 읽기 query POST, `2022-10-01`. [Resources](https://learn.microsoft.com/rest/api/azureresourcegraph/resourcegraph/resources/resources?view=rest-azureresourcegraph-resourcegraph-2022-10-01) | Resources·PolicyResources·SecurityResources 조회. [지원 테이블](https://learn.microsoft.com/azure/governance/resource-graph/reference/supported-tables-resources#securityresources) |
| 보안 권고 | SecurityResources assessments의 resourceDetails.Id·status.code | 조회 성공·빈 결과가 Defender AI 기능·라이선스 활성화 증거는 아님 |
| 보안 점수 참고 | GET `/subscriptions/{id}/providers/Microsoft.Security/secureScores`, `2020-01-01`. [안내](https://learn.microsoft.com/azure/defender-for-cloud/secure-score-security-controls#get-your-secure-score-from-the-rest-api) | `ascScore`, `score.current/max/percentage`(0~1) 실측. 현재 BI-SY-12 등급에는 미사용 |
| 진단 설정 | GET `{resourceId}/providers/Microsoft.Insights/diagnosticSettings`, `2021-05-01-preview`. [List](https://learn.microsoft.com/rest/api/monitor/diagnostic-settings/list?view=rest-monitor-2021-05-01-preview) | Agent 관련 실행 로그만. 구독 Activity Log는 `log_scope_exclusions`로 제외하며 조회 안 함 |
| workspace | GET `{workspaceResourceId}`, `2022-10-01`. [Get](https://learn.microsoft.com/rest/api/loganalytics/workspaces/get?view=rest-loganalytics-2022-10-01) | 보존 설정과 실제 로그·보호 테이블 권한 구분. 승인 구독 밖 sink는 권한 확대 없이 permission_denied |
| 메트릭 | GET `{resourceId}/providers/Microsoft.Insights/metrics`, `2018-01-01`. [List](https://learn.microsoft.com/rest/api/monitor/metrics/list?view=rest-monitor-2018-01-01) | metricDefinitions와 수치 표본 확인. timespan은 UTC `YYYY-MM-DDTHH:MM:SSZ`로 보내 `+` 재해석 방지 |
| 로그 query | Log Analytics query·AppServiceConsoleLogs. [열 정의](https://learn.microsoft.com/azure/azure-monitor/reference/tables/appserviceconsolelogs) | ResultDescription의 샘플 이벤트 집계. 누락 호출·토큰을 0으로 만들지 않음 |
| 비용 | POST `/subscriptions/{id}/providers/Microsoft.CostManagement/query`, `2023-03-01`. [Query Usage](https://learn.microsoft.com/rest/api/cost-management/query/usage?view=rest-cost-management-2023-03-01) | Daily·ResourceId·UsageDate·Cost·Currency. App Service site와 serverFarmId 대조, 공유 모델·모니터링 비용 중복 귀속 금지 |
| 예산 | GET `/subscriptions/{id}/providers/Microsoft.Consumption/budgets`, `2023-05-01`. [List·필드 정의](https://learn.microsoft.com/en-us/rest/api/consumption/budgets/list?view=rest-consumption-2023-05-01) | `properties.amount·category·timePeriod.startDate/endDate·filter·notifications` 확인. notifications의 `enabled·threshold·thresholdType=Actual/Forecasted`와 `contactEmails·contactGroups·contactRoles` 존재 확인. 수신자 값 대신 존재 여부·개수만 저장 |
| 작업 그룹 | GET `{actionGroupResourceId}`, `2021-09-01`. [Get·필드 정의](https://learn.microsoft.com/en-us/rest/api/monitor/action-groups/get?view=rest-monitor-2021-09-01) | `properties.enabled`와 `emailReceivers·smsReceivers·webhookReceivers·armRoleReceivers·azureFunctionReceivers·logicAppReceivers·itsmReceivers` 대조. 수신자 status가 있는 유형은 Enabled 확인. 그룹 비활성·수신자 비활성은 전달 경로 충족 아님 |
| 정책 할당 참고 | GET `/subscriptions/{id}/providers/Microsoft.Authorization/policyAssignments?$filter=atScope()`, `2023-04-01`. [List](https://learn.microsoft.com/rest/api/policy/policy-assignments/list?view=rest-policy-2023-04-01) | 할당·enforcementMode만으로 Deny 효과·자동 교정 추론 금지. 모델 허용 목록 등급에 미사용 |

### Foundry 역할과 초기 프로필

- [Foundry RBAC](https://learn.microsoft.com/azure/foundry/concepts/rbac-foundry)의 Reader는 관리 평면만 허용합니다. [평가 권한 안내](https://learn.microsoft.com/azure/foundry/observability/how-to/evaluation-permissions)는 최소 읽기 역할 보장이 아닙니다.
- [Foundry User](https://learn.microsoft.com/azure/role-based-access-control/built-in-roles/ai-machine-learning#foundry-user)는 `accounts/listkeys/action`, `Microsoft.Resources/deployments/*`, `Microsoft.CognitiveServices/*` 등 광범위 작업을 포함해 진단 계정에 부여하지 않습니다.
- [공식 공급자 작업](https://learn.microsoft.com/azure/role-based-access-control/permissions/ai-machine-learning#microsoftcognitiveservices)의 agents/read·evaluations/read를 확인했습니다. 신규 평가 목록 403에서 assets/read 요구를 실측해 v2 읽기 역할에 추가했으며 기존 v1은 변경하지 않았습니다. 수집기는 평가 관련 목록만 호출합니다.
- agents/read에는 threads/messages 읽기도 포함됩니다. 더 세밀한 Agent 메타데이터 전용 DataAction을 추측하지 않으며 실제 서비스 인가·테넌트 상태는 사전 점검으로 확인합니다. 사용자 지정 역할의 AssignableScopes는 입력 구독이며 현재 기본 할당은 승인 구독 상속입니다. [사용자 지정 역할 규칙](https://learn.microsoft.com/azure/role-based-access-control/custom-roles).
- 클래식은 명시적 `classic_v1`에서만 GET `/assistants?api-version=v1` 사용. [azure-ai-agents 1.1.0 연산](https://github.com/Azure/azure-sdk-for-python/blob/azure-ai-agents_1.1.0/sdk/ai/azure-ai-agents/azure/ai/agents/operations/_operations.py), [설정](https://github.com/Azure/azure-sdk-for-python/blob/azure-ai-agents_1.1.0/sdk/ai/azure-ai-agents/azure/ai/agents/_configuration.py).
- 초기 평가 `/evaluations/runs?api-version=2025-05-15-preview`는 이력이며 현재 신규 프로필로 자동 대체·역전환하지 않습니다. [azure-ai-projects 1.0.0b11 연산](https://github.com/Azure/azure-sdk-for-python/blob/azure-ai-projects_1.0.0b11/sdk/ai/azure-ai-projects/azure/ai/projects/operations/_operations.py), [설정](https://github.com/Azure/azure-sdk-for-python/blob/azure-ai-projects_1.0.0b11/sdk/ai/azure-ai-projects/azure/ai/projects/_configuration.py).
- Red team은 실제 읽기 SP의 공식 GET `/redTeams/runs?api-version=v1` 요청이 HTTP 401과 evaluations/write 요구로 거부되어 제외했습니다. 쓰기 권한 확대·일반 평가로 대체하지 않습니다.

### Entra Agent ID 계약

| 조회 | Graph v1.0 읽기 계약 |
| --- | --- |
| Blueprint | GET `/applications/microsoft.graph.agentIdentityBlueprint`, `AgentIdentityBlueprint.Read.All`. [공식 목록](https://learn.microsoft.com/graph/api/agentidentityblueprint-list) |
| Agent ID | GET `/servicePrincipals/microsoft.graph.agentIdentity`, `AgentIdentity.Read.All`. [공식 목록](https://learn.microsoft.com/graph/api/agentidentity-list) |
| 소유자·후원자 | GET `/servicePrincipals/{id}/microsoft.graph.agentIdentity/owners` 또는 `/sponsors`, `$select=id,accountEnabled`. 사람 이름·UPN 없이 관계 수를 보관. accountEnabled는 기본 권한에서 제한될 수 있는 참고 속성이며 OE-SY-20 충족 조건에 미사용 |
| 앱 역할 | GET `/servicePrincipals/{id}/appRoleAssignments`, `Application.Read.All`. 대상 리소스 SP의 `appRoles`로 역할 이름 해석 |
| 제외 | 위임 동의는 Directory.Read.All로 범위를 넓혀야 하므로 수집 안 함. ARM 관리 ID를 Graph Agent Identity로 간주하지 않음 |

- 모든 Graph 진단 호출은 GET이며 `graph.microsoft.com`에만 토큰을 보냅니다. 2026-11-04 승인된 읽기 조회에서 Agent ID 9개·Blueprint 9개를 확인했으며 태그의 구독·계정·프로젝트·Agent 식별자로 매칭했습니다.

### 의미 해석의 공식 근거

| 주제 | 근거·한계 |
| --- | --- |
| 네트워크 | [AI 네트워크 규칙](https://learn.microsoft.com/en-us/azure/ai-services/cognitive-services-virtual-networks), [App Service VNet](https://learn.microsoft.com/en-us/azure/app-service/overview-vnet-integration), [App Service 접근 제한·Unmatched rule](https://learn.microsoft.com/en-us/azure/app-service/overview-access-restrictions#unmatched-rule). 명시 `ipSecurityRestrictionsDefaultAction`이 우선하며 미지정 시 규칙 0개는 허용, 1개 이상은 암묵적 거부. Any·0.0.0.0/0·::/0 Allow 규칙은 경계로 인정하지 않음. VNet 통합은 송신 경로이며 인바운드 차단 증거 아님 |
| MCP | [도구 승인](https://learn.microsoft.com/en-us/agent-framework/agents/tools/tool-approval), [MCP 도구](https://learn.microsoft.com/en-us/azure/foundry/agents/how-to/tools/model-context-protocol). 승인 구성·HTTPS·allowed_tools는 런타임 우회 방지·송신 차단 보장 아님 |
| 콘텐츠 필터 | [기본값·설정](https://learn.microsoft.com/en-us/azure/ai-foundry/openai/how-to/content-filters?view=foundry-classic). 기본 필터도 존재할 수 있어 raiPolicyName 미지정을 실제 필터 부재라고 단정하지 않음 |
| 모델 업데이트 | [버전·업데이트](https://learn.microsoft.com/en-us/azure/ai-foundry/openai/concepts/model-versions?view=foundry-classic). NoAutoUpgrade는 영구 고정·퇴역 후 롤백 보장 아님 |
| 메타데이터 | [Agent 거버넌스](https://learn.microsoft.com/en-us/azure/cloud-adoption-framework/ai-agents/governance-security-across-organization). 상위 ARM 태그를 개별 Agent 승인으로 간주하지 않음 |
| 정책 평가 | [정책 효과](https://learn.microsoft.com/en-us/azure/governance/policy/concepts/effect-basics). Audit·Deny·Modify·DeployIfNotExists는 서로 다르며 준수 상태가 자동 교정을 입증하지 않음 |
| ID·로컬 인증 | [PIM 역할](https://learn.microsoft.com/en-us/entra/id-governance/privileged-identity-management/pim-resource-roles-assign-roles), [로컬 인증 비활성](https://learn.microsoft.com/en-us/azure/ai-services/disable-local-auth). 관리 ID 구성은 실제 사용·전체 최소 권한 증거 아님 |
| 관측·경보 | [trace 설정](https://learn.microsoft.com/en-us/azure/foundry/observability/how-to/trace-agent-setup), [작업 그룹](https://learn.microsoft.com/en-us/azure/azure-monitor/alerts/action-groups). 리소스·연결 존재가 실제 trace·전달·대응 성공 아님 |
| 지역·보존 | [모델 지역](https://learn.microsoft.com/en-us/azure/foundry/foundry-models/concepts/models-sold-directly-by-azure-region-availability), [테이블 보존](https://learn.microsoft.com/en-us/azure/azure-monitor/logs/data-retention-configure). Global·Data Zone의 처리 지역과 workspace·테이블 보존 구분 |
| 예산 | [예산 동작·평가 주기](https://learn.microsoft.com/en-us/azure/cost-management-billing/costs/tutorial-acm-create-budgets). 비용 갱신·평가 지연 존재. 예산은 통보 수단이며 초과 지출·리소스를 자동 중단하지 않음 |

## 관리자 데모의 공식 계약·실측 경계

이 절은 관리자 샘플 준비 이력이며 고객 진단의 쓰기 권한이나 현재 등급 근거가 아닙니다.

| 준비·검증 | 계약·공식 근거 |
| --- | --- |
| 웹 로그인 보호 | App Service `config/authsettingsV2`, ARM `2024-11-01`. 인증 필수·동일 tenant issuer·allowedPrincipals.identities, `/health`만 예외. [스키마](https://learn.microsoft.com/azure/templates/microsoft.web/sites/config-authsettingsv2) |
| 비밀번호 없는 로그인 | `OVERRIDE_USE_MI_FIC_ASSERTION_CLIENTID`, registration.clientSecretSettingName·앱 전용 User Assigned MI·Graph federatedIdentityCredential. [MI 로그인](https://learn.microsoft.com/azure/app-service/configure-authentication-provider-aad#use-a-managed-identity-instead-of-a-secret), [신뢰](https://learn.microsoft.com/entra/workload-id/workload-identity-federation-config-app-trust-managed-identity) |
| 앱 등록 | Graph v1.0 applications·servicePrincipals·federatedIdentityCredentials. 단일 테넌트·승인 redirect URL·소유 표식이 있는 샘플 앱만 재사용. [앱](https://learn.microsoft.com/graph/api/application-post-applications?view=graph-rest-1.0), [연합 자격증명](https://learn.microsoft.com/graph/api/application-post-federatedidentitycredentials?view=graph-rest-1.0) |
| 샘플 평가 | OpenAI-compatible evals·runs, custom item_schema·string_check(eq)·jsonl/file_content로 실제 응답·정답 비교. 관리자만 terminal status·output_items 조회. [정의](https://learn.microsoft.com/azure/foundry/reference/rest/evals-create-eval), [실행](https://learn.microsoft.com/azure/foundry/reference/rest/evals-create-eval-run), [데이터셋](https://learn.microsoft.com/azure/foundry/observability/how-to/cloud-evaluation-datasets) |
| 런타임 | SDK responses.create·LangChain create_agent. 웹 앱 MI가 추론하고 진단 SP는 추론하지 않음 |
| 인증서 | Graph application GET `$select=keyCredentials`로 기존 공개키를 보존하고 이번 임시 UUID만 추가·제거. 확보 불가 시 수정 안 함. 만료는 실제 not_valid_after_utc와 일치. [앱 갱신](https://learn.microsoft.com/graph/api/application-update?view=graph-rest-1.0), [keyCredential](https://learn.microsoft.com/graph/api/resources/keycredential?view=graph-rest-1.0) |
| 배포 확인 | 공식 Kudu ZIP의 이번 새 작업 ID·status=4·complete=true·실제 health 확인. 다른 origin·HTTP Location에 bearer 전송 금지. [Kudu API](https://github.com/projectkudu/kudu/wiki/Deploying-from-a-zip-file-or-url) |

- 모델 목록·쿼터만으로 신규 배포 가능성을 확정하지 않았습니다. Korea Central validate의 ServiceModelDeprecating 응답 뒤 validate를 통과한 gpt-4.1-nano 2025-04-14 GlobalStandard로 샘플을 변경했으며 지역은 유지했습니다.
- Oryx 설치 지연은 사전 패키징한 Linux wheel로 전환해 ELF x86_64·ZIP 무결성을 확인했습니다. ZIP 완료만으로 새 프로세스 실행을 단정하지 않고 명시적 재시작·새 revision·health를 확인했습니다.
- callback 401에서 Easy Auth의 `response_type=code id_token`을 확인해 ID 토큰 발급·기본 로그인 동의를 완료했으며 access token implicit은 껐습니다.
- 빈 POST 403은 no-referrer와 CSRF 검사 충돌로 same-origin을 적용했습니다. 플랫폼 CSRF는 끄지 않았으며 forwarded 헤더 대신 WEBSITE_HOSTNAME의 HTTPS 원점과 비교했습니다.
- 오래된 CLI CAE 토큰은 동일 관리자 DefaultAzureCredential로 Graph를 호출했습니다. 인증서 전파 AADSTS700027만 제한 재시도하며 다른 신원·관리자 토큰으로 진단 수집을 대체하지 않았습니다.
- 소형 모델 요청 한도·새 endpoint 공개 여부를 구분하고 연결 후 요청했으며 429만 제한 대기했습니다. 실패 문항도 보존하고 정확 일치 실패를 보안 위험 확정으로 바꾸지 않았습니다.
- 정확 일치 3문항은 포괄적 보안·품질 검증이 아닙니다. 관리자 published_at·관측 완료 시각은 운영 배포 서비스 증거가 아니며 Reader 판정에 자동 주입하지 않습니다.
- 당시 비용 행 없음·승인 범위 밖 중앙 로그·AI 권고/활성화 미확인은 각각 원래 null 사유로 보존했습니다. 인증서 등록은 관리자 준비이며 진단 SP에 Graph 쓰기를 부여하지 않습니다. 동일 앱 인증서를 동시에 변경하는 준비 실행은 피합니다.

## 미확정 범위와 이기종 Agent

- 게시·운영 배포 API와 Agent-평가-배포 lineage는 추가 검증이 필요합니다. created_at을 배포 시각으로 바꾸지 않으며 프로젝트 완료 평가를 배포 전 평가로 해석하지 않습니다.
- 메트릭 dimension의 Agent 식별력·90일 미사용 증명 가능성은 확정하지 않았습니다. 현재 지표는 리소스 단위 수치 표본 관측 범위입니다.
- Purview 감사의 Graph auditLogQuery는 질의 생성 POST이고 Agent 활동 유형·보존 정책 근거가 미확정입니다. DSPM for AI 읽기 API·Power Platform Maker 수·데이터 정책·관리형 환경 값은 미확정이며 비공식 BAP admin API를 사용하지 않습니다.
- 모든 권한이 있어도 제품 기능·라이선스·데이터가 없을 수 있습니다. 403은 IAM·방화벽·Private Endpoint 모두 가능하며 permission_denied로 남기되 원인을 단정하지 않습니다. license_missing은 명시적 라이선스 상태 응답에만 사용합니다.
- LangChain 앱 설정 list는 비밀을 반환할 수 있어 기본 수집에서 호출하지 않습니다. 승인 태그·메타데이터 또는 명시적 CSV 입력을 사용합니다.
- 공통 AgentEvidence는 platform과 필드별 null 사유로 플랫폼 차이를 보존합니다. 같은 이름의 Foundry Agent도 platform·subscription_id·resource_id·agent_id 복합 키로 구분하며 비용·사용량의 공유 리소스 중복 귀속을 금지합니다.
- `wasm-agent collect --manual-agents config/manual_agents.csv`는 manual/other 플랫폼의 직접 등록입니다. Google/AWS 자동 로그인 수집이 아닙니다. 최소 필드는 agent_id·agent_name·platform이며 날짜는 시간대 포함 ISO 8601, tags·tools·usage_30d·field_status는 JSON입니다.
- 빈 CSV 값은 null + not_found이며 0으로 채우지 않습니다. 수동 Agent는 인벤토리·플랫폼 개수에만 포함하고 Azure 전용 SE 분모에 섞지 않으며 CSV 행 evidence_refs로 API 실측과 구분합니다.
- 확장 Collector Protocol은 `discover(subscriptions)`와 `required_roles`를 사용합니다. 사례 커넥터 매핑·API Management AI Gateway·OpenTelemetry gen_ai 연계는 재사용 후보이며 구현·검증 완료로 표시하지 않습니다.
