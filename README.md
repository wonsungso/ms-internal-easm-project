# EASM (Enterprise Agent Service Management) 거버넌스 진단/수집 툴

- **점검 대상:** Microsoft Foundry, Azure 자체 호스팅 Agent, 운영 로그·비용·보안, Entra Agent ID
- **결과:** 실행별 `output/<실행시각-UTC>/` 폴더에 Excel 보고서와 원본 JSON 저장
- **원칙:** 진단 앱은 읽기 권한만 사용하며 리소스를 변경하거나 비밀값을 조회하지 않습니다
- **로그 범위:** Agent 관련 AI 계정·호스트의 실행 로그를 점검합니다.

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

고객 전달용 폴더에 **공개 인증서와 권한 설정 파일만** 준비합니다.

```bash
mkdir -p .wasm-agent/customer-setup
cp "$cert_dir/public-cert.pem" scripts/setup_account.py scripts/foundry-reader.json .wasm-agent/customer-setup/
```

고객에게 이 폴더의 **3개 파일만 전달**합니다. 고객에게 저장소·수집기를 제공할 필요는 없습니다. 개인키·`diagnostic.pem`·개인키 암호는 MS 담당자가 보관하며 전달하거나 저장소에 올리지 않습니다.

## Step 2. <span style='background-color: #dcffe4'>[고객사 담당자]</span> 진단 앱 등록

1. [Azure Portal](https://portal.azure.com) → **Microsoft Entra ID → 앱 등록 → 새 등록**. 이름은 `wasmagent-diagnostic`, 계정 유형은 **Single tenant**로 등록합니다.

![앱 등록 위치](docs/imgs/07-register-sp.png)

2. **개요**에서 Tenant ID와 Client ID를 기록합니다. SP Object ID는 **엔터프라이즈 애플리케이션 → 해당 앱 → 속성**에서 확인합니다.

![앱 ID 확인 위치](docs/imgs/08-sp-overview.png)

3. **인증서 및 암호 → 인증서 → 인증서 업로드**에서 받은 `public-cert.pem`을 등록합니다.

![공개 인증서 업로드](docs/imgs/09-upload-certificate.png)

MS 담당자에게 **Tenant ID, Client ID, SP Object ID, 승인 구독 ID 목록**을 전달합니다.

## Step 3. <span style='background-color: #dcffe4'>[고객사 담당자]</span> 전체 진단용 권한 부여

아래 읽기 권한을 **기본으로 모두 부여**합니다. Azure 역할과 Entra 권한은 서로 달라 둘 다 필요합니다.

| 종류 | 권한 전체 이름 | 부여 범위 |
| --- | --- | --- |
| Azure | `Reader` | 승인 구독 |
| Azure | `Cost Management Reader` | 승인 구독 |
| Azure | `Log Analytics Reader` | 승인 구독 |
| Azure | `Security Reader` | 승인 구독 |
| Foundry 사용자 지정 역할 | `WASMAgent Foundry Evidence Reader v2` | 승인 구독의 프로젝트에 상속 |
| Graph 애플리케이션 권한 | `AgentIdentity.Read.All` | 테넌트, 관리자 동의 필요 |
| Graph 애플리케이션 권한 | `AgentIdentityBlueprint.Read.All` | 테넌트, 관리자 동의 필요 |
| Graph 애플리케이션 권한 | `Application.Read.All` | 테넌트, 관리자 동의 필요 |

**권한을 부여하는 고객 관리자**에게는 구독 역할 할당·사용자 지정 역할 생성 권한과 Entra 관리자 동의 권한이 필요합니다.
진단 앱에는 Owner·Contributor를 부여하지 않습니다.

MS WASM 관리자로부터 전달받은 **[setup_account.py 다운로드](https://github.com/wonsungso/ms-internal-wasm-project/raw/refs/heads/main/scripts/setup_account.py) · [foundry-reader.json 다운로드](https://github.com/wonsungso/ms-internal-wasm-project/raw/refs/heads/main/scripts/foundry-reader.json)**을 같은 폴더에 두고, **Python 3.11 이상과 Azure CLI가 있는 승인된 Bash 환경**에서 아래를 실행합니다.

다운로드 링크는 저장소 접근 권한이 필요합니다. 고객에게 권한이 없으면 MS 담당자가 두 파일을 다운로드하여 별도로 전달합니다.

`apply`는 목록의 모든 승인 구독에 기본 Azure 역할 4개·Foundry 사용자 지정 역할을 할당하고 Graph 권한 3개를 추가·동의합니다.
고객은 자신의 관리자 계정으로 로그인하며 MS에 관리자 인증 정보를 전달하지 않습니다.

```bash
cat > setup.json <<'EOF'
{
  "tenant_id": "<Tenant ID>",
  "subscription_ids": [
    "<승인 구독 1 ID>",
    "<승인 구독 2 ID>",
    "<승인 구독 3 ID>"
  ],
  "account_type": "service-principal",
  "account_name": "wasmagent-diagnostic",
  "client_id": "<Client ID>",
  "principal_id": "<SP Object ID>"
}
EOF
python3 setup_account.py --config-file setup.json --login
python3 setup_account.py --config-file setup.json --dry-run  # 부여할 권한 확인, Azure 변경 없음
python3 setup_account.py --config-file setup.json --result-file setup.json --apply
```

완료된 **setup.json만 MS 담당자에게 반환**합니다. 고객에게 개인키를 보내거나 수집을 실행하도록 요청하지 않습니다. Azure 역할 관리자와 Entra 동의 관리자가 다르면 동일 파일로 각 승인 절차를 이어서 진행합니다.

스크립트 실행 후 아래 화면에서 권한을 확인할 수 있습니다. **포털에서 같은 권한을 다시 부여할 필요는 없습니다.**

<details>
<summary>Azure 역할 설정 (Portal 기준)</summary>


**구독 → 액세스 제어(IAM) → 역할 할당 추가**에서 역할과 진단 앱을 지정합니다.

![Azure Reader 역할 선택 위치](docs/imgs/10-reader-role.png)

### Foundry 사용자 지정 역할 설정

스크립트로 역할을 생성한 뒤 같은 IAM 화면에서 **WASMAgent Foundry Evidence Reader v2**를 선택합니다.

![Foundry 사용자 지정 읽기 역할 선택](docs/imgs/17-foundry-reader.png)

### Graph 애플리케이션 권한 설정

**Entra → 앱 등록 → 진단 앱 → API 사용 권한**에서 권한 3개를 확인하고 **관리자 동의**합니다.

![Graph 읽기 권한 3개와 관리자 동의 위치](docs/imgs/12-entra-consent.png)

### 나머지 역할·DataActions·승인 완료 화면

**구독 → 액세스 제어(IAM) → 역할 할당 추가**에서 아래 역할을 선택합니다. 수동으로 설정한다면 각 역할마다 진단 앱을 멤버로 지정하고 **검토 + 할당**합니다.

![진단 앱과 구독 범위 확인](docs/imgs/11-reader-review.png)

![Cost Management Reader 선택](docs/imgs/14-cost-reader.png)

![Log Analytics Reader 선택](docs/imgs/15-log-reader.png)

![Security Reader 선택](docs/imgs/16-security-reader.png)

Foundry 역할은 스크립트가 생성합니다. 같은 목록에서 **WASMAgent Foundry Evidence Reader v2**를 선택하고 **View → JSON** 또는 **Permissions → DataActions**에서 아래 읽기 권한 3개만 있는지 확인합니다.

| Foundry DataActions 전체 이름 |
| --- |
| `Microsoft.CognitiveServices/accounts/AIServices/agents/read` |
| `Microsoft.CognitiveServices/accounts/AIServices/evaluations/read` |
| `Microsoft.CognitiveServices/accounts/AIServices/assets/read` |

![Foundry JSON에서 읽기 DataActions 전체 이름 3개 확인](docs/imgs/18-foundry-permissions.png)

Entra에서는 **앱 등록 → 진단 앱 → API 사용 권한**에서 Graph 권한 3개와 승인 상태를 확인합니다. 수동 동의는 **Global Administrator 또는 Privileged Role Administrator**가 수행하며, PIM을 사용하면 먼저 해당 역할을 활성화합니다.

![관리자 동의 확인](docs/imgs/19-entra-confirm.png)

![Graph 읽기 권한 3개 승인 완료 확인](docs/imgs/13-entra-granted.png)

**Entra 점검도 필수입니다.** 권한이 빠지면 해당 항목은 점수를 낮추지 않고 **판정 보류**로 표시합니다. 권한을 보완한 뒤 다시 수집하면 됩니다.
</details>

## Step 4. <span style='background-color: #fff5b1'>[MS WASM 관리자]</span> 점검과 수집

MS 담당자는 고객이 반환한 `setup.json`을 이 저장소의 **.wasm-agent/setup.json**으로 저장하고, Step 1에서 보관한 인증서로 **별도 진단 터미널**에서 실행합니다. `scripts/setup.sh verify`와 수집기는 MS 담당자 환경에서만 실행합니다.

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

- 결과는 실행별 `output/<실행시각-UTC>/`에 저장됩니다.
- 권한·인증 점검이 실패하면 고객 관리자에게 보완을 요청합니다.

## Step 5. <span style='background-color: #e5dcf7'>[고객/MS 공동]</span> 결과 확인과 종료

- **6. 수집 결과**의 G열 **확인상태**에서 수집 여부와 인터뷰 필요 항목을 확인합니다.
- H열 **지표**에서 실제 확인한 수치·건수를 확인합니다.
- I열 **판정**에서 등급과 해당 평가기준을 함께 읽습니다.
- J열 **근거**에서 수집된 사실과 등급 산정 이유를 확인합니다.
- K열 **다음조치**에서 다음 등급에 필요한 조건을 확인합니다.
- L열 **평가 점수 (1~5)**는 수집 항목의 Level에 해당하는 점수입니다. 판정이 없는 항목은 빈칸이며 M열 **검토메모**에 공동 검토 내용을 기록합니다.
- **7. 수집결과 근거**와 **8. 수집 Raw 데이터**에서 상세 설정과 원본 값을 확인합니다.
- **9. 수집이슈 Raw 데이터**와 **10. 필드누락사유**에서 조회 실패·자료 부족의 원인을 확인합니다.
- 종료 후 고객은 진단 앱의 권한·인증서를 회수하고, MS는 개인키와 수집 데이터를 승인된 보관 기간에 맞춰 폐기합니다.

## 점검 항목 (System Evidence 31개)

✅ 수집 구현 / ⚠️ 일부 조회 또는 읽기 권한 제한 / ❌ 현재 수집 범위 밖입니다. 자세한 내용은 [점검 항목 상세](docs/checklist.md), 심사 기준은 [평가 템플릿](docs/assessment-result-template.xlsx)에서 확인합니다.

| 코드 | 영역 | 점검 내용 | 수집 | 신규 추가 |
| --- | --- | --- | --- | --- |
| [DM-SY-01](docs/checklist.md#dm-sy-01-agent-제작-허용-사용자-범위-및-허용-agent-유형-설정) | 1. Demand | Agent 제작 허용 범위 | ❌ | |
| [DM-SY-02](docs/checklist.md#dm-sy-02-copilot-studio-제작-권한-보유자-수-및-환경-현황) | 1. Demand | 제작 권한과 환경 | ❌ | |
| [DM-SY-03](docs/checklist.md#dm-sy-03-최근-6개월-신규-생성-agent-수-추이) | 1. Demand | 신규 Agent 생성 추이 | ❌ | |
| [DS-SY-04](docs/checklist.md#ds-sy-04-커넥터-분류차단-정책데이터-정책-적용-현황) | 2. Design | 커넥터·데이터 정책 | ❌ | |
| [DS-SY-05](docs/checklist.md#ds-sy-05-agent-id-템플릿blueprint-정의-여부-및-개수) | 2. Design | Agent ID 템플릿 | ✅ | |
| [DS-SY-06](docs/checklist.md#ds-sy-06-사용-중인-모델-배포-현황-및-허용-모델-목록) | 2. Design | 허용 모델 사용 | ✅ | |
| [DS-SY-07](docs/checklist.md#ds-sy-07-네트워크-경계와-공용-접근) | 2. Design | 네트워크 경계 | ✅ | ✓ |
| [DS-SY-08](docs/checklist.md#ds-sy-08-도구-구성과-승인-모드) | 2. Design | 도구 사용과 승인 | ✅ | ✓ |
| [DS-SY-09](docs/checklist.md#ds-sy-09-외부-도구-엔드포인트) | 2. Design | 외부 도구 연결 | ✅ | ✓ |
| [BI-SY-10](docs/checklist.md#bi-sy-10-환경-분리-및-관리형-환경-적용-여부) | 3. Build | 개발·운영 환경 분리 | ❌ | |
| [BI-SY-11](docs/checklist.md#bi-sy-11-품질안전성-자동-평가-수행-이력) | 3. Build | 품질·안전성 평가 | ✅ | |
| [BI-SY-12](docs/checklist.md#bi-sy-12-ai-워크로드-보안-태세-점검-결과) | 3. Build | AI 보안 점검 | ✅ | |
| [BI-SY-13](docs/checklist.md#bi-sy-13-content-safety-정책-연결) | 3. Build | 콘텐츠 필터 | ✅ | ✓ |
| [BI-SY-14](docs/checklist.md#bi-sy-14-릴리스-버전-고정런타임) | 3. Build | 버전·업데이트 관리 | ✅ | ✓ |
| [BI-SY-15](docs/checklist.md#bi-sy-15-agent-자산-대장책임-태그) | 3. Build | 자산 대장·담당자 | ✅ | ✓ |
| [BI-SY-16](docs/checklist.md#bi-sy-16-azure-정책-준수-상태) | 3. Build | Azure 정책 준수 | ✅ | ✓ |
| [DP-SY-17](docs/checklist.md#dp-sy-17-전체-agent-목록과-배포-범위게시-상태소유자) | 4. Deploy | Agent 등록·배포 현황 | ❌ | |
| [DP-SY-18](docs/checklist.md#dp-sy-18-agent-공유-허용-범위-및-사용자-설치-허용-설정) | 4. Deploy | 공유·설치 허용 범위 | ❌ | |
| [DP-SY-19](docs/checklist.md#dp-sy-19-고유-idagent-id가-부여된-agent-수--전체-agent-수) | 4. Deploy | Agent ID 부여율 | ⚠️ | |
| [OE-SY-20](docs/checklist.md#oe-sy-20-소유자후원자-미지정-agent-및-고아-agent-수) | 5. Operate | 소유자·후원자 지정 | ✅ | |
| [OE-SY-21](docs/checklist.md#oe-sy-21-agent별-부여-권한-및-과다-권한-agent) | 5. Operate | 과다 권한 | ✅ | |
| [OE-SY-22](docs/checklist.md#oe-sy-22-agent-활동-감사-로그-보관-여부-및-보관-기간) | 5. Operate | 감사 로그·보존 기간 | ✅ | |
| [OE-SY-23](docs/checklist.md#oe-sy-23-관리-id와-arm-역할-범위) | 5. Operate | 관리 ID·역할 범위 | ✅ | ✓ |
| [OE-SY-24](docs/checklist.md#oe-sy-24-관측경보-구성) | 5. Operate | 모니터링·경보 | ✅ | ✓ |
| [OE-SY-25](docs/checklist.md#oe-sy-25-경보-전달-경로) | 5. Operate | 경보 전달·대응 경로 | ✅ | ✓ |
| [OE-SY-26](docs/checklist.md#oe-sy-26-지역과-보존-설정) | 5. Operate | 데이터 지역·보존 | ⚠️ | ✓ |
| [OT-SY-27](docs/checklist.md#ot-sy-27-승인되지-않은-agentshadow-ai-탐지-결과) | 6. Optimize | 미승인 Agent 탐지 | ❌ | |
| [OT-SY-28](docs/checklist.md#ot-sy-28-agent별-활성-사용자-수-최근-사용일-미사용-agent-수) | 6. Optimize | 장기 미사용 Agent | ✅ | |
| [OT-SY-29](docs/checklist.md#ot-sy-29-사용량-기반-과금-정책-설정-여부-및-agent별-소비-비용) | 6. Optimize | Agent별 비용 | ✅ | |
| [OT-SY-30](docs/checklist.md#ot-sy-30-agent가-접근하는-민감-데이터-노출-현황) | 6. Optimize | 민감 데이터 노출 | ❌ | |
| [OT-SY-31](docs/checklist.md#ot-sy-31-예산예측-경보) | 6. Optimize | 예산·비용 경보 | ✅ | ✓ |

## 개발 참고

- [config/criteria.yaml](config/criteria.yaml): Level 1~5 임계값·등급 규칙. 기본 기준을 조정할 때 수정
- [config/custom-config.yaml](config/custom-config.yaml): 허용 모델·내부 보존기간·태그·정책 증적 등 고객별 선택 입력. 없어도 기본 수집 가능

두 파일은 저장소의 `config/` 폴더에서 관리합니다. 별도 기준 파일은 `wasm-agent collect --criteria <기준.yaml> --config <고객설정.yaml>`로 지정합니다. 수집 기본값은 `config/criteria.yaml`과 `config/custom-config.yaml`이며, 기준 파일이 없는 설치 환경은 배포 패키지에 포함한 기본 기준을 사용합니다. 명시한 기준 파일이 없거나 YAML이 잘못되면 오류로 종료합니다.

Level 문장과 규칙을 변경한 경우 평가 템플릿도 함께 갱신합니다: `python -m scripts.merge_assessment --source docs/assessment-result-template.xlsx --output <갱신할-템플릿.xlsx>`. 검토 후 갱신 파일을 기존 템플릿 대신 사용하세요. 기존 결과의 `package`는 점수를 다시 계산하지 않습니다.
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
