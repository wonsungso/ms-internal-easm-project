param location string
param tags object
param hostName string
param modelResourceId string
param deploymentName string

var hostTags = union(tags, {
  'agent-type': 'langchain'
  'agent-id': hostName
  'model-resource-id': modelResourceId
  'model-deployment': deploymentName
})

resource plan 'Microsoft.Web/serverfarms@2024-04-01' = {
  name: '${hostName}-plan'
  location: location
  kind: 'linux'
  tags: hostTags
  sku: {
    name: 'B1'
    tier: 'Basic'
    capacity: 1
  }
  properties: {
    reserved: true
  }
}

resource site 'Microsoft.Web/sites@2024-04-01' = {
  name: hostName
  location: location
  kind: 'app,linux'
  tags: hostTags
  identity: {
    type: 'SystemAssigned'
  }
  properties: {
    serverFarmId: plan.id
    httpsOnly: true
    siteConfig: {
      linuxFxVersion: 'PYTHON|3.11'
      appCommandLine: 'gunicorn --bind=0.0.0.0 --timeout 120 --workers 1 app:app'
      alwaysOn: true
      ftpsState: 'Disabled'
      minTlsVersion: '1.2'
    }
  }
}
