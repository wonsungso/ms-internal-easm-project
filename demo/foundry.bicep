param location string
param tags object
param accountName string
param projectName string
param deploymentName string
param modelName string
param modelVersion string
param modelSku string
param modelCapacity int
param retentionDays int
param extraModels array = []
param raiPolicyName string = 'wasmagent-demo-content-filter'

resource account 'Microsoft.CognitiveServices/accounts@2025-06-01' = {
  name: accountName
  location: location
  kind: 'AIServices'
  sku: {
    name: 'S0'
  }
  identity: {
    type: 'SystemAssigned'
  }
  tags: tags
  properties: {
    customSubDomainName: accountName
    allowProjectManagement: true
    disableLocalAuth: true
    publicNetworkAccess: 'Enabled'
  }
}

resource project 'Microsoft.CognitiveServices/accounts/projects@2025-06-01' = {
  parent: account
  name: projectName
  location: location
  identity: {
    type: 'SystemAssigned'
  }
  tags: tags
  properties: {
    displayName: 'Governance sample'
    description: 'Synthetic governance validation'
  }
}

// 주 모델 배포에만 연결하는 사용자 지정 콘텐츠 필터. 추가 모델 배포는 기본 정책을 유지해 적용 범위가 달라진다.
resource raiPolicy 'Microsoft.CognitiveServices/accounts/raiPolicies@2024-10-01' = {
  parent: account
  name: raiPolicyName
  dependsOn: [
    project
  ]
  tags: tags
  properties: {
    basePolicyName: 'Microsoft.DefaultV2'
    mode: 'Default'
    contentFilters: [
      {
        name: 'Hate'
        enabled: true
        blocking: true
        severityThreshold: 'High'
        source: 'Prompt'
      }
      {
        name: 'Hate'
        enabled: true
        blocking: true
        severityThreshold: 'High'
        source: 'Completion'
      }
    ]
  }
}

// 정책이 먼저 만들어져야 배포가 raiPolicyName을 참조할 수 있다.
resource model 'Microsoft.CognitiveServices/accounts/deployments@2024-10-01' = {
  parent: account
  name: deploymentName
  dependsOn: [
    project
    raiPolicy
  ]
  sku: {
    name: modelSku
    capacity: modelCapacity
  }
  properties: {
    model: {
      format: 'OpenAI'
      name: modelName
      version: modelVersion
    }
    raiPolicyName: raiPolicyName
  }
}

// 허용 목록 밖 모델을 한 개 더 배포해 모델 허용 비율이 1이 아닌 결과를 만든다. 같은 계정의 배포는 순차 생성한다.
@batchSize(1)
resource extra 'Microsoft.CognitiveServices/accounts/deployments@2024-10-01' = [for item in extraModels: {
  parent: account
  name: item.deploymentName
  dependsOn: [
    model
  ]
  sku: {
    name: item.sku
    capacity: item.capacity
  }
  properties: {
    model: {
      format: 'OpenAI'
      name: item.model
      version: item.version
    }
  }
}]

resource workspace 'Microsoft.OperationalInsights/workspaces@2022-10-01' = {
  name: 'wasmagent-observability'
  location: location
  tags: union(tags, {
    'agent-type': 'shared-observability'
  })
  properties: {
    sku: {
      name: 'PerGB2018'
    }
    retentionInDays: retentionDays
    workspaceCapping: {
      dailyQuotaGb: 1
    }
  }
}
