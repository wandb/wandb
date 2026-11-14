// File generated from our OpenAPI spec by Stainless.

package cwevals

import (
	"context"
	"errors"
	"fmt"
	"net/http"
	"net/url"
	"slices"

	"github.com/wandb/cwevals-go/internal/apijson"
	"github.com/wandb/cwevals-go/internal/apiquery"
	"github.com/wandb/cwevals-go/internal/param"
	"github.com/wandb/cwevals-go/internal/requestconfig"
	"github.com/wandb/cwevals-go/option"
)

// EvaluationVersionService contains methods and other services that help with
// interacting with the CoreWeave Evaluations API.
//
// Note, unlike clients, this service does not read variables from the environment
// automatically. You should not instantiate this service directly, and instead use
// the [NewEvaluationVersionService] method instead.
type EvaluationVersionService struct {
	Options []option.RequestOption
	Metrics *EvaluationVersionMetricService
	Results *EvaluationVersionResultService
	Queries *EvaluationVersionQueryService
	Rows    *EvaluationVersionRowService
}

// NewEvaluationVersionService generates a new service that applies the given
// options to each request. These options are applied after the parent client's
// options (if there is one), and before any request-specific options.
func NewEvaluationVersionService(opts ...option.RequestOption) (r *EvaluationVersionService) {
	r = &EvaluationVersionService{}
	r.Options = opts
	r.Metrics = NewEvaluationVersionMetricService(opts...)
	r.Results = NewEvaluationVersionResultService(opts...)
	r.Queries = NewEvaluationVersionQueryService(opts...)
	r.Rows = NewEvaluationVersionRowService(opts...)
	return
}

// Creates an immutable snapshot of one dataset version and the evaluation's
// currently registered scorer versions. The snapshot also records a publication
// cutoff for scores and reported metrics.
//
// Later writes do not change the frozen results.
//
// Request bodies must be at most 1 MiB. Bodies larger than the limit are rejected
// with 413 Request Entity Too Large.
func (r *EvaluationVersionService) New(
	ctx context.Context,
	evaluationID string,
	params EvaluationVersionNewParams,
	opts ...option.RequestOption,
) (res *EvaluationVersionNewResponse, err error) {
	opts = slices.Concat(r.Options, opts)
	precfg, err := requestconfig.PreRequestOptions(opts...)
	if err != nil {
		return nil, err
	}
	requestconfig.UseDefaultParam(&params.Namespace, precfg.Namespace)
	requestconfig.UseDefaultParam(&params.ScopeID, precfg.ScopeID)
	if params.Namespace.Value == "" {
		err = errors.New("missing required namespace parameter")
		return nil, err
	}
	if params.ScopeID.Value == "" {
		err = errors.New("missing required scope_id parameter")
		return nil, err
	}
	if evaluationID == "" {
		err = errors.New("missing required evaluation_id parameter")
		return nil, err
	}
	path := fmt.Sprintf(
		"v1/namespaces/%s/scopes/%s/evaluations/%s/versions",
		params.Namespace,
		params.ScopeID,
		evaluationID,
	)
	err = requestconfig.ExecuteNewRequest(ctx, http.MethodPost, path, params, &res, opts...)
	return res, err
}

// Returns published evaluation versions in publication order, with the same fields
// as the get-version operation. An evaluation that does not exist or is outside
// the requested scope returns 404.
func (r *EvaluationVersionService) List(
	ctx context.Context,
	evaluationID string,
	params EvaluationVersionListParams,
	opts ...option.RequestOption,
) (res *EvaluationVersionListResponse, err error) {
	opts = slices.Concat(r.Options, opts)
	precfg, err := requestconfig.PreRequestOptions(opts...)
	if err != nil {
		return nil, err
	}
	requestconfig.UseDefaultParam(&params.Namespace, precfg.Namespace)
	requestconfig.UseDefaultParam(&params.ScopeID, precfg.ScopeID)
	if params.Namespace.Value == "" {
		err = errors.New("missing required namespace parameter")
		return nil, err
	}
	if params.ScopeID.Value == "" {
		err = errors.New("missing required scope_id parameter")
		return nil, err
	}
	if evaluationID == "" {
		err = errors.New("missing required evaluation_id parameter")
		return nil, err
	}
	path := fmt.Sprintf(
		"v1/namespaces/%s/scopes/%s/evaluations/%s/versions",
		params.Namespace,
		params.ScopeID,
		evaluationID,
	)
	err = requestconfig.ExecuteNewRequest(ctx, http.MethodGet, path, params, &res, opts...)
	return res, err
}

// Returns the frozen evaluation snapshot exactly as created, including its dataset
// version, selected scorer versions, and publication cutoff.
func (r *EvaluationVersionService) Get(
	ctx context.Context,
	evaluationVersionID string,
	query EvaluationVersionGetParams,
	opts ...option.RequestOption,
) (res *EvaluationVersionGetResponse, err error) {
	opts = slices.Concat(r.Options, opts)
	precfg, err := requestconfig.PreRequestOptions(opts...)
	if err != nil {
		return nil, err
	}
	requestconfig.UseDefaultParam(&query.Namespace, precfg.Namespace)
	requestconfig.UseDefaultParam(&query.ScopeID, precfg.ScopeID)
	if query.Namespace.Value == "" {
		err = errors.New("missing required namespace parameter")
		return nil, err
	}
	if query.ScopeID.Value == "" {
		err = errors.New("missing required scope_id parameter")
		return nil, err
	}
	if evaluationVersionID == "" {
		err = errors.New("missing required evaluation_version_id parameter")
		return nil, err
	}
	path := fmt.Sprintf(
		"v1/namespaces/%s/scopes/%s/evaluation-versions/%s",
		query.Namespace,
		query.ScopeID,
		evaluationVersionID,
	)
	err = requestconfig.ExecuteNewRequest(ctx, http.MethodGet, path, nil, &res, opts...)
	return res, err
}

type EvaluationVersionNewResponse struct {
	DatasetID           string `json:"dataset_id"            api:"required" format:"uuid"`
	DatasetVersionID    string `json:"dataset_version_id"    api:"required" format:"uuid"`
	EvaluationID        string `json:"evaluation_id"         api:"required" format:"uuid"`
	EvaluationVersionID string `json:"evaluation_version_id" api:"required" format:"uuid"`
	// Last published write visible to this snapshot. Scores and reported metrics
	// published later are excluded.
	LastCommitID int64 `json:"last_commit_id" api:"required"`
	// Namespace that assigned the scope reference.
	Namespace         EvaluationVersionNewResponseNamespace         `json:"namespace"           api:"required"`
	PrimaryTargetKind EvaluationVersionNewResponsePrimaryTargetKind `json:"primary_target_kind" api:"required"`
	ScopeRef          string                                        `json:"scope_ref"           api:"required"`
	// Scorer versions selected for this snapshot, in the order used by result
	// responses.
	Scorers []EvaluationVersionNewResponseScorer `json:"scorers" api:"required"`
	JSON    evaluationVersionNewResponseJSON     `json:"-"`
}

// evaluationVersionNewResponseJSON contains the JSON metadata for the struct
// [EvaluationVersionNewResponse]
type evaluationVersionNewResponseJSON struct {
	DatasetID           apijson.Field
	DatasetVersionID    apijson.Field
	EvaluationID        apijson.Field
	EvaluationVersionID apijson.Field
	LastCommitID        apijson.Field
	Namespace           apijson.Field
	PrimaryTargetKind   apijson.Field
	ScopeRef            apijson.Field
	Scorers             apijson.Field
	raw                 string
	ExtraFields         map[string]apijson.Field
}

func (r *EvaluationVersionNewResponse) UnmarshalJSON(data []byte) (err error) {
	return apijson.UnmarshalRoot(data, r)
}

func (r evaluationVersionNewResponseJSON) RawJSON() string {
	return r.raw
}

// Namespace that assigned the scope reference.
type EvaluationVersionNewResponseNamespace string

const (
	EvaluationVersionNewResponseNamespaceWandb EvaluationVersionNewResponseNamespace = "wandb"
)

func (r EvaluationVersionNewResponseNamespace) IsKnown() bool {
	switch r {
	case EvaluationVersionNewResponseNamespaceWandb:
		return true
	}
	return false
}

type EvaluationVersionNewResponsePrimaryTargetKind string

const (
	EvaluationVersionNewResponsePrimaryTargetKindCase       EvaluationVersionNewResponsePrimaryTargetKind = "case"
	EvaluationVersionNewResponsePrimaryTargetKindTrajectory EvaluationVersionNewResponsePrimaryTargetKind = "trajectory"
)

func (r EvaluationVersionNewResponsePrimaryTargetKind) IsKnown() bool {
	switch r {
	case EvaluationVersionNewResponsePrimaryTargetKindCase, EvaluationVersionNewResponsePrimaryTargetKindTrajectory:
		return true
	}
	return false
}

type EvaluationVersionNewResponseScorer struct {
	ScorerID  string                                 `json:"scorer_id"  api:"required" format:"uuid"`
	VersionID string                                 `json:"version_id" api:"required" format:"uuid"`
	JSON      evaluationVersionNewResponseScorerJSON `json:"-"`
}

// evaluationVersionNewResponseScorerJSON contains the JSON metadata for the struct
// [EvaluationVersionNewResponseScorer]
type evaluationVersionNewResponseScorerJSON struct {
	ScorerID    apijson.Field
	VersionID   apijson.Field
	raw         string
	ExtraFields map[string]apijson.Field
}

func (r *EvaluationVersionNewResponseScorer) UnmarshalJSON(data []byte) (err error) {
	return apijson.UnmarshalRoot(data, r)
}

func (r evaluationVersionNewResponseScorerJSON) RawJSON() string {
	return r.raw
}

type EvaluationVersionListResponse struct {
	Results    []EvaluationVersionListResponseResult `json:"results"     api:"required"`
	NextCursor string                                `json:"next_cursor"`
	JSON       evaluationVersionListResponseJSON     `json:"-"`
}

// evaluationVersionListResponseJSON contains the JSON metadata for the struct
// [EvaluationVersionListResponse]
type evaluationVersionListResponseJSON struct {
	Results     apijson.Field
	NextCursor  apijson.Field
	raw         string
	ExtraFields map[string]apijson.Field
}

func (r *EvaluationVersionListResponse) UnmarshalJSON(data []byte) (err error) {
	return apijson.UnmarshalRoot(data, r)
}

func (r evaluationVersionListResponseJSON) RawJSON() string {
	return r.raw
}

type EvaluationVersionListResponseResult struct {
	DatasetID           string `json:"dataset_id"            api:"required" format:"uuid"`
	DatasetVersionID    string `json:"dataset_version_id"    api:"required" format:"uuid"`
	EvaluationID        string `json:"evaluation_id"         api:"required" format:"uuid"`
	EvaluationVersionID string `json:"evaluation_version_id" api:"required" format:"uuid"`
	// Last published write visible to this snapshot. Scores and reported metrics
	// published later are excluded.
	LastCommitID int64 `json:"last_commit_id" api:"required"`
	// Namespace that assigned the scope reference.
	Namespace         EvaluationVersionListResponseResultsNamespace         `json:"namespace"           api:"required"`
	PrimaryTargetKind EvaluationVersionListResponseResultsPrimaryTargetKind `json:"primary_target_kind" api:"required"`
	ScopeRef          string                                                `json:"scope_ref"           api:"required"`
	// Scorer versions selected for this snapshot, in the order used by result
	// responses.
	Scorers []EvaluationVersionListResponseResultsScorer `json:"scorers" api:"required"`
	JSON    evaluationVersionListResponseResultJSON      `json:"-"`
}

// evaluationVersionListResponseResultJSON contains the JSON metadata for the
// struct [EvaluationVersionListResponseResult]
type evaluationVersionListResponseResultJSON struct {
	DatasetID           apijson.Field
	DatasetVersionID    apijson.Field
	EvaluationID        apijson.Field
	EvaluationVersionID apijson.Field
	LastCommitID        apijson.Field
	Namespace           apijson.Field
	PrimaryTargetKind   apijson.Field
	ScopeRef            apijson.Field
	Scorers             apijson.Field
	raw                 string
	ExtraFields         map[string]apijson.Field
}

func (r *EvaluationVersionListResponseResult) UnmarshalJSON(data []byte) (err error) {
	return apijson.UnmarshalRoot(data, r)
}

func (r evaluationVersionListResponseResultJSON) RawJSON() string {
	return r.raw
}

// Namespace that assigned the scope reference.
type EvaluationVersionListResponseResultsNamespace string

const (
	EvaluationVersionListResponseResultsNamespaceWandb EvaluationVersionListResponseResultsNamespace = "wandb"
)

func (r EvaluationVersionListResponseResultsNamespace) IsKnown() bool {
	switch r {
	case EvaluationVersionListResponseResultsNamespaceWandb:
		return true
	}
	return false
}

type EvaluationVersionListResponseResultsPrimaryTargetKind string

const (
	EvaluationVersionListResponseResultsPrimaryTargetKindCase       EvaluationVersionListResponseResultsPrimaryTargetKind = "case"
	EvaluationVersionListResponseResultsPrimaryTargetKindTrajectory EvaluationVersionListResponseResultsPrimaryTargetKind = "trajectory"
)

func (r EvaluationVersionListResponseResultsPrimaryTargetKind) IsKnown() bool {
	switch r {
	case EvaluationVersionListResponseResultsPrimaryTargetKindCase,
		EvaluationVersionListResponseResultsPrimaryTargetKindTrajectory:
		return true
	}
	return false
}

type EvaluationVersionListResponseResultsScorer struct {
	ScorerID  string                                         `json:"scorer_id"  api:"required" format:"uuid"`
	VersionID string                                         `json:"version_id" api:"required" format:"uuid"`
	JSON      evaluationVersionListResponseResultsScorerJSON `json:"-"`
}

// evaluationVersionListResponseResultsScorerJSON contains the JSON metadata for
// the struct [EvaluationVersionListResponseResultsScorer]
type evaluationVersionListResponseResultsScorerJSON struct {
	ScorerID    apijson.Field
	VersionID   apijson.Field
	raw         string
	ExtraFields map[string]apijson.Field
}

func (r *EvaluationVersionListResponseResultsScorer) UnmarshalJSON(data []byte) (err error) {
	return apijson.UnmarshalRoot(data, r)
}

func (r evaluationVersionListResponseResultsScorerJSON) RawJSON() string {
	return r.raw
}

type EvaluationVersionGetResponse struct {
	DatasetID           string `json:"dataset_id"            api:"required" format:"uuid"`
	DatasetVersionID    string `json:"dataset_version_id"    api:"required" format:"uuid"`
	EvaluationID        string `json:"evaluation_id"         api:"required" format:"uuid"`
	EvaluationVersionID string `json:"evaluation_version_id" api:"required" format:"uuid"`
	// Last published write visible to this snapshot. Scores and reported metrics
	// published later are excluded.
	LastCommitID int64 `json:"last_commit_id" api:"required"`
	// Namespace that assigned the scope reference.
	Namespace         EvaluationVersionGetResponseNamespace         `json:"namespace"           api:"required"`
	PrimaryTargetKind EvaluationVersionGetResponsePrimaryTargetKind `json:"primary_target_kind" api:"required"`
	ScopeRef          string                                        `json:"scope_ref"           api:"required"`
	// Scorer versions selected for this snapshot, in the order used by result
	// responses.
	Scorers []EvaluationVersionGetResponseScorer `json:"scorers" api:"required"`
	JSON    evaluationVersionGetResponseJSON     `json:"-"`
}

// evaluationVersionGetResponseJSON contains the JSON metadata for the struct
// [EvaluationVersionGetResponse]
type evaluationVersionGetResponseJSON struct {
	DatasetID           apijson.Field
	DatasetVersionID    apijson.Field
	EvaluationID        apijson.Field
	EvaluationVersionID apijson.Field
	LastCommitID        apijson.Field
	Namespace           apijson.Field
	PrimaryTargetKind   apijson.Field
	ScopeRef            apijson.Field
	Scorers             apijson.Field
	raw                 string
	ExtraFields         map[string]apijson.Field
}

func (r *EvaluationVersionGetResponse) UnmarshalJSON(data []byte) (err error) {
	return apijson.UnmarshalRoot(data, r)
}

func (r evaluationVersionGetResponseJSON) RawJSON() string {
	return r.raw
}

// Namespace that assigned the scope reference.
type EvaluationVersionGetResponseNamespace string

const (
	EvaluationVersionGetResponseNamespaceWandb EvaluationVersionGetResponseNamespace = "wandb"
)

func (r EvaluationVersionGetResponseNamespace) IsKnown() bool {
	switch r {
	case EvaluationVersionGetResponseNamespaceWandb:
		return true
	}
	return false
}

type EvaluationVersionGetResponsePrimaryTargetKind string

const (
	EvaluationVersionGetResponsePrimaryTargetKindCase       EvaluationVersionGetResponsePrimaryTargetKind = "case"
	EvaluationVersionGetResponsePrimaryTargetKindTrajectory EvaluationVersionGetResponsePrimaryTargetKind = "trajectory"
)

func (r EvaluationVersionGetResponsePrimaryTargetKind) IsKnown() bool {
	switch r {
	case EvaluationVersionGetResponsePrimaryTargetKindCase, EvaluationVersionGetResponsePrimaryTargetKindTrajectory:
		return true
	}
	return false
}

type EvaluationVersionGetResponseScorer struct {
	ScorerID  string                                 `json:"scorer_id"  api:"required" format:"uuid"`
	VersionID string                                 `json:"version_id" api:"required" format:"uuid"`
	JSON      evaluationVersionGetResponseScorerJSON `json:"-"`
}

// evaluationVersionGetResponseScorerJSON contains the JSON metadata for the struct
// [EvaluationVersionGetResponseScorer]
type evaluationVersionGetResponseScorerJSON struct {
	ScorerID    apijson.Field
	VersionID   apijson.Field
	raw         string
	ExtraFields map[string]apijson.Field
}

func (r *EvaluationVersionGetResponseScorer) UnmarshalJSON(data []byte) (err error) {
	return apijson.UnmarshalRoot(data, r)
}

func (r evaluationVersionGetResponseScorerJSON) RawJSON() string {
	return r.raw
}

type EvaluationVersionNewParams struct {
	// Namespace that assigned the scope reference.
	//
	// Defaults to "wandb" if not set.
	Namespace param.Field[string] `path:"namespace" api:"required"`
	// Project reference assigned by the namespace. For wandb, use the internal W&B
	// project ID, not the project name or entity/project path.
	//
	// Percent-encode reserved characters so the reference occupies one URL path
	// segment. Only printable ASCII is accepted. References are compared exactly,
	// without parsing.
	//
	// Use [option.WithScopeID] on the client to set a global default for this field.
	ScopeID param.Field[string] `path:"scope_id" api:"required"`
	// Dataset version to freeze in the evaluation snapshot.
	//
	//   - For a fixed evaluation, omit this field or supply its configured dataset
	//     version ID.
	//   - For a live evaluation, supply a dataset version ID, or omit the field to
	//     publish the dataset's head and use it. Supplying the head's ID also publishes
	//     it.
	DatasetVersionID param.Field[string] `json:"dataset_version_id" format:"uuid"`
}

func (r EvaluationVersionNewParams) MarshalJSON() (data []byte, err error) {
	return apijson.MarshalRoot(r)
}

type EvaluationVersionListParams struct {
	// Namespace that assigned the scope reference.
	//
	// Defaults to "wandb" if not set.
	Namespace param.Field[string] `path:"namespace" api:"required"`
	// Project reference assigned by the namespace. For wandb, use the internal W&B
	// project ID, not the project name or entity/project path.
	//
	// Percent-encode reserved characters so the reference occupies one URL path
	// segment. Only printable ASCII is accepted. References are compared exactly,
	// without parsing.
	//
	// Use [option.WithScopeID] on the client to set a global default for this field.
	ScopeID param.Field[string] `path:"scope_id" api:"required"`
	// Cursor from the previous page's next_cursor. Omit for the first page.
	Cursor param.Field[string] `query:"cursor"`
	Limit  param.Field[int64]  `query:"limit"`
}

// URLQuery serializes [EvaluationVersionListParams]'s query parameters as
// `url.Values`.
func (r EvaluationVersionListParams) URLQuery() (v url.Values) {
	return apiquery.MarshalWithSettings(r, apiquery.QuerySettings{
		ArrayFormat:  apiquery.ArrayQueryFormatComma,
		NestedFormat: apiquery.NestedQueryFormatBrackets,
	})
}

type EvaluationVersionGetParams struct {
	// Namespace that assigned the scope reference.
	//
	// Defaults to "wandb" if not set.
	Namespace param.Field[string] `path:"namespace" api:"required"`
	// Project reference assigned by the namespace. For wandb, use the internal W&B
	// project ID, not the project name or entity/project path.
	//
	// Percent-encode reserved characters so the reference occupies one URL path
	// segment. Only printable ASCII is accepted. References are compared exactly,
	// without parsing.
	//
	// Use [option.WithScopeID] on the client to set a global default for this field.
	ScopeID param.Field[string] `path:"scope_id" api:"required"`
}
