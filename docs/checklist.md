# 점검 항목 상세 (System Evidence 31개)

항목별 점검 내용, Azure Portal 기준 확인 경로, 확인 화면입니다. 요약표는 [README](../README.md#점검-항목-system-evidence-31개)에 있습니다.

- 구현 표기: ✅ 구현 / ⚠️ 보조 증거 부분 수집·점수 보류 / ❌ 미구현
- Azure Portal 기준(참고): 같은 값을 사람이 포털에서 확인하는 경로와 캡처이며 수집기 동작에는 영향이 없습니다
- 캡처의 빨간 네모는 확인 위치이고 식별자는 마스킹했습니다. 표시 값은 데모 환경 기준이며 고객 환경과 다를 수 있습니다
- 22개 등급 산정 항목은 [API 평가 기준](api-notes.md#심사기준-검토와-점수-반영-2026-11-05)을 따릅니다. 6개는 보조 증거만 수집하며, DM-SY-01·03·OT-SY-27은 미구현입니다. [관리자 읽기 내보내기](api-notes.md#관리자-읽기-내보내기)는 진단 앱 권한을 확대하지 않습니다.

| API 충족률 | Level |
| --- | --- |
| 0% | L1 |
| 0% 초과~80% 미만 | L2 |
| 80% 이상~90% 미만 | L3 |
| 90% 이상~100% 미만 | L4 |
| 100% | L5 |

조회 실패·필수 필드 미확인·분모 0은 `null`과 사유로 남기며 L1이나 0%로 바꾸지 않습니다. 구성·기록의 충족률은 조직 승인, 정책 실효성, 자동화 동작을 입증하지 않습니다. 고객의 정성 입력은 등급에 반영하지 않습니다.

## Agent 365 등록부 교차 확인

| 순서 | M365 Admin Center 확인 위치 |
| --- | --- |
| 1 | [Microsoft 365 관리 센터](https://admin.microsoft.com/) 로그인 - **Agents > All agents > Registry** |
| 2 | 대상 Foundry Agent 선택 - **Details**에서 `Platform: Microsoft Foundry`, 패키지 버전·소유자·`Entra agent ID` 확인 |
| 3 | Entra agent ID를 기존 수집 ID와 대조. 패키지 버전은 Agent 실행 버전과 별개 |

![Agent 365 - 실제 Foundry Agent의 Details와 Entra agent ID 확인 위치](imgs/23-agent365-admin-details.png)

- 실제 테스트 화면이며 이름·계정·ID는 마스킹했습니다. 빨간 네모는 메뉴와 확인 위치입니다. 차단·삭제·동의 설정은 변경하지 않았습니다.
- 읽기 수집은 SDK 삽입 대신 공식 Graph 등록부 API를 사용합니다. DS-SY-05·DP-SY-19의 명시적 ID 연결만 일부 대조합니다. 나머지의 **동일 정보 미제공**은 Agent 365 등록부에 같은 판정 정보가 없다는 뜻이며, 기존 Azure/Graph API 평가는 그대로 수행합니다.
- 결과는 **7. 수집결과 근거 J~L열**과 **8. 수집 Raw 데이터**에 기록합니다. 일치 여부·라이선스·권한 실패는 기존 Level·점수를 변경하지 않습니다.

## DM-SY-01 Agent 제작 허용 사용자 범위 및 허용 Agent 유형 설정

- **진단 영역:** 1. Demand
- **제품/메뉴:** M365 Admin Center - Copilot > Agents 설정
- **구현:** ❌ 미구현
- **점검 내용:** Agent 제작을 허용한 사용자 범위(전체/특정 그룹), 허용 Agent 유형 설정값, 허용 그룹 구성원 수를 설정 화면에서 확인
- **Azure Portal 기준(참고):** 해당 없음 - Microsoft 365 관리 센터 > Copilot > 에이전트 설정

## DM-SY-02 Copilot Studio 제작 권한 보유자 수 및 환경 현황

- **진단 영역:** 1. Demand
- **제품/메뉴:** Power Platform Admin Center
- **구현:** ⚠️ 일부 구현
- **점검 내용:** 관리자 접근 가능 환경과 비 Dataverse 환경의 역할 할당 건수만 수집. 역할 할당 건수는 고유 Maker 수가 아니며 테넌트 전체 유효 권한은 미확인
- **Azure Portal 기준(참고):** 해당 없음 - Power Platform 관리 센터 > 환경

## DM-SY-03 최근 6개월 신규 생성 Agent 수 추이

- **진단 영역:** 1. Demand
- **제품/메뉴:** M365 Admin Center - Agent Registry
- **구현:** ❌ 미구현
- **점검 내용:** 월별 신규 Agent 생성 건수와 생성 요청 이력의 대사
- **Azure Portal 기준(참고):** 해당 없음 - Microsoft 365 관리 센터 > 에이전트 > 레지스트리

## DS-SY-04 커넥터 분류·차단 정책(데이터 정책) 적용 현황

- **진단 영역:** 2. Design
- **제품/메뉴:** Power Platform Admin Center - Data policies
- **구현:** ⚠️ 일부 구현
- **점검 내용:** 공식 Get-AdminDlpPolicy의 정책 객체 건수만 수집. 커넥터 분류·차단 및 환경별 준수 여부는 미확인
- **Azure Portal 기준(참고):** 해당 없음 - Power Platform 관리 센터 > 정책 > 데이터 정책

## DS-SY-05 Agent ID의 Blueprint 연결

- **진단 영역:** 2. Design
- **제품/메뉴:** Microsoft Entra Agent ID
- **구현:** ✅ 구현
- **점검 내용:** Graph Agent ID를 분모로 `agentIdentityBlueprintId`가 실제 Blueprint 목록에 연결되는 비율. Blueprint 개수나 대표 업무 유형 표준화·조직 승인은 평가하지 않음
- **Azure Portal 기준(참고):** Azure Portal > Microsoft Entra ID > Agent ID > Blueprint 목록

![DS-SY-05 확인 화면](portal/imgs/DS-SY-05.png)

## DS-SY-06 모델 배포 버전·업데이트 구성

- **진단 영역:** 2. Design
- **제품/메뉴:** Microsoft Foundry
- **구현:** ✅ 구현
- **점검 내용:** 모델 배포를 분모로 `model.name·version·format`과 기준에 정의된 `versionUpgradeOption`이 모두 있는 비율. 조직 허용 모델·퇴역 대응 완료 여부는 평가하지 않음
- **Azure Portal 기준(참고):** Azure Portal > Microsoft Foundry > (계정) > Go to Foundry portal > 모델 + 엔드포인트(배포 목록·업데이트 옵션)

![DS-SY-06 확인 화면](portal/imgs/DS-SY-06.png)

## DS-SY-07 AI 리소스 인바운드 경계 구성

- **진단 영역:** 2. Design
- **제품/메뉴:** Azure AI Services, App Service
- **구현:** ✅ 구현
- **점검 내용:** AI 계정·자체 Agent 호스트를 분모로 AI 계정의 공용 접근 비활성·Approved 프라이빗 연결, 호스트의 기본 거부 접근 제한 또는 비공개 ingress 구성 비율. App Service는 명시 기본값이 없으면 규칙 0개는 허용, 1개 이상은 암묵적 거부. Any·0.0.0.0/0·::/0 허용 규칙은 경계로 인정하지 않음. VNet 통합·HTTPS만으로 충족하지 않으며 실제 차단 효과는 입증하지 않음
- **Azure Portal 기준(참고):** Azure Portal > Microsoft Foundry > (계정) > Resource Management > Networking, App Service > (앱) > Networking

![DS-SY-07 확인 화면](portal/imgs/DS-SY-07.png)

## DS-SY-08 MCP 도구 필수 승인 모드

- **진단 영역:** 2. Design
- **제품/메뉴:** Microsoft Foundry Agent 정의
- **구현:** ✅ 구현
- **점검 내용:** Foundry Agent 최신 버전의 MCP 도구 선언을 분모로 `require_approval=always` 비율. `never`·명시적 객체형 `custom`은 미충족, 값 미확인은 `null`. 함수·내장 도구는 분모 제외. 런타임 승인 우회 방지는 입증하지 않음
- **Azure Portal 기준(참고):** Azure Portal > Microsoft Foundry > (계정) > Go to Foundry portal > (프로젝트) > Agents > (Agent) > Tools

![DS-SY-08 확인 화면](portal/imgs/DS-SY-08.png)

## DS-SY-09 외부 도구 HTTPS 연결 구성

- **진단 영역:** 2. Design
- **제품/메뉴:** Microsoft Foundry Agent 정의
- **구현:** ✅ 구현
- **점검 내용:** 명시적 외부 도구 URL을 분모로 HTTPS scheme·유효 hostname·userinfo 부재 비율. 경로·쿼리·인증값은 저장하지 않으며 업무 승인·상대 서버 신뢰·인증 성공은 입증하지 않음
- **Azure Portal 기준(참고):** Azure Portal > Microsoft Foundry > (계정) > Go to Foundry portal > (프로젝트) > Agents > (Agent) > Tools(MCP)

![DS-SY-09 확인 화면](portal/imgs/DS-SY-09.png)

## BI-SY-10 환경 분리 및 관리형 환경 적용 여부

- **진단 영역:** 3. Build
- **제품/메뉴:** Power Platform Admin Center
- **구현:** ⚠️ 일부 구현
- **점검 내용:** 환경 type·protectionLevel 원문만 수집. 개발·테스트·운영 분리와 관리형 운영 준수·파이프라인 이력은 미확인
- **Azure Portal 기준(참고):** 해당 없음 - Power Platform 관리 센터 > 환경 > 관리형 환경

## BI-SY-11 Foundry 프로젝트 평가 실행 이력

- **진단 영역:** 3. Build
- **제품/메뉴:** Microsoft Foundry
- **구현:** ✅ 구현
- **점검 내용:** Foundry 프로젝트를 분모로 `/openai/v1/evals`와 `/runs`에서 `completed` 또는 `succeeded` 실행을 보유한 비율. 프로젝트 읽기 역할 필요. 배포 전 평가·Agent 버전별 품질 통과율·자동 평가 파이프라인은 입증하지 않음
- **Azure Portal 기준(참고):** Azure Portal > Microsoft Foundry > (계정) > Go to Foundry portal > Build > Evaluations

![BI-SY-11 확인 화면](portal/imgs/BI-SY-11.png)

## BI-SY-12 AI 리소스 보안 권고 상태

- **진단 영역:** 3. Build
- **제품/메뉴:** Microsoft Defender
- **구현:** ✅ 구현
- **점검 내용:** AI 리소스에 연결된 적용 가능 보안 권고를 분모로 `Healthy` 비율. `NotApplicable` 제외. 권고 없음은 100%가 아닌 `null`. 구독 보안 점수·권고 나이·조치 SLA는 채점하지 않음
- **Azure Portal 기준(참고):** Azure Portal > Microsoft Defender for Cloud > Recommendations(AI 리소스 필터), Security posture(보안 점수)

![BI-SY-12 확인 화면](portal/imgs/BI-SY-12.png)

## BI-SY-13 콘텐츠 필터 정책 연결

- **진단 영역:** 3. Build
- **제품/메뉴:** Microsoft Foundry - 콘텐츠 필터
- **구현:** ✅ 구현
- **점검 내용:** 모델 배포를 분모로 `raiPolicyName`이 연결한 실제 정책을 조회하고 `contentFilters.enabled`를 대조한 활성 필터 연결 비율. 필터 값 미확인은 `null`. 정책명만으로 충족하지 않으며 실제 차단 효과·강도 승인은 입증하지 않음
- **Azure Portal 기준(참고):** Azure Portal > Microsoft Foundry > (계정) > Go to Foundry portal > Build > Guardrails(콘텐츠 필터)

![BI-SY-13 확인 화면](portal/imgs/BI-SY-13.png)

## BI-SY-14 Agent 버전·호스트 런타임 식별

- **진단 영역:** 3. Build
- **제품/메뉴:** Azure OpenAI 배포, App Service
- **구현:** ✅ 구현
- **점검 내용:** Foundry Agent·자체 호스트를 분모로 Agent `version`, App Service `linuxFxVersion` 또는 Container Apps 이미지 sha256 다이제스트 식별 비율. 소스·빌드 출처·운영 배포 승인·롤백 기록은 입증하지 않음
- **Azure Portal 기준(참고):** Azure Portal > Microsoft Foundry > (계정) > Go to Foundry portal > 모델 + 엔드포인트(버전 업데이트 정책), App Service > (앱) > Settings > Configuration > Stack settings

![BI-SY-14 확인 화면](portal/imgs/BI-SY-14.png)

## BI-SY-15 Agent 책임·환경·비용 메타데이터

- **진단 영역:** 3. Build
- **제품/메뉴:** Azure 리소스 태그
- **구현:** ✅ 구현
- **점검 내용:** Azure Agent를 분모로 동일 Agent의 태그 또는 API metadata에 owner·sponsor·env·cost-center가 모두 존재하는 비율. 값의 업무 승인·인사 상태·자산 대장 대사는 입증하지 않음
- **Azure Portal 기준(참고):** Azure Portal > Microsoft Foundry 또는 App Service > (리소스) > Tags

![BI-SY-15 확인 화면](portal/imgs/BI-SY-15.png)

## BI-SY-16 AI 리소스 정책 평가 준수

- **진단 영역:** 3. Build
- **제품/메뉴:** Azure Policy
- **구현:** ✅ 구현
- **점검 내용:** 정책 평가가 있는 AI 관련 리소스를 분모로 해당 리소스의 모든 `policyStates` 평가가 `Compliant`인 비율. `Exempt`·`Unknown`·평가 없음은 준수로 간주하지 않으며 정책 자동 교정은 입증하지 않음
- **Azure Portal 기준(참고):** Azure Portal > Policy > Compliance

![BI-SY-16 확인 화면](portal/imgs/BI-SY-16.png)

## DP-SY-17 전체 Agent 목록과 배포 범위·게시 상태·소유자

- **진단 영역:** 4. Deploy
- **제품/메뉴:** M365 Admin Center - Agent Registry
- **구현:** ⚠️ 일부 구현 - 등록부 정보만 부분 수집, 점수 보류
- **점검 내용:** 공식 등록부 API의 패키지 이름·플랫폼·버전·배포 범위·차단 상태 수집. 미등록 Agent 탐지·운영 소유자·승인 등록부 정합성은 입증하지 않음. [실제 확인 화면](#agent-365-등록부-교차-확인)
- **Azure Portal 기준(참고):** 해당 없음 - Microsoft 365 관리 센터 > 에이전트 > 레지스트리

## DP-SY-18 Agent 공유 허용 범위 및 사용자 설치 허용 설정

- **진단 영역:** 4. Deploy
- **제품/메뉴:** M365 Admin Center - Copilot > Agents 설정
- **구현:** ⚠️ 일부 구현 - 패키지 접근·배포 상태만 부분 수집, 점수 보류
- **점검 내용:** 공식 등록부 API의 availableTo·deployedTo·isBlocked 수집. 테넌트 제작·직접 설치 정책 또는 승인된 사용자 범위와의 일치는 입증하지 않음. [실제 확인 화면](#agent-365-등록부-교차-확인)
- **Azure Portal 기준(참고):** 해당 없음 - Microsoft 365 관리 센터 > Copilot > 에이전트 설정

## DP-SY-19 Azure Agent의 Entra Blueprint 귀속

- **진단 영역:** 4. Deploy
- **제품/메뉴:** Microsoft Entra Agent ID
- **구현:** ✅ 구현 - 현재 API 기준 완료, 연결 충족률과 구현 여부는 별개
- **점검 내용:** Azure Agent를 분모로 Blueprint 태그의 subscriptionId·accountName·projectName·agentName을 Foundry Agent와 정확 대조하고 실제 Agent ID가 해당 Blueprint를 참조하는 귀속 비율. Entra Agent ID·Blueprint 전체 조회 완료 필요. LangChain 관리 ID를 Entra Agent ID로 대신 간주하지 않으며 Registry 전체를 분모로 쓰지 않음
- **Azure Portal 기준(참고):** Azure Portal > Microsoft Entra ID > Agent ID > 에이전트 ID 목록. 포털은 Foundry 프로젝트 관리 ID(`.../projects/<프로젝트>`)도 목록에 함께 표시하므로 수집 개수(Agent ID 9)보다 1개 많게(10) 보임

![DP-SY-19 확인 화면](portal/imgs/DP-SY-19.png)

## OE-SY-20 Agent ID 소유자·스폰서 연결

- **진단 영역:** 5. Operate
- **제품/메뉴:** Microsoft Entra Agent ID
- **구현:** ✅ 구현
- **점검 내용:** Graph Agent ID를 분모로 실제 owners·sponsors 수가 각각 1개 이상인 비율. 기본 Graph 읽기 권한에서 소유자 사용자 속성이 제한될 수 있어 `accountEnabled`는 충족 조건이 아님. 이름·UPN 미저장. 계정 활성 상태·퇴사자 판정·인사 대사는 입증하지 않음
- **Azure Portal 기준(참고):** Azure Portal > Microsoft Entra ID > Agent ID > (에이전트 ID) > 소유자/스폰서

![OE-SY-20 확인 화면](portal/imgs/OE-SY-20.png)

## OE-SY-21 Agent ID 앱 역할 읽기 범위

- **진단 영역:** 5. Operate
- **제품/메뉴:** Microsoft Entra - Agent ID, ID Governance
- **구현:** ✅ 구현
- **점검 내용:** Graph Agent ID를 분모로 `appRoleAssignments`의 실제 역할 이름을 해석해 기준 파일의 쓰기·전체제어 패턴에 해당하는 앱 역할이 없는 비율. ARM·위임·앱 내부 권한은 포함하지 않음
- **Azure Portal 기준(참고):** Azure Portal > Microsoft Entra ID > Agent ID > (에이전트 ID) > 권한

![OE-SY-21 확인 화면](portal/imgs/OE-SY-21.png)

## OE-SY-22 Agent 리소스 실행 로그 연결

- **진단 영역:** 5. Operate
- **제품/메뉴:** Azure Monitor - Diagnostic settings
- **구현:** ✅ 구현
- **점검 내용:** AI 계정·자체 Agent 호스트를 분모로 활성 로그와 Log Analytics `workspaceId` 연결 비율. 구독 공통 Activity Log·Purview 감사 제외. 실제 이벤트 유입·테이블 유효 보존기간은 입증하지 않으며 승인 구독 밖 workspace는 권한 제한 사유를 보존
- **Azure Portal 기준(참고):** Azure Portal > Microsoft Foundry > (계정) > Monitoring > Diagnostic settings, Log Analytics workspaces > (workspace) > Tables(보존 기간)

![OE-SY-22 확인 화면](portal/imgs/OE-SY-22.png)

## OE-SY-23 관리 ID·키 인증·직접 ARM 역할 구성

- **진단 영역:** 5. Operate
- **제품/메뉴:** Azure Resource Graph, Azure RBAC
- **구현:** ✅ 구현
- **점검 내용:** AI 계정·자체 Agent 호스트를 분모로 관리 ID 존재·광범위 직접 ARM 역할 없음·AI 계정의 `disableLocalAuth=true` 충족 비율. 동일 구독 직접 할당만 보며 타 구독·상속·데이터 평면 역할과 실제 인증 사용은 포함하지 않음
- **Azure Portal 기준(참고):** Azure Portal > Microsoft Foundry > (계정) > Resource Management > Identity, Access control (IAM) > Role assignments, Keys and Endpoint

![OE-SY-23 확인 화면](portal/imgs/OE-SY-23.png)

## OE-SY-24 AI 리소스 활성 경보 범위

- **진단 영역:** 5. Operate
- **제품/메뉴:** Azure Monitor
- **구현:** ✅ 구현
- **점검 내용:** AI 계정·자체 Agent 호스트를 분모로 활성 metricAlerts·scheduledQueryRules·activityLogAlerts의 `scopes`가 실제 리소스 ID를 포함하는 비율. 경보 발생·SLO 충족·trace 유입은 입증하지 않음
- **Azure Portal 기준(참고):** Azure Portal > Monitor > Alerts > Alert rules, Application Insights, Microsoft Foundry > (계정) > Monitoring > Diagnostic settings

![OE-SY-24 확인 화면](portal/imgs/OE-SY-24.png)

## OE-SY-25 AI 경보의 작업 그룹·수신자 연결

- **진단 영역:** 5. Operate
- **제품/메뉴:** Azure Monitor - 작업 그룹
- **구현:** ✅ 구현
- **점검 내용:** AI 대상 경보를 분모로 활성 경보에 존재하는 작업 그룹과 활성 수신자가 연결된 비율. 수신자 주소·이름 미저장. 실제 전달 성공·온콜 대응 시간·복구 시험은 입증하지 않음
- **Azure Portal 기준(참고):** Azure Portal > Monitor > Alerts > Action groups

![OE-SY-25 확인 화면](portal/imgs/OE-SY-25.png)

## OE-SY-26 리소스 지역·workspace 보존 구성

- **진단 영역:** 5. Operate
- **제품/메뉴:** Azure 리소스 위치, Log Analytics
- **구현:** ✅ 구현 - 현재 API 기준 완료, 보존 기준 충족률과 구현 여부는 별개
- **점검 내용:** AI 계정·자체 Agent 호스트를 분모로 지역 식별·활성 로그 연결 workspace의 보존 기준 충족 비율. 기본 기준은 `workspace_retention_target_days=90`. 실제 모델 처리 지역·테이블별 유효 보존·법적 삭제는 입증하지 않음
- **Azure Portal 기준(참고):** Azure Portal > Microsoft Foundry > (계정) > Overview(Location), Log Analytics workspaces > (workspace) > Tables(보존 기간)

![OE-SY-26 확인 화면](portal/imgs/OE-SY-26.png)

## OT-SY-27 승인되지 않은 Agent(Shadow AI) 탐지 결과

- **진단 영역:** 6. Optimize
- **제품/메뉴:** Agent 365 - Shadow AI Detection
- **구현:** ❌ 미구현
- **점검 내용:** Shadow AI 탐지 리포트와 미승인 Agent 목록 (Agent 365 라이선스 필요)
- **Azure Portal 기준(참고):** 해당 없음 - Agent 365 관리 화면 > Shadow AI

## OT-SY-28 AI 리소스 사용량 관측 범위

- **진단 영역:** 6. Optimize
- **제품/메뉴:** Azure Monitor - Metrics
- **구현:** ✅ 구현
- **점검 내용:** AI 계정·자체 Agent 호스트를 분모로 조회 기간(기본 30일)의 `metrics.timeseries.data`에 숫자 표본이 있는 비율. 값 0도 관측 표본이며 빈 시계열과 다름. Agent별 사용자 수·90일 미사용 여부는 평가하지 않음
- **Azure Portal 기준(참고):** Azure Portal > Microsoft Foundry > (계정) > Monitoring > Metrics, Logs

![OT-SY-28 확인 화면](portal/imgs/OT-SY-28.png)

## OT-SY-29 AI 비용의 단일 Agent 귀속

- **진단 영역:** 6. Optimize
- **제품/메뉴:** Azure Cost Management
- **구현:** ✅ 구현
- **점검 내용:** 동일 통화의 양수 AI 비용 금액을 분모로 일자가 존재하고 단일 Agent에 귀속되는 금액 비율(기본 30일). 공유 모델·모니터링 비용은 중복 배분하지 않으며 통화 혼재·음수 조정·분모 0은 `null`
- **Azure Portal 기준(참고):** Azure Portal > Cost Management > Cost analysis, Budgets

![OT-SY-29 확인 화면](portal/imgs/OT-SY-29.png)

## OT-SY-30 Agent가 접근하는 민감 데이터 노출 현황

- **진단 영역:** 6. Optimize
- **제품/메뉴:** Microsoft Purview - DSPM for AI
- **구현:** ⚠️ 일부 구현
- **점검 내용:** Purview 활동 탐색기의 AI 상호 작용·DLP 이벤트를 개인정보 없이 집계. 민감 정보·민감도 레이블은 실제 반환된 필드만 집계하며, 접근을 유출로 해석하거나 Agent별 노출·조치 완료로 판정하지 않음
- **Azure Portal 기준(참고):** 해당 없음 - Microsoft Purview 포털 > DSPM for AI

## OT-SY-31 구독 예산·실제·예측 경보 구성

- **진단 영역:** 6. Optimize
- **제품/메뉴:** Azure Cost Management
- **구현:** ✅ 구현
- **점검 내용:** 승인 구독을 분모로 현재 유효한 양수·무필터 `Cost` 예산에 활성 Actual·Forecasted 임계값 경보와 수신자가 모두 구성된 비율. Agent별 예산·실제 전달 성공·통보 후 자동 조치는 입증하지 않음
- **Azure Portal 기준(참고):** Azure Portal > Cost Management > Budgets

![OT-SY-31 확인 화면](portal/imgs/OT-SY-31.png)
