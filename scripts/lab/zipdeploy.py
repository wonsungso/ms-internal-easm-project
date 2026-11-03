from __future__ import annotations

import time
from pathlib import Path
from typing import Any
from urllib.parse import urljoin, urlparse

import requests


def deploy_zip(
    site: dict[str, Any], archive: Path, credential: Any, previous_ids: set[str],
) -> dict[str, Any]:
    host = site["defaultHostName"]
    if not host.endswith(".azurewebsites.net") or "/" in host:
        raise ValueError("승인된 Azure 웹 앱 호스트가 아닙니다.")
    scm = "https://" + host.removesuffix(".azurewebsites.net") + ".scm.azurewebsites.net"
    token = credential.get_token("https://management.azure.com/.default").token
    headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/zip"}
    print(f"직접 Kudu ZIP 전송: {site['name']}", flush=True)
    with archive.open("rb") as stream:
        response = requests.post(
            scm + "/api/zipdeploy?isAsync=true", data=stream, headers=headers,
            timeout=(30, 300), allow_redirects=False,
        )
    location = response.headers.get("Location")
    status = response.status_code
    response.close()
    if status not in (200, 201, 202) or not location:
        raise RuntimeError(f"Kudu 직접 ZIP 접수 실패: HTTP {status}, 상태 URL 존재={bool(location)}")
    status_url = urljoin(scm, location)
    if urlparse(status_url).scheme != "https" or urlparse(status_url).netloc != urlparse(scm).netloc:
        print("Kudu Location 원점이 달라 신뢰한 원래 SCM의 새 배포 상태를 검증합니다.", flush=True)
        status_url = scm + "/api/deployments/latest"
    for attempt in range(60):
        response = requests.get(status_url, headers={"Authorization": f"Bearer {token}"},
                                timeout=30, allow_redirects=False)
        if response.status_code == 202:
            response.close()
            if attempt % 6 == 0:
                print(f"Kudu 비동기 처리 중: {site['name']}", flush=True)
            time.sleep(10)
            continue
        try:
            if response.status_code != 200:
                raise RuntimeError(f"Kudu 상태 조회 실패: HTTP {response.status_code}")
            state = response.json()
        finally:
            response.close()
        if state["id"] not in previous_ids:
            if state.get("status") == 3:
                raise RuntimeError("Kudu 직접 ZIP 배포 실패(status=3)")
            if state.get("status") == 4 and state.get("complete"):
                print(f"Kudu 새 배포 완료 확인: {site['name']}", flush=True)
                return state
        if attempt % 6 == 0:
            print(f"Kudu 상태 대기: {site['name']}, status={state.get('status')}", flush=True)
        time.sleep(10)
    raise RuntimeError("Kudu 직접 ZIP 배포 완료 확인 시간 초과")
