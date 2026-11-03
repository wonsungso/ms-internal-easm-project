# API 및 RBAC 확인 메모

- 초기 확인일: 2026-11-02. 초기 Step 0/0.5 메모를 보존하며, 아래 신규 프로필이 Step 1~9 구현의 기본입니다. 2026-11-03 승인된 대상 구독 샘플에서 신규 API·실제 수집을 검증했습니다. 이는 고객의 모든 서비스·버전에서 지원됨을 보장하지 않습니다.

## 신규 수집기 프로필 (2026-11-03)

- **실제 로컬 환경**
  - 사용 계약·근거: Python 3.11.18, azure-ai-projects 2.4.0, openai 2.54.0
- **신규 Agent**
  - 사용 계약·근거: project endpoint의 GET `/agents`, `/agents/{name}/versions`, api-version=v1. data/last_id/has_more 페이지 처리
- **Agent 개수**
  - 사용 계약·근거: 논리 Agent당 1건. 최신 보이는 버전 모델을 연결하며 버전 개수를 Agent 수로 부풀리지 않음. 최신 버전이 운영 배포라는 주장은 하지 않음
- **평가 목록**
  - 사용 계약·근거: GET `/openai/v1/evals`, `/openai/v1/evals/{id}/runs`. API 응답의 completed_at이 없으면 생성 시각으로 대체하지 않음
- **프로젝트 ARM**
  - 사용 계약·근거: 공급자 메타데이터와 공식 관리 SDK에서 확인한 accounts/projects 2025-06-01
- **모델 배포**
  - 사용 계약·근거: ARM deployments 2024-10-01. raiPolicyName은 연결 정책 존재만 의미하며 안전 통제의 실효성 입증이 아님
- **로그**
  - 사용 계약·근거: Log Analytics query, AppServiceConsoleLogs의 ResultDescription에서 샘플 Agent 이벤트 집계. 누락 토큰을 0으로 만들지 않음
- **공유 리소스**
  - 사용 계약·근거: App Service 비용은 site뿐 아니라 serverFarmId도 대조. 공유 모델·모니터링 비용은 여러 Agent에 중복 귀속하지 않음
- **클래식**
  - 사용 계약·근거: 명시적 classic_v1에서만 assistants 사용. 미지원 신규 API를 클래식으로 자동 변경하지 않음

- 공식 근거: [SDK 2.4 Agent 샘플](https://github.com/Azure/azure-sdk-for-python/blob/azure-ai-projects_2.4.0/sdk/ai/azure-ai-projects/samples/agents/sample_agent_basic.py), [관리 ARM 스펙](https://github.com/Azure/azure-rest-api-specs/blob/main/specification/cognitiveservices/resource-manager/Microsoft.CognitiveServices/CognitiveServices/stable/2025-06-01/cognitiveservices.json), [평가 SDK 안내](https://learn.microsoft.com/azure/foundry/observability/how-to/evaluate-agent), [AppServiceConsoleLogs 열](https://learn.microsoft.com/azure/azure-monitor/reference/tables/appserviceconsolelogs).

- gpt-4o-mini의 모델 목록·쿼터 존재만으로 신규 배포 가능성을 확정할 수 없었습니다. 실제 ARM validate가 ServiceModelDeprecating을 반환하여 동일 Korea Central에서 validate를 통과한 gpt-4.1-nano 2025-04-14 GlobalStandard로 샘플을 변경했습니다. 다른 지역으로 변경하지 않았습니다.

## 실측으로 보완한 계약

- 신규 OpenAI 호환 평가 목록의 403 응답이 `AIServices/assets/read`를 명시적으로 요구했습니다.
  공식 공급자 작업 목록에서도 확인해 v2 읽기 역할에 추가했습니다. 프로젝트 asset 메타데이터도
  읽을 수 있는 권한 단위이며, 수집기는 평가 관련 목록만 호출합니다. 기존 v1 정의는 변경하지 않았습니다.
- Azure Metrics가 `+00:00`의 `+`를 공백으로 재해석한 실제 400 응답을 확인했습니다.
  요청 timespan은 정규 UTC `YYYY-MM-DDTHH:MM:SSZ`로 전송합니다.
- 초기 Azure CLI 인증서 삭제 경로에는 `--cert`가 필요했습니다. 최종 자동화는 아래 공식 Graph 방식으로 변경했습니다.
- Entra 인증서 등록 전파 때문에 첫 토큰 요청이 실패할 수 있어 읽기 수집을 제한적으로 재시도합니다.
  자격증명을 관리자 토큰으로 대체하지 않습니다.
- App Service Oryx의 Python SDK 설치가 지연되어 사전 패키징된 Linux wheel 배포로 전환했습니다.
  실제 ELF x86_64와 ZIP 무결성을 확인하고 비동기 배포의 새 작업 ID·health를 별도 검증합니다.

## 챗봇 샘플 확장에 사용하는 공식 계약

- **로그인 보호**
  - 계약·근거·한계: App Service `config/authsettingsV2` ARM 2024-11-01. 인증 필수·동일 tenant issuer·allowedPrincipals.identities. /health만 인증 예외
- **비밀번호 없는 웹 로그인**
  - 계약·근거·한계: 공식 `OVERRIDE_USE_MI_FIC_ASSERTION_CLIENTID` 앱 설정 및 registration.clientSecretSettingName. 앱별 전용 User Assigned MI와 Graph federatedIdentityCredential 사용
- **앱 등록**
  - 계약·근거·한계: Graph v1.0 applications / servicePrincipals / applications/{id}/federatedIdentityCredentials. 단일 테넌트·승인된 redirect URL, 소유 표식이 있는 샘플 앱만 재사용
- **Foundry 평가**
  - 계약·근거·한계: OpenAI-compatible `/openai/v1/evals`와 `/runs`, custom item_schema + string_check(eq) + jsonl/file_content. 실제 응답·정답을 비교
- **평가 결과**
  - 계약·근거·한계: 관리자 샘플은 run terminal status 및 output_items 다운로드. 수집기는 run 목록의 result_counts(passed/failed/errored/total)와 Agent/버전 metadata만 읽고 질문/응답 본문은 조회하지 않음. completed_at이 없으면 추정하지 않음
- **배포 영수증**
  - 계약·근거·한계: 관리자 샘플의 published_at/관측 완료 시각은 운영 배포의 서비스 증거가 아님. Reader 판정에 자동 주입하지 않음
- **대화**
  - 계약·근거·한계: SDK responses.create + 기존 LangChain create_agent. 웹 앱 MI가 추론하고 진단 SP는 추론하지 않음

- 공식 근거: [App Service MI 로그인](https://learn.microsoft.com/azure/app-service/configure-authentication-provider-aad#use-a-managed-identity-instead-of-a-secret), [MI 신뢰 설정](https://learn.microsoft.com/entra/workload-id/workload-identity-federation-config-app-trust-managed-identity), [authsettingsV2 스키마](https://learn.microsoft.com/azure/templates/microsoft.web/sites/config-authsettingsv2), [Graph 앱 등록](https://learn.microsoft.com/graph/api/application-post-applications?view=graph-rest-1.0), [Graph 연합 자격증명](https://learn.microsoft.com/graph/api/application-post-federatedidentitycredentials?view=graph-rest-1.0), [평가 정의](https://learn.microsoft.com/azure/foundry/reference/rest/evals-create-eval), [평가 실행](https://learn.microsoft.com/azure/foundry/reference/rest/evals-create-eval-run), [데이터셋 평가](https://learn.microsoft.com/azure/foundry/observability/how-to/cloud-evaluation-datasets).

- 기본 원칙 응답의 정확 일치 검사 3문항은 포괄적 보안·품질 검증이 아닙니다. 고객용 보고서는 기계값을 한글로 설명하지만 JSON의 null·reason·N/A 계약은 유지합니다.

- 실제 웹 로그인·대화에서 확인한 사항:

- **로그인 callback 401**
  - 확인과 수정: Easy Auth가 `response_type=code id_token`을 요청함을 확인. 웹 앱 등록의 ID 토큰 발급을 활성화하고 기본 로그인 동의를 완료. access token implicit 발급은 끈 상태 유지
- **ZIP 완료인데 이전 health 화면**
  - 확인과 수정: ZIP과 서버 파일은 일치하지만 기존 Python 프로세스가 남아 있음을 확인. 명시적 앱 재시작 및 새 챗봇 revision을 확인해야 배포 완료 처리
- **POST가 빈 403**
  - 확인과 수정: `no-referrer`가 플랫폼 CSRF 검사와 충돌. 외부에는 referrer를 보내지 않고 같은 사이트 요청에만 보내는 `same-origin` 적용. CSRF 기능은 끄지 않음
- **앱이 같은 사이트 요청을 거부**
  - 확인과 수정: 외부 HTTPS와 내부 HTTP 프록시 경로 차이. 사용자 제공 forwarded 헤더 대신 플랫폼 WEBSITE_HOSTNAME의 HTTPS 원점과 비교
- **평가가 오래 걸림**
  - 확인과 수정: 소형 모델 요청 한도·새 endpoint 공개 여부를 구분. endpoint 연결 후 요청하고 429만 제한적으로 기다림

- 평가 실패 문항도 원본에 보존합니다. 정확 일치 검사의 실패를 보안 위험 확정으로 바꾸지 않습니다.

## 최종 실행에서 확인한 경계

- **Azure CLI Graph의 오래된 CAE 정책 토큰**
  - 처리: 정상 디바이스 재인증 후에도 `az ad`가 이전 토큰을 선택. 동일 관리자의 DefaultAzureCredential로 공식 Graph v1.0 GET/PATCH application.keyCredentials 사용
- **기존 인증서**
  - 처리: 개별 앱 GET `$select=keyCredentials`로 기존 공개키를 확보·보존하고 이번 임시 UUID만 추가/제거. 확보 불가 시 수정하지 않음
- **인증서 시각·전파**
  - 처리: Graph 만료는 실제 인증서 not_valid_after_utc와 일치. 전파 오류 AADSTS700027만 제한 재시도하며 다른 신원으로 대체하지 않음
- **Kudu**
  - 처리: 공식 ZIP API를 직접 호출. 이번 실행의 새 ID·status=4·complete=true·실제 health를 모두 확인. 다른 origin이나 HTTP Location에 bearer 전송 금지
- **중앙 로그**
  - 처리: 진단 설정의 sink가 선택 대상 구독 밖이면 추가 GET·권한 확대 없이 permission_denied. 설정 목록 성공과 sink 보존 기간 확보는 다름
- **실제 증거 제한**
  - 처리: 신규 비용 행 없음 3건, 범위 밖 중앙 로그 3건, AI 연결 Defender 권고/활성화 미확인 3건. null 사유 보존

- 공식 근거: [Graph application update](https://learn.microsoft.com/graph/api/application-update?view=graph-rest-1.0), [keyCredential](https://learn.microsoft.com/graph/api/resources/keycredential?view=graph-rest-1.0), [Kudu ZIP API](https://github.com/projectkudu/kudu/wiki/Deploying-from-a-zip-file-or-url). 인증서 등록은 관리자 bootstrap이며 진단 SP에 Graph 쓰기 권한을 부여하지 않습니다. 같은 앱의 인증서를 동시에 변경하는 bootstrap 실행은 피해야 합니다.

## 읽기 전용 Foundry 역할 결정

- [Foundry RBAC](https://learn.microsoft.com/azure/foundry/concepts/rbac-foundry)는 Reader가
   관리 평면의 프로젝트/계정을 읽지만 프로젝트 데이터 작업을 허용하지 않는다고 설명합니다.
- [평가 권한 안내](https://learn.microsoft.com/azure/foundry/observability/how-to/evaluation-permissions)는
   평가 실행/조회에 Foundry User 또는 동등 권한을 안내합니다. **읽기 전용 최소 역할을 보장하는 안내가 아닙니다.**
- [Foundry User 정의](https://learn.microsoft.com/azure/role-based-access-control/built-in-roles/ai-machine-learning#foundry-user)의
   역할 ID는 `53ca6127-db72-4b80-b1b0-d745d6d5456d`이며 다음 광범위 작업이 있습니다.
   `accounts/listkeys/action`, `Microsoft.Resources/deployments/*`, DataActions `Microsoft.CognitiveServices/*`.
   따라서 진단 계정에 부여하지 않습니다.
- [공식 공급자 작업 목록](https://learn.microsoft.com/azure/role-based-access-control/permissions/ai-machine-learning#microsoftcognitiveservices)에서
   `Microsoft.CognitiveServices/accounts/AIServices/agents/read`와
   `Microsoft.CognitiveServices/accounts/AIServices/evaluations/read`가 **DataAction**으로 등록되어 있음을 확인했습니다.
- 사용자 확인으로 사용자 지정 읽기 전용 역할 방식을 선택했습니다.
   [사용자 지정 역할 규칙](https://learn.microsoft.com/azure/role-based-access-control/custom-roles)에 따라
   관리 그룹이 아닌 입력 구독에 AssignableScopes를 설정하고 실제 할당은 프로젝트 scope로 제한합니다.
   역할 생성·할당은 관리자 예외이며 수집 계정이 수행하지 않습니다.

- 한계: agents/read에는 threads/messages 읽기도 포함됩니다. 더 세밀한 Agent 메타데이터 전용 DataAction을 추측해서 추가하지 않았습니다. 실제 서비스 인가·테넌트별 등록 상태는 사전 점검으로 확인해야 합니다.

## 사전 점검에 사용하는 REST 프로필

- **구독 자동 열거**
  - HTTP / 버전: GET `/subscriptions`, `2022-12-01`
  - 근거 및 한계: [Subscriptions List](https://learn.microsoft.com/rest/api/resources/subscriptions/list?view=rest-resources-2022-12-01); 지정 테넌트의 Enabled 구독만 사용
- **구독별 유효 권한 확인**
  - HTTP / 버전: GET `/subscriptions/{id}/providers/Microsoft.Authorization/permissions`, `2022-04-01`
  - 근거 및 한계: [Permissions List](https://learn.microsoft.com/rest/api/authorization/permissions/list-for-scope?view=rest-authorization-2022-04-01); 알려진 광범위/명시적 쓰기 권한의 안전 가드, 완전한 IAM 감사 아님
- **리소스 열거**
  - HTTP / 버전: GET `/subscriptions/{id}/resources`, `2021-04-01`
  - 근거 및 한계: [Resources List](https://learn.microsoft.com/rest/api/resources/resources/list?view=rest-resources-2021-04-01); ARM `nextLink` 처리
- **모델 배포**
  - HTTP / 버전: GET `{accountResourceId}/deployments`, `2024-10-01`
  - 근거 및 한계: [Deployments List](https://learn.microsoft.com/rest/api/aiservices/accountmanagement/deployments/list?view=rest-aiservices-accountmanagement-2024-10-01); `properties.model`, `sku`, `provisioningState`는 후속 수집기에서 사용 예정
- **Foundry Agent**
  - HTTP / 버전: GET `{projectEndpoint}/assistants?api-version=v1&limit=1`
  - 근거 및 한계: [공식 azure-ai-agents 1.1.0 연산 소스](https://github.com/Azure/azure-sdk-for-python/blob/azure-ai-agents_1.1.0/sdk/ai/azure-ai-agents/azure/ai/agents/operations/_operations.py), [설정 소스](https://github.com/Azure/azure-sdk-for-python/blob/azure-ai-agents_1.1.0/sdk/ai/azure-ai-agents/azure/ai/agents/_configuration.py); **클래식 assistants 프로필**. 신규 agents 버전 API로 자동 전환하지 않음
- **Foundry Evaluation**
  - HTTP / 버전: GET `{projectEndpoint}/evaluations/runs?api-version=2025-05-15-preview`
  - 근거 및 한계: [공식 azure-ai-projects 1.0.0b11 연산 소스](https://github.com/Azure/azure-sdk-for-python/blob/azure-ai-projects_1.0.0b11/sdk/ai/azure-ai-projects/azure/ai/projects/operations/_operations.py), [설정 소스](https://github.com/Azure/azure-sdk-for-python/blob/azure-ai-projects_1.0.0b11/sdk/ai/azure-ai-projects/azure/ai/projects/_configuration.py); 미리 보기 프로필, 현재 서비스의 지원 여부는 실측 필요
- **Defender 권고 접근 경로**
  - HTTP / 버전: POST Resource Graph `2022-10-01`, `securityresources`의 assessments 쿼리
  - 근거 및 한계: [Resource Graph Resources](https://learn.microsoft.com/rest/api/azureresourcegraph/resourcegraph/resources/resources?view=rest-azureresourcegraph-resourcegraph-2022-10-01), [SecurityResources 참조](https://learn.microsoft.com/azure/governance/resource-graph/reference/supported-tables-resources#securityresources); 직접 Defender AI 전용 API를 추측하지 않는 대안. 쿼리 성공이 AI 기능/라이선스 활성화 증거는 아님
- **진단 설정**
  - HTTP / 버전: GET `{resourceId}/providers/Microsoft.Insights/diagnosticSettings`, `2021-05-01-preview`
  - 근거 및 한계: [Diagnostic Settings List](https://learn.microsoft.com/rest/api/monitor/diagnostic-settings/list?view=rest-monitor-2021-05-01-preview); 구독 Activity Log 목적지와 리소스별 목적지 접근 점검
- **Log Analytics 워크스페이스 설정**
  - HTTP / 버전: GET `{workspaceResourceId}`, `2022-10-01`
  - 근거 및 한계: [Workspaces Get](https://learn.microsoft.com/rest/api/loganalytics/workspaces/get?view=rest-loganalytics-2022-10-01); 설정 읽기만 확인. 로그 내용/보호 테이블의 읽기 권한은 별도
- **Monitor 메트릭**
  - HTTP / 버전: GET `{resourceId}/providers/Microsoft.Insights/metrics`, `2018-01-01`
  - 근거 및 한계: [Metrics List](https://learn.microsoft.com/rest/api/monitor/metrics/list?view=rest-monitor-2018-01-01); 접근 점검만 수행. Agent별 호출/토큰/90일 데이터 존재를 보장하지 않음
- **비용 조회**
  - HTTP / 버전: POST `/subscriptions/{id}/providers/Microsoft.CostManagement/query`, `2023-03-01`
  - 근거 및 한계: [Query Usage](https://learn.microsoft.com/rest/api/cost-management/query/usage?view=rest-cost-management-2023-03-01); `Usage`, `Custom`, 최근 30일, `PreTaxCost` 합계 접근만 확인

- 위 Agent/Evaluation SDK는 **REST 프로필을 확인한 출처 버전**이며 설치 의존성이 아닙니다. 현재 실행 의존성은 `pyproject.toml`의 azure-identity와 requests입니다. 인증 구현은 DefaultAzureCredential만 사용하며 관리자 셋업의 Azure CLI는 명시된 예외입니다. Azure Public Cloud만 현재 지원합니다. 소버린 클라우드의 호스트·audience는 추측하지 않습니다.

## 구현하지 않은 API / 다음 단계 TODO

- 최신 Foundry Agent 버전/게시/배포 API 및 Agent-평가-배포 버전 연결: 실제 테스트베드의 API 프로필/샘플을 받은 후 확정.
- `created_at`은 Agent 생성 시각이며 배포 시각의 대용으로 사용하지 않음.
- 평가 성공 여부, 평가 종료 시각, 배포 버전 연결 키는 실제 API 응답으로 확인하기 전 확정하지 않음.
- Defender AI 활성화/라이선스 판정 및 AI 권고 필터는 실측/공식 근거 추가 확인 필요.
  권고가 없다는 이유로 고위험 권고 0건/보안 양호로 판단하지 않음.
- Metric 이름·dimension의 Agent 식별력, 마지막 사용일·90일 미사용 증명 가능성 검증 필요.
- LangChain 앱 설정은 list 액션으로 비밀을 반환할 수 있으므로 기본 수집에서 호출하지 않을 예정.
  승인된 태그/메타데이터 또는 수동 입력을 우선 사용.
- 사전 점검은 원본 데이터 수집기가 아니므로 응답 본문/대화/평가 데이터셋을 증적으로 저장하지 않음.
  후속 수집기는 `evidence/<timestamp>/`의 마스킹·민감필드 제외 정책을 먼저 구현해야 함.
- HTTP 403은 IAM과 Private Endpoint/방화벽 원인을 모두 점검해야 함. 현재 접근 실패 사유는
  `permission_denied`로 남기되 원인을 단정하지 않음.
- `license_missing`은 명시적 라이선스 상태 응답이 있을 때만 사용. 현재 사전 점검은 이 값을 추측하지 않음.
