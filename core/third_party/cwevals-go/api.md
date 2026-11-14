# Service

Response Types:

- <a href="https://pkg.go.dev/github.com/wandb/cwevals-go">cwevals</a>.<a href="https://pkg.go.dev/github.com/wandb/cwevals-go#ServiceGetResponse">ServiceGetResponse</a>

Methods:

- <code title="get /">client.Service.<a href="https://pkg.go.dev/github.com/wandb/cwevals-go#ServiceService.Get">Get</a>(ctx <a href="https://pkg.go.dev/context">context</a>.<a href="https://pkg.go.dev/context#Context">Context</a>) (\*<a href="https://pkg.go.dev/github.com/wandb/cwevals-go">cwevals</a>.<a href="https://pkg.go.dev/github.com/wandb/cwevals-go#ServiceGetResponse">ServiceGetResponse</a>, <a href="https://pkg.go.dev/builtin#error">error</a>)</code>

# Verification

Response Types:

- <a href="https://pkg.go.dev/github.com/wandb/cwevals-go">cwevals</a>.<a href="https://pkg.go.dev/github.com/wandb/cwevals-go#VerificationGetResponse">VerificationGetResponse</a>

Methods:

- <code title="get /test">client.Verification.<a href="https://pkg.go.dev/github.com/wandb/cwevals-go#VerificationService.Get">Get</a>(ctx <a href="https://pkg.go.dev/context">context</a>.<a href="https://pkg.go.dev/context#Context">Context</a>) (\*<a href="https://pkg.go.dev/github.com/wandb/cwevals-go">cwevals</a>.<a href="https://pkg.go.dev/github.com/wandb/cwevals-go#VerificationGetResponse">VerificationGetResponse</a>, <a href="https://pkg.go.dev/builtin#error">error</a>)</code>

# Datasets

Params Types:

- <a href="https://pkg.go.dev/github.com/wandb/cwevals-go">cwevals</a>.<a href="https://pkg.go.dev/github.com/wandb/cwevals-go#CaseFieldValueUnionParam">CaseFieldValueUnionParam</a>
- <a href="https://pkg.go.dev/github.com/wandb/cwevals-go">cwevals</a>.<a href="https://pkg.go.dev/github.com/wandb/cwevals-go#CaseValueUnionParam">CaseValueUnionParam</a>
- <a href="https://pkg.go.dev/github.com/wandb/cwevals-go">cwevals</a>.<a href="https://pkg.go.dev/github.com/wandb/cwevals-go#WandbAudioV1Param">WandbAudioV1Param</a>
- <a href="https://pkg.go.dev/github.com/wandb/cwevals-go">cwevals</a>.<a href="https://pkg.go.dev/github.com/wandb/cwevals-go#WandbBokehV1Param">WandbBokehV1Param</a>
- <a href="https://pkg.go.dev/github.com/wandb/cwevals-go">cwevals</a>.<a href="https://pkg.go.dev/github.com/wandb/cwevals-go#WandbHTMLV1Param">WandbHTMLV1Param</a>
- <a href="https://pkg.go.dev/github.com/wandb/cwevals-go">cwevals</a>.<a href="https://pkg.go.dev/github.com/wandb/cwevals-go#WandbImageBoxesV1Param">WandbImageBoxesV1Param</a>
- <a href="https://pkg.go.dev/github.com/wandb/cwevals-go">cwevals</a>.<a href="https://pkg.go.dev/github.com/wandb/cwevals-go#WandbImageMaskV1Param">WandbImageMaskV1Param</a>
- <a href="https://pkg.go.dev/github.com/wandb/cwevals-go">cwevals</a>.<a href="https://pkg.go.dev/github.com/wandb/cwevals-go#WandbImageV1Param">WandbImageV1Param</a>
- <a href="https://pkg.go.dev/github.com/wandb/cwevals-go">cwevals</a>.<a href="https://pkg.go.dev/github.com/wandb/cwevals-go#WandbMoleculeV1Param">WandbMoleculeV1Param</a>
- <a href="https://pkg.go.dev/github.com/wandb/cwevals-go">cwevals</a>.<a href="https://pkg.go.dev/github.com/wandb/cwevals-go#WandbObject3dV1Param">WandbObject3dV1Param</a>
- <a href="https://pkg.go.dev/github.com/wandb/cwevals-go">cwevals</a>.<a href="https://pkg.go.dev/github.com/wandb/cwevals-go#WandbVideoV1Param">WandbVideoV1Param</a>

Response Types:

- <a href="https://pkg.go.dev/github.com/wandb/cwevals-go">cwevals</a>.<a href="https://pkg.go.dev/github.com/wandb/cwevals-go#DatasetNewResponse">DatasetNewResponse</a>
- <a href="https://pkg.go.dev/github.com/wandb/cwevals-go">cwevals</a>.<a href="https://pkg.go.dev/github.com/wandb/cwevals-go#DatasetUpdateResponse">DatasetUpdateResponse</a>
- <a href="https://pkg.go.dev/github.com/wandb/cwevals-go">cwevals</a>.<a href="https://pkg.go.dev/github.com/wandb/cwevals-go#DatasetListResponse">DatasetListResponse</a>
- <a href="https://pkg.go.dev/github.com/wandb/cwevals-go">cwevals</a>.<a href="https://pkg.go.dev/github.com/wandb/cwevals-go#DatasetGetResponse">DatasetGetResponse</a>

Methods:

- <code title="post /v1/namespaces/{namespace}/scopes/{scope_id}/datasets">client.Datasets.<a href="https://pkg.go.dev/github.com/wandb/cwevals-go#DatasetService.New">New</a>(ctx <a href="https://pkg.go.dev/context">context</a>.<a href="https://pkg.go.dev/context#Context">Context</a>, params <a href="https://pkg.go.dev/github.com/wandb/cwevals-go">cwevals</a>.<a href="https://pkg.go.dev/github.com/wandb/cwevals-go#DatasetNewParams">DatasetNewParams</a>) (\*<a href="https://pkg.go.dev/github.com/wandb/cwevals-go">cwevals</a>.<a href="https://pkg.go.dev/github.com/wandb/cwevals-go#DatasetNewResponse">DatasetNewResponse</a>, <a href="https://pkg.go.dev/builtin#error">error</a>)</code>
- <code title="patch /v1/namespaces/{namespace}/scopes/{scope_id}/datasets/{dataset_id}">client.Datasets.<a href="https://pkg.go.dev/github.com/wandb/cwevals-go#DatasetService.Update">Update</a>(ctx <a href="https://pkg.go.dev/context">context</a>.<a href="https://pkg.go.dev/context#Context">Context</a>, datasetID <a href="https://pkg.go.dev/builtin#string">string</a>, params <a href="https://pkg.go.dev/github.com/wandb/cwevals-go">cwevals</a>.<a href="https://pkg.go.dev/github.com/wandb/cwevals-go#DatasetUpdateParams">DatasetUpdateParams</a>) (\*<a href="https://pkg.go.dev/github.com/wandb/cwevals-go">cwevals</a>.<a href="https://pkg.go.dev/github.com/wandb/cwevals-go#DatasetUpdateResponse">DatasetUpdateResponse</a>, <a href="https://pkg.go.dev/builtin#error">error</a>)</code>
- <code title="get /v1/namespaces/{namespace}/scopes/{scope_id}/datasets">client.Datasets.<a href="https://pkg.go.dev/github.com/wandb/cwevals-go#DatasetService.List">List</a>(ctx <a href="https://pkg.go.dev/context">context</a>.<a href="https://pkg.go.dev/context#Context">Context</a>, params <a href="https://pkg.go.dev/github.com/wandb/cwevals-go">cwevals</a>.<a href="https://pkg.go.dev/github.com/wandb/cwevals-go#DatasetListParams">DatasetListParams</a>) (\*<a href="https://pkg.go.dev/github.com/wandb/cwevals-go">cwevals</a>.<a href="https://pkg.go.dev/github.com/wandb/cwevals-go#DatasetListResponse">DatasetListResponse</a>, <a href="https://pkg.go.dev/builtin#error">error</a>)</code>
- <code title="delete /v1/namespaces/{namespace}/scopes/{scope_id}/datasets/{dataset_id}">client.Datasets.<a href="https://pkg.go.dev/github.com/wandb/cwevals-go#DatasetService.Delete">Delete</a>(ctx <a href="https://pkg.go.dev/context">context</a>.<a href="https://pkg.go.dev/context#Context">Context</a>, datasetID <a href="https://pkg.go.dev/builtin#string">string</a>, body <a href="https://pkg.go.dev/github.com/wandb/cwevals-go">cwevals</a>.<a href="https://pkg.go.dev/github.com/wandb/cwevals-go#DatasetDeleteParams">DatasetDeleteParams</a>) <a href="https://pkg.go.dev/builtin#error">error</a></code>
- <code title="get /v1/namespaces/{namespace}/scopes/{scope_id}/datasets/{dataset_id}">client.Datasets.<a href="https://pkg.go.dev/github.com/wandb/cwevals-go#DatasetService.Get">Get</a>(ctx <a href="https://pkg.go.dev/context">context</a>.<a href="https://pkg.go.dev/context#Context">Context</a>, datasetID <a href="https://pkg.go.dev/builtin#string">string</a>, query <a href="https://pkg.go.dev/github.com/wandb/cwevals-go">cwevals</a>.<a href="https://pkg.go.dev/github.com/wandb/cwevals-go#DatasetGetParams">DatasetGetParams</a>) (\*<a href="https://pkg.go.dev/github.com/wandb/cwevals-go">cwevals</a>.<a href="https://pkg.go.dev/github.com/wandb/cwevals-go#DatasetGetResponse">DatasetGetResponse</a>, <a href="https://pkg.go.dev/builtin#error">error</a>)</code>

## Cases

Response Types:

- <a href="https://pkg.go.dev/github.com/wandb/cwevals-go">cwevals</a>.<a href="https://pkg.go.dev/github.com/wandb/cwevals-go#DatasetCaseAddResponse">DatasetCaseAddResponse</a>

Methods:

- <code title="patch /v1/namespaces/{namespace}/scopes/{scope_id}/datasets/{dataset_id}/cases">client.Datasets.Cases.<a href="https://pkg.go.dev/github.com/wandb/cwevals-go#DatasetCaseService.Add">Add</a>(ctx <a href="https://pkg.go.dev/context">context</a>.<a href="https://pkg.go.dev/context#Context">Context</a>, datasetID <a href="https://pkg.go.dev/builtin#string">string</a>, params <a href="https://pkg.go.dev/github.com/wandb/cwevals-go">cwevals</a>.<a href="https://pkg.go.dev/github.com/wandb/cwevals-go#DatasetCaseAddParams">DatasetCaseAddParams</a>) (\*<a href="https://pkg.go.dev/github.com/wandb/cwevals-go">cwevals</a>.<a href="https://pkg.go.dev/github.com/wandb/cwevals-go#DatasetCaseAddResponse">DatasetCaseAddResponse</a>, <a href="https://pkg.go.dev/builtin#error">error</a>)</code>

## Fields

Response Types:

- <a href="https://pkg.go.dev/github.com/wandb/cwevals-go">cwevals</a>.<a href="https://pkg.go.dev/github.com/wandb/cwevals-go#DatasetFieldNewResponse">DatasetFieldNewResponse</a>

Methods:

- <code title="post /v1/namespaces/{namespace}/scopes/{scope_id}/datasets/{dataset_id}/fields">client.Datasets.Fields.<a href="https://pkg.go.dev/github.com/wandb/cwevals-go#DatasetFieldService.New">New</a>(ctx <a href="https://pkg.go.dev/context">context</a>.<a href="https://pkg.go.dev/context#Context">Context</a>, datasetID <a href="https://pkg.go.dev/builtin#string">string</a>, params <a href="https://pkg.go.dev/github.com/wandb/cwevals-go">cwevals</a>.<a href="https://pkg.go.dev/github.com/wandb/cwevals-go#DatasetFieldNewParams">DatasetFieldNewParams</a>) (\*<a href="https://pkg.go.dev/github.com/wandb/cwevals-go">cwevals</a>.<a href="https://pkg.go.dev/github.com/wandb/cwevals-go#DatasetFieldNewResponse">DatasetFieldNewResponse</a>, <a href="https://pkg.go.dev/builtin#error">error</a>)</code>

## Versions

Response Types:

- <a href="https://pkg.go.dev/github.com/wandb/cwevals-go">cwevals</a>.<a href="https://pkg.go.dev/github.com/wandb/cwevals-go#DatasetVersionNewResponse">DatasetVersionNewResponse</a>
- <a href="https://pkg.go.dev/github.com/wandb/cwevals-go">cwevals</a>.<a href="https://pkg.go.dev/github.com/wandb/cwevals-go#DatasetVersionListResponse">DatasetVersionListResponse</a>
- <a href="https://pkg.go.dev/github.com/wandb/cwevals-go">cwevals</a>.<a href="https://pkg.go.dev/github.com/wandb/cwevals-go#DatasetVersionGetResponse">DatasetVersionGetResponse</a>

Methods:

- <code title="post /v1/namespaces/{namespace}/scopes/{scope_id}/datasets/{dataset_id}/versions">client.Datasets.Versions.<a href="https://pkg.go.dev/github.com/wandb/cwevals-go#DatasetVersionService.New">New</a>(ctx <a href="https://pkg.go.dev/context">context</a>.<a href="https://pkg.go.dev/context#Context">Context</a>, datasetID <a href="https://pkg.go.dev/builtin#string">string</a>, params <a href="https://pkg.go.dev/github.com/wandb/cwevals-go">cwevals</a>.<a href="https://pkg.go.dev/github.com/wandb/cwevals-go#DatasetVersionNewParams">DatasetVersionNewParams</a>) (\*<a href="https://pkg.go.dev/github.com/wandb/cwevals-go">cwevals</a>.<a href="https://pkg.go.dev/github.com/wandb/cwevals-go#DatasetVersionNewResponse">DatasetVersionNewResponse</a>, <a href="https://pkg.go.dev/builtin#error">error</a>)</code>
- <code title="get /v1/namespaces/{namespace}/scopes/{scope_id}/datasets/{dataset_id}/versions">client.Datasets.Versions.<a href="https://pkg.go.dev/github.com/wandb/cwevals-go#DatasetVersionService.List">List</a>(ctx <a href="https://pkg.go.dev/context">context</a>.<a href="https://pkg.go.dev/context#Context">Context</a>, datasetID <a href="https://pkg.go.dev/builtin#string">string</a>, params <a href="https://pkg.go.dev/github.com/wandb/cwevals-go">cwevals</a>.<a href="https://pkg.go.dev/github.com/wandb/cwevals-go#DatasetVersionListParams">DatasetVersionListParams</a>) (\*<a href="https://pkg.go.dev/github.com/wandb/cwevals-go">cwevals</a>.<a href="https://pkg.go.dev/github.com/wandb/cwevals-go#DatasetVersionListResponse">DatasetVersionListResponse</a>, <a href="https://pkg.go.dev/builtin#error">error</a>)</code>
- <code title="get /v1/namespaces/{namespace}/scopes/{scope_id}/dataset-versions/{dataset_version_id}">client.Datasets.Versions.<a href="https://pkg.go.dev/github.com/wandb/cwevals-go#DatasetVersionService.Get">Get</a>(ctx <a href="https://pkg.go.dev/context">context</a>.<a href="https://pkg.go.dev/context#Context">Context</a>, datasetVersionID <a href="https://pkg.go.dev/builtin#string">string</a>, query <a href="https://pkg.go.dev/github.com/wandb/cwevals-go">cwevals</a>.<a href="https://pkg.go.dev/github.com/wandb/cwevals-go#DatasetVersionGetParams">DatasetVersionGetParams</a>) (\*<a href="https://pkg.go.dev/github.com/wandb/cwevals-go">cwevals</a>.<a href="https://pkg.go.dev/github.com/wandb/cwevals-go#DatasetVersionGetResponse">DatasetVersionGetResponse</a>, <a href="https://pkg.go.dev/builtin#error">error</a>)</code>

### Cases

Response Types:

- <a href="https://pkg.go.dev/github.com/wandb/cwevals-go">cwevals</a>.<a href="https://pkg.go.dev/github.com/wandb/cwevals-go#DatasetVersionCaseListResponse">DatasetVersionCaseListResponse</a>

Methods:

- <code title="get /v1/namespaces/{namespace}/scopes/{scope_id}/dataset-versions/{dataset_version_id}/cases">client.Datasets.Versions.Cases.<a href="https://pkg.go.dev/github.com/wandb/cwevals-go#DatasetVersionCaseService.List">List</a>(ctx <a href="https://pkg.go.dev/context">context</a>.<a href="https://pkg.go.dev/context#Context">Context</a>, datasetVersionID <a href="https://pkg.go.dev/builtin#string">string</a>, params <a href="https://pkg.go.dev/github.com/wandb/cwevals-go">cwevals</a>.<a href="https://pkg.go.dev/github.com/wandb/cwevals-go#DatasetVersionCaseListParams">DatasetVersionCaseListParams</a>) (\*<a href="https://pkg.go.dev/github.com/wandb/cwevals-go">cwevals</a>.<a href="https://pkg.go.dev/github.com/wandb/cwevals-go#DatasetVersionCaseListResponse">DatasetVersionCaseListResponse</a>, <a href="https://pkg.go.dev/builtin#error">error</a>)</code>

### Fields

Response Types:

- <a href="https://pkg.go.dev/github.com/wandb/cwevals-go">cwevals</a>.<a href="https://pkg.go.dev/github.com/wandb/cwevals-go#DatasetVersionFieldListResponse">DatasetVersionFieldListResponse</a>

Methods:

- <code title="get /v1/namespaces/{namespace}/scopes/{scope_id}/dataset-versions/{dataset_version_id}/fields">client.Datasets.Versions.Fields.<a href="https://pkg.go.dev/github.com/wandb/cwevals-go#DatasetVersionFieldService.List">List</a>(ctx <a href="https://pkg.go.dev/context">context</a>.<a href="https://pkg.go.dev/context#Context">Context</a>, datasetVersionID <a href="https://pkg.go.dev/builtin#string">string</a>, query <a href="https://pkg.go.dev/github.com/wandb/cwevals-go">cwevals</a>.<a href="https://pkg.go.dev/github.com/wandb/cwevals-go#DatasetVersionFieldListParams">DatasetVersionFieldListParams</a>) (\*<a href="https://pkg.go.dev/github.com/wandb/cwevals-go">cwevals</a>.<a href="https://pkg.go.dev/github.com/wandb/cwevals-go#DatasetVersionFieldListResponse">DatasetVersionFieldListResponse</a>, <a href="https://pkg.go.dev/builtin#error">error</a>)</code>

## Trajectories

Response Types:

- <a href="https://pkg.go.dev/github.com/wandb/cwevals-go">cwevals</a>.<a href="https://pkg.go.dev/github.com/wandb/cwevals-go#DatasetTrajectoryNewResponse">DatasetTrajectoryNewResponse</a>
- <a href="https://pkg.go.dev/github.com/wandb/cwevals-go">cwevals</a>.<a href="https://pkg.go.dev/github.com/wandb/cwevals-go#DatasetTrajectoryListResponse">DatasetTrajectoryListResponse</a>
- <a href="https://pkg.go.dev/github.com/wandb/cwevals-go">cwevals</a>.<a href="https://pkg.go.dev/github.com/wandb/cwevals-go#DatasetTrajectoryGetResponse">DatasetTrajectoryGetResponse</a>

Methods:

- <code title="post /v1/namespaces/{namespace}/scopes/{scope_id}/datasets/{dataset_id}/trajectories">client.Datasets.Trajectories.<a href="https://pkg.go.dev/github.com/wandb/cwevals-go#DatasetTrajectoryService.New">New</a>(ctx <a href="https://pkg.go.dev/context">context</a>.<a href="https://pkg.go.dev/context#Context">Context</a>, datasetID <a href="https://pkg.go.dev/builtin#string">string</a>, params <a href="https://pkg.go.dev/github.com/wandb/cwevals-go">cwevals</a>.<a href="https://pkg.go.dev/github.com/wandb/cwevals-go#DatasetTrajectoryNewParams">DatasetTrajectoryNewParams</a>) (\*<a href="https://pkg.go.dev/github.com/wandb/cwevals-go">cwevals</a>.<a href="https://pkg.go.dev/github.com/wandb/cwevals-go#DatasetTrajectoryNewResponse">DatasetTrajectoryNewResponse</a>, <a href="https://pkg.go.dev/builtin#error">error</a>)</code>
- <code title="get /v1/namespaces/{namespace}/scopes/{scope_id}/datasets/{dataset_id}/trajectories">client.Datasets.Trajectories.<a href="https://pkg.go.dev/github.com/wandb/cwevals-go#DatasetTrajectoryService.List">List</a>(ctx <a href="https://pkg.go.dev/context">context</a>.<a href="https://pkg.go.dev/context#Context">Context</a>, datasetID <a href="https://pkg.go.dev/builtin#string">string</a>, params <a href="https://pkg.go.dev/github.com/wandb/cwevals-go">cwevals</a>.<a href="https://pkg.go.dev/github.com/wandb/cwevals-go#DatasetTrajectoryListParams">DatasetTrajectoryListParams</a>) (\*<a href="https://pkg.go.dev/github.com/wandb/cwevals-go">cwevals</a>.<a href="https://pkg.go.dev/github.com/wandb/cwevals-go#DatasetTrajectoryListResponse">DatasetTrajectoryListResponse</a>, <a href="https://pkg.go.dev/builtin#error">error</a>)</code>
- <code title="get /v1/namespaces/{namespace}/scopes/{scope_id}/trajectories/{trajectory_id}">client.Datasets.Trajectories.<a href="https://pkg.go.dev/github.com/wandb/cwevals-go#DatasetTrajectoryService.Get">Get</a>(ctx <a href="https://pkg.go.dev/context">context</a>.<a href="https://pkg.go.dev/context#Context">Context</a>, trajectoryID <a href="https://pkg.go.dev/builtin#string">string</a>, query <a href="https://pkg.go.dev/github.com/wandb/cwevals-go">cwevals</a>.<a href="https://pkg.go.dev/github.com/wandb/cwevals-go#DatasetTrajectoryGetParams">DatasetTrajectoryGetParams</a>) (\*<a href="https://pkg.go.dev/github.com/wandb/cwevals-go">cwevals</a>.<a href="https://pkg.go.dev/github.com/wandb/cwevals-go#DatasetTrajectoryGetResponse">DatasetTrajectoryGetResponse</a>, <a href="https://pkg.go.dev/builtin#error">error</a>)</code>

### Cases

Response Types:

- <a href="https://pkg.go.dev/github.com/wandb/cwevals-go">cwevals</a>.<a href="https://pkg.go.dev/github.com/wandb/cwevals-go#DatasetTrajectoryCaseListResponse">DatasetTrajectoryCaseListResponse</a>

Methods:

- <code title="get /v1/namespaces/{namespace}/scopes/{scope_id}/trajectories/{trajectory_id}/cases">client.Datasets.Trajectories.Cases.<a href="https://pkg.go.dev/github.com/wandb/cwevals-go#DatasetTrajectoryCaseService.List">List</a>(ctx <a href="https://pkg.go.dev/context">context</a>.<a href="https://pkg.go.dev/context#Context">Context</a>, trajectoryID <a href="https://pkg.go.dev/builtin#string">string</a>, params <a href="https://pkg.go.dev/github.com/wandb/cwevals-go">cwevals</a>.<a href="https://pkg.go.dev/github.com/wandb/cwevals-go#DatasetTrajectoryCaseListParams">DatasetTrajectoryCaseListParams</a>) (\*<a href="https://pkg.go.dev/github.com/wandb/cwevals-go">cwevals</a>.<a href="https://pkg.go.dev/github.com/wandb/cwevals-go#DatasetTrajectoryCaseListResponse">DatasetTrajectoryCaseListResponse</a>, <a href="https://pkg.go.dev/builtin#error">error</a>)</code>

# Cases

Response Types:

- <a href="https://pkg.go.dev/github.com/wandb/cwevals-go">cwevals</a>.<a href="https://pkg.go.dev/github.com/wandb/cwevals-go#CaseGetResponse">CaseGetResponse</a>

Methods:

- <code title="get /v1/namespaces/{namespace}/scopes/{scope_id}/cases/{case_id}">client.Cases.<a href="https://pkg.go.dev/github.com/wandb/cwevals-go#CaseService.Get">Get</a>(ctx <a href="https://pkg.go.dev/context">context</a>.<a href="https://pkg.go.dev/context#Context">Context</a>, caseID <a href="https://pkg.go.dev/builtin#string">string</a>, query <a href="https://pkg.go.dev/github.com/wandb/cwevals-go">cwevals</a>.<a href="https://pkg.go.dev/github.com/wandb/cwevals-go#CaseGetParams">CaseGetParams</a>) (\*<a href="https://pkg.go.dev/github.com/wandb/cwevals-go">cwevals</a>.<a href="https://pkg.go.dev/github.com/wandb/cwevals-go#CaseGetResponse">CaseGetResponse</a>, <a href="https://pkg.go.dev/builtin#error">error</a>)</code>

# Comparisons

Response Types:

- <a href="https://pkg.go.dev/github.com/wandb/cwevals-go">cwevals</a>.<a href="https://pkg.go.dev/github.com/wandb/cwevals-go#ComparisonNewResponse">ComparisonNewResponse</a>
- <a href="https://pkg.go.dev/github.com/wandb/cwevals-go">cwevals</a>.<a href="https://pkg.go.dev/github.com/wandb/cwevals-go#ComparisonGetResponse">ComparisonGetResponse</a>

Methods:

- <code title="post /v1/namespaces/{namespace}/scopes/{scope_id}/comparisons">client.Comparisons.<a href="https://pkg.go.dev/github.com/wandb/cwevals-go#ComparisonService.New">New</a>(ctx <a href="https://pkg.go.dev/context">context</a>.<a href="https://pkg.go.dev/context#Context">Context</a>, params <a href="https://pkg.go.dev/github.com/wandb/cwevals-go">cwevals</a>.<a href="https://pkg.go.dev/github.com/wandb/cwevals-go#ComparisonNewParams">ComparisonNewParams</a>) (\*<a href="https://pkg.go.dev/github.com/wandb/cwevals-go">cwevals</a>.<a href="https://pkg.go.dev/github.com/wandb/cwevals-go#ComparisonNewResponse">ComparisonNewResponse</a>, <a href="https://pkg.go.dev/builtin#error">error</a>)</code>
- <code title="get /v1/namespaces/{namespace}/scopes/{scope_id}/comparisons/{comparison_id}">client.Comparisons.<a href="https://pkg.go.dev/github.com/wandb/cwevals-go#ComparisonService.Get">Get</a>(ctx <a href="https://pkg.go.dev/context">context</a>.<a href="https://pkg.go.dev/context#Context">Context</a>, comparisonID <a href="https://pkg.go.dev/builtin#string">string</a>, query <a href="https://pkg.go.dev/github.com/wandb/cwevals-go">cwevals</a>.<a href="https://pkg.go.dev/github.com/wandb/cwevals-go#ComparisonGetParams">ComparisonGetParams</a>) (\*<a href="https://pkg.go.dev/github.com/wandb/cwevals-go">cwevals</a>.<a href="https://pkg.go.dev/github.com/wandb/cwevals-go#ComparisonGetResponse">ComparisonGetResponse</a>, <a href="https://pkg.go.dev/builtin#error">error</a>)</code>

# Scorers

Response Types:

- <a href="https://pkg.go.dev/github.com/wandb/cwevals-go">cwevals</a>.<a href="https://pkg.go.dev/github.com/wandb/cwevals-go#ScorerNewResponse">ScorerNewResponse</a>
- <a href="https://pkg.go.dev/github.com/wandb/cwevals-go">cwevals</a>.<a href="https://pkg.go.dev/github.com/wandb/cwevals-go#ScorerListResponse">ScorerListResponse</a>
- <a href="https://pkg.go.dev/github.com/wandb/cwevals-go">cwevals</a>.<a href="https://pkg.go.dev/github.com/wandb/cwevals-go#ScorerGetResponse">ScorerGetResponse</a>

Methods:

- <code title="post /v1/namespaces/{namespace}/scopes/{scope_id}/scorers">client.Scorers.<a href="https://pkg.go.dev/github.com/wandb/cwevals-go#ScorerService.New">New</a>(ctx <a href="https://pkg.go.dev/context">context</a>.<a href="https://pkg.go.dev/context#Context">Context</a>, params <a href="https://pkg.go.dev/github.com/wandb/cwevals-go">cwevals</a>.<a href="https://pkg.go.dev/github.com/wandb/cwevals-go#ScorerNewParams">ScorerNewParams</a>) (\*<a href="https://pkg.go.dev/github.com/wandb/cwevals-go">cwevals</a>.<a href="https://pkg.go.dev/github.com/wandb/cwevals-go#ScorerNewResponse">ScorerNewResponse</a>, <a href="https://pkg.go.dev/builtin#error">error</a>)</code>
- <code title="get /v1/namespaces/{namespace}/scopes/{scope_id}/scorers">client.Scorers.<a href="https://pkg.go.dev/github.com/wandb/cwevals-go#ScorerService.List">List</a>(ctx <a href="https://pkg.go.dev/context">context</a>.<a href="https://pkg.go.dev/context#Context">Context</a>, params <a href="https://pkg.go.dev/github.com/wandb/cwevals-go">cwevals</a>.<a href="https://pkg.go.dev/github.com/wandb/cwevals-go#ScorerListParams">ScorerListParams</a>) (\*<a href="https://pkg.go.dev/github.com/wandb/cwevals-go">cwevals</a>.<a href="https://pkg.go.dev/github.com/wandb/cwevals-go#ScorerListResponse">ScorerListResponse</a>, <a href="https://pkg.go.dev/builtin#error">error</a>)</code>
- <code title="delete /v1/namespaces/{namespace}/scopes/{scope_id}/scorers/{scorer_id}">client.Scorers.<a href="https://pkg.go.dev/github.com/wandb/cwevals-go#ScorerService.Delete">Delete</a>(ctx <a href="https://pkg.go.dev/context">context</a>.<a href="https://pkg.go.dev/context#Context">Context</a>, scorerID <a href="https://pkg.go.dev/builtin#string">string</a>, body <a href="https://pkg.go.dev/github.com/wandb/cwevals-go">cwevals</a>.<a href="https://pkg.go.dev/github.com/wandb/cwevals-go#ScorerDeleteParams">ScorerDeleteParams</a>) <a href="https://pkg.go.dev/builtin#error">error</a></code>
- <code title="get /v1/namespaces/{namespace}/scopes/{scope_id}/scorers/{scorer_id}">client.Scorers.<a href="https://pkg.go.dev/github.com/wandb/cwevals-go#ScorerService.Get">Get</a>(ctx <a href="https://pkg.go.dev/context">context</a>.<a href="https://pkg.go.dev/context#Context">Context</a>, scorerID <a href="https://pkg.go.dev/builtin#string">string</a>, query <a href="https://pkg.go.dev/github.com/wandb/cwevals-go">cwevals</a>.<a href="https://pkg.go.dev/github.com/wandb/cwevals-go#ScorerGetParams">ScorerGetParams</a>) (\*<a href="https://pkg.go.dev/github.com/wandb/cwevals-go">cwevals</a>.<a href="https://pkg.go.dev/github.com/wandb/cwevals-go#ScorerGetResponse">ScorerGetResponse</a>, <a href="https://pkg.go.dev/builtin#error">error</a>)</code>

## Versions

Response Types:

- <a href="https://pkg.go.dev/github.com/wandb/cwevals-go">cwevals</a>.<a href="https://pkg.go.dev/github.com/wandb/cwevals-go#ScorerVersionNewResponse">ScorerVersionNewResponse</a>
- <a href="https://pkg.go.dev/github.com/wandb/cwevals-go">cwevals</a>.<a href="https://pkg.go.dev/github.com/wandb/cwevals-go#ScorerVersionListResponse">ScorerVersionListResponse</a>
- <a href="https://pkg.go.dev/github.com/wandb/cwevals-go">cwevals</a>.<a href="https://pkg.go.dev/github.com/wandb/cwevals-go#ScorerVersionGetResponse">ScorerVersionGetResponse</a>

Methods:

- <code title="post /v1/namespaces/{namespace}/scopes/{scope_id}/scorers/{scorer_id}/versions">client.Scorers.Versions.<a href="https://pkg.go.dev/github.com/wandb/cwevals-go#ScorerVersionService.New">New</a>(ctx <a href="https://pkg.go.dev/context">context</a>.<a href="https://pkg.go.dev/context#Context">Context</a>, scorerID <a href="https://pkg.go.dev/builtin#string">string</a>, params <a href="https://pkg.go.dev/github.com/wandb/cwevals-go">cwevals</a>.<a href="https://pkg.go.dev/github.com/wandb/cwevals-go#ScorerVersionNewParams">ScorerVersionNewParams</a>) (\*<a href="https://pkg.go.dev/github.com/wandb/cwevals-go">cwevals</a>.<a href="https://pkg.go.dev/github.com/wandb/cwevals-go#ScorerVersionNewResponse">ScorerVersionNewResponse</a>, <a href="https://pkg.go.dev/builtin#error">error</a>)</code>
- <code title="get /v1/namespaces/{namespace}/scopes/{scope_id}/scorers/{scorer_id}/versions">client.Scorers.Versions.<a href="https://pkg.go.dev/github.com/wandb/cwevals-go#ScorerVersionService.List">List</a>(ctx <a href="https://pkg.go.dev/context">context</a>.<a href="https://pkg.go.dev/context#Context">Context</a>, scorerID <a href="https://pkg.go.dev/builtin#string">string</a>, params <a href="https://pkg.go.dev/github.com/wandb/cwevals-go">cwevals</a>.<a href="https://pkg.go.dev/github.com/wandb/cwevals-go#ScorerVersionListParams">ScorerVersionListParams</a>) (\*<a href="https://pkg.go.dev/github.com/wandb/cwevals-go">cwevals</a>.<a href="https://pkg.go.dev/github.com/wandb/cwevals-go#ScorerVersionListResponse">ScorerVersionListResponse</a>, <a href="https://pkg.go.dev/builtin#error">error</a>)</code>
- <code title="get /v1/namespaces/{namespace}/scopes/{scope_id}/scorers/{scorer_id}/versions/{scorer_version_id}">client.Scorers.Versions.<a href="https://pkg.go.dev/github.com/wandb/cwevals-go#ScorerVersionService.Get">Get</a>(ctx <a href="https://pkg.go.dev/context">context</a>.<a href="https://pkg.go.dev/context#Context">Context</a>, scorerID <a href="https://pkg.go.dev/builtin#string">string</a>, scorerVersionID <a href="https://pkg.go.dev/builtin#string">string</a>, query <a href="https://pkg.go.dev/github.com/wandb/cwevals-go">cwevals</a>.<a href="https://pkg.go.dev/github.com/wandb/cwevals-go#ScorerVersionGetParams">ScorerVersionGetParams</a>) (\*<a href="https://pkg.go.dev/github.com/wandb/cwevals-go">cwevals</a>.<a href="https://pkg.go.dev/github.com/wandb/cwevals-go#ScorerVersionGetResponse">ScorerVersionGetResponse</a>, <a href="https://pkg.go.dev/builtin#error">error</a>)</code>

# Scores

Response Types:

- <a href="https://pkg.go.dev/github.com/wandb/cwevals-go">cwevals</a>.<a href="https://pkg.go.dev/github.com/wandb/cwevals-go#ScoreNewResponse">ScoreNewResponse</a>
- <a href="https://pkg.go.dev/github.com/wandb/cwevals-go">cwevals</a>.<a href="https://pkg.go.dev/github.com/wandb/cwevals-go#ScoreGetResponse">ScoreGetResponse</a>

Methods:

- <code title="post /v1/namespaces/{namespace}/scopes/{scope_id}/scores">client.Scores.<a href="https://pkg.go.dev/github.com/wandb/cwevals-go#ScoreService.New">New</a>(ctx <a href="https://pkg.go.dev/context">context</a>.<a href="https://pkg.go.dev/context#Context">Context</a>, params <a href="https://pkg.go.dev/github.com/wandb/cwevals-go">cwevals</a>.<a href="https://pkg.go.dev/github.com/wandb/cwevals-go#ScoreNewParams">ScoreNewParams</a>) (\*<a href="https://pkg.go.dev/github.com/wandb/cwevals-go">cwevals</a>.<a href="https://pkg.go.dev/github.com/wandb/cwevals-go#ScoreNewResponse">ScoreNewResponse</a>, <a href="https://pkg.go.dev/builtin#error">error</a>)</code>
- <code title="get /v1/namespaces/{namespace}/scopes/{scope_id}/scores/{score_id}">client.Scores.<a href="https://pkg.go.dev/github.com/wandb/cwevals-go#ScoreService.Get">Get</a>(ctx <a href="https://pkg.go.dev/context">context</a>.<a href="https://pkg.go.dev/context#Context">Context</a>, scoreID <a href="https://pkg.go.dev/builtin#string">string</a>, query <a href="https://pkg.go.dev/github.com/wandb/cwevals-go">cwevals</a>.<a href="https://pkg.go.dev/github.com/wandb/cwevals-go#ScoreGetParams">ScoreGetParams</a>) (\*<a href="https://pkg.go.dev/github.com/wandb/cwevals-go">cwevals</a>.<a href="https://pkg.go.dev/github.com/wandb/cwevals-go#ScoreGetResponse">ScoreGetResponse</a>, <a href="https://pkg.go.dev/builtin#error">error</a>)</code>

# Evaluations

Response Types:

- <a href="https://pkg.go.dev/github.com/wandb/cwevals-go">cwevals</a>.<a href="https://pkg.go.dev/github.com/wandb/cwevals-go#EvaluationNewResponse">EvaluationNewResponse</a>
- <a href="https://pkg.go.dev/github.com/wandb/cwevals-go">cwevals</a>.<a href="https://pkg.go.dev/github.com/wandb/cwevals-go#EvaluationUpdateResponse">EvaluationUpdateResponse</a>
- <a href="https://pkg.go.dev/github.com/wandb/cwevals-go">cwevals</a>.<a href="https://pkg.go.dev/github.com/wandb/cwevals-go#EvaluationListResponse">EvaluationListResponse</a>
- <a href="https://pkg.go.dev/github.com/wandb/cwevals-go">cwevals</a>.<a href="https://pkg.go.dev/github.com/wandb/cwevals-go#EvaluationGetResponse">EvaluationGetResponse</a>

Methods:

- <code title="post /v1/namespaces/{namespace}/scopes/{scope_id}/evaluations">client.Evaluations.<a href="https://pkg.go.dev/github.com/wandb/cwevals-go#EvaluationService.New">New</a>(ctx <a href="https://pkg.go.dev/context">context</a>.<a href="https://pkg.go.dev/context#Context">Context</a>, params <a href="https://pkg.go.dev/github.com/wandb/cwevals-go">cwevals</a>.<a href="https://pkg.go.dev/github.com/wandb/cwevals-go#EvaluationNewParams">EvaluationNewParams</a>) (\*<a href="https://pkg.go.dev/github.com/wandb/cwevals-go">cwevals</a>.<a href="https://pkg.go.dev/github.com/wandb/cwevals-go#EvaluationNewResponse">EvaluationNewResponse</a>, <a href="https://pkg.go.dev/builtin#error">error</a>)</code>
- <code title="patch /v1/namespaces/{namespace}/scopes/{scope_id}/evaluations/{evaluation_id}">client.Evaluations.<a href="https://pkg.go.dev/github.com/wandb/cwevals-go#EvaluationService.Update">Update</a>(ctx <a href="https://pkg.go.dev/context">context</a>.<a href="https://pkg.go.dev/context#Context">Context</a>, evaluationID <a href="https://pkg.go.dev/builtin#string">string</a>, params <a href="https://pkg.go.dev/github.com/wandb/cwevals-go">cwevals</a>.<a href="https://pkg.go.dev/github.com/wandb/cwevals-go#EvaluationUpdateParams">EvaluationUpdateParams</a>) (\*<a href="https://pkg.go.dev/github.com/wandb/cwevals-go">cwevals</a>.<a href="https://pkg.go.dev/github.com/wandb/cwevals-go#EvaluationUpdateResponse">EvaluationUpdateResponse</a>, <a href="https://pkg.go.dev/builtin#error">error</a>)</code>
- <code title="get /v1/namespaces/{namespace}/scopes/{scope_id}/evaluations">client.Evaluations.<a href="https://pkg.go.dev/github.com/wandb/cwevals-go#EvaluationService.List">List</a>(ctx <a href="https://pkg.go.dev/context">context</a>.<a href="https://pkg.go.dev/context#Context">Context</a>, params <a href="https://pkg.go.dev/github.com/wandb/cwevals-go">cwevals</a>.<a href="https://pkg.go.dev/github.com/wandb/cwevals-go#EvaluationListParams">EvaluationListParams</a>) (\*<a href="https://pkg.go.dev/github.com/wandb/cwevals-go">cwevals</a>.<a href="https://pkg.go.dev/github.com/wandb/cwevals-go#EvaluationListResponse">EvaluationListResponse</a>, <a href="https://pkg.go.dev/builtin#error">error</a>)</code>
- <code title="delete /v1/namespaces/{namespace}/scopes/{scope_id}/evaluations/{evaluation_id}">client.Evaluations.<a href="https://pkg.go.dev/github.com/wandb/cwevals-go#EvaluationService.Delete">Delete</a>(ctx <a href="https://pkg.go.dev/context">context</a>.<a href="https://pkg.go.dev/context#Context">Context</a>, evaluationID <a href="https://pkg.go.dev/builtin#string">string</a>, body <a href="https://pkg.go.dev/github.com/wandb/cwevals-go">cwevals</a>.<a href="https://pkg.go.dev/github.com/wandb/cwevals-go#EvaluationDeleteParams">EvaluationDeleteParams</a>) <a href="https://pkg.go.dev/builtin#error">error</a></code>
- <code title="get /v1/namespaces/{namespace}/scopes/{scope_id}/evaluations/{evaluation_id}">client.Evaluations.<a href="https://pkg.go.dev/github.com/wandb/cwevals-go#EvaluationService.Get">Get</a>(ctx <a href="https://pkg.go.dev/context">context</a>.<a href="https://pkg.go.dev/context#Context">Context</a>, evaluationID <a href="https://pkg.go.dev/builtin#string">string</a>, query <a href="https://pkg.go.dev/github.com/wandb/cwevals-go">cwevals</a>.<a href="https://pkg.go.dev/github.com/wandb/cwevals-go#EvaluationGetParams">EvaluationGetParams</a>) (\*<a href="https://pkg.go.dev/github.com/wandb/cwevals-go">cwevals</a>.<a href="https://pkg.go.dev/github.com/wandb/cwevals-go#EvaluationGetResponse">EvaluationGetResponse</a>, <a href="https://pkg.go.dev/builtin#error">error</a>)</code>

## Metrics

Response Types:

- <a href="https://pkg.go.dev/github.com/wandb/cwevals-go">cwevals</a>.<a href="https://pkg.go.dev/github.com/wandb/cwevals-go#EvaluationMetricListResponse">EvaluationMetricListResponse</a>
- <a href="https://pkg.go.dev/github.com/wandb/cwevals-go">cwevals</a>.<a href="https://pkg.go.dev/github.com/wandb/cwevals-go#EvaluationMetricReportResponse">EvaluationMetricReportResponse</a>

Methods:

- <code title="get /v1/namespaces/{namespace}/scopes/{scope_id}/evaluations/{evaluation_id}/metrics">client.Evaluations.Metrics.<a href="https://pkg.go.dev/github.com/wandb/cwevals-go#EvaluationMetricService.List">List</a>(ctx <a href="https://pkg.go.dev/context">context</a>.<a href="https://pkg.go.dev/context#Context">Context</a>, evaluationID <a href="https://pkg.go.dev/builtin#string">string</a>, query <a href="https://pkg.go.dev/github.com/wandb/cwevals-go">cwevals</a>.<a href="https://pkg.go.dev/github.com/wandb/cwevals-go#EvaluationMetricListParams">EvaluationMetricListParams</a>) (\*<a href="https://pkg.go.dev/github.com/wandb/cwevals-go">cwevals</a>.<a href="https://pkg.go.dev/github.com/wandb/cwevals-go#EvaluationMetricListResponse">EvaluationMetricListResponse</a>, <a href="https://pkg.go.dev/builtin#error">error</a>)</code>
- <code title="post /v1/namespaces/{namespace}/scopes/{scope_id}/evaluations/{evaluation_id}/metrics">client.Evaluations.Metrics.<a href="https://pkg.go.dev/github.com/wandb/cwevals-go#EvaluationMetricService.Report">Report</a>(ctx <a href="https://pkg.go.dev/context">context</a>.<a href="https://pkg.go.dev/context#Context">Context</a>, evaluationID <a href="https://pkg.go.dev/builtin#string">string</a>, params <a href="https://pkg.go.dev/github.com/wandb/cwevals-go">cwevals</a>.<a href="https://pkg.go.dev/github.com/wandb/cwevals-go#EvaluationMetricReportParams">EvaluationMetricReportParams</a>) (\*<a href="https://pkg.go.dev/github.com/wandb/cwevals-go">cwevals</a>.<a href="https://pkg.go.dev/github.com/wandb/cwevals-go#EvaluationMetricReportResponse">EvaluationMetricReportResponse</a>, <a href="https://pkg.go.dev/builtin#error">error</a>)</code>

## Rows

Response Types:

- <a href="https://pkg.go.dev/github.com/wandb/cwevals-go">cwevals</a>.<a href="https://pkg.go.dev/github.com/wandb/cwevals-go#EvaluationRowListResponse">EvaluationRowListResponse</a>
- <a href="https://pkg.go.dev/github.com/wandb/cwevals-go">cwevals</a>.<a href="https://pkg.go.dev/github.com/wandb/cwevals-go#EvaluationRowSearchResponse">EvaluationRowSearchResponse</a>

Methods:

- <code title="get /v1/namespaces/{namespace}/scopes/{scope_id}/evaluations/{evaluation_id}/rows">client.Evaluations.Rows.<a href="https://pkg.go.dev/github.com/wandb/cwevals-go#EvaluationRowService.List">List</a>(ctx <a href="https://pkg.go.dev/context">context</a>.<a href="https://pkg.go.dev/context#Context">Context</a>, evaluationID <a href="https://pkg.go.dev/builtin#string">string</a>, params <a href="https://pkg.go.dev/github.com/wandb/cwevals-go">cwevals</a>.<a href="https://pkg.go.dev/github.com/wandb/cwevals-go#EvaluationRowListParams">EvaluationRowListParams</a>) (\*<a href="https://pkg.go.dev/github.com/wandb/cwevals-go">cwevals</a>.<a href="https://pkg.go.dev/github.com/wandb/cwevals-go#EvaluationRowListResponse">EvaluationRowListResponse</a>, <a href="https://pkg.go.dev/builtin#error">error</a>)</code>
- <code title="post /v1/namespaces/{namespace}/scopes/{scope_id}/evaluations/{evaluation_id}/rows/search">client.Evaluations.Rows.<a href="https://pkg.go.dev/github.com/wandb/cwevals-go#EvaluationRowService.Search">Search</a>(ctx <a href="https://pkg.go.dev/context">context</a>.<a href="https://pkg.go.dev/context#Context">Context</a>, evaluationID <a href="https://pkg.go.dev/builtin#string">string</a>, params <a href="https://pkg.go.dev/github.com/wandb/cwevals-go">cwevals</a>.<a href="https://pkg.go.dev/github.com/wandb/cwevals-go#EvaluationRowSearchParams">EvaluationRowSearchParams</a>) (\*<a href="https://pkg.go.dev/github.com/wandb/cwevals-go">cwevals</a>.<a href="https://pkg.go.dev/github.com/wandb/cwevals-go#EvaluationRowSearchResponse">EvaluationRowSearchResponse</a>, <a href="https://pkg.go.dev/builtin#error">error</a>)</code>

## Scorers

Response Types:

- <a href="https://pkg.go.dev/github.com/wandb/cwevals-go">cwevals</a>.<a href="https://pkg.go.dev/github.com/wandb/cwevals-go#EvaluationScorerAddResponse">EvaluationScorerAddResponse</a>

Methods:

- <code title="patch /v1/namespaces/{namespace}/scopes/{scope_id}/evaluations/{evaluation_id}/scorers">client.Evaluations.Scorers.<a href="https://pkg.go.dev/github.com/wandb/cwevals-go#EvaluationScorerService.Add">Add</a>(ctx <a href="https://pkg.go.dev/context">context</a>.<a href="https://pkg.go.dev/context#Context">Context</a>, evaluationID <a href="https://pkg.go.dev/builtin#string">string</a>, params <a href="https://pkg.go.dev/github.com/wandb/cwevals-go">cwevals</a>.<a href="https://pkg.go.dev/github.com/wandb/cwevals-go#EvaluationScorerAddParams">EvaluationScorerAddParams</a>) (\*<a href="https://pkg.go.dev/github.com/wandb/cwevals-go">cwevals</a>.<a href="https://pkg.go.dev/github.com/wandb/cwevals-go#EvaluationScorerAddResponse">EvaluationScorerAddResponse</a>, <a href="https://pkg.go.dev/builtin#error">error</a>)</code>

## Queries

Response Types:

- <a href="https://pkg.go.dev/github.com/wandb/cwevals-go">cwevals</a>.<a href="https://pkg.go.dev/github.com/wandb/cwevals-go#EvaluationQueryNewResponse">EvaluationQueryNewResponse</a>
- <a href="https://pkg.go.dev/github.com/wandb/cwevals-go">cwevals</a>.<a href="https://pkg.go.dev/github.com/wandb/cwevals-go#EvaluationQueryListResponse">EvaluationQueryListResponse</a>
- <a href="https://pkg.go.dev/github.com/wandb/cwevals-go">cwevals</a>.<a href="https://pkg.go.dev/github.com/wandb/cwevals-go#EvaluationQueryGetResponse">EvaluationQueryGetResponse</a>

Methods:

- <code title="post /v1/namespaces/{namespace}/scopes/{scope_id}/evaluations/{evaluation_id}/queries">client.Evaluations.Queries.<a href="https://pkg.go.dev/github.com/wandb/cwevals-go#EvaluationQueryService.New">New</a>(ctx <a href="https://pkg.go.dev/context">context</a>.<a href="https://pkg.go.dev/context#Context">Context</a>, evaluationID <a href="https://pkg.go.dev/builtin#string">string</a>, params <a href="https://pkg.go.dev/github.com/wandb/cwevals-go">cwevals</a>.<a href="https://pkg.go.dev/github.com/wandb/cwevals-go#EvaluationQueryNewParams">EvaluationQueryNewParams</a>) (\*<a href="https://pkg.go.dev/github.com/wandb/cwevals-go">cwevals</a>.<a href="https://pkg.go.dev/github.com/wandb/cwevals-go#EvaluationQueryNewResponse">EvaluationQueryNewResponse</a>, <a href="https://pkg.go.dev/builtin#error">error</a>)</code>
- <code title="get /v1/namespaces/{namespace}/scopes/{scope_id}/evaluations/{evaluation_id}/queries">client.Evaluations.Queries.<a href="https://pkg.go.dev/github.com/wandb/cwevals-go#EvaluationQueryService.List">List</a>(ctx <a href="https://pkg.go.dev/context">context</a>.<a href="https://pkg.go.dev/context#Context">Context</a>, evaluationID <a href="https://pkg.go.dev/builtin#string">string</a>, params <a href="https://pkg.go.dev/github.com/wandb/cwevals-go">cwevals</a>.<a href="https://pkg.go.dev/github.com/wandb/cwevals-go#EvaluationQueryListParams">EvaluationQueryListParams</a>) (\*<a href="https://pkg.go.dev/github.com/wandb/cwevals-go">cwevals</a>.<a href="https://pkg.go.dev/github.com/wandb/cwevals-go#EvaluationQueryListResponse">EvaluationQueryListResponse</a>, <a href="https://pkg.go.dev/builtin#error">error</a>)</code>
- <code title="get /v1/namespaces/{namespace}/scopes/{scope_id}/evaluations/{evaluation_id}/queries/{evaluation_query_id}">client.Evaluations.Queries.<a href="https://pkg.go.dev/github.com/wandb/cwevals-go#EvaluationQueryService.Get">Get</a>(ctx <a href="https://pkg.go.dev/context">context</a>.<a href="https://pkg.go.dev/context#Context">Context</a>, evaluationID <a href="https://pkg.go.dev/builtin#string">string</a>, evaluationQueryID <a href="https://pkg.go.dev/builtin#string">string</a>, query <a href="https://pkg.go.dev/github.com/wandb/cwevals-go">cwevals</a>.<a href="https://pkg.go.dev/github.com/wandb/cwevals-go#EvaluationQueryGetParams">EvaluationQueryGetParams</a>) (\*<a href="https://pkg.go.dev/github.com/wandb/cwevals-go">cwevals</a>.<a href="https://pkg.go.dev/github.com/wandb/cwevals-go#EvaluationQueryGetResponse">EvaluationQueryGetResponse</a>, <a href="https://pkg.go.dev/builtin#error">error</a>)</code>

### Results

Response Types:

- <a href="https://pkg.go.dev/github.com/wandb/cwevals-go">cwevals</a>.<a href="https://pkg.go.dev/github.com/wandb/cwevals-go#EvaluationQueryResultListResponse">EvaluationQueryResultListResponse</a>

Methods:

- <code title="get /v1/namespaces/{namespace}/scopes/{scope_id}/evaluations/{evaluation_id}/queries/{evaluation_query_id}/results">client.Evaluations.Queries.Results.<a href="https://pkg.go.dev/github.com/wandb/cwevals-go#EvaluationQueryResultService.List">List</a>(ctx <a href="https://pkg.go.dev/context">context</a>.<a href="https://pkg.go.dev/context#Context">Context</a>, evaluationID <a href="https://pkg.go.dev/builtin#string">string</a>, evaluationQueryID <a href="https://pkg.go.dev/builtin#string">string</a>, params <a href="https://pkg.go.dev/github.com/wandb/cwevals-go">cwevals</a>.<a href="https://pkg.go.dev/github.com/wandb/cwevals-go#EvaluationQueryResultListParams">EvaluationQueryResultListParams</a>) (\*<a href="https://pkg.go.dev/github.com/wandb/cwevals-go">cwevals</a>.<a href="https://pkg.go.dev/github.com/wandb/cwevals-go#EvaluationQueryResultListResponse">EvaluationQueryResultListResponse</a>, <a href="https://pkg.go.dev/builtin#error">error</a>)</code>

## Versions

Response Types:

- <a href="https://pkg.go.dev/github.com/wandb/cwevals-go">cwevals</a>.<a href="https://pkg.go.dev/github.com/wandb/cwevals-go#EvaluationVersionNewResponse">EvaluationVersionNewResponse</a>
- <a href="https://pkg.go.dev/github.com/wandb/cwevals-go">cwevals</a>.<a href="https://pkg.go.dev/github.com/wandb/cwevals-go#EvaluationVersionListResponse">EvaluationVersionListResponse</a>
- <a href="https://pkg.go.dev/github.com/wandb/cwevals-go">cwevals</a>.<a href="https://pkg.go.dev/github.com/wandb/cwevals-go#EvaluationVersionGetResponse">EvaluationVersionGetResponse</a>

Methods:

- <code title="post /v1/namespaces/{namespace}/scopes/{scope_id}/evaluations/{evaluation_id}/versions">client.Evaluations.Versions.<a href="https://pkg.go.dev/github.com/wandb/cwevals-go#EvaluationVersionService.New">New</a>(ctx <a href="https://pkg.go.dev/context">context</a>.<a href="https://pkg.go.dev/context#Context">Context</a>, evaluationID <a href="https://pkg.go.dev/builtin#string">string</a>, params <a href="https://pkg.go.dev/github.com/wandb/cwevals-go">cwevals</a>.<a href="https://pkg.go.dev/github.com/wandb/cwevals-go#EvaluationVersionNewParams">EvaluationVersionNewParams</a>) (\*<a href="https://pkg.go.dev/github.com/wandb/cwevals-go">cwevals</a>.<a href="https://pkg.go.dev/github.com/wandb/cwevals-go#EvaluationVersionNewResponse">EvaluationVersionNewResponse</a>, <a href="https://pkg.go.dev/builtin#error">error</a>)</code>
- <code title="get /v1/namespaces/{namespace}/scopes/{scope_id}/evaluations/{evaluation_id}/versions">client.Evaluations.Versions.<a href="https://pkg.go.dev/github.com/wandb/cwevals-go#EvaluationVersionService.List">List</a>(ctx <a href="https://pkg.go.dev/context">context</a>.<a href="https://pkg.go.dev/context#Context">Context</a>, evaluationID <a href="https://pkg.go.dev/builtin#string">string</a>, params <a href="https://pkg.go.dev/github.com/wandb/cwevals-go">cwevals</a>.<a href="https://pkg.go.dev/github.com/wandb/cwevals-go#EvaluationVersionListParams">EvaluationVersionListParams</a>) (\*<a href="https://pkg.go.dev/github.com/wandb/cwevals-go">cwevals</a>.<a href="https://pkg.go.dev/github.com/wandb/cwevals-go#EvaluationVersionListResponse">EvaluationVersionListResponse</a>, <a href="https://pkg.go.dev/builtin#error">error</a>)</code>
- <code title="get /v1/namespaces/{namespace}/scopes/{scope_id}/evaluation-versions/{evaluation_version_id}">client.Evaluations.Versions.<a href="https://pkg.go.dev/github.com/wandb/cwevals-go#EvaluationVersionService.Get">Get</a>(ctx <a href="https://pkg.go.dev/context">context</a>.<a href="https://pkg.go.dev/context#Context">Context</a>, evaluationVersionID <a href="https://pkg.go.dev/builtin#string">string</a>, query <a href="https://pkg.go.dev/github.com/wandb/cwevals-go">cwevals</a>.<a href="https://pkg.go.dev/github.com/wandb/cwevals-go#EvaluationVersionGetParams">EvaluationVersionGetParams</a>) (\*<a href="https://pkg.go.dev/github.com/wandb/cwevals-go">cwevals</a>.<a href="https://pkg.go.dev/github.com/wandb/cwevals-go#EvaluationVersionGetResponse">EvaluationVersionGetResponse</a>, <a href="https://pkg.go.dev/builtin#error">error</a>)</code>

### Metrics

Response Types:

- <a href="https://pkg.go.dev/github.com/wandb/cwevals-go">cwevals</a>.<a href="https://pkg.go.dev/github.com/wandb/cwevals-go#EvaluationVersionMetricListResponse">EvaluationVersionMetricListResponse</a>

Methods:

- <code title="get /v1/namespaces/{namespace}/scopes/{scope_id}/evaluation-versions/{evaluation_version_id}/metrics">client.Evaluations.Versions.Metrics.<a href="https://pkg.go.dev/github.com/wandb/cwevals-go#EvaluationVersionMetricService.List">List</a>(ctx <a href="https://pkg.go.dev/context">context</a>.<a href="https://pkg.go.dev/context#Context">Context</a>, evaluationVersionID <a href="https://pkg.go.dev/builtin#string">string</a>, query <a href="https://pkg.go.dev/github.com/wandb/cwevals-go">cwevals</a>.<a href="https://pkg.go.dev/github.com/wandb/cwevals-go#EvaluationVersionMetricListParams">EvaluationVersionMetricListParams</a>) (\*<a href="https://pkg.go.dev/github.com/wandb/cwevals-go">cwevals</a>.<a href="https://pkg.go.dev/github.com/wandb/cwevals-go#EvaluationVersionMetricListResponse">EvaluationVersionMetricListResponse</a>, <a href="https://pkg.go.dev/builtin#error">error</a>)</code>

### Results

Response Types:

- <a href="https://pkg.go.dev/github.com/wandb/cwevals-go">cwevals</a>.<a href="https://pkg.go.dev/github.com/wandb/cwevals-go#EvaluationVersionResultListResponse">EvaluationVersionResultListResponse</a>

Methods:

- <code title="get /v1/namespaces/{namespace}/scopes/{scope_id}/evaluation-versions/{evaluation_version_id}/results">client.Evaluations.Versions.Results.<a href="https://pkg.go.dev/github.com/wandb/cwevals-go#EvaluationVersionResultService.List">List</a>(ctx <a href="https://pkg.go.dev/context">context</a>.<a href="https://pkg.go.dev/context#Context">Context</a>, evaluationVersionID <a href="https://pkg.go.dev/builtin#string">string</a>, params <a href="https://pkg.go.dev/github.com/wandb/cwevals-go">cwevals</a>.<a href="https://pkg.go.dev/github.com/wandb/cwevals-go#EvaluationVersionResultListParams">EvaluationVersionResultListParams</a>) (\*<a href="https://pkg.go.dev/github.com/wandb/cwevals-go">cwevals</a>.<a href="https://pkg.go.dev/github.com/wandb/cwevals-go#EvaluationVersionResultListResponse">EvaluationVersionResultListResponse</a>, <a href="https://pkg.go.dev/builtin#error">error</a>)</code>

### Queries

#### Results

Response Types:

- <a href="https://pkg.go.dev/github.com/wandb/cwevals-go">cwevals</a>.<a href="https://pkg.go.dev/github.com/wandb/cwevals-go#EvaluationVersionQueryResultListResponse">EvaluationVersionQueryResultListResponse</a>

Methods:

- <code title="get /v1/namespaces/{namespace}/scopes/{scope_id}/evaluation-versions/{evaluation_version_id}/queries/{evaluation_query_id}/results">client.Evaluations.Versions.Queries.Results.<a href="https://pkg.go.dev/github.com/wandb/cwevals-go#EvaluationVersionQueryResultService.List">List</a>(ctx <a href="https://pkg.go.dev/context">context</a>.<a href="https://pkg.go.dev/context#Context">Context</a>, evaluationVersionID <a href="https://pkg.go.dev/builtin#string">string</a>, evaluationQueryID <a href="https://pkg.go.dev/builtin#string">string</a>, params <a href="https://pkg.go.dev/github.com/wandb/cwevals-go">cwevals</a>.<a href="https://pkg.go.dev/github.com/wandb/cwevals-go#EvaluationVersionQueryResultListParams">EvaluationVersionQueryResultListParams</a>) (\*<a href="https://pkg.go.dev/github.com/wandb/cwevals-go">cwevals</a>.<a href="https://pkg.go.dev/github.com/wandb/cwevals-go#EvaluationVersionQueryResultListResponse">EvaluationVersionQueryResultListResponse</a>, <a href="https://pkg.go.dev/builtin#error">error</a>)</code>

### Rows

Response Types:

- <a href="https://pkg.go.dev/github.com/wandb/cwevals-go">cwevals</a>.<a href="https://pkg.go.dev/github.com/wandb/cwevals-go#EvaluationVersionRowListResponse">EvaluationVersionRowListResponse</a>
- <a href="https://pkg.go.dev/github.com/wandb/cwevals-go">cwevals</a>.<a href="https://pkg.go.dev/github.com/wandb/cwevals-go#EvaluationVersionRowSearchResponse">EvaluationVersionRowSearchResponse</a>

Methods:

- <code title="get /v1/namespaces/{namespace}/scopes/{scope_id}/evaluation-versions/{evaluation_version_id}/rows">client.Evaluations.Versions.Rows.<a href="https://pkg.go.dev/github.com/wandb/cwevals-go#EvaluationVersionRowService.List">List</a>(ctx <a href="https://pkg.go.dev/context">context</a>.<a href="https://pkg.go.dev/context#Context">Context</a>, evaluationVersionID <a href="https://pkg.go.dev/builtin#string">string</a>, params <a href="https://pkg.go.dev/github.com/wandb/cwevals-go">cwevals</a>.<a href="https://pkg.go.dev/github.com/wandb/cwevals-go#EvaluationVersionRowListParams">EvaluationVersionRowListParams</a>) (\*<a href="https://pkg.go.dev/github.com/wandb/cwevals-go">cwevals</a>.<a href="https://pkg.go.dev/github.com/wandb/cwevals-go#EvaluationVersionRowListResponse">EvaluationVersionRowListResponse</a>, <a href="https://pkg.go.dev/builtin#error">error</a>)</code>
- <code title="post /v1/namespaces/{namespace}/scopes/{scope_id}/evaluation-versions/{evaluation_version_id}/rows/search">client.Evaluations.Versions.Rows.<a href="https://pkg.go.dev/github.com/wandb/cwevals-go#EvaluationVersionRowService.Search">Search</a>(ctx <a href="https://pkg.go.dev/context">context</a>.<a href="https://pkg.go.dev/context#Context">Context</a>, evaluationVersionID <a href="https://pkg.go.dev/builtin#string">string</a>, params <a href="https://pkg.go.dev/github.com/wandb/cwevals-go">cwevals</a>.<a href="https://pkg.go.dev/github.com/wandb/cwevals-go#EvaluationVersionRowSearchParams">EvaluationVersionRowSearchParams</a>) (\*<a href="https://pkg.go.dev/github.com/wandb/cwevals-go">cwevals</a>.<a href="https://pkg.go.dev/github.com/wandb/cwevals-go#EvaluationVersionRowSearchResponse">EvaluationVersionRowSearchResponse</a>, <a href="https://pkg.go.dev/builtin#error">error</a>)</code>

#### Compare

Response Types:

- <a href="https://pkg.go.dev/github.com/wandb/cwevals-go">cwevals</a>.<a href="https://pkg.go.dev/github.com/wandb/cwevals-go#EvaluationVersionRowCompareListResponse">EvaluationVersionRowCompareListResponse</a>
- <a href="https://pkg.go.dev/github.com/wandb/cwevals-go">cwevals</a>.<a href="https://pkg.go.dev/github.com/wandb/cwevals-go#EvaluationVersionRowCompareSearchResponse">EvaluationVersionRowCompareSearchResponse</a>

Methods:

- <code title="get /v1/namespaces/{namespace}/scopes/{scope_id}/evaluation-versions/{evaluation_version_id}/rows/compare">client.Evaluations.Versions.Rows.Compare.<a href="https://pkg.go.dev/github.com/wandb/cwevals-go#EvaluationVersionRowCompareService.List">List</a>(ctx <a href="https://pkg.go.dev/context">context</a>.<a href="https://pkg.go.dev/context#Context">Context</a>, evaluationVersionID <a href="https://pkg.go.dev/builtin#string">string</a>, params <a href="https://pkg.go.dev/github.com/wandb/cwevals-go">cwevals</a>.<a href="https://pkg.go.dev/github.com/wandb/cwevals-go#EvaluationVersionRowCompareListParams">EvaluationVersionRowCompareListParams</a>) (\*<a href="https://pkg.go.dev/github.com/wandb/cwevals-go">cwevals</a>.<a href="https://pkg.go.dev/github.com/wandb/cwevals-go#EvaluationVersionRowCompareListResponse">EvaluationVersionRowCompareListResponse</a>, <a href="https://pkg.go.dev/builtin#error">error</a>)</code>
- <code title="post /v1/namespaces/{namespace}/scopes/{scope_id}/evaluation-versions/{evaluation_version_id}/rows/compare/search">client.Evaluations.Versions.Rows.Compare.<a href="https://pkg.go.dev/github.com/wandb/cwevals-go#EvaluationVersionRowCompareService.Search">Search</a>(ctx <a href="https://pkg.go.dev/context">context</a>.<a href="https://pkg.go.dev/context#Context">Context</a>, evaluationVersionID <a href="https://pkg.go.dev/builtin#string">string</a>, params <a href="https://pkg.go.dev/github.com/wandb/cwevals-go">cwevals</a>.<a href="https://pkg.go.dev/github.com/wandb/cwevals-go#EvaluationVersionRowCompareSearchParams">EvaluationVersionRowCompareSearchParams</a>) (\*<a href="https://pkg.go.dev/github.com/wandb/cwevals-go">cwevals</a>.<a href="https://pkg.go.dev/github.com/wandb/cwevals-go#EvaluationVersionRowCompareSearchResponse">EvaluationVersionRowCompareSearchResponse</a>, <a href="https://pkg.go.dev/builtin#error">error</a>)</code>

# EvalTables

Response Types:

- <a href="https://pkg.go.dev/github.com/wandb/cwevals-go">cwevals</a>.<a href="https://pkg.go.dev/github.com/wandb/cwevals-go#EvalTableNewResponse">EvalTableNewResponse</a>

Methods:

- <code title="post /v1/namespaces/{namespace}/scopes/{scope_id}/eval-tables">client.EvalTables.<a href="https://pkg.go.dev/github.com/wandb/cwevals-go#EvalTableService.New">New</a>(ctx <a href="https://pkg.go.dev/context">context</a>.<a href="https://pkg.go.dev/context#Context">Context</a>, params <a href="https://pkg.go.dev/github.com/wandb/cwevals-go">cwevals</a>.<a href="https://pkg.go.dev/github.com/wandb/cwevals-go#EvalTableNewParams">EvalTableNewParams</a>) (\*<a href="https://pkg.go.dev/github.com/wandb/cwevals-go">cwevals</a>.<a href="https://pkg.go.dev/github.com/wandb/cwevals-go#EvalTableNewResponse">EvalTableNewResponse</a>, <a href="https://pkg.go.dev/builtin#error">error</a>)</code>

## Columns

Response Types:

- <a href="https://pkg.go.dev/github.com/wandb/cwevals-go">cwevals</a>.<a href="https://pkg.go.dev/github.com/wandb/cwevals-go#EvalTableColumnNewResponse">EvalTableColumnNewResponse</a>

Methods:

- <code title="post /v1/namespaces/{namespace}/scopes/{scope_id}/eval-tables/{evaluation_id}/columns">client.EvalTables.Columns.<a href="https://pkg.go.dev/github.com/wandb/cwevals-go#EvalTableColumnService.New">New</a>(ctx <a href="https://pkg.go.dev/context">context</a>.<a href="https://pkg.go.dev/context#Context">Context</a>, evaluationID <a href="https://pkg.go.dev/builtin#string">string</a>, params <a href="https://pkg.go.dev/github.com/wandb/cwevals-go">cwevals</a>.<a href="https://pkg.go.dev/github.com/wandb/cwevals-go#EvalTableColumnNewParams">EvalTableColumnNewParams</a>) (\*<a href="https://pkg.go.dev/github.com/wandb/cwevals-go">cwevals</a>.<a href="https://pkg.go.dev/github.com/wandb/cwevals-go#EvalTableColumnNewResponse">EvalTableColumnNewResponse</a>, <a href="https://pkg.go.dev/builtin#error">error</a>)</code>

## Rows

Response Types:

- <a href="https://pkg.go.dev/github.com/wandb/cwevals-go">cwevals</a>.<a href="https://pkg.go.dev/github.com/wandb/cwevals-go#EvalTableRowListResponse">EvalTableRowListResponse</a>
- <a href="https://pkg.go.dev/github.com/wandb/cwevals-go">cwevals</a>.<a href="https://pkg.go.dev/github.com/wandb/cwevals-go#EvalTableRowAddResponse">EvalTableRowAddResponse</a>
- <a href="https://pkg.go.dev/github.com/wandb/cwevals-go">cwevals</a>.<a href="https://pkg.go.dev/github.com/wandb/cwevals-go#EvalTableRowSearchResponse">EvalTableRowSearchResponse</a>

Methods:

- <code title="get /v1/namespaces/{namespace}/scopes/{scope_id}/eval-tables/{evaluation_id}/rows">client.EvalTables.Rows.<a href="https://pkg.go.dev/github.com/wandb/cwevals-go#EvalTableRowService.List">List</a>(ctx <a href="https://pkg.go.dev/context">context</a>.<a href="https://pkg.go.dev/context#Context">Context</a>, evaluationID <a href="https://pkg.go.dev/builtin#string">string</a>, params <a href="https://pkg.go.dev/github.com/wandb/cwevals-go">cwevals</a>.<a href="https://pkg.go.dev/github.com/wandb/cwevals-go#EvalTableRowListParams">EvalTableRowListParams</a>) (\*<a href="https://pkg.go.dev/github.com/wandb/cwevals-go">cwevals</a>.<a href="https://pkg.go.dev/github.com/wandb/cwevals-go#EvalTableRowListResponse">EvalTableRowListResponse</a>, <a href="https://pkg.go.dev/builtin#error">error</a>)</code>
- <code title="post /v1/namespaces/{namespace}/scopes/{scope_id}/eval-tables/{evaluation_id}/rows">client.EvalTables.Rows.<a href="https://pkg.go.dev/github.com/wandb/cwevals-go#EvalTableRowService.Add">Add</a>(ctx <a href="https://pkg.go.dev/context">context</a>.<a href="https://pkg.go.dev/context#Context">Context</a>, evaluationID <a href="https://pkg.go.dev/builtin#string">string</a>, params <a href="https://pkg.go.dev/github.com/wandb/cwevals-go">cwevals</a>.<a href="https://pkg.go.dev/github.com/wandb/cwevals-go#EvalTableRowAddParams">EvalTableRowAddParams</a>) (\*<a href="https://pkg.go.dev/github.com/wandb/cwevals-go">cwevals</a>.<a href="https://pkg.go.dev/github.com/wandb/cwevals-go#EvalTableRowAddResponse">EvalTableRowAddResponse</a>, <a href="https://pkg.go.dev/builtin#error">error</a>)</code>
- <code title="post /v1/namespaces/{namespace}/scopes/{scope_id}/eval-tables/{evaluation_id}/rows/search">client.EvalTables.Rows.<a href="https://pkg.go.dev/github.com/wandb/cwevals-go#EvalTableRowService.Search">Search</a>(ctx <a href="https://pkg.go.dev/context">context</a>.<a href="https://pkg.go.dev/context#Context">Context</a>, evaluationID <a href="https://pkg.go.dev/builtin#string">string</a>, params <a href="https://pkg.go.dev/github.com/wandb/cwevals-go">cwevals</a>.<a href="https://pkg.go.dev/github.com/wandb/cwevals-go#EvalTableRowSearchParams">EvalTableRowSearchParams</a>) (\*<a href="https://pkg.go.dev/github.com/wandb/cwevals-go">cwevals</a>.<a href="https://pkg.go.dev/github.com/wandb/cwevals-go#EvalTableRowSearchResponse">EvalTableRowSearchResponse</a>, <a href="https://pkg.go.dev/builtin#error">error</a>)</code>

## Versions

Response Types:

- <a href="https://pkg.go.dev/github.com/wandb/cwevals-go">cwevals</a>.<a href="https://pkg.go.dev/github.com/wandb/cwevals-go#EvalTableVersionNewResponse">EvalTableVersionNewResponse</a>

Methods:

- <code title="post /v1/namespaces/{namespace}/scopes/{scope_id}/eval-tables/{evaluation_id}/versions">client.EvalTables.Versions.<a href="https://pkg.go.dev/github.com/wandb/cwevals-go#EvalTableVersionService.New">New</a>(ctx <a href="https://pkg.go.dev/context">context</a>.<a href="https://pkg.go.dev/context#Context">Context</a>, evaluationID <a href="https://pkg.go.dev/builtin#string">string</a>, body <a href="https://pkg.go.dev/github.com/wandb/cwevals-go">cwevals</a>.<a href="https://pkg.go.dev/github.com/wandb/cwevals-go#EvalTableVersionNewParams">EvalTableVersionNewParams</a>) (\*<a href="https://pkg.go.dev/github.com/wandb/cwevals-go">cwevals</a>.<a href="https://pkg.go.dev/github.com/wandb/cwevals-go#EvalTableVersionNewResponse">EvalTableVersionNewResponse</a>, <a href="https://pkg.go.dev/builtin#error">error</a>)</code>

### Columns

Response Types:

- <a href="https://pkg.go.dev/github.com/wandb/cwevals-go">cwevals</a>.<a href="https://pkg.go.dev/github.com/wandb/cwevals-go#EvalTableVersionColumnGetResponse">EvalTableVersionColumnGetResponse</a>

Methods:

- <code title="get /v1/namespaces/{namespace}/scopes/{scope_id}/eval-table-versions/{evaluation_version_id}/columns">client.EvalTables.Versions.Columns.<a href="https://pkg.go.dev/github.com/wandb/cwevals-go#EvalTableVersionColumnService.Get">Get</a>(ctx <a href="https://pkg.go.dev/context">context</a>.<a href="https://pkg.go.dev/context#Context">Context</a>, evaluationVersionID <a href="https://pkg.go.dev/builtin#string">string</a>, query <a href="https://pkg.go.dev/github.com/wandb/cwevals-go">cwevals</a>.<a href="https://pkg.go.dev/github.com/wandb/cwevals-go#EvalTableVersionColumnGetParams">EvalTableVersionColumnGetParams</a>) (\*<a href="https://pkg.go.dev/github.com/wandb/cwevals-go">cwevals</a>.<a href="https://pkg.go.dev/github.com/wandb/cwevals-go#EvalTableVersionColumnGetResponse">EvalTableVersionColumnGetResponse</a>, <a href="https://pkg.go.dev/builtin#error">error</a>)</code>

### Rows

Response Types:

- <a href="https://pkg.go.dev/github.com/wandb/cwevals-go">cwevals</a>.<a href="https://pkg.go.dev/github.com/wandb/cwevals-go#EvalTableVersionRowListResponse">EvalTableVersionRowListResponse</a>
- <a href="https://pkg.go.dev/github.com/wandb/cwevals-go">cwevals</a>.<a href="https://pkg.go.dev/github.com/wandb/cwevals-go#EvalTableVersionRowSearchResponse">EvalTableVersionRowSearchResponse</a>

Methods:

- <code title="get /v1/namespaces/{namespace}/scopes/{scope_id}/eval-table-versions/{evaluation_version_id}/rows">client.EvalTables.Versions.Rows.<a href="https://pkg.go.dev/github.com/wandb/cwevals-go#EvalTableVersionRowService.List">List</a>(ctx <a href="https://pkg.go.dev/context">context</a>.<a href="https://pkg.go.dev/context#Context">Context</a>, evaluationVersionID <a href="https://pkg.go.dev/builtin#string">string</a>, params <a href="https://pkg.go.dev/github.com/wandb/cwevals-go">cwevals</a>.<a href="https://pkg.go.dev/github.com/wandb/cwevals-go#EvalTableVersionRowListParams">EvalTableVersionRowListParams</a>) (\*<a href="https://pkg.go.dev/github.com/wandb/cwevals-go">cwevals</a>.<a href="https://pkg.go.dev/github.com/wandb/cwevals-go#EvalTableVersionRowListResponse">EvalTableVersionRowListResponse</a>, <a href="https://pkg.go.dev/builtin#error">error</a>)</code>
- <code title="post /v1/namespaces/{namespace}/scopes/{scope_id}/eval-table-versions/{evaluation_version_id}/rows/search">client.EvalTables.Versions.Rows.<a href="https://pkg.go.dev/github.com/wandb/cwevals-go#EvalTableVersionRowService.Search">Search</a>(ctx <a href="https://pkg.go.dev/context">context</a>.<a href="https://pkg.go.dev/context#Context">Context</a>, evaluationVersionID <a href="https://pkg.go.dev/builtin#string">string</a>, params <a href="https://pkg.go.dev/github.com/wandb/cwevals-go">cwevals</a>.<a href="https://pkg.go.dev/github.com/wandb/cwevals-go#EvalTableVersionRowSearchParams">EvalTableVersionRowSearchParams</a>) (\*<a href="https://pkg.go.dev/github.com/wandb/cwevals-go">cwevals</a>.<a href="https://pkg.go.dev/github.com/wandb/cwevals-go#EvalTableVersionRowSearchResponse">EvalTableVersionRowSearchResponse</a>, <a href="https://pkg.go.dev/builtin#error">error</a>)</code>

#### Compare

Response Types:

- <a href="https://pkg.go.dev/github.com/wandb/cwevals-go">cwevals</a>.<a href="https://pkg.go.dev/github.com/wandb/cwevals-go#EvalTableVersionRowCompareListResponse">EvalTableVersionRowCompareListResponse</a>
- <a href="https://pkg.go.dev/github.com/wandb/cwevals-go">cwevals</a>.<a href="https://pkg.go.dev/github.com/wandb/cwevals-go#EvalTableVersionRowCompareSearchResponse">EvalTableVersionRowCompareSearchResponse</a>

Methods:

- <code title="get /v1/namespaces/{namespace}/scopes/{scope_id}/eval-table-versions/{evaluation_version_id}/rows/compare">client.EvalTables.Versions.Rows.Compare.<a href="https://pkg.go.dev/github.com/wandb/cwevals-go#EvalTableVersionRowCompareService.List">List</a>(ctx <a href="https://pkg.go.dev/context">context</a>.<a href="https://pkg.go.dev/context#Context">Context</a>, evaluationVersionID <a href="https://pkg.go.dev/builtin#string">string</a>, params <a href="https://pkg.go.dev/github.com/wandb/cwevals-go">cwevals</a>.<a href="https://pkg.go.dev/github.com/wandb/cwevals-go#EvalTableVersionRowCompareListParams">EvalTableVersionRowCompareListParams</a>) (\*<a href="https://pkg.go.dev/github.com/wandb/cwevals-go">cwevals</a>.<a href="https://pkg.go.dev/github.com/wandb/cwevals-go#EvalTableVersionRowCompareListResponse">EvalTableVersionRowCompareListResponse</a>, <a href="https://pkg.go.dev/builtin#error">error</a>)</code>
- <code title="post /v1/namespaces/{namespace}/scopes/{scope_id}/eval-table-versions/{evaluation_version_id}/rows/compare/search">client.EvalTables.Versions.Rows.Compare.<a href="https://pkg.go.dev/github.com/wandb/cwevals-go#EvalTableVersionRowCompareService.Search">Search</a>(ctx <a href="https://pkg.go.dev/context">context</a>.<a href="https://pkg.go.dev/context#Context">Context</a>, evaluationVersionID <a href="https://pkg.go.dev/builtin#string">string</a>, params <a href="https://pkg.go.dev/github.com/wandb/cwevals-go">cwevals</a>.<a href="https://pkg.go.dev/github.com/wandb/cwevals-go#EvalTableVersionRowCompareSearchParams">EvalTableVersionRowCompareSearchParams</a>) (\*<a href="https://pkg.go.dev/github.com/wandb/cwevals-go">cwevals</a>.<a href="https://pkg.go.dev/github.com/wandb/cwevals-go#EvalTableVersionRowCompareSearchResponse">EvalTableVersionRowCompareSearchResponse</a>, <a href="https://pkg.go.dev/builtin#error">error</a>)</code>
