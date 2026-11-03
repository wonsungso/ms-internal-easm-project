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

var commonTags = {
    'seagent-lab': labId
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
  name: 'seagent-foundry'
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
  }
}

module host 'host.bicep' = if (workload == 'langchain') {
  name: 'seagent-host'
  scope: group
  params: {
    location: location
    tags: commonTags
    hostName: hostName
    modelResourceId: modelResourceId
    deploymentName: deploymentName
  }
}
