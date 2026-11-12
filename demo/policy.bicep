// Audit 효과만 사용하고 DoNotEnforce로 두어 아무 것도 차단하지 않는다. 대상 계정은 publicNetworkAccess가 Enabled이므로 비준수로 평가된다.
// 이 내장 정의는 Microsoft가 Deprecated로 표시했지만 할당과 준수 평가는 가능하다.
var builtInDefinitionId = '/providers/Microsoft.Authorization/policyDefinitions/0725b4dd-7e76-479c-a735-68e7ee23d5ca'

resource assignment 'Microsoft.Authorization/policyAssignments@2024-05-01' = {
  name: 'easmagent-demo-cs-public-access'
  properties: {
    displayName: '[DEMO] easmagent - Cognitive Services public network access (audit only)'
    description: 'Demo assignment for governance validation. Audit effect, DoNotEnforce: nothing is blocked.'
    policyDefinitionId: builtInDefinitionId
    enforcementMode: 'DoNotEnforce'
    parameters: {
      effect: {
        value: 'Audit'
      }
    }
  }
}
