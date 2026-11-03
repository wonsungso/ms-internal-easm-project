# 설계

## 실행 경계

- **관리자 bootstrap**
  - 인증·권한: 관리자 디바이스 코드 로그인
  - 허용 작업: 승인된 샘플 배포, 역할, 일회성 공개 인증서 등록/정리
- **진단 수집기**
  - 인증·권한: DefaultAzureCredential + 진단 SP
  - 허용 작업: Reader 중심 GET 및 Resource Graph/비용/로그의 읽기 query POST만
- **샘플 Agent 런타임**
  - 인증·권한: 앱 Managed Identity
  - 허용 작업: 해당 모델의 제한된 추론, 합성 smoke 입력만

- 임시 인증서 개인키는 승인된 저장소 밖 사용자 전용 임시 경로에서만 사용합니다. 수집기에는 관리자 SDK/CLI·샘플 배포 모듈을 import하지 않습니다.

## 공통 모델

- `AgentEvidence`는 collected_at, tenant/subscription/resource_group, platform, agent_id/name/resource_id/hosting_type, owner/sponsor/tags, model/tools, created_at/last_used_at, cost_30d, usage_30d(calls,tokens), evaluated_before_deploy, guardrail_applied, detection_confidence, evidence_refs, se_codes, field_status를 포함합니다.

- **deployed_at**
  - 목적: 생성 시각을 배포 시각으로 대체하지 않음
- **model_version/model_resource_id**
  - 목적: 허용 모델 버전 대조, 공유 모델 비용·사용량의 오귀속 방지
- **currency**
  - 목적: 서로 다른 통화를 임의 합산하지 않음
- **calls_90d/usage_coverage_start**
  - 목적: 관측 누락을 비활성 0건으로 바꾸지 않음

- 보조 모델: ModelDeployment, EvaluationRun, CostRecord, SecurityRecommendation, LogSetting. 각 API의 실패는 Issue, 필드 누락은 null + FieldStatus로 기록합니다. 이기종은 같은 모델의 manual/other 플랫폼으로 수용하며 Azure 점수 분모에는 섞지 않습니다. 같은 이름의 Foundry Agent가 여러 프로젝트에 있을 수 있으므로 중복 키는 platform + subscription_id + resource_id + agent_id로 구성합니다.

## 수집·판정 흐름

- 설정 검증, 실제 credential의 tenant/object ID 일치 및 광범위 권한 거부.
- 접근 가능한 구독 자동 열거 또는 CLI로 제한, 구독별 병렬 처리.
- Resource Graph 인벤토리, 필요한 ARM 하위 리소스 목록으로 보완.
- Foundry 신규 Agent/버전, 모델 배포, 평가 및 LangChain 태그/이름 후보 정규화.
- 비용·메트릭·로그·보안 증적을 읽고 귀속 가능한 필드만 연결.
- criteria.yaml의 수치와 정성 조건을 평가, inventory.json/CSV와 report.md/summary.csv 출력.

- Collector Protocol: `discover(subscriptions) -> Collection`, `required_roles` 선언. Evaluator: `Collection + criteria.yaml -> Finding[]`; se_code, metric_value, level, rationale, evidence_refs, N/A 사유·다음 단계·interview_level·gap_flag를 반환합니다.

## 판정 원칙

- 원문이 비운 수치 구간은 임의 보간하지 않습니다. 증거 부족은 N/A와 추가 조건을 설명합니다.
- L4/L5 정성 조건은 외부 정책 증적의 명시적 입력을 요구하며 설정값만으로 정책 준수를 확정하지 않습니다.
- 평가 완료와 배포일 및 같은 Agent/버전 연결이 모두 있어야 배포 전 평가 여부를 계산합니다.
- 공유 리소스의 호출·토큰·비용을 여러 Agent에 중복 배분하지 않습니다.
- partial은 Azure 부분 범위의 초안입니다. Purview/조직 전체 결과로 재해석하지 않습니다.
- 신규 샘플은 30일 비용·90일 관측 기간을 충족하지 못할 수 있습니다.

- RBAC 상세: [rbac.md](rbac.md). API 버전·프로필 차이: [api-notes.md](api-notes.md).
