# EASM (Enterprise Agent Service Management) 거버넌스 진단/수집 툴

- **점검 대상:** Microsoft Foundry, Azure 자체 호스팅 Agent, 운영 로그·비용·보안, Entra Agent ID
- **결과:** 실행별 `output/<실행시각-UTC>/` 폴더에 Excel 보고서와 원본 JSON 저장
- **원칙:** 진단 앱은 읽기 권한만 사용하며 리소스를 변경하거나 비밀값을 조회하지 않습니다

## 진행 순서

| 순서 | 담당 | 할 일 |
| --- | --- | --- |
| 1 | <span style='background-color: #fff5b1'>**MS WASM 관리자**</span> | Codespaces와 인증서 준비 |
| 2 | <span style='background-color: #dcffe4'>**고객사 담당자**</span> | 진단 앱 등록, 공개 인증서 업로드 |
| 3 | <span style='background-color: #dcffe4'>**고객사 담당자**</span> | 전체 진단용 읽기 권한 부여 |
| 4 | <span style='background-color: #fff5b1'>**MS WASM 관리자**</span> | 점검·수집 후 결과 다운로드 |
| 5 | <span style='background-color: #e5dcf7'>**고객/MS 공동**</span> | 결과 검토와 권한 회수 |

## Step 1. <span style='background-color: #fff5b1'>[MS WASM 관리자]</span> Codespaces와 인증서 준비

저장소 **Code → Codespaces → Create codespace**에서 열고 아래를 실행합니다. 개인키 암호는 안전하게 보관합니다.

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
```

고객에게 `public-cert.pem`만 전달합니다. 개인키가 포함된 나머지 파일은 전달하거나 저장소에 올리지 않습니다.

## Step 2. <span style='background-color: #dcffe4'>[고객사 담당자]</span> 진단 앱 등록

1. [Azure Portal](https://portal.azure.com) → **Microsoft Entra ID → 앱 등록 → 새 등록**. 이름은 `wasmagent-diagnostic`, 계정 유형은 **Single tenant**로 등록합니다.

![앱 등록 위치](docs/imgs/07-register-sp.png)

2. **개요**에서 Tenant ID와 Client ID를 기록합니다. SP Object ID는 **엔터프라이즈 애플리케이션 → 해당 앱 → 속성**에서 확인합니다.

![앱 ID 확인 위치](docs/imgs/08-sp-overview.png)

3. **인증서 및 암호 → 인증서 → 인증서 업로드**에서 받은 `public-cert.pem`을 등록합니다.

![공개 인증서 업로드](docs/imgs/09-upload-certificate.png)

화면의 식별자·테넌트 이름은 마스킹했습니다.

MS 담당자에게 **Tenant ID, Client ID, SP Object ID, 승인 구독 ID 목록**을 전달합니다.

## Step 3. <span style='background-color: #dcffe4'>[고객사 담당자]</span> 전체 진단용 권한 부여

아래 읽기 권한을 **기본으로 모두 부여**합니다. Azure 역할과 Entra 권한은 서로 달라 둘 다 필요합니다.

| 범위 | 기본 권한 |
| --- | --- |
| 승인 구독 | Reader, Cost Management Reader, Log Analytics Reader, Security Reader |
| 승인 구독의 Foundry 프로젝트 | 사용자 지정 읽기 역할 - Agent·평가·평가 자산 조회만 허용 |
| Microsoft Graph | `AgentIdentity.Read.All`, `AgentIdentityBlueprint.Read.All`, `Application.Read.All` + 관리자 동의 |

**권한을 부여하는 고객 관리자**에게는 구독 역할 할당·사용자 지정 역할 생성 권한과 Entra 관리자 동의 권한이 필요합니다. 담당자가 다르면 각각 승인합니다. 진단 앱에는 Owner·Contributor를 부여하지 않습니다.

고객의 승인된 Bash 호스트에서 아래를 실행하면 기본 권한 전체를 설정합니다.

```bash
mkdir -p .wasm-agent
cat > .wasm-agent/setup.json <<'EOF'
{
  "tenant_id": "<Tenant ID>",
  "subscription_ids": ["<승인 구독 ID>"],
  "account_type": "service-principal",
  "account_name": "wasmagent-diagnostic",
  "client_id": "<Client ID>",
  "principal_id": "<SP Object ID>"
}
EOF
bash scripts/setup.sh login
bash scripts/setup.sh plan     # 부여할 권한 확인, Azure 변경 없음
bash scripts/setup.sh apply    # 기본 읽기 권한 전체 부여 및 확인
```

포털에서는 **구독 → 액세스 제어(IAM) → 역할 할당 추가**에서 Azure 역할을 확인합니다.

![역할 선택 위치](docs/imgs/10-reader-role.png)

![진단 앱과 구독 범위 확인](docs/imgs/11-reader-review.png)

Entra에서는 **앱 등록 → 진단 앱 → API 사용 권한**에서 위 Graph 권한 3개가 승인됐는지 확인합니다. 관리자 동의는 **Global Administrator 또는 Privileged Role Administrator**가 수행합니다.

![관리자 동의 위치 - 화면은 기존 촬영 예시이며 현재 필요한 권한은 위 3개](docs/imgs/12-entra-consent.png)

![권한 승인 상태 확인 위치 - 기존 촬영 예시](docs/imgs/13-entra-granted.png)

**Entra 점검도 필수입니다.** 권한이 빠지면 해당 항목은 점수를 낮추지 않고 **판정 보류**로 표시합니다. 권한을 보완한 뒤 다시 수집하면 됩니다.

## Step 4. <span style='background-color: #fff5b1'>[MS WASM 관리자]</span> 점검과 수집

전달받은 `setup.json`과 Step 1의 인증서로 **별도 진단 터미널**에서 실행합니다.

```bash
export AZURE_TENANT_ID='<Tenant ID>'
export AZURE_CLIENT_ID='<Client ID>'
export AZURE_CLIENT_CERTIFICATE_PATH="$cert_dir/diagnostic.pem"
read -r -s -p 'Certificate password: ' AZURE_CLIENT_CERTIFICATE_PASSWORD; printf '\n'
export AZURE_CLIENT_CERTIFICATE_PASSWORD
unset AZURE_CLIENT_SECRET AZURE_FEDERATED_TOKEN_FILE

bash scripts/setup.sh verify --certificate-path "$AZURE_CLIENT_CERTIFICATE_PATH"
wasm-agent collect --setup-file .wasm-agent/setup.json --output-dir output
```

- 결과는 실행별 `output/<실행시각-UTC>/`에 저장됩니다. 해당 폴더를 우클릭 → **Download**합니다.
- 권한·인증 점검이 실패하면 고객 관리자에게 보완을 요청합니다. 관리자 계정으로 대신 수집하지 않습니다.

## Step 5. <span style='background-color: #e5dcf7'>[고객/MS 공동]</span> 결과 확인과 종료

- Excel의 **진단 체크리스트**를 함께 검토합니다. **판정 보류**는 자료가 부족하다는 뜻이며 낮은 점수가 아닙니다.
- 종료 후 고객은 진단 앱의 권한·인증서를 회수하고, MS는 개인키와 수집 데이터를 승인된 보관 기간에 맞춰 폐기합니다.

## 점검 항목 (System Evidence 32개)

✅ 수집 구현 / ⚠️ 일부 조회 또는 읽기 권한 제한 / ❌ 현재 수집 범위 밖입니다. 자세한 내용은 [점검 항목 상세](docs/checklist.md), 심사 기준은 [평가 템플릿](docs/assessment-template.xlsx)에서 확인합니다.

| 코드 | 영역 | 점검 내용 | 수집 | 신규 추가 |
| --- | --- | --- | --- | --- |
| [DM-SY-01](docs/checklist.md#dm-sy-01-agent-제작-허용-사용자-범위-및-허용-agent-유형-설정) | Demand | Agent 제작 허용 범위 | ❌ | |
| [DM-SY-02](docs/checklist.md#dm-sy-02-copilot-studio-제작-권한-보유자-수-및-환경-현황) | Demand | 제작 권한과 환경 | ❌ | |
| [DM-SY-03](docs/checklist.md#dm-sy-03-최근-6개월-신규-생성-agent-수-추이) | Demand | 신규 Agent 생성 추이 | ❌ | |
| [DS-SY-04](docs/checklist.md#ds-sy-04-커넥터-분류차단-정책데이터-정책-적용-현황) | Design | 커넥터·데이터 정책 | ❌ | |
| [DS-SY-05](docs/checklist.md#ds-sy-05-agent-id-템플릿blueprint-정의-여부-및-개수) | Design | Agent ID 템플릿 | ✅ | |
| [DS-SY-06](docs/checklist.md#ds-sy-06-사용-중인-모델-배포-현황-및-허용-모델-목록) | Design | 허용 모델 사용 | ✅ | |
| [DS-SY-07](docs/checklist.md#ds-sy-07-네트워크-경계와-공용-접근) | Design | 네트워크 경계 | ✅ | ✓ |
| [DS-SY-08](docs/checklist.md#ds-sy-08-도구-구성과-승인-모드) | Design | 도구 사용과 승인 | ✅ | ✓ |
| [DS-SY-09](docs/checklist.md#ds-sy-09-외부-도구-엔드포인트) | Design | 외부 도구 연결 | ✅ | ✓ |
| [BI-SY-07](docs/checklist.md#bi-sy-07-환경-분리-및-관리형-환경-적용-여부) | Build | 개발·운영 환경 분리 | ❌ | |
| [BI-SY-08](docs/checklist.md#bi-sy-08-품질안전성-자동-평가-수행-이력) | Build | 품질·안전성 평가 | ✅ | |
| [BI-SY-09](docs/checklist.md#bi-sy-09-ai-워크로드-보안-태세-점검-결과) | Build | AI 보안 점검 | ✅ | |
| [BI-SY-10](docs/checklist.md#bi-sy-10-content-safety-정책-연결) | Build | 콘텐츠 필터 | ✅ | ✓ |
| [BI-SY-11](docs/checklist.md#bi-sy-11-적대적-시험red-team-이력) | Build | 적대적 시험 이력 | ⚠️ | ✓ |
| [BI-SY-12](docs/checklist.md#bi-sy-12-릴리스-버전-고정런타임) | Build | 버전·업데이트 관리 | ✅ | ✓ |
| [BI-SY-13](docs/checklist.md#bi-sy-13-agent-자산-대장책임-태그) | Build | 자산 대장·담당자 | ✅ | ✓ |
| [BI-SY-14](docs/checklist.md#bi-sy-14-azure-정책-준수-상태) | Build | Azure 정책 준수 | ✅ | ✓ |
| [DP-SY-10](docs/checklist.md#dp-sy-10-전체-agent-목록과-배포-범위게시-상태소유자) | Deploy | Agent 등록·배포 현황 | ❌ | |
| [DP-SY-11](docs/checklist.md#dp-sy-11-agent-공유-허용-범위-및-사용자-설치-허용-설정) | Deploy | 공유·설치 허용 범위 | ❌ | |
| [DP-SY-12](docs/checklist.md#dp-sy-12-고유-idagent-id가-부여된-agent-수--전체-agent-수) | Deploy | Agent ID 부여율 | ⚠️ | |
| [OE-SY-13](docs/checklist.md#oe-sy-13-소유자후원자-미지정-agent-및-고아-agent-수) | Operate | 소유자·후원자 지정 | ✅ | |
| [OE-SY-14](docs/checklist.md#oe-sy-14-agent별-부여-권한-및-과다-권한-agent) | Operate | 과다 권한 | ✅ | |
| [OE-SY-15](docs/checklist.md#oe-sy-15-agent-활동-감사-로그-보관-여부-및-보관-기간) | Operate | 감사 로그·보존 기간 | ✅ | |
| [OE-SY-17](docs/checklist.md#oe-sy-17-관리-id와-arm-역할-범위) | Operate | 관리 ID·역할 범위 | ✅ | ✓ |
| [OE-SY-18](docs/checklist.md#oe-sy-18-관측경보-구성) | Operate | 모니터링·경보 | ✅ | ✓ |
| [OE-SY-19](docs/checklist.md#oe-sy-19-경보-전달-경로) | Operate | 경보 전달·대응 경로 | ✅ | ✓ |
| [OE-SY-20](docs/checklist.md#oe-sy-20-지역과-보존-설정) | Operate | 데이터 지역·보존 | ⚠️ | ✓ |
| [OT-SY-17](docs/checklist.md#ot-sy-17-승인되지-않은-agentshadow-ai-탐지-결과) | Optimize | 미승인 Agent 탐지 | ❌ | |
| [OT-SY-18](docs/checklist.md#ot-sy-18-agent별-활성-사용자-수-최근-사용일-미사용-agent-수) | Optimize | 장기 미사용 Agent | ✅ | |
| [OT-SY-19](docs/checklist.md#ot-sy-19-사용량-기반-과금-정책-설정-여부-및-agent별-소비-비용) | Optimize | Agent별 비용 | ✅ | |
| [OT-SY-20](docs/checklist.md#ot-sy-20-agent가-접근하는-민감-데이터-노출-현황) | Optimize | 민감 데이터 노출 | ❌ | |
| [OT-SY-21](docs/checklist.md#ot-sy-21-예산예측-경보) | Optimize | 예산·비용 경보 | ✅ | ✓ |

## 개발 참고

- [config/config.yaml](config/config.yaml): 허용 모델·내부 기준 등 선택 입력
- [docs/api-notes.md](docs/api-notes.md): 권한·API·심사 근거와 기술적 한계
- 검사: `python -m pytest -q`, `python -m ruff check src scripts demo tests`

<details>
<summary>Excel 보고서만 다시 만들기</summary>

`wasm-agent package --output-dir output`을 실행합니다. 최신 실행 폴더의 `raw-data-<타임스탬프>.json`에서 `report-<타임스탬프>.xlsx`를 재생성합니다.

</details>

<details>
<summary>개발용 데모 실행</summary>

고객 진단에는 필요 없습니다. 승인된 테스트 환경에서만 실행합니다.

```bash
bash demo/run.sh --apply
bash demo/run.sh --apply --collect
```

첫 명령의 수집은 나중에 수동 실행합니다. 자세한 내용은 [demo/README.md](demo/README.md)를 참고하세요.

</details>
