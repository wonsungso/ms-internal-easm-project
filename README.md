# EASM (Enterprise Agent Service Management) 거버넌스 진단/수집 툴

- **수집 대상:** 
  - Microsoft Foundry(계정·프로젝트·Agent·모델 배포·평가)
  - App Service·Container Apps 등의 자체 구성 Agent
  - Azure Monitor·비용·Defender·정책
  - Entra Agent ID
- **결과물:** `output/report-<타임스탬프>.xlsx` (체크리스트·Raw 데이터) / `output/raw-data-<타임스탬프>.json` (Rawdata 포함 원본)

## 진행 순서

| 순서 | 담당 | 해야 할 일 | 상대에게 전달 |
| --- | --- | --- | --- |
| 1 | **MS WASM 관리자** | Codespaces 생성, 인증서 생성 | `public-cert.pem` |
| 2 | **고객사 담당자** | 앱 등록(SP 생성), 공개 인증서 등록 | Tenant ID, Client ID, SP Object ID |
| 3 | **고객사 담당자** | 승인 구독마다 Reader 부여, (Entra 수집 시) Graph 읽기 권한 동의 | 승인 구독 ID 목록 |
| 4 | **MS WASM 관리자** | SP 점검, 수집, 결과 다운로드 | Excel 보고서, raw-data JSON |
| 5 | **고객/MS 공동** | 결과 검토, 종료 후 권한·인증서 회수 | - |

- **필요 권한:** 2단계는 앱 등록 허용 또는 Cloud Application Administrator, 3단계는 구독의 Role Based Access Control Administrator 또는 User Access Administrator (별개 권한이므로 담당자가 나뉘어도 됨)
- **금지:** SP에 Owner·Contributor·client secret을 부여하거나 만들지 않음. Graph 권한은 읽기 전용 5개만 부여

## 1. [MS WASM 관리자] Codespaces와 인증서 준비

- 저장소 **Code → Codespaces → Create codespace** (Python 3.11·Azure CLI·의존성 자동 준비). `wasm-agent --help`로 확인
- 조직 발급 인증서가 있으면 우선 사용. 자체 서명이 승인된 경우 아래를 실행 (개인키 암호는 프롬프트에만 입력)

```bash
umask 077
cert_dir="$HOME/.config/wasm-agent/auth-$(date -u +%Y%m%dT%H%M%SZ)-$$"
mkdir -p "$HOME/.config/wasm-agent"
mkdir -m 700 "$cert_dir" || exit 1
openssl req -x509 -newkey rsa:3072 -sha256 -days 90 \
  -subj '/CN=wasmagent-diagnostic' \
  -keyout "$cert_dir/private-key.pem" -out "$cert_dir/public-cert.pem"
cat "$cert_dir/private-key.pem" "$cert_dir/public-cert.pem" > "$cert_dir/diagnostic.pem"
chmod 600 "$cert_dir/private-key.pem" "$cert_dir/diagnostic.pem"
openssl x509 -in "$cert_dir/public-cert.pem" -noout -dates -fingerprint -sha256
```

- **전달:** 고객에게 `public-cert.pem`**만** 전달. `private-key.pem`·`diagnostic.pem`은 저장소 밖에 보관

## 2. [고객사 담당자] 앱 등록(SP 생성)과 공개 인증서 등록

- [Azure Portal](https://portal.azure.com) → **Microsoft Entra ID → 앱 등록 → 새 등록**. 이름 `wasmagent-diagnostic`, 계정 유형 **이 조직 디렉터리만(Single tenant)**, 리디렉션 URI 비움 → **등록** (SP가 함께 생성됨)

![앱 이름·단일 테넌트·등록 위치](docs/imgs/07-register-sp.png)

- **개요**에서 Application (client) ID, Directory (tenant) ID 기록. **SP Object ID**는 **엔터프라이즈 애플리케이션 → 해당 앱 → 속성**에서 확인 (개요의 Object ID는 앱 등록 ID)

![앱 개요의 ID 확인 위치](docs/imgs/08-sp-overview.png)

- **인증서 및 암호 → 인증서 → 인증서 업로드** → `public-cert.pem` 선택 → **추가**. 목록의 지문·만료일을 MS와 대조

![공개 인증서 파일 선택과 추가](docs/imgs/09-upload-certificate.png)

- **전달:** Tenant ID, Client ID, SP Object ID

## 3. [고객사 담당자] 권한 부여

**Reader (필수)** - **구독 → 승인 구독 → 액세스 제어(IAM) → 추가 → 역할 할당 추가** → **Reader**(Owner·Contributor 아님) → 멤버에서 진단 앱 선택 → **검토 + 할당**. 승인 구독마다 반복

![Reader 역할 선택 위치](docs/imgs/10-reader-role.png)

![구독 범위·Reader·진단 SP 확인 후 할당](docs/imgs/11-reader-review.png)

구독이 많으면 고객의 승인된 Bash 호스트에서 일괄 부여 (MS에 관리자 계정·토큰을 전달하지 않음)

```bash
mkdir -p .wasm-agent
cat > .wasm-agent/setup.json <<'EOF'
{
  "tenant_id": "<Tenant ID>",
  "subscription_ids": ["<승인 구독 ID>", "<추가 승인 구독 ID>"],
  "account_type": "service-principal",
  "account_name": "wasmagent-diagnostic",
  "client_id": "<Client ID>",
  "principal_id": "<SP Object ID>"
}
EOF
bash scripts/setup.sh login    # 관리자 디바이스 코드 로그인
bash scripts/setup.sh plan     # Azure 호출 없는 계획 확인
bash scripts/setup.sh apply    # 역할 할당 + 재조회
```

**추가 권한 (필요할 때만)**

| 수집 항목 | 추가 권한 |
| --- | --- |
| Foundry Agent·평가 | 프로젝트 범위 읽기 역할(`agents/read`, `evaluations/read`, `assets/read`만, 대화 본문 미조회): `bash scripts/setup.sh apply --foundry-project-scopes '<project-resource-id>' --create-foundry-read-role` ([근거](docs/api-notes.md#읽기-전용-foundry-역할-결정)) |
| Agent 귀속 로그 | 지정 워크스페이스의 Log Analytics Reader |
| 비용·보안 권고 | `apply --cost-reader` / `apply --security-reader` |
| Entra Agent ID | Graph 애플리케이션 읽기 권한 5개(`AgentIdentity.Read.All`, `AgentIdentityBlueprint.Read.All`, `Application.Read.All`, `Policy.Read.All`, `IdentityRiskyAgent.Read.All`) + 관리자 동의 |

**Entra 관리자 동의** (Global Administrator 또는 Privileged Role Administrator 필요. 권한이 없으면 아래 **Grant admin consent** 버튼이 비활성이거나 "관리자 승인 필요" 화면이 나타나므로 해당 담당자가 동의)

- **스크립트:** `bash scripts/setup.sh apply --entra-reader` (5개 부여 후 재조회, 이미 부여됐으면 건너뜀)
- **포털:** 앱 등록 → 진단 앱 → **API 사용 권한 → 권한 추가 → Microsoft Graph → 애플리케이션 권한**에서 5개 선택 → **Add permissions** → **Grant admin consent** → 모두 **Granted** 확인 (`User.Read`는 포털 기본값이며 미사용)

![Graph 읽기 권한 5개 추가 후, 동의 전 상태와 Grant admin consent 버튼 위치](docs/imgs/12-entra-consent.png)

![관리자 동의 후 5개 권한이 모두 Granted](docs/imgs/13-entra-granted.png)

- 동의하지 않았거나 Entra를 수집하지 않으려면 수집 시 `--no-entra`. 동의 없이 수집하면 Entra 5개 항목만 **판정 보류**이고 Azure 항목은 정상 수집됨. 동의 후 실측은 Blueprint 9개·DP-SY-12 L3(0.8)이며 `riskyAgents`(beta)는 "tenant is not licensed"(403)로 응답해 OE-SY-15는 `license_missing` 판정 보류
- **전달:** 승인 구독 ID 목록 (`.wasm-agent/setup.json`은 승인된 경로로 전달)

## 4. [MS WASM 관리자] SP 점검과 수집

전달받은 값으로 `.wasm-agent/setup.json`을 만들고(위 JSON 형식) **별도 진단 터미널**에서 실행. 점검이 실패해도 **관리자 계정으로 우회하지 않음**

```bash
export AZURE_TENANT_ID='<Tenant ID>'
export AZURE_CLIENT_ID='<Client ID>'
export AZURE_CLIENT_CERTIFICATE_PATH="$cert_dir/diagnostic.pem"
read -r -s -p 'Certificate password: ' AZURE_CLIENT_CERTIFICATE_PASSWORD; printf '\n'
export AZURE_CLIENT_CERTIFICATE_PASSWORD
unset AZURE_CLIENT_SECRET AZURE_FEDERATED_TOKEN_FILE

bash scripts/setup.sh verify --certificate-path "$AZURE_CLIENT_CERTIFICATE_PATH"   # SP 점검
wasm-agent collect --setup-file .wasm-agent/setup.json --dry-run                   # 계획만 확인
wasm-agent collect --setup-file .wasm-agent/setup.json --output-dir output         # 수집 (setup.json의 승인 구독)
```

- 다른 구독만: `--subscriptions '<승인 구독 ID>' ...` / 접근 가능한 활성 구독 전체(전체가 승인된 경우만): `--all-subscriptions`
- 다른 플랫폼 Agent: `--manual-agents config/manual_agents.csv`
- Entra Agent ID 항목(DS-SY-05, DP-SY-12, OE-SY-13~15)은 기본 포함. 생략은 `--no-entra` (점검은 `verify --no-entra`)
- 선택 입력(허용 모델·내부 기준·정성 조건·태그 규약 등)은 [config/config.yaml](config/config.yaml)의 주석대로 적으면 반영. 비워도 수집은 실행되며 해당 조건만 판정 보류
- **결과:** `report-<타임스탬프>.xlsx`(체크리스트·추가 제안 현황·Raw 데이터·증거 참조)와 `raw-data-<타임스탬프>.json`(증거 포함 원본, `wasm-agent package`가 Excel 재생성). Codespaces 탐색기에서 우클릭 → **Download** (재실행하면 타임스탬프별로 누적)
- **종료 코드:** `0` 오류 없음 / `2` 일부 자료 미확보(Excel의 수집이슈 시트 확인) / `1` 입력·인증·실행 오류

## 5. [고객/MS 공동] 결과 검토와 종료

- 자동 판정은 **Azure 범위 초안**이며 조직 전체 확정 점수가 아님. 조회 실패·빈 결과·관측 기간 부족은 0이나 L1로 바꾸지 않고, L4/L5는 비율 외 정책·자동화 증거가 필요
- [평가 모델 템플릿](docs/assessment-template.xlsx): 원본 5개 시트·서식을 그대로 두고 추가 제안 13개를 시트 2(영역별 System Evidence)와 시트 4(질문별 평가 기준)의 각 진단 영역 블록에 같은 서식으로 병합. 추가 제안의 L1~L5와 확인 증적은 MS Learn 근거 초안(승인 전, 근거는 [api-notes](docs/api-notes.md#level-기준-초안-근거-2026-11-05-조사-승인-전))이며 시트 5 점수 산정에는 포함하지 않음 (`scripts/merge_assessment.py`로 재생성)
- **고객:** IAM의 진단 SP 역할과 앱의 공개 인증서 회수, 전용 앱이 불필요하면 삭제 / **MS:** 개인키·Codespace·수집 데이터를 승인된 기간 후 폐기
- 스크린샷은 실제 포털 화면(2026-11-04 검증 테넌트)이며 식별자·테넌트 이름은 마스킹했습니다. 12·13번 화면의 테넌트 이름은 Customer로 바꿔 캡처했습니다 ([캡처 범위](docs/manifest.json))

## 점검 항목 (System Evidence 20개 + Azure 추가 제안 13개)

- **구현 표기:** ✅ 구현 / ⚠️ 일부 구현 / ⚠️ 읽기 전용 불가(구현했으나 읽기 전용 역할로는 조회 불가) / ❌ 미구현 (M365·Agent 365·Purview·Power Platform 영역)
- **현황:** 기존 20개 중 ✅ 10 / ⚠️ 1 / ❌ 9
- **상세:** 항목 코드를 누르면 [점검 항목 상세](docs/checklist.md)로 이동합니다. 항목별 점검 내용, Azure Portal 기준(참고) 확인 경로, 구현 항목의 포털 확인 화면(빨간 네모는 확인 위치, 식별자 마스킹, 데모 환경 기준)이 있습니다

| 코드 | 진단 영역 | 항목명 | 제품/메뉴 | 구현 |
| --- | --- | --- | --- | --- |
| [DM-SY-01](docs/checklist.md#dm-sy-01-agent-제작-허용-사용자-범위-및-허용-agent-유형-설정) | 1. Demand | Agent 제작 허용 사용자 범위 및 허용 Agent 유형 설정 | M365 Admin Center - Copilot > Agents 설정 | ❌ 미구현 |
| [DM-SY-02](docs/checklist.md#dm-sy-02-copilot-studio-제작-권한-보유자-수-및-환경-현황) | 1. Demand | Copilot Studio 제작 권한 보유자 수 및 환경 현황 | Power Platform Admin Center | ❌ 미구현 |
| [DM-SY-03](docs/checklist.md#dm-sy-03-최근-6개월-신규-생성-agent-수-추이) | 1. Demand | 최근 6개월 신규 생성 Agent 수 추이 | M365 Admin Center - Agent Registry | ❌ 미구현 |
| [DS-SY-04](docs/checklist.md#ds-sy-04-커넥터-분류차단-정책데이터-정책-적용-현황) | 2. Design | 커넥터 분류·차단 정책(데이터 정책) 적용 현황 | Power Platform Admin Center - Data policies | ❌ 미구현 |
| [DS-SY-05](docs/checklist.md#ds-sy-05-agent-id-템플릿blueprint-정의-여부-및-개수) | 2. Design | Agent ID 템플릿(Blueprint) 정의 여부 및 개수 | Microsoft Entra Agent ID | ✅ 구현 |
| [DS-SY-06](docs/checklist.md#ds-sy-06-사용-중인-모델-배포-현황-및-허용-모델-목록) | 2. Design | 사용 중인 모델 배포 현황 및 허용 모델 목록 | Microsoft Foundry | ✅ 구현 |
| [DS-SY-07](docs/checklist.md#ds-sy-07-네트워크-경계와-공용-접근) | 2. Design | 네트워크 경계와 공용 접근 | Azure AI Services, App Service | ✅ 구현 |
| [DS-SY-08](docs/checklist.md#ds-sy-08-도구-구성과-승인-모드) | 2. Design | 도구 구성과 승인 모드 | Microsoft Foundry Agent 정의 | ✅ 구현 |
| [DS-SY-09](docs/checklist.md#ds-sy-09-외부-도구-엔드포인트) | 2. Design | 외부 도구 엔드포인트 | Microsoft Foundry Agent 정의 | ✅ 구현 |
| [BI-SY-07](docs/checklist.md#bi-sy-07-환경-분리-및-관리형-환경-적용-여부) | 3. Build | 환경 분리 및 관리형 환경 적용 여부 | Power Platform Admin Center | ❌ 미구현 |
| [BI-SY-08](docs/checklist.md#bi-sy-08-품질안전성-자동-평가-수행-이력) | 3. Build | 품질·안전성 자동 평가 수행 이력 | Microsoft Foundry | ✅ 구현 |
| [BI-SY-09](docs/checklist.md#bi-sy-09-ai-워크로드-보안-태세-점검-결과) | 3. Build | AI 워크로드 보안 태세 점검 결과 | Microsoft Defender | ✅ 구현 |
| [BI-SY-10](docs/checklist.md#bi-sy-10-content-safety-정책-연결) | 3. Build | Content Safety 정책 연결 | Microsoft Foundry - 콘텐츠 필터 | ✅ 구현 |
| [BI-SY-11](docs/checklist.md#bi-sy-11-적대적-시험red-team-이력) | 3. Build | 적대적 시험(Red team) 이력 | Microsoft Foundry - 평가 | ⚠️ 읽기 전용 불가 |
| [BI-SY-12](docs/checklist.md#bi-sy-12-릴리스-버전-고정런타임) | 3. Build | 릴리스 버전 고정·런타임 | Azure OpenAI 배포, App Service | ✅ 구현 |
| [BI-SY-13](docs/checklist.md#bi-sy-13-agent-자산-대장책임-태그) | 3. Build | Agent 자산 대장·책임 태그 | Azure 리소스 태그 | ✅ 구현 |
| [BI-SY-14](docs/checklist.md#bi-sy-14-azure-정책-준수-상태) | 3. Build | Azure 정책 준수 상태 | Azure Policy | ✅ 구현 |
| [DP-SY-10](docs/checklist.md#dp-sy-10-전체-agent-목록과-배포-범위게시-상태소유자) | 4. Deploy | 전체 Agent 목록과 배포 범위·게시 상태·소유자 | M365 Admin Center - Agent Registry | ❌ 미구현 |
| [DP-SY-11](docs/checklist.md#dp-sy-11-agent-공유-허용-범위-및-사용자-설치-허용-설정) | 4. Deploy | Agent 공유 허용 범위 및 사용자 설치 허용 설정 | M365 Admin Center - Copilot > Agents 설정 | ❌ 미구현 |
| [DP-SY-12](docs/checklist.md#dp-sy-12-고유-idagent-id가-부여된-agent-수--전체-agent-수) | 4. Deploy | 고유 ID(Agent ID)가 부여된 Agent 수 / 전체 Agent 수 | Microsoft Entra Agent ID | ⚠️ 일부 구현 |
| [OE-SY-13](docs/checklist.md#oe-sy-13-소유자후원자-미지정-agent-및-고아-agent-수) | 5. Operate | 소유자·후원자 미지정 Agent 및 고아 Agent 수 | Microsoft Entra Agent ID | ✅ 구현 |
| [OE-SY-14](docs/checklist.md#oe-sy-14-agent별-부여-권한-및-과다-권한-agent) | 5. Operate | Agent별 부여 권한 및 과다 권한 Agent | Microsoft Entra - Agent ID, ID Governance | ✅ 구현 |
| [OE-SY-15](docs/checklist.md#oe-sy-15-agent-대상-조건부-접근-정책-적용-및-위험-agent-탐지-건수) | 5. Operate | Agent 대상 조건부 접근 정책 적용 및 위험 Agent 탐지 건수 | Microsoft Entra - Conditional Access, ID Protection | ✅ 구현 |
| [OE-SY-16](docs/checklist.md#oe-sy-16-agent-활동-감사-로그-보관-여부-및-보관-기간) | 5. Operate | Agent 활동 감사 로그 보관 여부 및 보관 기간 | Microsoft Purview - Audit | ✅ 구현 |
| [OE-SY-17](docs/checklist.md#oe-sy-17-관리-id와-arm-역할-범위) | 5. Operate | 관리 ID와 ARM 역할 범위 | Azure Resource Graph, Azure RBAC | ✅ 구현 |
| [OE-SY-18](docs/checklist.md#oe-sy-18-관측경보-구성) | 5. Operate | 관측·경보 구성 | Azure Monitor | ✅ 구현 |
| [OE-SY-19](docs/checklist.md#oe-sy-19-경보-전달-경로) | 5. Operate | 경보 전달 경로 | Azure Monitor - 작업 그룹 | ✅ 구현 |
| [OE-SY-20](docs/checklist.md#oe-sy-20-지역과-보존-설정) | 5. Operate | 지역과 보존 설정 | Azure 리소스 위치, Log Analytics | ⚠️ 일부 구현 |
| [OT-SY-17](docs/checklist.md#ot-sy-17-승인되지-않은-agentshadow-ai-탐지-결과) | 6. Optimize | 승인되지 않은 Agent(Shadow AI) 탐지 결과 | Agent 365 - Shadow AI Detection | ❌ 미구현 |
| [OT-SY-18](docs/checklist.md#ot-sy-18-agent별-활성-사용자-수-최근-사용일-미사용-agent-수) | 6. Optimize | Agent별 활성 사용자 수, 최근 사용일, 미사용 Agent 수 | M365 Admin Center - Agent 사용 현황 / Agent 365 | ✅ 구현 |
| [OT-SY-19](docs/checklist.md#ot-sy-19-사용량-기반-과금-정책-설정-여부-및-agent별-소비-비용) | 6. Optimize | 사용량 기반 과금 정책 설정 여부 및 Agent별 소비 비용 | M365 Admin Center - Billing policy / Azure Cost Management | ✅ 구현 |
| [OT-SY-20](docs/checklist.md#ot-sy-20-agent가-접근하는-민감-데이터-노출-현황) | 6. Optimize | Agent가 접근하는 민감 데이터 노출 현황 | Microsoft Purview - DSPM for AI | ❌ 미구현 |
| [OT-SY-21](docs/checklist.md#ot-sy-21-예산예측-경보) | 6. Optimize | 예산·예측 경보 | Azure Cost Management | ✅ 구현 |

- 추가 제안 13개(DS-SY-07~09, BI-SY-10~14, OE-SY-17~20, OT-SY-21)는 [평가 모델 템플릿](docs/assessment-template.xlsx)에 병합되어 있으며 결과는 보고서 `추가 제안 현황` 시트(상태: 수집됨/일부 수집/수집 불가)에 나옵니다. 각 제안은 평가 모델의 6개 진단 영역(1. Demand ~ 6. Optimize) 중 하나로 분류하며(표의 `진단 영역` 열, 근거는 [docs/api-notes.md](docs/api-notes.md#azure-운영-추가-제안-13개-수집-ds-sy-07ot-sy-21)) 방법과 기존 항목과의 구분도 같은 곳에 있습니다
- 일부 항목의 Level은 원문 기준의 대리 지표로 산출하므로 고객 검토가 필요합니다 (예: BI-SY-09 "30일 내 조치"는 상태 변경일 경과, OT-SY-19 "조직별 배분"은 비용센터 태그, OE-SY-13 "고아"는 소유자 전원 비활성)

## 개발 참고

- 구성: [src/wasm_agent/](src/wasm_agent/) 수집기·내장 판정 기준([criteria.yaml](src/wasm_agent/criteria.yaml)) / [config/](config/) 고객 선택 입력 / [scripts/](scripts/) 관리자 셋업·점검 / [demo/](demo/) 개발용 데모(고객 수집과 무관) / [docs/api-notes.md](docs/api-notes.md) 개발자용 API·평가 근거
- 검사: `python -m pytest -q`, `python -m ruff check src scripts demo tests` (Azure 미호출). 데모 테스트는 `python -m pip install -e ".[dev,demo]"`

<details>
<summary>개발용 데모와 함께 통합 실행하려면</summary>

- 고객 진단에는 불필요. 데모 전용 설정과 승인된 관리자 배포 권한이 필요하며 비용이 발생합니다.

```bash
bash demo/run.sh --apply --collect
```

</details>

<details>
<summary>데모용 인프라와 Agent만 배포하려면 - 수집은 나중에 수동 실행</summary>

- 프로젝트 루트의 `.wasm-agent/setup.json`에 `tenant_id`·`subscription_ids`·`account_name`만 있으면 배포 가능. 모델 호출·유지 비용 발생. [삭제·재배포](demo/README.md)

```bash
bash scripts/setup.sh login
bash demo/run.sh --apply
```

</details>
