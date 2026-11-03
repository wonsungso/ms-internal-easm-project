# 이기종 Agent 수용

- 수집 대상: Azure·Microsoft Foundry Agent 및 공통 형식으로 수동 등록한 다른 플랫폼 Agent.

- Azure가 아닌 곳의 Agent도 **같은 목록에 함께 정리**할 수 있습니다. 현재는 CSV에 직접 적는 방식이며 Google/AWS 등에 자동 로그인해서 수집하는 기능은 아닙니다. 고객이 적어 준 값과 Azure API로 확인한 값을 보고서에서 구분합니다.

- **공통 스키마**
  - 적용: AgentEvidence의 platform 및 필드별 null 사유로 플랫폼 차이를 보존
- **수동 등록**
  - 적용: `wasm-agent collect --manual-agents templates/manual_agents.csv`; manual/other만 허용
- **확장 플러그인**
  - 적용: Collector Protocol의 discover(subscriptions), required_roles를 구현하고 공통 모델 반환
- **재사용 후보**
  - 적용: LG U+ Connector/ISD 사례의 커넥터·메타데이터 매핑을 조사할 자리. 현재 구현·검증 안 함
- **API Management AI Gateway**
  - 적용: 요청/모델/토큰 메타데이터의 공통 수집 가능성. 검증 필요
- **OpenTelemetry**
  - 적용: gen_ai 메타데이터 및 Agent 식별자를 연결할 가능성. 검증 필요

- 수동 CSV는 최소 agent_id, agent_name 및 manual/other 플랫폼을 입력합니다. 날짜는 시간대 포함 ISO 8601, tags/tools/usage_30d/field_status는 JSON을 사용합니다. 빈 값은 '확인 자료 없음'으로 표시하며 비용/사용량을 0으로 채우지 않습니다. 프로그램용 파일에는 이 상태가 `null`과 `not_found`로 저장됩니다.

- 이기종 Agent는 통합 인벤토리·플랫폼별 개수에 포함하지만 Azure 전용 SE의 분모에는 섞지 않습니다. 수동 입력은 자동 API 실측과 동일한 신뢰도로 표시하지 않으며 원본 CSV 행을 evidence_refs로 남깁니다.
