# 고객과 확인할 자료

- 수집 대상: Microsoft Foundry, Azure 자체 호스팅 Agent, Azure Monitor·Log Analytics, 비용·보안 권고.

- 수집 실행만으로 모든 진단 기준을 확정할 수는 없습니다. 아래 자료를 고객과 확정하거나 시간이 지난 뒤 재확인하세요. 명령 실행 방법은 [고객 실행 안내](../README.md)를 참고하세요.

- **샘플 배포**
  - 자동화/남은 확인: `bash scripts/lab/manage.sh all --apply`; 관리자와 진단 SP 분리
- **재수집**
  - 자동화/남은 확인: `bash scripts/lab/manage.sh collect`; 임시 인증서 자동 등록·정리
- **고객 허용 모델**
  - 자동화/남은 확인: config/allowed_models.yaml의 샘플 정책을 고객 승인 목록으로 교체
- **태그 규약**
  - 자동화/남은 확인: config/tag_conventions.yaml의 owner/sponsor/env/cost-center/agent-id 확정
- **운영 Agent**
  - 자동화/남은 확인: sample env=test는 운영 배포 전 평가 분모가 아님. 실제 운영 범위 확정
- **배포 전 평가**
  - 자동화/남은 확인: 평가 실행 여부뿐 아니라 실제 Agent/버전·평가 완료·배포 시각 연결 자료 확보. 생성 시각으로 대체 금지
- **로그**
  - 자동화/남은 확인: AppServiceConsoleLogs 유입 지연, 수집 시작·누락·토큰 필드 및 보존 기간 확인
- **90일 비활성**
  - 자동화/남은 확인: 실제 장기 관측 필요. 최근 사용이 없다는 이유만으로 비활성 판정 금지
- **비용**
  - 자동화/남은 확인: 신규 샘플의 청구 반영 지연 확인. 공유 모델·App Service 플랜·모니터링 비용 분모 검토
- **Defender**
  - 자동화/남은 확인: AI 기능·라이선스와 실제 AI 리소스 연결 권고 표본 확보. 빈 권고를 양호로 단정 금지
- **내부 기준**
  - 자동화/남은 확인: required_retention_days 및 internal_security_score_min은 고객 규정으로 입력
- **상위 성숙도**
  - 자동화/남은 확인: '정책 적용 여부 + 근거 파일'을 제공. 설정에서는 policy_facts의 value와 evidence_refs로 입력. 비율만 높다고 상위 단계로 올리지 않음
- **과금**
  - 자동화/남은 확인: 샘플 유지 승인. B1 플랜 2개만 USD 0.864/일, 모델·로그 비용은 별도
- **자격증명**
  - 자동화/남은 확인: 임시 인증서 정상 정리 여부와 기존 인증서 보존 확인. 강제 종료 시 공개키 만료/정리 확인

- 원본 응답 표본: Foundry 신규 Agent/버전, 프로젝트 endpoint, 모델 배포, 평가 run, Cost Management의 columns/rows, metrics definition·dimension, Log Analytics query, 진단 설정·워크스페이스 보존, Defender assessment의 리소스 연결을 비식별화해서 검토합니다.
