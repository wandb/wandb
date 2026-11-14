// File generated from our OpenAPI spec by Stainless.

package cwevals

import (
	"context"
	"errors"
	"fmt"
	"net/http"
	"slices"

	"github.com/wandb/cwevals-go/internal/apijson"
	"github.com/wandb/cwevals-go/internal/param"
	"github.com/wandb/cwevals-go/internal/requestconfig"
	"github.com/wandb/cwevals-go/option"
)

// ScoreService contains methods and other services that help with interacting with
// the CoreWeave Evaluations API.
//
// Note, unlike clients, this service does not read variables from the environment
// automatically. You should not instantiate this service directly, and instead use
// the [NewScoreService] method instead.
type ScoreService struct {
	Options []option.RequestOption
}

// NewScoreService generates a new service that applies the given options to each
// request. These options are applied after the parent client's options (if there
// is one), and before any request-specific options.
func NewScoreService(opts ...option.RequestOption) (r *ScoreService) {
	r = &ScoreService{}
	r.Options = opts
	return
}

// Stores score values that your application has calculated for existing targets.
//
//   - Each value must match the referenced scorer version's `value_type`.
//   - Each target must already be published and have a kind allowed by that scorer
//     version.
//   - The response includes `publish_operation_id`, `commit_id`, and `score_ids`.
//     Score IDs follow request order.
//
// Request bodies must be at most 16 MiB. Bodies larger than the limit are rejected
// with 413 Request Entity Too Large.
func (r *ScoreService) New(
	ctx context.Context,
	params ScoreNewParams,
	opts ...option.RequestOption,
) (res *ScoreNewResponse, err error) {
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
	path := fmt.Sprintf("v1/namespaces/%s/scopes/%s/scores", params.Namespace, params.ScopeID)
	err = requestconfig.ExecuteNewRequest(ctx, http.MethodPost, path, params, &res, opts...)
	return res, err
}

// Returns one score published in the requested scope. `value` contains the stored
// value as JSON. `value_type` distinguishes an integer score from a number score.
func (r *ScoreService) Get(
	ctx context.Context,
	scoreID string,
	query ScoreGetParams,
	opts ...option.RequestOption,
) (res *ScoreGetResponse, err error) {
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
	if scoreID == "" {
		err = errors.New("missing required score_id parameter")
		return nil, err
	}
	path := fmt.Sprintf("v1/namespaces/%s/scopes/%s/scores/%s", query.Namespace, query.ScopeID, scoreID)
	err = requestconfig.ExecuteNewRequest(ctx, http.MethodGet, path, nil, &res, opts...)
	return res, err
}

type ScoreNewResponse struct {
	CommitID           int64                `json:"commit_id"            api:"required"`
	PublishOperationID string               `json:"publish_operation_id" api:"required" format:"uuid"`
	ScoreIDs           []string             `json:"score_ids"            api:"required" format:"uuid"`
	JSON               scoreNewResponseJSON `json:"-"`
}

// scoreNewResponseJSON contains the JSON metadata for the struct
// [ScoreNewResponse]
type scoreNewResponseJSON struct {
	CommitID           apijson.Field
	PublishOperationID apijson.Field
	ScoreIDs           apijson.Field
	raw                string
	ExtraFields        map[string]apijson.Field
}

func (r *ScoreNewResponse) UnmarshalJSON(data []byte) (err error) {
	return apijson.UnmarshalRoot(data, r)
}

func (r scoreNewResponseJSON) RawJSON() string {
	return r.raw
}

type ScoreGetResponse struct {
	Attributes map[string]interface{} `json:"attributes" api:"required"`
	CommitID   int64                  `json:"commit_id"  api:"required"`
	// Namespace that assigned the scope reference.
	Namespace       ScoreGetResponseNamespace `json:"namespace"         api:"required"`
	ScopeRef        string                    `json:"scope_ref"         api:"required"`
	ScoreID         string                    `json:"score_id"          api:"required" format:"uuid"`
	ScorerID        string                    `json:"scorer_id"         api:"required" format:"uuid"`
	ScorerVersionID string                    `json:"scorer_version_id" api:"required" format:"uuid"`
	Target          ScoreGetResponseTarget    `json:"target"            api:"required"`
	Value           interface{}               `json:"value"             api:"required"`
	ValueType       ScoreGetResponseValueType `json:"value_type"        api:"required"`
	JSON            scoreGetResponseJSON      `json:"-"`
}

// scoreGetResponseJSON contains the JSON metadata for the struct
// [ScoreGetResponse]
type scoreGetResponseJSON struct {
	Attributes      apijson.Field
	CommitID        apijson.Field
	Namespace       apijson.Field
	ScopeRef        apijson.Field
	ScoreID         apijson.Field
	ScorerID        apijson.Field
	ScorerVersionID apijson.Field
	Target          apijson.Field
	Value           apijson.Field
	ValueType       apijson.Field
	raw             string
	ExtraFields     map[string]apijson.Field
}

func (r *ScoreGetResponse) UnmarshalJSON(data []byte) (err error) {
	return apijson.UnmarshalRoot(data, r)
}

func (r scoreGetResponseJSON) RawJSON() string {
	return r.raw
}

// Namespace that assigned the scope reference.
type ScoreGetResponseNamespace string

const (
	ScoreGetResponseNamespaceWandb ScoreGetResponseNamespace = "wandb"
)

func (r ScoreGetResponseNamespace) IsKnown() bool {
	switch r {
	case ScoreGetResponseNamespaceWandb:
		return true
	}
	return false
}

type ScoreGetResponseTarget struct {
	// ID of the published case, comparison, or trajectory selected by kind.
	ID string `json:"id" api:"required" format:"uuid"`
	// Kind of resource being scored.
	Kind ScoreGetResponseTargetKind `json:"kind" api:"required"`
	JSON scoreGetResponseTargetJSON `json:"-"`
}

// scoreGetResponseTargetJSON contains the JSON metadata for the struct
// [ScoreGetResponseTarget]
type scoreGetResponseTargetJSON struct {
	ID          apijson.Field
	Kind        apijson.Field
	raw         string
	ExtraFields map[string]apijson.Field
}

func (r *ScoreGetResponseTarget) UnmarshalJSON(data []byte) (err error) {
	return apijson.UnmarshalRoot(data, r)
}

func (r scoreGetResponseTargetJSON) RawJSON() string {
	return r.raw
}

// Kind of resource being scored.
type ScoreGetResponseTargetKind string

const (
	ScoreGetResponseTargetKindCase       ScoreGetResponseTargetKind = "case"
	ScoreGetResponseTargetKindComparison ScoreGetResponseTargetKind = "comparison"
	ScoreGetResponseTargetKindTrajectory ScoreGetResponseTargetKind = "trajectory"
)

func (r ScoreGetResponseTargetKind) IsKnown() bool {
	switch r {
	case ScoreGetResponseTargetKindCase, ScoreGetResponseTargetKindComparison, ScoreGetResponseTargetKindTrajectory:
		return true
	}
	return false
}

type ScoreGetResponseValueType string

const (
	ScoreGetResponseValueTypeNull    ScoreGetResponseValueType = "null"
	ScoreGetResponseValueTypeBoolean ScoreGetResponseValueType = "boolean"
	ScoreGetResponseValueTypeInteger ScoreGetResponseValueType = "integer"
	ScoreGetResponseValueTypeNumber  ScoreGetResponseValueType = "number"
	ScoreGetResponseValueTypeString  ScoreGetResponseValueType = "string"
	ScoreGetResponseValueTypeJson    ScoreGetResponseValueType = "json"
)

func (r ScoreGetResponseValueType) IsKnown() bool {
	switch r {
	case ScoreGetResponseValueTypeNull,
		ScoreGetResponseValueTypeBoolean,
		ScoreGetResponseValueTypeInteger,
		ScoreGetResponseValueTypeNumber,
		ScoreGetResponseValueTypeString,
		ScoreGetResponseValueTypeJson:
		return true
	}
	return false
}

type ScoreNewParams struct {
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
	ScopeID param.Field[string]                `path:"scope_id" api:"required"`
	Scores  param.Field[[]ScoreNewParamsScore] `                api:"required" json:"scores"`
}

func (r ScoreNewParams) MarshalJSON() (data []byte, err error) {
	return apijson.MarshalRoot(r)
}

type ScoreNewParamsScore struct {
	ScorerID        param.Field[string]                     `json:"scorer_id"         api:"required" format:"uuid"`
	ScorerVersionID param.Field[string]                     `json:"scorer_version_id" api:"required" format:"uuid"`
	Target          param.Field[ScoreNewParamsScoresTarget] `json:"target"            api:"required"`
	// Score calculated by your application. Its JSON type must match the referenced
	// scorer version's value_type.
	Value      param.Field[interface{}]            `json:"value"      api:"required"`
	Attributes param.Field[map[string]interface{}] `json:"attributes"`
}

func (r ScoreNewParamsScore) MarshalJSON() (data []byte, err error) {
	return apijson.MarshalRoot(r)
}

type ScoreNewParamsScoresTarget struct {
	// ID of the published case, comparison, or trajectory selected by kind.
	ID param.Field[string] `json:"id" api:"required" format:"uuid"`
	// Kind of resource being scored.
	Kind param.Field[ScoreNewParamsScoresTargetKind] `json:"kind" api:"required"`
}

func (r ScoreNewParamsScoresTarget) MarshalJSON() (data []byte, err error) {
	return apijson.MarshalRoot(r)
}

// Kind of resource being scored.
type ScoreNewParamsScoresTargetKind string

const (
	ScoreNewParamsScoresTargetKindCase       ScoreNewParamsScoresTargetKind = "case"
	ScoreNewParamsScoresTargetKindComparison ScoreNewParamsScoresTargetKind = "comparison"
	ScoreNewParamsScoresTargetKindTrajectory ScoreNewParamsScoresTargetKind = "trajectory"
)

func (r ScoreNewParamsScoresTargetKind) IsKnown() bool {
	switch r {
	case ScoreNewParamsScoresTargetKindCase,
		ScoreNewParamsScoresTargetKindComparison,
		ScoreNewParamsScoresTargetKindTrajectory:
		return true
	}
	return false
}

type ScoreGetParams struct {
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
