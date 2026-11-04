targetScope = 'subscription'

param location string
param resourceGroupName string
param labId string
@allowed(['foundry', 'langchain'])
param workload string
param accountName string = ''
param projectName string = ''
param deploymentName string = ''
param modelName string = ''
param modelVersion string = ''
param modelSku string = 'GlobalStandard'
param modelCapacity int = 1
param hostName string = ''
param modelResourceId string = ''
param retentionDays int = 90
param extraModels array = []

var commonTags = {
    'wasmagent-lab': labId
    owner: 'governance-sample-team'
    sponsor: 'governance-sample'
    env: 'test'
    'cost-center': 'governance-lab'
}

resource group 'Microsoft.Resources/resourceGroups@2024-03-01' = {
  name: resourceGroupName
  location: location
  tags: commonTags
}

module foundry 'foundry.bicep' = if (workload == 'foundry') {
  name: 'wasmagent-foundry'
  scope: group
  params: {
    location: location
    tags: commonTags
    accountName: accountName
    projectName: projectName
    deploymentName: deploymentName
    modelName: modelName
    modelVersion: modelVersion
    modelSku: modelSku
    modelCapacity: modelCapacity
    retentionDays: retentionDays
    extraModels: extraModels
  }
}

module host 'host.bicep' = if (workload == 'langchain') {
  name: 'wasmagent-host'
  scope: group
  params: {
    location: location
    tags: commonTags
    hostName: hostName
    modelResourceId: modelResourceId
    deploymentName: deploymentName
  }
}

module monitor 'monitor.bicep' = {
  name: 'wasmagent-monitor'
  scope: group
  dependsOn: [
    foundry
    host
  ]
  params: {
    tags: commonTags
    workload: workload
    targetResourceId: resourceId(
      subscription().subscriptionId,
      resourceGroupName,
      workload == 'foundry' ? 'Microsoft.CognitiveServices/accounts' : 'Microsoft.Web/sites',
      workload == 'foundry' ? accountName : hostName
    )
  }
}

module policy 'policy.bicep' = if (workload == 'foundry') {
  name: 'wasmagent-policy'
  scope: group
  dependsOn: [
    foundry
  ]
}
