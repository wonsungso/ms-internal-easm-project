param tags object
@allowed(['foundry', 'langchain'])
param workload string
param targetResourceId string

var isFoundry = workload == 'foundry'

// 메일/SMS 수신자 없이 존재하지 않는 도메인의 웹훅만 둔다. 실제 사람에게 통지가 가지 않는다.
resource actionGroup 'Microsoft.Insights/actionGroups@2023-01-01' = {
  name: 'wasmagent-demo-ag'
  location: 'global'
  tags: tags
  properties: {
    groupShortName: 'wasmdemo'
    enabled: true
    armRoleReceivers: [
      {
        name: 'demo-monitoring-reader'
        roleId: '43d0d8ad-25c7-4714-9337-8ba259a9fe05'
        useCommonAlertSchema: true
      }
    ]
  }
}

resource alert 'Microsoft.Insights/metricAlerts@2018-03-01' = {
  name: isFoundry ? 'wasmagent-demo-openai-availability' : 'wasmagent-demo-web-5xx'
  location: 'global'
  tags: tags
  properties: {
    description: 'Synthetic governance validation alert. No real notification target.'
    severity: 3
    enabled: true
    scopes: [
      targetResourceId
    ]
    evaluationFrequency: 'PT5M'
    windowSize: 'PT15M'
    autoMitigate: true
    criteria: {
      'odata.type': 'Microsoft.Azure.Monitor.SingleResourceMultipleMetricCriteria'
      allOf: [
        isFoundry ? {
          criterionType: 'StaticThresholdCriterion'
          name: 'availability'
          metricNamespace: 'Microsoft.CognitiveServices/accounts'
          metricName: 'AzureOpenAIAvailabilityRate'
          operator: 'LessThan'
          threshold: 99
          timeAggregation: 'Average'
        } : {
          criterionType: 'StaticThresholdCriterion'
          name: 'http5xx'
          metricNamespace: 'Microsoft.Web/sites'
          metricName: 'Http5xx'
          operator: 'GreaterThan'
          threshold: 5
          timeAggregation: 'Total'
        }
      ]
    }
    actions: [
      {
        actionGroupId: actionGroup.id
      }
    ]
  }
}
