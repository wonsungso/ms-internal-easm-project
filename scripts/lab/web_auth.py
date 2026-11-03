from __future__ import annotations

from typing import Any

from scripts.lab.bootstrap import AdminARM
from scripts.lab.certificates import GraphCertificates
from scripts.setup.setup_account import AzureCLI


def auth_settings(tenant: str, app_id: str, allowed_oids: list[str]) -> dict[str, Any]:
    if not allowed_oids:
        raise ValueError("허용할 사용자 Object ID가 필요합니다.")
    return {"properties": {
        "platform": {"enabled": True, "runtimeVersion": "~1"},
        "globalValidation": {
            "requireAuthentication": True, "unauthenticatedClientAction": "RedirectToLoginPage",
            "redirectToProvider": "azureactivedirectory", "excludedPaths": ["/health"],
        },
        "identityProviders": {"azureActiveDirectory": {
            "enabled": True,
            "registration": {
                "clientId": app_id, "openIdIssuer": f"https://login.microsoftonline.com/{tenant}/v2.0",
                "clientSecretSettingName": "OVERRIDE_USE_MI_FIC_ASSERTION_CLIENTID",
            },
            "validation": {
                "allowedAudiences": [app_id],
                "defaultAuthorizationPolicy": {"allowedPrincipals": {"identities": allowed_oids}},
            },
            "login": {"loginParameters": ["scope=openid profile email"]},
        }},
        "login": {"tokenStore": {"enabled": True}},
        "httpSettings": {"requireHttps": True},
    }}


def configure(
    cli: AzureCLI, arm: AdminARM, graph: GraphCertificates, setup: dict, lab: dict,
    host: dict, allowed_oids: list[str],
) -> dict:
    sid = host["id"].split("/")[2]
    group = host["id"].split("/")[4]
    identity_id = (
        f"/subscriptions/{sid}/resourceGroups/{group}/providers/"
        f"Microsoft.ManagedIdentity/userAssignedIdentities/{host['name']}-login"
    )
    providers = cli.run("provider", "list", "--subscription", sid)
    if not any(row["namespace"] == "Microsoft.ManagedIdentity" and row["registrationState"] == "Registered"
               for row in providers):
        cli.run("provider", "register", "--namespace", "Microsoft.ManagedIdentity", "--subscription", sid, "--wait")
    identity = arm.ensure(identity_id, "2023-01-31", {
        "location": lab["region"], "tags": {"seagent-lab": lab["lab_id"]},
    }, lab["lab_id"])
    site = arm.request("GET", host["id"], "2024-11-01")
    identities = (site.get("identity") or {}).get("userAssignedIdentities") or {}
    if identity_id.lower() not in {key.lower() for key in identities}:
        cli.run("webapp", "identity", "assign", "--name", host["name"], "--resource-group", group,
                "--subscription", sid, "--identities", identity_id)
    display = host["name"] + "-chat-login"
    marker = "SEAgent chatbot lab " + lab["lab_id"]
    apps = graph.request("GET", "/applications", params={
        "$filter": f"displayName eq '{display}'", "$select": "id,appId,notes,web,signInAudience",
    })["value"]
    if len(apps) > 1 or (apps and apps[0].get("notes") != marker):
        raise RuntimeError("챗봇 로그인 앱 소유 표식이 없거나 유일하지 않습니다.")
    redirect = "https://" + host["name"] + ".azurewebsites.net/.auth/login/aad/callback"
    if not apps:
        application = graph.request("POST", "/applications", {
            "displayName": display, "notes": marker, "signInAudience": "AzureADMyOrg",
            "web": {"redirectUris": [redirect], "implicitGrantSettings": {"enableIdTokenIssuance": True}},
        })
    else:
        application = apps[0]
        if application.get("signInAudience") != "AzureADMyOrg" or redirect not in application["web"]["redirectUris"]:
            raise RuntimeError("기존 챗봇 로그인 앱의 테넌트/redirect 설정이 예상과 다릅니다.")
        if not (application["web"].get("implicitGrantSettings") or {}).get("enableIdTokenIssuance"):
            graph.request("PATCH", "/applications/" + application["id"], {"web": {
                "redirectUris": application["web"]["redirectUris"],
                "implicitGrantSettings": {"enableIdTokenIssuance": True, "enableAccessTokenIssuance": False},
            }})
    app_id, object_id = application["appId"], application["id"]
    principals = graph.request("GET", "/servicePrincipals", params={
        "$filter": f"appId eq '{app_id}'", "$select": "id",
    })["value"]
    if not principals:
        graph.request("POST", "/servicePrincipals", {"appId": app_id})
    fic = {
        "name": "seagent-web-login", "issuer": f"https://login.microsoftonline.com/{setup['tenant_id']}/v2.0",
        "subject": identity["properties"]["principalId"], "audiences": ["api://AzureADTokenExchange"],
    }
    credentials = graph.request("GET", f"/applications/{object_id}/federatedIdentityCredentials")["value"]
    existing = next((entry for entry in credentials if entry["name"] == fic["name"]), None)
    if existing is None:
        graph.request("POST", f"/applications/{object_id}/federatedIdentityCredentials", fic)
    elif any(existing.get(key) != value for key, value in fic.items()):
        raise RuntimeError("기존 연합 자격증명이 이번 로그인 identity와 다릅니다.")
    cli.run(
        "webapp", "config", "appsettings", "set", "--name", host["name"], "--resource-group", group,
        "--subscription", sid, "--settings",
        "OVERRIDE_USE_MI_FIC_ASSERTION_CLIENTID=" + identity["properties"]["clientId"],
        "SEAGENT_CHAT_ALLOWED_OIDS=" + ",".join(allowed_oids),
        "--slot-settings", "OVERRIDE_USE_MI_FIC_ASSERTION_CLIENTID=" + identity["properties"]["clientId"],
    )
    settings = auth_settings(setup["tenant_id"], app_id, allowed_oids)
    arm.request("PUT", host["id"] + "/config/authsettingsV2", "2024-11-01", settings)
    actual = arm.request("GET", host["id"] + "/config/authsettingsV2", "2024-11-01")
    if actual["properties"]["globalValidation"]["requireAuthentication"] is not True:
        raise RuntimeError("App Service의 인증 필수 설정이 반영되지 않았습니다.")
    return {"client_id": app_id, "identity_id": identity_id, "secret_created": False,
            "allowed_user_count": len(allowed_oids), "authentication_required": True}
