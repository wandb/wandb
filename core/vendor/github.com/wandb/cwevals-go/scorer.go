// File generated from our OpenAPI spec by Stainless.

package cwevals

import (
	"context"
	"errors"
	"fmt"
	"net/http"
	"net/url"
	"slices"
	"time"

	"github.com/wandb/cwevals-go/internal/apijson"
	"github.com/wandb/cwevals-go/internal/apiquery"
	"github.com/wandb/cwevals-go/internal/param"
	"github.com/wandb/cwevals-go/internal/requestconfig"
	"github.com/wandb/cwevals-go/option"
)

// ScorerService contains methods and other services that help with interacting
// with the CoreWeave Evaluations API.
//
// Note, unlike clients, this service does not read variables from the environment
// automatically. You should not instantiate this service directly, and instead use
// the [NewScorerService] method instead.
type ScorerService struct {
	Options  []option.RequestOption
	Versions *ScorerVersionService
}

// NewScorerService generates a new service that applies the given options to each
// request. These options are applied after the parent client's options (if there
// is one), and before any request-specific options.
func NewScorerService(opts ...option.RequestOption) (r *ScorerService) {
	r = &ScorerService{}
	r.Options = opts
	r.Versions = NewScorerVersionService(opts...)
	return
}

// Creates a stable scorer identity and its first immutable version. The version
// defines the scorer name, score value type, and allowed target kinds.
//
// This operation records the scorer's specification. Your application calculates
// score values and submits them through the scores API.
//
// Request bodies must be at most 1 MiB. Bodies larger than the limit are rejected
// with 413 Request Entity Too Large.
func (r *ScorerService) New(
	ctx context.Context,
	params ScorerNewParams,
	opts ...option.RequestOption,
) (res *ScorerNewResponse, err error) {
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
	path := fmt.Sprintf("v1/namespaces/%s/scopes/%s/scorers", params.Namespace, params.ScopeID)
	err = requestconfig.ExecuteNewRequest(ctx, http.MethodPost, path, params, &res, opts...)
	return res, err
}

// Returns one page of the scope's Scorers.
func (r *ScorerService) List(
	ctx context.Context,
	params ScorerListParams,
	opts ...option.RequestOption,
) (res *ScorerListResponse, err error) {
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
	path := fmt.Sprintf("v1/namespaces/%s/scopes/%s/scorers", params.Namespace, params.ScopeID)
	err = requestconfig.ExecuteNewRequest(ctx, http.MethodGet, path, params, &res, opts...)
	return res, err
}

// Soft-deletes the Scorer. It and its ScorerVersions then return 404 and leave
// list-scorers, and new versions and Scores for it are rejected with 404. A Scorer
// that an Evaluation's unpublished head still selects returns 409 resource_in_use.
// Delete that Evaluation first. Published EvaluationVersions that selected it, and
// Scores already written, are unchanged. An absent or already deleted Scorer
// returns 404. A retry with the same Idempotency-Key replays the first response.
func (r *ScorerService) Delete(
	ctx context.Context,
	scorerID string,
	body ScorerDeleteParams,
	opts ...option.RequestOption,
) (err error) {
	opts = slices.Concat(r.Options, opts)
	opts = append([]option.RequestOption{option.WithHeader("Accept", "*/*")}, opts...)
	precfg, err := requestconfig.PreRequestOptions(opts...)
	if err != nil {
		return err
	}
	requestconfig.UseDefaultParam(&body.Namespace, precfg.Namespace)
	requestconfig.UseDefaultParam(&body.ScopeID, precfg.ScopeID)
	if body.Namespace.Value == "" {
		err = errors.New("missing required namespace parameter")
		return err
	}
	if body.ScopeID.Value == "" {
		err = errors.New("missing required scope_id parameter")
		return err
	}
	if scorerID == "" {
		err = errors.New("missing required scorer_id parameter")
		return err
	}
	path := fmt.Sprintf("v1/namespaces/%s/scopes/%s/scorers/%s", body.Namespace, body.ScopeID, scorerID)
	err = requestconfig.ExecuteNewRequest(ctx, http.MethodDelete, path, nil, nil, opts...)
	return err
}

// Returns the scorer's stable ID and creation time. To read its name, score type,
// and allowed targets, get a specific scorer version.
func (r *ScorerService) Get(
	ctx context.Context,
	scorerID string,
	query ScorerGetParams,
	opts ...option.RequestOption,
) (res *ScorerGetResponse, err error) {
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
	if scorerID == "" {
		err = errors.New("missing required scorer_id parameter")
		return nil, err
	}
	path := fmt.Sprintf("v1/namespaces/%s/scopes/%s/scorers/%s", query.Namespace, query.ScopeID, scorerID)
	err = requestconfig.ExecuteNewRequest(ctx, http.MethodGet, path, nil, &res, opts...)
	return res, err
}

type ScorerNewResponse struct {
	AllowedTargetKinds []ScorerNewResponseAllowedTargetKind `json:"allowed_target_kinds" api:"required"`
	Description        string                               `json:"description"          api:"required,nullable"`
	Name               string                               `json:"name"                 api:"required"`
	// Namespace that assigned the scope reference.
	Namespace ScorerNewResponseNamespace `json:"namespace"  api:"required"`
	ScopeRef  string                     `json:"scope_ref"  api:"required"`
	ScorerID  string                     `json:"scorer_id"  api:"required" format:"uuid"`
	ValueType ScorerNewResponseValueType `json:"value_type" api:"required"`
	VersionID string                     `json:"version_id" api:"required" format:"uuid"`
	JSON      scorerNewResponseJSON      `json:"-"`
}

// scorerNewResponseJSON contains the JSON metadata for the struct
// [ScorerNewResponse]
type scorerNewResponseJSON struct {
	AllowedTargetKinds apijson.Field
	Description        apijson.Field
	Name               apijson.Field
	Namespace          apijson.Field
	ScopeRef           apijson.Field
	ScorerID           apijson.Field
	ValueType          apijson.Field
	VersionID          apijson.Field
	raw                string
	ExtraFields        map[string]apijson.Field
}

func (r *ScorerNewResponse) UnmarshalJSON(data []byte) (err error) {
	return apijson.UnmarshalRoot(data, r)
}

func (r scorerNewResponseJSON) RawJSON() string {
	return r.raw
}

type ScorerNewResponseAllowedTargetKind string

const (
	ScorerNewResponseAllowedTargetKindCase       ScorerNewResponseAllowedTargetKind = "case"
	ScorerNewResponseAllowedTargetKindComparison ScorerNewResponseAllowedTargetKind = "comparison"
	ScorerNewResponseAllowedTargetKindTrajectory ScorerNewResponseAllowedTargetKind = "trajectory"
)

func (r ScorerNewResponseAllowedTargetKind) IsKnown() bool {
	switch r {
	case ScorerNewResponseAllowedTargetKindCase,
		ScorerNewResponseAllowedTargetKindComparison,
		ScorerNewResponseAllowedTargetKindTrajectory:
		return true
	}
	return false
}

// Namespace that assigned the scope reference.
type ScorerNewResponseNamespace string

const (
	ScorerNewResponseNamespaceWandb ScorerNewResponseNamespace = "wandb"
)

func (r ScorerNewResponseNamespace) IsKnown() bool {
	switch r {
	case ScorerNewResponseNamespaceWandb:
		return true
	}
	return false
}

type ScorerNewResponseValueType string

const (
	ScorerNewResponseValueTypeNull    ScorerNewResponseValueType = "null"
	ScorerNewResponseValueTypeBoolean ScorerNewResponseValueType = "boolean"
	ScorerNewResponseValueTypeInteger ScorerNewResponseValueType = "integer"
	ScorerNewResponseValueTypeNumber  ScorerNewResponseValueType = "number"
	ScorerNewResponseValueTypeString  ScorerNewResponseValueType = "string"
	ScorerNewResponseValueTypeJson    ScorerNewResponseValueType = "json"
)

func (r ScorerNewResponseValueType) IsKnown() bool {
	switch r {
	case ScorerNewResponseValueTypeNull,
		ScorerNewResponseValueTypeBoolean,
		ScorerNewResponseValueTypeInteger,
		ScorerNewResponseValueTypeNumber,
		ScorerNewResponseValueTypeString,
		ScorerNewResponseValueTypeJson:
		return true
	}
	return false
}

type ScorerListResponse struct {
	Results    []ScorerListResponseResult `json:"results"     api:"required"`
	NextCursor string                     `json:"next_cursor"`
	JSON       scorerListResponseJSON     `json:"-"`
}

// scorerListResponseJSON contains the JSON metadata for the struct
// [ScorerListResponse]
type scorerListResponseJSON struct {
	Results     apijson.Field
	NextCursor  apijson.Field
	raw         string
	ExtraFields map[string]apijson.Field
}

func (r *ScorerListResponse) UnmarshalJSON(data []byte) (err error) {
	return apijson.UnmarshalRoot(data, r)
}

func (r scorerListResponseJSON) RawJSON() string {
	return r.raw
}

type ScorerListResponseResult struct {
	CreatedAt time.Time `json:"created_at" api:"required" format:"date-time"`
	// Namespace that assigned the scope reference.
	Namespace ScorerListResponseResultsNamespace `json:"namespace" api:"required"`
	ScopeRef  string                             `json:"scope_ref" api:"required"`
	ScorerID  string                             `json:"scorer_id" api:"required" format:"uuid"`
	JSON      scorerListResponseResultJSON       `json:"-"`
}

// scorerListResponseResultJSON contains the JSON metadata for the struct
// [ScorerListResponseResult]
type scorerListResponseResultJSON struct {
	CreatedAt   apijson.Field
	Namespace   apijson.Field
	ScopeRef    apijson.Field
	ScorerID    apijson.Field
	raw         string
	ExtraFields map[string]apijson.Field
}

func (r *ScorerListResponseResult) UnmarshalJSON(data []byte) (err error) {
	return apijson.UnmarshalRoot(data, r)
}

func (r scorerListResponseResultJSON) RawJSON() string {
	return r.raw
}

// Namespace that assigned the scope reference.
type ScorerListResponseResultsNamespace string

const (
	ScorerListResponseResultsNamespaceWandb ScorerListResponseResultsNamespace = "wandb"
)

func (r ScorerListResponseResultsNamespace) IsKnown() bool {
	switch r {
	case ScorerListResponseResultsNamespaceWandb:
		return true
	}
	return false
}

type ScorerGetResponse struct {
	CreatedAt time.Time `json:"created_at" api:"required" format:"date-time"`
	// Namespace that assigned the scope reference.
	Namespace ScorerGetResponseNamespace `json:"namespace" api:"required"`
	ScopeRef  string                     `json:"scope_ref" api:"required"`
	ScorerID  string                     `json:"scorer_id" api:"required" format:"uuid"`
	JSON      scorerGetResponseJSON      `json:"-"`
}

// scorerGetResponseJSON contains the JSON metadata for the struct
// [ScorerGetResponse]
type scorerGetResponseJSON struct {
	CreatedAt   apijson.Field
	Namespace   apijson.Field
	ScopeRef    apijson.Field
	ScorerID    apijson.Field
	raw         string
	ExtraFields map[string]apijson.Field
}

func (r *ScorerGetResponse) UnmarshalJSON(data []byte) (err error) {
	return apijson.UnmarshalRoot(data, r)
}

func (r scorerGetResponseJSON) RawJSON() string {
	return r.raw
}

// Namespace that assigned the scope reference.
type ScorerGetResponseNamespace string

const (
	ScorerGetResponseNamespaceWandb ScorerGetResponseNamespace = "wandb"
)

func (r ScorerGetResponseNamespace) IsKnown() bool {
	switch r {
	case ScorerGetResponseNamespaceWandb:
		return true
	}
	return false
}

type ScorerNewParams struct {
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
	// Kinds of resource this scorer version can score: individual cases, comparisons,
	// or trajectories.
	AllowedTargetKinds param.Field[[]ScorerNewParamsAllowedTargetKind] `json:"allowed_target_kinds" api:"required"`
	// Name of this scoring specification, such as accuracy or relevance. Leading and
	// trailing whitespace are not allowed.
	Name param.Field[string] `json:"name" api:"required"`
	// JSON type that every score recorded with this scorer version must use.
	ValueType param.Field[ScorerNewParamsValueType] `json:"value_type" api:"required"`
	// Human-readable explanation of what this scorer version measures.
	Description param.Field[string] `json:"description"`
}

func (r ScorerNewParams) MarshalJSON() (data []byte, err error) {
	return apijson.MarshalRoot(r)
}

type ScorerNewParamsAllowedTargetKind string

const (
	ScorerNewParamsAllowedTargetKindCase       ScorerNewParamsAllowedTargetKind = "case"
	ScorerNewParamsAllowedTargetKindComparison ScorerNewParamsAllowedTargetKind = "comparison"
	ScorerNewParamsAllowedTargetKindTrajectory ScorerNewParamsAllowedTargetKind = "trajectory"
)

func (r ScorerNewParamsAllowedTargetKind) IsKnown() bool {
	switch r {
	case ScorerNewParamsAllowedTargetKindCase,
		ScorerNewParamsAllowedTargetKindComparison,
		ScorerNewParamsAllowedTargetKindTrajectory:
		return true
	}
	return false
}

// JSON type that every score recorded with this scorer version must use.
type ScorerNewParamsValueType string

const (
	ScorerNewParamsValueTypeNull    ScorerNewParamsValueType = "null"
	ScorerNewParamsValueTypeBoolean ScorerNewParamsValueType = "boolean"
	ScorerNewParamsValueTypeInteger ScorerNewParamsValueType = "integer"
	ScorerNewParamsValueTypeNumber  ScorerNewParamsValueType = "number"
	ScorerNewParamsValueTypeString  ScorerNewParamsValueType = "string"
	ScorerNewParamsValueTypeJson    ScorerNewParamsValueType = "json"
)

func (r ScorerNewParamsValueType) IsKnown() bool {
	switch r {
	case ScorerNewParamsValueTypeNull,
		ScorerNewParamsValueTypeBoolean,
		ScorerNewParamsValueTypeInteger,
		ScorerNewParamsValueTypeNumber,
		ScorerNewParamsValueTypeString,
		ScorerNewParamsValueTypeJson:
		return true
	}
	return false
}

type ScorerListParams struct {
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
	// The previous response's next_cursor value. Omit for the first page.
	Cursor param.Field[string] `query:"cursor"`
	// Maximum number of results to return in one page.
	Limit param.Field[int64] `query:"limit"`
}

// URLQuery serializes [ScorerListParams]'s query parameters as `url.Values`.
func (r ScorerListParams) URLQuery() (v url.Values) {
	return apiquery.MarshalWithSettings(r, apiquery.QuerySettings{
		ArrayFormat:  apiquery.ArrayQueryFormatComma,
		NestedFormat: apiquery.NestedQueryFormatBrackets,
	})
}

type ScorerDeleteParams struct {
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

type ScorerGetParams struct {
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
