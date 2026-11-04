# 설계, API 계약과 System Evidence 기준

- 수집 대상: Microsoft Foundry, Azure 자체 호스팅 Agent, Azure Monitor·Log Analytics, 비용·보안 권고.

- 기준 원본: `4) AI Agent Governance Readiness 진단_System Evidence 수집 기준.docx`. 평가 모델 XLSX의 `4. 질문별 평가 기준`에 있는 20개 SE 행의 L1~L5와 공백 차이를 제외하고 일치함을 변환 시 검증했습니다.
- 승인된 원본은 로컬 `docs/source`에 별도 보관하며 저장소에는 포함하지 않습니다. Codespaces에는 원본이 없어도 되므로 로컬 원본 파일을 문서 링크로 연결하지 않습니다.

## 범위 원칙

- in_scope 6개, partial 5개, out_of_scope 9개. out_of_scope는 문서에만 표시하며 수집·판정하지 않습니다.
- Entra Agent ID 항목(DS-SY-05, DP-SY-12, OE-SY-13~15)은 `--entra`로 명시할 때만 수집하며 진단 SP에 Graph 애플리케이션 읽기 권한과 관리자 동의가 필요합니다. 그 외 Azure 수집에는 Graph 권한이 필요 없습니다.
- Azure 인벤토리의 ID·소유자 태그는 Agent Registry와 퇴사자 확인을 대체하지 않습니다. 따라서 DM-SY-03, DP-SY-10을 Azure 인벤토리로 재해석하지 않습니다.
- partial의 수치와 L 레벨은 Azure 부분 범위의 초안이며 조직 전체 원 항목의 최종 점수가 아닙니다. 특히 OE-SY-16의 Azure 로그는 Purview Audit 보관을 입증하지 못합니다.
- L1~L5는 원문 그대로 보존합니다. 권한 거부·기능 미제공을 L1로 취급하지 않고 null 및 사유를 남깁니다. 실제 통제가 없다는 증거와 통제를 조회할 수 없다는 상태를 구분합니다.
- 예: DS-SY-06의 80% 초과~90% 미만, BI-SY-08의 30% 이상~80% 미만처럼 원문이 다루지 않는 구간은 임의로 L2/L3에 배정하지 않습니다. L4/L5의 자동화·정책·지속 운영은 비율만으로 충족 처리할 수 없습니다.
- OE-SY-16의 1년은 내부 규정의 예시이지 모든 고객에게 적용할 고정 임계값이 아닙니다. BI-SY-09의 내부 보안 점수 기준도 고객 입력이 필요합니다.
- 평가 원문은 인터뷰와의 괴리 시 영역 점수 보정도 설명하나, 이번 요청의 자동 기능은 괴리 플래그입니다. 영역 점수 자동 보정은 별도 승인 없이 구현하지 않습니다.

## 20개 항목

- **DM-SY-01**
  - 항목명: Agent 제작 허용 사용자 범위 및 허용 Agent 유형 설정
  - 유형: T1
  - 제품/메뉴: M365 Admin Center - Copilot &gt; Agents 설정
  - 측정방법: 타 담당 확인: Copilot &gt; Agents 설정 화면 캡처, 허용 그룹 구성원 목록; 본 프로젝트에서는 구현하지 않음
  - L1: 기본값(전 사용자 제작 허용) 그대로이며 설정 확인 불가
  - L2: 일부 유형만 제한, 제작 허용 사용자가 전체의 50% 이상
  - L3: 허용 사용자가 지정 그룹으로 제한되고 허용 Agent 유형이 정의됨
  - L4: 허용 그룹이 요청 승인과 연동되어 자동 관리, 비허용 제작 0건
  - L5: 설정 변경 이력을 정기 검토하고 위험 신호 시 자동으로 제한함
  - scope: out_of_scope
  - 분류 근거: 원 항목의 담당 제품은 M365 Admin Center - Copilot &gt; Agents 설정이며 Azure/Foundry 담당 범위가 아니다.
- **DM-SY-02**
  - 항목명: Copilot Studio 제작 권한 보유자 수 및 환경(Environment) 현황
  - 유형: T2
  - 제품/메뉴: Power Platform Admin Center
  - 측정방법: 타 담당 확인: PPAC 환경 목록, 환경별 Maker 역할 보유자 수; 본 프로젝트에서는 구현하지 않음
  - L1: 기본 환경만 사용, 사실상 전 직원이 제작 권한을 보유함
  - L2: 환경은 일부 분리됐으나 제작 권한자가 전 직원의 20% 이상
  - L3: 제작 권한자가 승인 인원과 일치하고 용도별 환경이 분리됨
  - L4: 권한 불일치 5% 미만, 신규 환경 생성은 관리자 승인으로만 가능
  - L5: 미사용 권한·환경을 자동 회수하고 월간 현황을 모니터링함
  - scope: out_of_scope
  - 분류 근거: 원 항목의 담당 제품은 Power Platform Admin Center이며 Azure/Foundry 담당 범위가 아니다.
- **DM-SY-03**
  - 항목명: 최근 6개월 신규 생성 Agent 수 추이 (요청 절차 대비 실제 생성 규모 비교)
  - 유형: T2
  - 제품/메뉴: M365 Admin Center - Agent Registry
  - 측정방법: 타 담당 확인: Agent Registry 월별 생성 건수 추출, 요청 이력과의 대사 결과; 본 프로젝트에서는 구현하지 않음
  - L1: 생성 추이 확인 불가 또는 요청 기록과 비교 불가
  - L2: 신규 생성 Agent 중 승인 요청과 매칭되는 비율 50% 미만
  - L3: 신규 생성 Agent의 80% 이상이 승인 요청과 매칭됨
  - L4: 매칭률 95% 이상, 미승인 생성이 자동 탐지·통보됨
  - L5: 매칭률 100% 유지, 생성 추이로 수요를 예측해 계획에 반영함
  - scope: out_of_scope
  - 분류 근거: 원 항목의 담당 제품은 M365 Admin Center - Agent Registry이며 Azure/Foundry 담당 범위가 아니다.
- **DS-SY-04**
  - 항목명: 커넥터 분류·차단 정책(데이터 정책) 적용 현황
  - 유형: T1
  - 제품/메뉴: Power Platform Admin Center - Data policies
  - 측정방법: 타 담당 확인: Data policies 목록, 정책별 적용 환경 범위; 본 프로젝트에서는 구현하지 않음
  - L1: 데이터 정책(DLP)이 하나도 설정되어 있지 않음
  - L2: 정책은 있으나 일부 환경(50% 미만)에만 적용됨
  - L3: 전 환경의 80% 이상에 커넥터 분류·차단 정책이 적용됨
  - L4: 전 환경 100% 적용, 신규 환경에 정책이 자동 상속됨
  - L5: 정책 위반 시도를 모니터링하고 정책을 분기별로 갱신함
  - scope: out_of_scope
  - 분류 근거: 원 항목의 담당 제품은 Power Platform Admin Center - Data policies이며 Azure/Foundry 담당 범위가 아니다.
- **DS-SY-05**
  - 항목명: Agent ID 템플릿(Blueprint) 정의 여부 및 개수
  - 유형: T3
  - 제품/메뉴: Microsoft Entra Agent ID
  - 측정방법: Graph v1.0 agentIdentityBlueprint 목록과 agentIdentity의 Blueprint 연결로 Blueprint 수·적용 비율 집계; 주요 유형별 정의·정기 개정은 고객 입력
  - L1: Agent ID 미사용 또는 Blueprint 정의 0개
  - L2: Blueprint 1~2개 시범 정의, 실제 적용 Agent는 소수
  - L3: 주요 유형별 Blueprint 정의, 신규 Agent의 50% 이상에 적용
  - L4: 신규 Agent의 90% 이상이 Blueprint 기반으로 생성됨
  - L5: Blueprint 사용 데이터로 템플릿을 정기 개정, 적용률 100% 유지
  - scope: in_scope
  - 분류 근거: Microsoft Entra Agent ID의 Blueprint는 Graph 읽기 권한으로 수집하며 진단 SP의 Graph 애플리케이션 권한과 관리자 동의가 필요하다.
- **DS-SY-06**
  - 항목명: 사용 중인 모델 배포 현황 및 허용 모델 목록
  - 유형: T2
  - 제품/메뉴: Microsoft Foundry
  - 측정방법: ARM 모델 배포 목록과 고객 허용 모델 목록을 모델·버전 기준 대조; 배포를 분모로 집계
  - L1: 모델 배포 현황 확인 불가, 허용 모델 목록 없음
  - L2: 배포 현황은 확인되나 허용 목록 외 모델 비율 20% 이상
  - L3: 배포 모델의 90% 이상이 허용 모델 목록과 일치함
  - L4: 허용 외 모델 배포 0건, 정책으로 배포 자체가 제한됨
  - L5: 모델별 사용량·성능을 모니터링해 교체·폐기를 선제 수행함
  - scope: in_scope
  - 분류 근거: Foundry 모델 배포 및 고객 허용 모델 목록이 Azure 담당 범위이다.
- **BI-SY-07**
  - 항목명: 환경 분리(개발 / 테스트 / 운영) 현황 및 관리형 환경(Managed Environment) 적용 여부
  - 유형: T2
  - 제품/메뉴: Power Platform Admin Center
  - 측정방법: 타 담당 확인: PPAC 환경 목록, 관리형 환경 설정, 파이프라인 이력; 본 프로젝트에서는 구현하지 않음
  - L1: 기본 환경 하나에서 모든 Agent를 개발·운영함
  - L2: 환경은 분리됐으나 관리형 환경 적용률 30% 미만
  - L3: 개발/테스트/운영 분리, 운영 환경의 관리형 환경 적용 100%
  - L4: 전 환경 관리형 적용, 파이프라인 외 운영 반영 0건
  - L5: 환경 사용량·위반 지표를 상시 모니터링하고 자동 조치함
  - scope: out_of_scope
  - 분류 근거: 원 항목의 담당 제품은 Power Platform Admin Center이며 Azure/Foundry 담당 범위가 아니다.
- **BI-SY-08**
  - 항목명: 품질·안전성 자동 평가(Evaluation) 수행 이력
  - 유형: T4
  - 제품/메뉴: Microsoft Foundry
  - 측정방법: 평가 이력을 Agent·배포 버전에 연결하고 성공 평가 종료일과 실제 배포일 비교; 생성일을 배포일로 대체하지 않음
  - L1: 평가(Evaluation) 수행 이력 없음
  - L2: 일부 Agent(30% 미만)만 수동으로 평가를 실행함
  - L3: 운영 Agent의 80% 이상이 배포 전 평가 이력을 보유함
  - L4: 배포 Agent 100% 평가, 파이프라인에서 자동 실행됨
  - L5: 운영 중 지속 평가로 품질 저하를 자동 탐지·알림함
  - scope: in_scope
  - 분류 근거: Foundry 평가 이력과 배포 전 평가 여부가 Azure 담당 범위이다.
- **BI-SY-09**
  - 항목명: AI 워크로드 보안 태세 점검 결과
  - 유형: T4
  - 제품/메뉴: Microsoft Defender
  - 측정방법: Azure AI 리소스에 연결된 Defender 권고·심각도·조치 이력·보안 점수 조회; 내부 보안 점수 기준 별도 입력
  - L1: AI 워크로드 보안 태세 점검 기능 미사용
  - L2: 기능은 활성화되었으나 고위험 권고 사항 다수가 미조치
  - L3: 고위험 권고 0건, 보안 점수가 내부 기준 이상 유지됨
  - L4: 신규 권고가 30일 내 조치되고 보안 정책이 자동 적용됨
  - L5: 공격 경로 분석을 상시 운영하고 위험을 자동 조치함
  - scope: partial
  - 분류 근거: Defender for Cloud의 Azure AI 워크로드 권고만 포함하며 타 제품 Defender 영역은 제외한다.
- **DP-SY-10**
  - 항목명: 전체 Agent 목록과 배포 범위·게시 상태·소유자
  - 유형: T2
  - 제품/메뉴: M365 Admin Center - Agent Registry
  - 측정방법: 타 담당 확인: Agent Registry 목록 추출, 등록부 대사 결과; 본 프로젝트에서는 구현하지 않음
  - L1: Agent Registry 확인 불가 또는 목록 추출 불가
  - L2: 목록은 추출되나 소유자·배포 범위 누락 30% 이상
  - L3: 누락 10% 미만, 공식 등록부와 Registry 일치율 90% 이상
  - L4: 누락 2% 미만, 등록부 일치율 98% 이상 유지됨
  - L5: 불일치 0건, 게시 상태 변경이 자동 동기화·알림됨
  - scope: out_of_scope
  - 분류 근거: 원 항목의 담당 제품은 M365 Admin Center - Agent Registry이며 Azure/Foundry 담당 범위가 아니다.
- **DP-SY-11**
  - 항목명: Agent 공유 허용 범위 및 사용자 설치 허용 설정
  - 유형: T1
  - 제품/메뉴: M365 Admin Center - Copilot &gt; Agents 설정
  - 측정방법: 타 담당 확인: Copilot &gt; Agents 공유·설치 설정 화면 캡처; 본 프로젝트에서는 구현하지 않음
  - L1: 공유·설치 설정이 기본값(전체 허용) 상태임
  - L2: 공유 범위는 일부 제한, 사용자 직접 설치는 허용됨
  - L3: 조직 전체 공유는 관리자 승인 필수, 설치는 승인 Agent만 허용
  - L4: 미승인 Agent 설치 0건, 설정 변경이 감사 로그로 추적됨
  - L5: 설정 준수를 상시 모니터링하고 위반 시 자동 차단함
  - scope: out_of_scope
  - 분류 근거: 원 항목의 담당 제품은 M365 Admin Center - Copilot &gt; Agents 설정이며 Azure/Foundry 담당 범위가 아니다.
- **DP-SY-12**
  - 항목명: 고유 ID(Agent ID)가 부여된 Agent 수 / 전체 Agent 수
  - 유형: T3
  - 제품/메뉴: Microsoft Entra Agent ID
  - 측정방법: Entra Agent ID와 Blueprint 태그(agentName·projectName·accountName·subscriptionId)로 Azure에서 수집한 Foundry Agent와 매칭해 부여율 산출; 분모는 Azure 수집 Agent이며 Agent Registry 전체가 아님
  - L1: Agent ID 미사용, 부여율 0%
  - L2: Agent ID 부여율 50% 미만
  - L3: Agent ID 부여율 80% 이상
  - L4: 부여율 95% 이상, 신규 Agent는 생성 시 자동 부여됨
  - L5: 부여율 100% 유지, 미부여 Agent 자동 탐지·조치
  - scope: partial
  - 분류 근거: Azure에서 수집한 Agent 대비 Entra Agent ID 부여율만 산출하며 Agent Registry(M365) 기준 전체 Agent는 제외한다.
- **OE-SY-13**
  - 항목명: 소유자·후원자(Sponsor) 미지정 Agent 및 소유자 퇴사 Agent(고아 Agent) 수
  - 유형: T3
  - 제품/메뉴: Microsoft Entra Agent ID / M365 Admin Center
  - 측정방법: Graph v1.0 agentIdentity의 owner·sponsor 관계를 조회해 미지정 및 소유자 전원 비활성(고아) Agent 비율 산출
  - L1: Agent ID 미사용, 소유자 정보 확인 불가
  - L2: 소유자 정보는 있으나 미지정·고아 Agent 비율 30% 이상
  - L3: 미지정·고아 Agent 비율 10% 미만
  - L4: 미지정·고아 Agent 비율 2% 미만, 수명주기 정책이 자동 적용됨
  - L5: 고아 Agent 0건 유지, 소유자 변경 시 자동 재지정·알림 운영
  - scope: in_scope
  - 분류 근거: Microsoft Entra Agent ID의 소유자·후원자를 Graph 읽기 권한으로 수집한다. 소유자 비활성 여부로 고아를 판단하며 퇴사 처리 상태 자체는 확인하지 않는다.
- **OE-SY-14**
  - 항목명: Agent별 부여 권한(API 권한, 접근 패키지) 및 과다 권한 Agent
  - 유형: T3
  - 제품/메뉴: Microsoft Entra - Agent ID, ID Governance
  - 측정방법: Graph v1.0 appRoleAssignments로 Agent별 애플리케이션 권한을 조회하고 고객 승인 과다 권한 패턴과 대조; 접근 패키지·접근 검토 자동화는 고객 입력
  - L1: Agent별 부여 권한 확인 불가
  - L2: 권한은 확인되나 과다 권한 Agent 비율 20% 이상
  - L3: 과다 권한 Agent 비율 5% 미만
  - L4: 과다 권한 1% 미만, 접근 패키지·만료가 자동 적용됨
  - L5: 과다 권한 0건 유지, 정기 접근 검토가 자동 수행됨
  - scope: in_scope
  - 분류 근거: Agent별 애플리케이션 권한은 Application.Read.All로 수집한다. 위임(OAuth) 권한 동의는 Directory.Read.All이 필요해 수집하지 않는다.
- **OE-SY-15**
  - 항목명: Agent 대상 조건부 접근 정책 적용 여부 및 위험 Agent 탐지 건수
  - 유형: T1
  - 제품/메뉴: Microsoft Entra - Conditional Access, ID Protection
  - 측정방법: Graph beta 조건부 접근 정책의 conditions.agents와 Graph beta riskyAgents로 정책 적용 범위·고위험 차단·미조치 탐지 산출; 라이선스 없으면 license_missing이 아니라 조회 실패 사유로 기록
  - L1: Agent 대상 조건부 접근 정책 없음, 위험 탐지 미사용
  - L2: 정책은 있으나 일부 Agent(50% 미만)에만 적용됨
  - L3: 운영 Agent 90% 이상에 정책 적용, 위험 탐지 활성화됨
  - L4: 적용률 100%, 고위험 Agent 자동 차단, 미조치 탐지 0건
  - L5: 탐지 추세를 분석해 정책을 정기 강화하고 자동 대응을 운영함
  - scope: in_scope
  - 분류 근거: Microsoft Entra 조건부 접근과 ID Protection의 Agent 대상 항목을 Graph 읽기 권한(Policy.Read.All, IdentityRiskyAgent.Read.All)으로 수집한다. 두 기능은 문서상 Agent 365 또는 M365 E7 라이선스가 전제될 수 있다.
- **OE-SY-16**
  - 항목명: Agent 활동 감사 로그 보관 여부 및 보관 기간
  - 유형: T5
  - 제품/메뉴: Microsoft Purview - Audit
  - 측정방법: Azure 진단 설정·로그 목적지·Log Analytics 보존 기간 조회; 내부 보관 규정과 대조; Purview와 동등 판정 금지
  - L1: Agent 활동 감사 로그 미수집
  - L2: 감사 로그는 수집되나 보관 기간이 기본값(90일 이하)임
  - L3: 내부 규정 기간(예: 1년) 이상 보관 정책이 적용됨
  - L4: 보관 정책 100% 적용, 로그 기반 정기 리포트가 자동 생성됨
  - L5: 감사 로그를 상시 분석해 이상 활동을 자동 경보함
  - scope: partial
  - 분류 근거: Azure 진단 로그·Activity Log·보존 설정만 대체 증적으로 수집하며 Purview Audit는 제외한다.
- **OT-SY-17**
  - 항목명: 승인되지 않은 Agent(Shadow AI) 탐지 결과 ※ Agent 365 라이선스 필요
  - 유형: T4
  - 제품/메뉴: Agent 365 - Shadow AI Detection
  - 측정방법: 타 담당 확인: Agent 365 Shadow AI 탐지 리포트 ※ Agent 365 미보유 시 평가 제외(N/A); 본 프로젝트에서는 구현하지 않음
  - L1: Shadow AI 탐지 기능 미사용, 탐지 결과 확인 불가
  - L2: 탐지는 되나 미승인 Agent 비율 20% 이상, 조치 미흡
  - L3: 미승인 Agent 비율 5% 미만, 탐지 건 80% 이상 조치됨
  - L4: 미승인 비율 1% 미만, 탐지 시 자동 차단·통보됨
  - L5: 미승인 0건 유지, 탐지 추세로 수요를 파악해 공식화함
  - scope: out_of_scope
  - 분류 근거: 원 항목의 담당 제품은 Agent 365 - Shadow AI Detection이며 Azure/Foundry 담당 범위가 아니다.
- **OT-SY-18**
  - 항목명: Agent별 활성 사용자 수, 최근 사용일, 미사용 Agent 수
  - 유형: T5
  - 제품/메뉴: M365 Admin Center - Agent 사용 현황 / Agent 365 - 고급 사용 분석
  - 측정방법: 최근 90일 관측 구간 전체의 Agent별 호출·토큰·최종 사용일 조회; 수집 공백을 비활성으로 간주하지 않음
  - L1: Agent별 사용 현황 확인 불가
  - L2: 사용 현황은 확인되나 90일 미사용 Agent 비율 40% 이상
  - L3: 90일 미사용 Agent 비율 20% 미만
  - L4: 미사용 비율 10% 미만, 미사용 Agent가 자동 알림·정리됨
  - L5: 미사용 5% 미만 유지, 사용 추세로 확대·폐기를 결정함
  - scope: partial
  - 분류 근거: Azure Monitor로 확인 가능한 Azure 호스팅 Agent만 포함하며 M365·Agent 365 사용 분석은 제외한다.
- **OT-SY-19**
  - 항목명: 사용량 기반 과금 정책 설정 여부 및 Agent별 소비 비용
  - 유형: T5
  - 제품/메뉴: M365 Admin Center - Billing policy / Azure Cost Management
  - 측정방법: 최근 30일 Azure AI 비용 총액 대비 중복 없이 Agent에 귀속 가능한 비용 비율; 통화별 분리 및 월별 집계 증적 구분
  - L1: 사용량 기반 과금 정책 미설정, 비용 확인 불가
  - L2: 과금 정책은 있으나 Agent별 비용 구분 불가
  - L3: Agent별 비용이 80% 이상 식별되고 월별 집계됨
  - L4: 비용 100% 식별, 조직별 배분·예산 경보가 자동 적용됨
  - L5: 비용 추세 예측으로 예산 초과를 선제 통제함
  - scope: partial
  - 분류 근거: Azure Cost Management 비용만 포함하며 M365 Billing policy는 제외한다.
- **OT-SY-20**
  - 항목명: Agent가 접근하는 민감 데이터 노출 현황
  - 유형: T4
  - 제품/메뉴: Microsoft Purview - DSPM for AI
  - 측정방법: 타 담당 확인: DSPM for AI 리포트, 민감 데이터 노출 목록; 본 프로젝트에서는 구현하지 않음
  - L1: DSPM for AI 미사용, 민감 데이터 노출 확인 불가
  - L2: 노출은 확인되나 고위험 노출 건 조치율 50% 미만
  - L3: 고위험 노출 조치율 90% 이상, 레이블 기반 보호 적용
  - L4: 고위험 노출 미조치 0건, DLP 정책이 자동 적용됨
  - L5: 노출 위험을 상시 모니터링하고 자동 조치·정책 갱신함
  - scope: out_of_scope
  - 분류 근거: 원 항목의 담당 제품은 Microsoft Purview - DSPM for AI이며 Azure/Foundry 담당 범위가 아니다.

## 원본 및 변환 범위

- DOCX 1개, XLSX 1개(5개 시트), TXT 2개를 같은 디렉터리에 `.원본확장자.md`로 변환합니다. 헤더에 원본 파일명을 보존하고 표는 Markdown 표로 유지합니다. PPTX 3개는 보조 제안 자료이며 Step 0의 명시된 DOCX/XLSX/TXT 변환 대상 및 판정 기준 출처에 포함하지 않았습니다. 원본 파일은 변경하지 않습니다. 회의록에는 개인 식별 정보가 있을 수 있으므로 외부 보고서에 그대로 복사하지 않습니다.

## 개발필요항목의 6개 안건 매핑

- **1. 항목 정의**
  - 프로젝트 산출물: docs/api-notes.md의 원문 범위와 추가 제안
  - 현재 상태/한계: 20개 원 항목과 추가 제안을 구분; 추가 제안은 미구현
- **2. 측정 방안**
  - 프로젝트 산출물: docs/api-notes.md, README.md, src/wasm_agent/
  - 현재 상태/한계: 읽기 계약과 권한 한계를 아래에 보존; 고객별 지원은 실제 접근 확인 필요
- **3. 분석 기준**
  - 프로젝트 산출물: src/wasm_agent/criteria.yaml, src/wasm_agent/evaluation.py, tests/
  - 현재 상태/한계: 원문 미정의 구간은 임의 보간 금지
- **4. 보고서**
  - 프로젝트 산출물: report-<타임스탬프>.xlsx, raw-data-<타임스탬프>.json
  - 현재 상태/한계: 사용자 전달 파일은 Excel 보고서와 raw-data JSON(raw + evidence + meta) 2개뿐입니다. HTML/ZIP/중복 CSV/Markdown 출력은 제거했습니다. 원 안건의 PPT는 산출물에 포함되지 않음
- **5. 개선 과제**
  - 프로젝트 산출물: criteria.yaml 기반 다음 단계 조건, 보고서 개선 후보
  - 현재 상태/한계: 자동 변경/정책 적용은 하지 않음
- **6. 이기종 적용**
  - 프로젝트 산출물: 공통 AgentEvidence, config/manual_agents.csv, 이 문서의 이기종 절
  - 현재 상태/한계: 사례/AI Gateway/OpenTelemetry는 검증 필요

## 실행 경계와 설계

- 수집 대상은 Microsoft Foundry, Azure 자체 호스팅 Agent, Azure Monitor/Log Analytics, 비용/보안 권고입니다. 관리자 준비/필드 안내는 [README](../README.md), 샘플 배포는 [개발자 데모](../demo/README.md)를 참고합니다.
- 관리자 bootstrap: 관리자 디바이스 코드 로그인. 승인된 샘플 배포, 역할, 일회성 공개 인증서 등록/정리만 별도 수행.
- 진단 수집기: DefaultAzureCredential + 진단 SP. Reader 중심 GET 및 Resource Graph/비용/로그의 읽기 query POST만 허용.
- 샘플 런타임: 앱 Managed Identity. 해당 모델의 제한된 추론과 합성 smoke 입력만 허용.
- 임시 개인키는 승인된 저장소 밖 사용자 전용 보호 경로에서 사용합니다. 수집기는 관리자 SDK/CLI와 샘플 배포 모듈을 import하지 않습니다.

### 공통 모델과 흐름

- `AgentEvidence`: collected_at, tenant/subscription/resource_group, platform, agent_id/name/resource_id/hosting_type, owner/sponsor/tags, model/tools, created_at/last_used_at, cost_30d, usage_30d(calls,tokens), evaluated_before_deploy, guardrail_applied, detection_confidence, evidence_refs, se_codes, field_status.
- 추가 필드:
  - `deployed_at`: 생성 시각을 배포 시각으로 대체하지 않음.
  - `model_version`, `model_resource_id`: 허용 버전 대조, 공유 모델 비용/사용량의 오귀속 방지.
  - `currency`: 서로 다른 통화를 임의 합산하지 않음.
  - `calls_90d`, `usage_coverage_start`: 관측 누락을 비활성 0건으로 바꾸지 않음.
- 보조 모델: ModelDeployment, EvaluationRun, CostRecord, SecurityRecommendation, LogSetting. API 실패는 Issue, 필드 누락은 null + FieldStatus.
- 같은 이름의 Foundry Agent가 여러 프로젝트에 있을 수 있으므로 중복 키는 platform + subscription_id + resource_id + agent_id.
- 수집 순서:
  - 설정 검증, 실제 credential의 tenant/object ID 일치와 광범위 권한 거부.
  - 접근 가능한 구독 자동 열거 또는 CLI 제한, 구독별 병렬 실행.
  - Resource Graph 인벤토리와 ARM 하위 리소스 목록 보완.
  - Foundry Agent/버전, 모델 배포, 평가 및 LangChain 태그/이름 후보 정규화.
  - 비용/메트릭/로그/보안 증거 중 귀속 가능한 필드만 연결.
  - `src/wasm_agent/criteria.yaml`(내장 임계값, 고객 입력은 선택 `config/config.yaml`) 수치/정성 조건 평가, XLSX 및 raw-data JSON 생성.
- 페이지 처리, 429/일시 오류 재시도와 부분 실패 기록을 유지합니다.
- Collector Protocol: `discover(subscriptions) -> Collection`, `required_roles` 선언.
- Evaluator: `Collection + criteria.yaml -> Finding[]`; se_code, metric_value, level, rationale, evidence_refs, N/A 사유/다음 단계/interview_level/gap_flag 반환.
- 사용자 전달은 `report-<타임스탬프>.xlsx`(검토 체크리스트와 Raw 데이터 시트)와 `raw-data-<타임스탬프>.json` 2개입니다. raw-data JSON은 raw + evidence + meta를 통합하며, 같은 폴더의 가장 최근 `raw-data-*.json`으로 `wasm-agent package`가 Excel을 다시 만듭니다. 내부 연동용 설정은 `.wasm-agent/`에 보존합니다.

### 판정 원칙

- 원문이 비운 수치 구간은 보간하지 않습니다. 증거 부족은 N/A와 추가 조건을 설명합니다.
- L4/L5 정성 조건은 외부 정책 증거의 명시적 입력이 필요하며 설정값만으로 정책 준수를 확정하지 않습니다.
- 평가 완료, 배포일, 같은 Agent/버전 연결이 모두 있어야 배포 전 평가 여부를 계산합니다.
- 공유 리소스 호출/토큰/비용을 여러 Agent에 중복 배분하지 않습니다.
- partial은 Azure 부분 범위 초안이며 Purview/조직 전체 결과가 아닙니다.
- 신규 샘플은 30일 비용/90일 관측 기간을 충족하지 못할 수 있습니다.

## API 및 RBAC 확인 메모

- 초기 확인일: 2026-11-02. 초기 Step 0/0.5 프로필은 아래에 이력으로 보존하며 신규 프로필이 Step 1~9 구현의 기본입니다.
- 2026-11-03 승인된 대상 구독 샘플에서 신규 API와 실제 수집을 검증했습니다. 모든 고객 서비스/버전 지원을 보장하지 않습니다.

### 신규 수집기 프로필 (2026-11-03)

- 실제 로컬 환경: Python 3.11.18, azure-ai-projects 2.4.0, openai 2.54.0.
- 신규 Agent: project endpoint의 GET `/agents`, `/agents/{name}/versions`, `api-version=v1`. data/last_id/has_more 페이지 처리.
- Agent 개수: 논리 Agent당 1건. 최신 보이는 버전 모델을 연결하되 버전 수로 Agent 수를 부풀리지 않으며 최신 버전이 운영 배포라고 주장하지 않음.
- 평가 목록: GET `/openai/v1/evals`, `/openai/v1/evals/{id}/runs`. completed_at이 없으면 생성 시각으로 대체하지 않음.
- 프로젝트 ARM: 공급자 메타데이터와 공식 관리 SDK에서 확인한 accounts/projects `2025-06-01`.
- 모델 배포: ARM deployments `2024-10-01`. raiPolicyName은 연결 정책 존재만 의미하며 안전 통제의 실효성 증거가 아님.
- 로그: Log Analytics query, AppServiceConsoleLogs의 ResultDescription에서 샘플 Agent 이벤트 집계. 누락 토큰을 0으로 만들지 않음.
- 공유 리소스: App Service 비용은 site뿐 아니라 serverFarmId도 대조. 공유 모델/모니터링 비용을 여러 Agent에 중복 귀속하지 않음.
- 클래식: 명시적 `classic_v1`에서만 assistants 사용. 미지원 신규 API를 클래식으로 자동 변경하지 않음.
- 공식 근거:
  - [SDK 2.4 Agent 샘플](https://github.com/Azure/azure-sdk-for-python/blob/azure-ai-projects_2.4.0/sdk/ai/azure-ai-projects/samples/agents/sample_agent_basic.py).
  - [관리 ARM 스펙](https://github.com/Azure/azure-rest-api-specs/blob/main/specification/cognitiveservices/resource-manager/Microsoft.CognitiveServices/CognitiveServices/stable/2025-06-01/cognitiveservices.json).
  - [평가 SDK 안내](https://learn.microsoft.com/azure/foundry/observability/how-to/evaluate-agent).
  - [AppServiceConsoleLogs 열](https://learn.microsoft.com/azure/azure-monitor/reference/tables/appserviceconsolelogs).
- gpt-4o-mini 모델 목록/쿼터만으로 신규 배포 가능성을 확정할 수 없었습니다. ARM validate의 ServiceModelDeprecating 응답 후 같은 Korea Central에서 validate를 통과한 gpt-4.1-nano 2025-04-14 GlobalStandard로 샘플을 변경했으며 지역은 변경하지 않았습니다.

### 실측으로 보완한 계약

- 신규 OpenAI 호환 평가 목록의 403이 `AIServices/assets/read`를 명시적으로 요구했습니다. 공식 공급자 작업 목록 확인 후 v2 읽기 역할에 추가했습니다. 프로젝트 asset 메타데이터도 허용하는 권한 단위이며 수집기는 평가 관련 목록만 호출합니다. 기존 v1 정의는 변경하지 않았습니다.
- Azure Metrics가 `+00:00`의 `+`를 공백으로 재해석한 실제 400 응답을 확인하여 timespan은 UTC `YYYY-MM-DDTHH:MM:SSZ`로 전송합니다.
- 초기 Azure CLI 인증서 삭제에는 `--cert`가 필요했습니다. 최종 자동화는 아래 공식 Graph 방식으로 변경했습니다.
- Entra 인증서 등록 전파로 첫 토큰 요청이 실패할 수 있어 읽기 수집을 제한 재시도하며 관리자 토큰으로 대체하지 않습니다.
- App Service Oryx의 Python SDK 설치 지연으로 사전 패키징한 Linux wheel로 전환했습니다. ELF x86_64/ZIP 무결성을 확인하고 비동기 배포의 새 작업 ID와 health를 별도로 검증합니다.

### 챗봇 샘플 확장의 공식 계약

- 로그인 보호: App Service `config/authsettingsV2` ARM `2024-11-01`. 인증 필수, 동일 tenant issuer, allowedPrincipals.identities. `/health`만 인증 예외.
- 비밀번호 없는 웹 로그인: 공식 `OVERRIDE_USE_MI_FIC_ASSERTION_CLIENTID` 앱 설정, registration.clientSecretSettingName. 앱별 전용 User Assigned MI와 Graph federatedIdentityCredential 사용.
- 앱 등록: Graph v1.0 applications / servicePrincipals / applications/{id}/federatedIdentityCredentials. 단일 테넌트와 승인 redirect URL, 소유 표식이 있는 샘플 앱만 재사용.
- Foundry 평가: OpenAI-compatible `/openai/v1/evals`와 `/runs`, custom item_schema + string_check(eq) + jsonl/file_content. 실제 응답/정답 비교.
- 평가 결과: 관리자 샘플은 run terminal status와 output_items 다운로드. 수집기는 run 목록의 result_counts(passed/failed/errored/total), Agent/버전 metadata만 읽고 질문/응답 본문을 조회하지 않음. completed_at이 없으면 추정하지 않음.
- 배포 영수증: 관리자 샘플 published_at/관측 완료 시각은 운영 배포의 서비스 증거가 아니며 Reader 판정에 자동 주입하지 않음.
- 대화: SDK responses.create + 기존 LangChain create_agent. 웹 앱 MI가 추론하고 진단 SP는 추론하지 않음.
- 공식 근거:
  - [App Service MI 로그인](https://learn.microsoft.com/azure/app-service/configure-authentication-provider-aad#use-a-managed-identity-instead-of-a-secret).
  - [MI 신뢰 설정](https://learn.microsoft.com/entra/workload-id/workload-identity-federation-config-app-trust-managed-identity).
  - [authsettingsV2 스키마](https://learn.microsoft.com/azure/templates/microsoft.web/sites/config-authsettingsv2).
  - [Graph 앱 등록](https://learn.microsoft.com/graph/api/application-post-applications?view=graph-rest-1.0).
  - [Graph 연합 자격증명](https://learn.microsoft.com/graph/api/application-post-federatedidentitycredentials?view=graph-rest-1.0).
  - [평가 정의](https://learn.microsoft.com/azure/foundry/reference/rest/evals-create-eval).
  - [평가 실행](https://learn.microsoft.com/azure/foundry/reference/rest/evals-create-eval-run).
  - [데이터셋 평가](https://learn.microsoft.com/azure/foundry/observability/how-to/cloud-evaluation-datasets).
- 기본 원칙 응답의 정확 일치 3문항은 포괄적 보안/품질 검증이 아닙니다. 고객 보고서는 기계값을 한글로 설명하되 JSON의 null/reason/N/A 계약을 유지합니다.
- 실제 웹 로그인/대화에서 확인한 사항:
  - callback 401: Easy Auth의 `response_type=code id_token` 요청 확인 후 웹 앱 등록의 ID 토큰 발급과 기본 로그인 동의 완료. access token implicit 발급은 끈 상태 유지.
  - ZIP 완료인데 이전 health 화면: ZIP/서버 파일 일치와 별개로 기존 Python 프로세스 잔존 확인. 명시적 재시작과 새 챗봇 revision을 확인해야 배포 완료 처리.
  - 빈 POST 403: `no-referrer`와 플랫폼 CSRF 검사 충돌. 외부에는 referrer를 보내지 않고 같은 사이트 요청에만 보내는 `same-origin` 적용. CSRF를 끄지 않음.
  - 같은 사이트 요청 거부: 외부 HTTPS/내부 HTTP 프록시 차이. 사용자 제공 forwarded 헤더 대신 플랫폼 WEBSITE_HOSTNAME의 HTTPS 원점과 비교.
  - 긴 평가: 소형 모델 요청 한도와 새 endpoint 공개 여부 구분. 연결 후 요청하고 429만 제한 대기.
- 실패 문항도 원본에 보존하며 정확 일치 실패를 보안 위험 확정으로 바꾸지 않습니다.

### 최종 실행에서 확인한 경계

- Azure CLI Graph의 오래된 CAE 정책 토큰: 정상 디바이스 재인증 후에도 `az ad`가 이전 토큰 선택. 동일 관리자의 DefaultAzureCredential로 공식 Graph v1.0 GET/PATCH application.keyCredentials 사용.
- 기존 인증서: 개별 앱 GET `$select=keyCredentials`로 기존 공개키를 확보/보존하고 이번 임시 UUID만 추가/제거. 확보 불가 시 수정하지 않음.
- 인증서 시각/전파: Graph 만료는 실제 not_valid_after_utc와 일치. AADSTS700027만 제한 재시도하며 다른 신원으로 대체하지 않음.
- Kudu: 공식 ZIP API 직접 호출. 이번 실행의 새 ID, status=4, complete=true와 실제 health 모두 확인. 다른 origin이나 HTTP Location에 bearer 전송 금지.
- 중앙 로그: sink가 선택 대상 구독 밖이면 추가 GET/권한 확대 없이 permission_denied. 설정 목록 성공과 sink 보존 기간 확보는 다름.
- 실제 증거 제한: 신규 비용 행 없음 3건, 범위 밖 중앙 로그 3건, AI 연결 Defender 권고/활성화 미확인 3건. null 사유 보존.
- 공식 근거: [Graph application update](https://learn.microsoft.com/graph/api/application-update?view=graph-rest-1.0), [keyCredential](https://learn.microsoft.com/graph/api/resources/keycredential?view=graph-rest-1.0), [Kudu ZIP API](https://github.com/projectkudu/kudu/wiki/Deploying-from-a-zip-file-or-url).
- 인증서 등록은 관리자 bootstrap이며 진단 SP에 Graph 쓰기를 부여하지 않습니다. 같은 앱의 인증서를 동시에 변경하는 bootstrap 실행은 피합니다.

## 읽기 전용 Foundry 역할 결정

- [Foundry RBAC](https://learn.microsoft.com/azure/foundry/concepts/rbac-foundry): Reader는 관리 평면의 프로젝트/계정을 읽지만 프로젝트 데이터 작업을 허용하지 않음.
- [평가 권한 안내](https://learn.microsoft.com/azure/foundry/observability/how-to/evaluation-permissions): 평가 실행/조회에 Foundry User 또는 동등 권한 안내. 읽기 전용 최소 역할을 보장하는 안내가 아님.
- [Foundry User 정의](https://learn.microsoft.com/azure/role-based-access-control/built-in-roles/ai-machine-learning#foundry-user): 역할 ID `53ca6127-db72-4b80-b1b0-d745d6d5456d`, `accounts/listkeys/action`, `Microsoft.Resources/deployments/*`, DataActions `Microsoft.CognitiveServices/*` 등 광범위 작업을 포함하므로 진단 계정에 부여하지 않음.
- [공식 공급자 작업 목록](https://learn.microsoft.com/azure/role-based-access-control/permissions/ai-machine-learning#microsoftcognitiveservices): `Microsoft.CognitiveServices/accounts/AIServices/agents/read`, `Microsoft.CognitiveServices/accounts/AIServices/evaluations/read`가 DataAction임을 확인.
- 사용자 확인으로 사용자 지정 읽기 전용 역할 선택. [사용자 지정 역할 규칙](https://learn.microsoft.com/azure/role-based-access-control/custom-roles)에 따라 관리 그룹이 아닌 입력 구독에 AssignableScopes를 설정하고 실제 할당은 프로젝트 scope로 제한.
- 역할 생성/할당은 관리자 예외이며 수집 계정이 수행하지 않습니다.
- agents/read에는 threads/messages 읽기도 포함됩니다. 더 세밀한 Agent 메타데이터 전용 DataAction을 추측하지 않았습니다. 실제 서비스 인가/테넌트 등록 상태는 사전 점검으로 확인해야 합니다.

### 초기 사전 점검 REST 프로필

- 다음은 초기 이력입니다. 신규 수집기에 초기 클래식/미리 보기 프로필을 자동 적용하지 않습니다.
- 구독 자동 열거: GET `/subscriptions`, `2022-12-01`.
  - [Subscriptions List](https://learn.microsoft.com/rest/api/resources/subscriptions/list?view=rest-resources-2022-12-01). 지정 테넌트 Enabled 구독만 사용.
- 구독별 유효 권한: GET `/subscriptions/{id}/providers/Microsoft.Authorization/permissions`, `2022-04-01`.
  - [Permissions List](https://learn.microsoft.com/rest/api/authorization/permissions/list-for-scope?view=rest-authorization-2022-04-01). 알려진 광범위/명시적 쓰기 권한의 안전 가드이며 완전한 IAM 감사 아님.
- 리소스 열거: GET `/subscriptions/{id}/resources`, `2021-04-01`.
  - [Resources List](https://learn.microsoft.com/rest/api/resources/resources/list?view=rest-resources-2021-04-01). ARM nextLink 처리.
- 모델 배포: GET `{accountResourceId}/deployments`, `2024-10-01`.
  - [Deployments List](https://learn.microsoft.com/rest/api/aiservices/accountmanagement/deployments/list?view=rest-aiservices-accountmanagement-2024-10-01). 초기 메모의 properties.model/sku/provisioningState는 후속 수집 대상으로 확인.
- Foundry Agent: GET `{projectEndpoint}/assistants?api-version=v1&limit=1`.
  - [azure-ai-agents 1.1.0 연산 소스](https://github.com/Azure/azure-sdk-for-python/blob/azure-ai-agents_1.1.0/sdk/ai/azure-ai-agents/azure/ai/agents/operations/_operations.py), [설정 소스](https://github.com/Azure/azure-sdk-for-python/blob/azure-ai-agents_1.1.0/sdk/ai/azure-ai-agents/azure/ai/agents/_configuration.py). 클래식 assistants 프로필이며 신규 agents API로 자동 전환하지 않음.
- Foundry Evaluation: GET `{projectEndpoint}/evaluations/runs?api-version=2025-05-15-preview`.
  - [azure-ai-projects 1.0.0b11 연산 소스](https://github.com/Azure/azure-sdk-for-python/blob/azure-ai-projects_1.0.0b11/sdk/ai/azure-ai-projects/azure/ai/projects/operations/_operations.py), [설정 소스](https://github.com/Azure/azure-sdk-for-python/blob/azure-ai-projects_1.0.0b11/sdk/ai/azure-ai-projects/azure/ai/projects/_configuration.py). 미리 보기 프로필이며 현 서비스 지원은 실측 필요.
- Defender 권고: POST Resource Graph `2022-10-01`, securityresources의 assessments 쿼리.
  - [Resource Graph Resources](https://learn.microsoft.com/rest/api/azureresourcegraph/resourcegraph/resources/resources?view=rest-azureresourcegraph-resourcegraph-2022-10-01), [SecurityResources 참조](https://learn.microsoft.com/azure/governance/resource-graph/reference/supported-tables-resources#securityresources). 직접 Defender AI 전용 API를 추측하지 않는 대안. 쿼리 성공이 AI 기능/라이선스 활성화 증거는 아님.
- 진단 설정: GET `{resourceId}/providers/Microsoft.Insights/diagnosticSettings`, `2021-05-01-preview`.
  - [Diagnostic Settings List](https://learn.microsoft.com/rest/api/monitor/diagnostic-settings/list?view=rest-monitor-2021-05-01-preview). 구독 Activity Log/리소스별 목적지 접근 점검.
- 워크스페이스: GET `{workspaceResourceId}`, `2022-10-01`.
  - [Workspaces Get](https://learn.microsoft.com/rest/api/loganalytics/workspaces/get?view=rest-loganalytics-2022-10-01). 설정 읽기만 확인하며 로그 내용/보호 테이블 권한은 별도.
- Monitor 메트릭: GET `{resourceId}/providers/Microsoft.Insights/metrics`, `2018-01-01`.
  - [Metrics List](https://learn.microsoft.com/rest/api/monitor/metrics/list?view=rest-monitor-2018-01-01). 접근 점검만 수행하며 Agent별 호출/토큰/90일 데이터 존재를 보장하지 않음.
- 비용: POST `/subscriptions/{id}/providers/Microsoft.CostManagement/query`, `2023-03-01`.
  - [Query Usage](https://learn.microsoft.com/rest/api/cost-management/query/usage?view=rest-cost-management-2023-03-01). Usage/Custom/최근 30일/PreTaxCost 합계 접근만 확인.
- 구독 보안 점수: GET `/subscriptions/{id}/providers/Microsoft.Security/secureScores`, `2020-01-01`.
  - [Secure Scores API](https://learn.microsoft.com/rest/api/defenderforcloud-composite/secure-scores) 및 [Defender 보안 점수 문서](https://learn.microsoft.com/azure/defender-for-cloud/secure-score-security-controls#get-your-secure-score-from-the-rest-api). 실측(2026-11-04): `name=ascScore`, `properties.score.{current,max,percentage}`(percentage는 0~1). 평가는 대상 구독 중 최저값 x 100을 내부 기준(%)과 비교. Security Reader로 점수가 0으로 보인 사례가 있어 값이 아닌 조회 성공과 구분해 확인.
- 권고 평가일: Resource Graph `securityresources`의 assessments `properties.status.{firstEvaluationDate,statusChangeDate}`. 실측으로 두 필드 존재 확인(소수점 7자리 ISO 8601). BI-SY-09 L4의 "30일 내 조치"는 미조치(Unhealthy) 권고의 상태 변경일(없으면 최초 평가일) 기준 경과 일수로 파생하며 원문의 대리 지표입니다.
- 정책 할당: GET `/subscriptions/{id}/providers/Microsoft.Authorization/policyAssignments?$filter=atScope()`, `2023-04-01`.
  - [Policy Assignments List](https://learn.microsoft.com/rest/api/policy/policy-assignments/list). 상속 할당 포함, Reader로 조회. 고객이 `config.yaml`의 `model_policy_definition_ids`로 지정한 정의/이니셔티브만 저장하며 `enforcementMode=Default`일 때만 강제로 인정. 어떤 정책이 "모델 제한"인지는 추측하지 않고 고객 지정 값에 의존.
- 예산: GET `/subscriptions/{id}/providers/Microsoft.Consumption/budgets`, `2023-05-01`.
  - [Budgets List](https://learn.microsoft.com/rest/api/consumption/budgets/list). 실측으로 `properties.{amount,category,timeGrain,notifications}` 확인. 활성(`enabled=true`) 경보 수와 임계값만 저장하고 `contactEmails` 등 수신자 정보는 저장하지 않음. OT-SY-19 L4의 "예산 경보"에 사용하며 "조직별 배분"은 모든 Azure Agent의 비용센터 태그 유무로 확인(대리 지표).
- 위 초기 SDK 버전은 REST 프로필 확인 출처이지 설치 의존성이 아닙니다. 실행 의존성은 `pyproject.toml`의 azure-identity와 requests, 인증은 DefaultAzureCredential이며 관리자 Azure CLI는 명시된 예외입니다.
- Azure Public Cloud만 현재 지원하며 소버린 클라우드 호스트/audience는 추측하지 않습니다.

### 미확정 API와 남은 검증

- 초기 TODO 중 신규 Agent/버전과 평가 목록은 위 신규 프로필/실측으로 보완했습니다. 게시/운영 배포 API와 Agent-평가-배포 lineage는 실제 프로필/샘플을 더 확인해야 합니다.
- `created_at`은 생성 시각이지 배포 시각이 아닙니다. 평가 성공/종료 시각/배포 버전 연결은 실제 응답으로 확인하기 전 확정하지 않습니다.
- Defender AI 활성화/라이선스와 AI 권고 필터는 실측/공식 근거 추가 확인 필요. 빈 권고로 고위험 0건/보안 양호를 판단하지 않습니다.
- Entra Agent ID(`--entra`, 진단 SP에 Graph 애플리케이션 읽기 권한 5개와 관리자 동의): 모든 호출은 GET이며 `graph.microsoft.com`으로만 토큰을 보냅니다.
  - Blueprint: `GET /v1.0/applications/microsoft.graph.agentIdentityBlueprint` (`AgentIdentityBlueprint.Read.All`). Agent ID: `GET /v1.0/servicePrincipals/microsoft.graph.agentIdentity` (`AgentIdentity.Read.All`). 공식: [agentIdentityBlueprint 목록](https://learn.microsoft.com/graph/api/agentidentityblueprint-list), [agentIdentity 목록](https://learn.microsoft.com/graph/api/agentidentity-list).
  - 소유자·후원자: `GET /v1.0/servicePrincipals/{id}/microsoft.graph.agentIdentity/owners|sponsors?$select=id,accountEnabled`. 사람 이름·UPN은 저장하지 않고 수와 비활성 여부만 보관합니다.
  - 애플리케이션 권한: `GET /v1.0/servicePrincipals/{id}/appRoleAssignments`(`Application.Read.All`)와 리소스 SP의 `appRoles`로 권한 이름 해석. 위임(OAuth) 권한 동의는 `Directory.Read.All`이 필요해 권한 범위를 넓히지 않기 위해 수집하지 않습니다.
  - 조건부 접근: `GET /beta/identity/conditionalAccess/policies`의 `conditions.agents`(`Policy.Read.All`). 위험 Agent: `GET /beta/identityProtection/riskyAgents`(`IdentityRiskyAgent.Read.All`, 공식 문서상 beta). beta 스키마는 바뀔 수 있습니다.
  - 실측(2026-11-04, 관리자 읽기 전용 GET): Agent ID 9개, Blueprint 9개, `agentIdentityBlueprintId`가 Blueprint `appId`/`id`와 일치. Blueprint `tags`에 `agentName`, `projectName`, `accountName`, `subscriptionId`가 있어 Foundry Agent와 매칭(DP-SY-12). `riskyAgents`는 관리자 토큰에 필요한 범위가 없어 403이었고 이 경로의 성공 응답과 `conditions.agents`가 채워진 정책은 실환경에서 확인하지 못했습니다(공식 문서와 단위 테스트 기준).
  - 미구현: Purview 감사(Graph `auditLogQuery`는 질의 생성 POST이며 Agent 활동 레코드 유형과 보존 정책을 확정할 근거가 없음), DSPM for AI(읽기 공식 API 미확인), Power Platform(공식 Power Platform API에서 환경 목록만 확인, Maker 수·데이터 정책·관리형 환경 값은 미확인이며 비공식 BAP admin API는 사용하지 않음).
- Metric 이름/dimension의 Agent 식별력, 마지막 사용일과 90일 미사용 증명 가능성 검증 필요.
- LangChain 앱 설정은 list 액션으로 비밀을 반환할 수 있어 기본 수집에서 호출하지 않으며 승인 태그/메타데이터 또는 수동 입력 우선.
- 사전 점검은 응답 본문/대화/평가 데이터셋을 증적으로 저장하지 않습니다. 수집 증거는 `evidence/<timestamp>/`에 저장하기 전에 비밀/토큰/연결문자열/개인 식별 정보를 마스킹하고 통합 데이터의 evidence로 보존합니다.
- 403은 IAM과 Private Endpoint/방화벽 모두 점검해야 합니다. permission_denied로 남기되 원인을 단정하지 않습니다.
- license_missing은 명시적 라이선스 상태 응답에만 사용하며 추측하지 않습니다.

## Azure/Foundry 관점 추가 제안

- 기존 20개 SE에 추가를 검토할 후보이며 현재 구현 대상이 아닙니다. 기존 코드에 편입하거나 기존 항목의 최종 점수로 사용하지 않습니다.
- Foundry 프로젝트/Agent 인벤토리:
  - 이유: 구독에 분산된 규모와 플랫폼별 분포 확인.
  - 읽기 증거: Resource Graph 계정/프로젝트, Foundry Agent 목록, 수동 등록 목록.
  - 확인: 관리/데이터 평면 구분, 클래식/신규 API, 중복 키, 버전/배포 구분.
- 콘텐츠 필터/가드레일 적용률:
  - 이유: 모델 호출 경로별 안전 통제.
  - 읽기 증거: 모델 배포 정책 연결, Agent 가드레일 구성, API Gateway 정책.
  - 확인: 정책 연결만으로 실효성을 입증하지 못함. LangChain 우회/사용자 정의 가드레일은 별도 증거.
- 트레이싱/모니터링 활성화율:
  - 이유: 호출/토큰/오류/지연 관측 기반 확인.
  - 읽기 증거: 진단 설정, App Insights 연계, OpenTelemetry 설정 메타데이터.
  - 확인: 연결문자열/프롬프트/응답 본문 수집 금지. 설정 존재와 실제 로그 유입 구분.
- 네트워크 격리/Managed Identity/RBAC:
  - 이유: 공용 노출, 비밀키 의존, 과다 권한 점검.
  - 읽기 증거: publicNetworkAccess, Private Endpoint 상태, identity와 Azure 역할 할당 메타데이터.
  - 확인: Azure RBAC/Entra API 권한 구분, 네트워크 제한 시 수집기 접근 경로 필요.
- Azure Policy 준수율:
  - 이유: 승인 모델/지역/보안 정책 구성 통제.
  - 읽기 증거: 정책 할당, Policy Insights 준수 상태.
  - 확인: 비준수/미평가, 면제/평가 지연 구분. 읽기 전용만 허용.
- 쿼터/예산 알림:
  - 이유: 과소/과다 용량과 예산 초과 사전 관리.
  - 읽기 증거: 쿼터 사용량, 예산/알림 메타데이터.
  - 확인: 쿼터 별도 역할, 비용 계약별 가시성, 예산 설정과 실제 발송/대응 이력 구분.
- 확정 절차:
  - 고객/평가 담당자와 코드, 분모, 관측 기간, T1~T5 유형 합의.
  - 적용 제품/구독 범위, 읽기 전용 API/역할을 공식 문서로 검증.
  - L1~L5와 N/A 기준 별도 승인. 다른 지표의 비율 재사용 금지.
  - 합의 전 수치/성숙도 점수 산출 금지.

## Azure 운영 추가 제안 13개 수집 (AZ-SY-P01~P13)

- 원칙: 승인 전 제안이라 L1~L5·임계값을 만들지 않고 **Azure에서 읽을 수 있는 구성 사실**만 `추가 제안 현황` 시트와 raw-data JSON의 `collection.proposals`에 기록합니다. 상태는 `수집됨/일부 수집/수집 불가`이며 실패는 사유와 함께 남기고 0으로 바꾸지 않습니다. 기존 20개 항목의 판정과 점수는 바꾸지 않습니다.
- 모든 호출은 GET 또는 기존 허용 POST(Resource Graph)이며 Reader로 가능합니다.

| 코드 | 수집 방법 | 근거/버전 | 중복 구분 |
| --- | --- | --- | --- |
| P01 | 수집된 Azure Agent의 소유자·후원자·환경·비용센터 태그 보유 수 | 기존 인벤토리 재사용 | OE-SY-13(Entra 소유자)과 달리 Azure 태그만 |
| P02 | Resource Graph `identity`(시스템·사용자 할당 principal)와 `GET /subscriptions/{id}/providers/Microsoft.Authorization/roleAssignments?api-version=2022-04-01`로 Agent 호스트·AI 계정의 ARM 역할 수와 광범위 역할(Owner, Contributor, User Access Administrator, RBAC Administrator) 수, 계정 `disableLocalAuth` | [Role Assignments List](https://learn.microsoft.com/rest/api/authorization/role-assignments/list-for-subscription) | DP-SY-12/OE-SY-14의 Entra·Graph 권한과 구분, ARM만 |
| P03 | Resource Graph로 AI 계정 `publicNetworkAccess`, `networkAcls.defaultAction`, 프라이빗 엔드포인트 수, 호스트 `httpsOnly`·VNet 통합, `GET sites/{n}/config/web?api-version=2024-04-01`의 `ipSecurityRestrictions` 수 | [Web Apps Get Configuration](https://learn.microsoft.com/rest/api/appservice/web-apps/get-configuration) | 신규 |
| P04 | `GET {account}/raiPolicies?api-version=2024-10-01`의 사용자 지정 정책 수와 모델 배포 `raiPolicyName` 대조 | [Rai Policies List](https://learn.microsoft.com/rest/api/aiservices/accountmanagement/rai-policies/list) | DS-SY-06의 허용 모델과 구분 |
| P05 | Foundry 프로젝트 `GET /redTeams/runs?api-version=v1` (azure-ai-projects 2.4.0 `beta.red_teams.list`와 동일 경로, 사전 문서상 beta) | SDK 소스 `build_beta_red_teams_list_request` | BI-SY-08과 구분. 응답 형식은 `value`/`data` 모두 허용, 실패는 사유 기록 |
| P06, P09 | Resource Graph `microsoft.insights/metricalerts·scheduledqueryrules·activitylogalerts·components·actiongroups`. 경보의 대상 범위가 AI 리소스를 포함하는지, 작업 그룹 연결 여부, 수신자 유형별 개수(주소·이름 미수집), App Insights 보존일 | Resource Graph 테이블 `Resources` | OE-SY-16(진단 설정)과 구분 |
| P07, P08 | Foundry Agent 정의의 도구 유형, MCP `require_approval` 값, 도구 `server_url`의 호스트(경로·쿼리·인증값 제외) | 기존 Agent 목록 응답 | 신규 |
| P10 | `Microsoft.Consumption/budgets` 알림의 `thresholdType=Forecasted` 수 | 기존 예산 수집(2023-05-01) | OT-SY-19의 예산 경보 유무와 구분, 예측 경보만 추가 |
| P11 | AI 계정·호스트·Log Analytics의 `location` 분포와 로그·App Insights 보존일 | 기존 인벤토리·진단 설정 재사용 | OE-SY-16의 필요 보존일 판정과 구분 |
| P12 | Resource Graph `PolicyResources` 테이블의 `microsoft.policyinsights/policystates`에서 AI 관련 리소스 유형의 준수 상태(리소스 수) | [Policy states in Resource Graph](https://learn.microsoft.com/azure/governance/policy/samples/resource-graph-samples) | DS-SY-06 L4의 고객 지정 정책 할당 확인과 구분 |
| P13 | 호스트 `linuxFxVersion`, 컨테이너 앱 이미지의 다이제스트 고정 여부, 모델 배포 `versionUpgradeOption` | ARM 배포 속성 | DS-SY-06의 모델 버전 대조와 구분 |

- 한계: 앱 내부 승인 게이트, 실제 방어 효과, SOC 수신, 훈련, 지역별 실제 처리, 소스·빌드 출처는 Reader로 입증할 수 없어 수집하지 않고 각 항목의 `한계` 열에 명시합니다.

## 이기종 Agent 수용

- Azure 외 Agent도 같은 목록에 정리할 수 있습니다. 현재는 CSV 직접 등록이며 Google/AWS 자동 로그인 수집이 아닙니다. 고객 입력과 Azure API 확인값을 구분합니다.
- 공통 스키마: AgentEvidence의 platform과 필드별 null 사유로 플랫폼 차이 보존.
- 수동 등록: `wasm-agent collect --manual-agents config/manual_agents.csv`; manual/other만 허용. CSV는 입력 템플릿이며 사용자 결과 CSV를 뜻하지 않음.
- 확장 플러그인: Collector Protocol의 discover(subscriptions), required_roles를 구현하고 공통 모델 반환.
- 재사용 후보: LG U+ Connector/ISD 사례의 커넥터/메타데이터 매핑 조사 자리. 현재 구현/검증 안 함.
- API Management AI Gateway: 요청/모델/토큰 메타데이터 공통 수집 가능성. 검증 필요.
- OpenTelemetry: gen_ai 메타데이터와 Agent 식별자 연결 가능성. 검증 필요.
- 수동 CSV 최소 필드는 agent_id, agent_name, manual/other 플랫폼입니다. 날짜는 시간대 포함 ISO 8601, tags/tools/usage_30d/field_status는 JSON입니다.
- 빈 값은 확인 자료 없음으로 표시하며 비용/사용량을 0으로 채우지 않습니다. 프로그램용 통합 데이터에는 null + not_found를 저장합니다.
- 이기종은 통합 인벤토리와 플랫폼별 개수에 포함하되 Azure 전용 SE 분모에는 섞지 않습니다. 수동 입력을 API 실측과 같은 신뢰도로 표시하지 않으며 원본 CSV 행을 evidence_refs로 남깁니다.
