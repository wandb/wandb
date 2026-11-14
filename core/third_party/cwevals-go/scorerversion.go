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

// ScorerVersionService contains methods and other services that help with
// interacting with the CoreWeave Evaluations API.
//
// Note, unlike clients, this service does not read variables from the environment
// automatically. You should not instantiate this service directly, and instead use
// the [NewScorerVersionService] method instead.
type ScorerVersionService struct {
	Options []option.RequestOption
}

// NewScorerVersionService generates a new service that applies the given options
// to each request. These options are applied after the parent client's options (if
// there is one), and before any request-specific options.
func NewScorerVersionService(opts ...option.RequestOption) (r *ScorerVersionService) {
	r = &ScorerVersionService{}
	r.Options = opts
	return
}

// Creates an immutable specification under an existing scorer, with its own name,
// score value type, allowed target kinds, and optional description. Existing
// versions and their scores remain unchanged.
//
// Request bodies must be at most 1 MiB. Bodies larger than the limit are rejected
// with 413 Request Entity Too Large.
func (r *ScorerVersionService) New(
	ctx context.Context,
	scorerID string,
	params ScorerVersionNewParams,
	opts ...option.RequestOption,
) (res *ScorerVersionNewResponse, err error) {
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
	if scorerID == "" {
		err = errors.New("missing required scorer_id parameter")
		return nil, err
	}
	path := fmt.Sprintf("v1/namespaces/%s/scopes/%s/scorers/%s/versions", params.Namespace, params.ScopeID, scorerID)
	err = requestconfig.ExecuteNewRequest(ctx, http.MethodPost, path, params, &res, opts...)
	return res, err
}

// Returns one page of a Scorer's immutable versions.
func (r *ScorerVersionService) List(
	ctx context.Context,
	scorerID string,
	params ScorerVersionListParams,
	opts ...option.RequestOption,
) (res *ScorerVersionListResponse, err error) {
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
	if scorerID == "" {
		err = errors.New("missing required scorer_id parameter")
		return nil, err
	}
	path := fmt.Sprintf("v1/namespaces/%s/scopes/%s/scorers/%s/versions", params.Namespace, params.ScopeID, scorerID)
	err = requestconfig.ExecuteNewRequest(ctx, http.MethodGet, path, params, &res, opts...)
	return res, err
}

// Returns one immutable scorer specification, including its name, score value
// type, and allowed target kinds.
func (r *ScorerVersionService) Get(
	ctx context.Context,
	scorerID string,
	scorerVersionID string,
	query ScorerVersionGetParams,
	opts ...option.RequestOption,
) (res *ScorerVersionGetResponse, err error) {
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
	if scorerVersionID == "" {
		err = errors.New("missing required scorer_version_id parameter")
		return nil, err
	}
	path := fmt.Sprintf(
		"v1/namespaces/%s/scopes/%s/scorers/%s/versions/%s",
		query.Namespace,
		query.ScopeID,
		scorerID,
		scorerVersionID,
	)
	err = requestconfig.ExecuteNewRequest(ctx, http.MethodGet, path, nil, &res, opts...)
	return res, err
}

type ScorerVersionNewResponse struct {
	AllowedTargetKinds []ScorerVersionNewResponseAllowedTargetKind `json:"allowed_target_kinds" api:"required"`
	Description        string                                      `json:"description"          api:"required,nullable"`
	Name               string                                      `json:"name"                 api:"required"`
	// Namespace that assigned the scope reference.
	Namespace ScorerVersionNewResponseNamespace `json:"namespace"  api:"required"`
	ScopeRef  string                            `json:"scope_ref"  api:"required"`
	ScorerID  string                            `json:"scorer_id"  api:"required" format:"uuid"`
	ValueType ScorerVersionNewResponseValueType `json:"value_type" api:"required"`
	VersionID string                            `json:"version_id" api:"required" format:"uuid"`
	JSON      scorerVersionNewResponseJSON      `json:"-"`
}

// scorerVersionNewResponseJSON contains the JSON metadata for the struct
// [ScorerVersionNewResponse]
type scorerVersionNewResponseJSON struct {
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

func (r *ScorerVersionNewResponse) UnmarshalJSON(data []byte) (err error) {
	return apijson.UnmarshalRoot(data, r)
}

func (r scorerVersionNewResponseJSON) RawJSON() string {
	return r.raw
}

type ScorerVersionNewResponseAllowedTargetKind string

const (
	ScorerVersionNewResponseAllowedTargetKindCase       ScorerVersionNewResponseAllowedTargetKind = "case"
	ScorerVersionNewResponseAllowedTargetKindComparison ScorerVersionNewResponseAllowedTargetKind = "comparison"
	ScorerVersionNewResponseAllowedTargetKindTrajectory ScorerVersionNewResponseAllowedTargetKind = "trajectory"
)

func (r ScorerVersionNewResponseAllowedTargetKind) IsKnown() bool {
	switch r {
	case ScorerVersionNewResponseAllowedTargetKindCase,
		ScorerVersionNewResponseAllowedTargetKindComparison,
		ScorerVersionNewResponseAllowedTargetKindTrajectory:
		return true
	}
	return false
}

// Namespace that assigned the scope reference.
type ScorerVersionNewResponseNamespace string

const (
	ScorerVersionNewResponseNamespaceWandb ScorerVersionNewResponseNamespace = "wandb"
)

func (r ScorerVersionNewResponseNamespace) IsKnown() bool {
	switch r {
	case ScorerVersionNewResponseNamespaceWandb:
		return true
	}
	return false
}

type ScorerVersionNewResponseValueType string

const (
	ScorerVersionNewResponseValueTypeNull    ScorerVersionNewResponseValueType = "null"
	ScorerVersionNewResponseValueTypeBoolean ScorerVersionNewResponseValueType = "boolean"
	ScorerVersionNewResponseValueTypeInteger ScorerVersionNewResponseValueType = "integer"
	ScorerVersionNewResponseValueTypeNumber  ScorerVersionNewResponseValueType = "number"
	ScorerVersionNewResponseValueTypeString  ScorerVersionNewResponseValueType = "string"
	ScorerVersionNewResponseValueTypeJson    ScorerVersionNewResponseValueType = "json"
)

func (r ScorerVersionNewResponseValueType) IsKnown() bool {
	switch r {
	case ScorerVersionNewResponseValueTypeNull,
		ScorerVersionNewResponseValueTypeBoolean,
		ScorerVersionNewResponseValueTypeInteger,
		ScorerVersionNewResponseValueTypeNumber,
		ScorerVersionNewResponseValueTypeString,
		ScorerVersionNewResponseValueTypeJson:
		return true
	}
	return false
}

type ScorerVersionListResponse struct {
	Results    []ScorerVersionListResponseResult `json:"results"     api:"required"`
	NextCursor string                            `json:"next_cursor"`
	JSON       scorerVersionListResponseJSON     `json:"-"`
}

// scorerVersionListResponseJSON contains the JSON metadata for the struct
// [ScorerVersionListResponse]
type scorerVersionListResponseJSON struct {
	Results     apijson.Field
	NextCursor  apijson.Field
	raw         string
	ExtraFields map[string]apijson.Field
}

func (r *ScorerVersionListResponse) UnmarshalJSON(data []byte) (err error) {
	return apijson.UnmarshalRoot(data, r)
}

func (r scorerVersionListResponseJSON) RawJSON() string {
	return r.raw
}

type ScorerVersionListResponseResult struct {
	AllowedTargetKinds []ScorerVersionListResponseResultsAllowedTargetKind `json:"allowed_target_kinds" api:"required"`
	Description        string                                              `json:"description"          api:"required,nullable"`
	Name               string                                              `json:"name"                 api:"required"`
	// Namespace that assigned the scope reference.
	Namespace ScorerVersionListResponseResultsNamespace `json:"namespace"  api:"required"`
	ScopeRef  string                                    `json:"scope_ref"  api:"required"`
	ScorerID  string                                    `json:"scorer_id"  api:"required" format:"uuid"`
	ValueType ScorerVersionListResponseResultsValueType `json:"value_type" api:"required"`
	VersionID string                                    `json:"version_id" api:"required" format:"uuid"`
	JSON      scorerVersionListResponseResultJSON       `json:"-"`
}

// scorerVersionListResponseResultJSON contains the JSON metadata for the struct
// [ScorerVersionListResponseResult]
type scorerVersionListResponseResultJSON struct {
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

func (r *ScorerVersionListResponseResult) UnmarshalJSON(data []byte) (err error) {
	return apijson.UnmarshalRoot(data, r)
}

func (r scorerVersionListResponseResultJSON) RawJSON() string {
	return r.raw
}

type ScorerVersionListResponseResultsAllowedTargetKind string

const (
	ScorerVersionListResponseResultsAllowedTargetKindCase       ScorerVersionListResponseResultsAllowedTargetKind = "case"
	ScorerVersionListResponseResultsAllowedTargetKindComparison ScorerVersionListResponseResultsAllowedTargetKind = "comparison"
	ScorerVersionListResponseResultsAllowedTargetKindTrajectory ScorerVersionListResponseResultsAllowedTargetKind = "trajectory"
)

func (r ScorerVersionListResponseResultsAllowedTargetKind) IsKnown() bool {
	switch r {
	case ScorerVersionListResponseResultsAllowedTargetKindCase,
		ScorerVersionListResponseResultsAllowedTargetKindComparison,
		ScorerVersionListResponseResultsAllowedTargetKindTrajectory:
		return true
	}
	return false
}

// Namespace that assigned the scope reference.
type ScorerVersionListResponseResultsNamespace string

const (
	ScorerVersionListResponseResultsNamespaceWandb ScorerVersionListResponseResultsNamespace = "wandb"
)

func (r ScorerVersionListResponseResultsNamespace) IsKnown() bool {
	switch r {
	case ScorerVersionListResponseResultsNamespaceWandb:
		return true
	}
	return false
}

type ScorerVersionListResponseResultsValueType string

const (
	ScorerVersionListResponseResultsValueTypeNull    ScorerVersionListResponseResultsValueType = "null"
	ScorerVersionListResponseResultsValueTypeBoolean ScorerVersionListResponseResultsValueType = "boolean"
	ScorerVersionListResponseResultsValueTypeInteger ScorerVersionListResponseResultsValueType = "integer"
	ScorerVersionListResponseResultsValueTypeNumber  ScorerVersionListResponseResultsValueType = "number"
	ScorerVersionListResponseResultsValueTypeString  ScorerVersionListResponseResultsValueType = "string"
	ScorerVersionListResponseResultsValueTypeJson    ScorerVersionListResponseResultsValueType = "json"
)

func (r ScorerVersionListResponseResultsValueType) IsKnown() bool {
	switch r {
	case ScorerVersionListResponseResultsValueTypeNull,
		ScorerVersionListResponseResultsValueTypeBoolean,
		ScorerVersionListResponseResultsValueTypeInteger,
		ScorerVersionListResponseResultsValueTypeNumber,
		ScorerVersionListResponseResultsValueTypeString,
		ScorerVersionListResponseResultsValueTypeJson:
		return true
	}
	return false
}

type ScorerVersionGetResponse struct {
	AllowedTargetKinds []ScorerVersionGetResponseAllowedTargetKind `json:"allowed_target_kinds" api:"required"`
	Description        string                                      `json:"description"          api:"required,nullable"`
	Name               string                                      `json:"name"                 api:"required"`
	// Namespace that assigned the scope reference.
	Namespace ScorerVersionGetResponseNamespace `json:"namespace"  api:"required"`
	ScopeRef  string                            `json:"scope_ref"  api:"required"`
	ScorerID  string                            `json:"scorer_id"  api:"required" format:"uuid"`
	ValueType ScorerVersionGetResponseValueType `json:"value_type" api:"required"`
	VersionID string                            `json:"version_id" api:"required" format:"uuid"`
	JSON      scorerVersionGetResponseJSON      `json:"-"`
}

// scorerVersionGetResponseJSON contains the JSON metadata for the struct
// [ScorerVersionGetResponse]
type scorerVersionGetResponseJSON struct {
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

func (r *ScorerVersionGetResponse) UnmarshalJSON(data []byte) (err error) {
	return apijson.UnmarshalRoot(data, r)
}

func (r scorerVersionGetResponseJSON) RawJSON() string {
	return r.raw
}

type ScorerVersionGetResponseAllowedTargetKind string

const (
	ScorerVersionGetResponseAllowedTargetKindCase       ScorerVersionGetResponseAllowedTargetKind = "case"
	ScorerVersionGetResponseAllowedTargetKindComparison ScorerVersionGetResponseAllowedTargetKind = "comparison"
	ScorerVersionGetResponseAllowedTargetKindTrajectory ScorerVersionGetResponseAllowedTargetKind = "trajectory"
)

func (r ScorerVersionGetResponseAllowedTargetKind) IsKnown() bool {
	switch r {
	case ScorerVersionGetResponseAllowedTargetKindCase,
		ScorerVersionGetResponseAllowedTargetKindComparison,
		ScorerVersionGetResponseAllowedTargetKindTrajectory:
		return true
	}
	return false
}

// Namespace that assigned the scope reference.
type ScorerVersionGetResponseNamespace string

const (
	ScorerVersionGetResponseNamespaceWandb ScorerVersionGetResponseNamespace = "wandb"
)

func (r ScorerVersionGetResponseNamespace) IsKnown() bool {
	switch r {
	case ScorerVersionGetResponseNamespaceWandb:
		return true
	}
	return false
}

type ScorerVersionGetResponseValueType string

const (
	ScorerVersionGetResponseValueTypeNull    ScorerVersionGetResponseValueType = "null"
	ScorerVersionGetResponseValueTypeBoolean ScorerVersionGetResponseValueType = "boolean"
	ScorerVersionGetResponseValueTypeInteger ScorerVersionGetResponseValueType = "integer"
	ScorerVersionGetResponseValueTypeNumber  ScorerVersionGetResponseValueType = "number"
	ScorerVersionGetResponseValueTypeString  ScorerVersionGetResponseValueType = "string"
	ScorerVersionGetResponseValueTypeJson    ScorerVersionGetResponseValueType = "json"
)

func (r ScorerVersionGetResponseValueType) IsKnown() bool {
	switch r {
	case ScorerVersionGetResponseValueTypeNull,
		ScorerVersionGetResponseValueTypeBoolean,
		ScorerVersionGetResponseValueTypeInteger,
		ScorerVersionGetResponseValueTypeNumber,
		ScorerVersionGetResponseValueTypeString,
		ScorerVersionGetResponseValueTypeJson:
		return true
	}
	return false
}

type ScorerVersionNewParams struct {
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
	AllowedTargetKinds param.Field[[]ScorerVersionNewParamsAllowedTargetKind] `json:"allowed_target_kinds" api:"required"`
	// Name of this scoring specification, such as accuracy or relevance. Leading and
	// trailing whitespace are not allowed.
	Name param.Field[string] `json:"name" api:"required"`
	// JSON type that every score recorded with this scorer version must use.
	ValueType param.Field[ScorerVersionNewParamsValueType] `json:"value_type" api:"required"`
	// Human-readable explanation of what this scorer version measures.
	Description param.Field[string] `json:"description"`
}

func (r ScorerVersionNewParams) MarshalJSON() (data []byte, err error) {
	return apijson.MarshalRoot(r)
}

type ScorerVersionNewParamsAllowedTargetKind string

const (
	ScorerVersionNewParamsAllowedTargetKindCase       ScorerVersionNewParamsAllowedTargetKind = "case"
	ScorerVersionNewParamsAllowedTargetKindComparison ScorerVersionNewParamsAllowedTargetKind = "comparison"
	ScorerVersionNewParamsAllowedTargetKindTrajectory ScorerVersionNewParamsAllowedTargetKind = "trajectory"
)

func (r ScorerVersionNewParamsAllowedTargetKind) IsKnown() bool {
	switch r {
	case ScorerVersionNewParamsAllowedTargetKindCase,
		ScorerVersionNewParamsAllowedTargetKindComparison,
		ScorerVersionNewParamsAllowedTargetKindTrajectory:
		return true
	}
	return false
}

// JSON type that every score recorded with this scorer version must use.
type ScorerVersionNewParamsValueType string

const (
	ScorerVersionNewParamsValueTypeNull    ScorerVersionNewParamsValueType = "null"
	ScorerVersionNewParamsValueTypeBoolean ScorerVersionNewParamsValueType = "boolean"
	ScorerVersionNewParamsValueTypeInteger ScorerVersionNewParamsValueType = "integer"
	ScorerVersionNewParamsValueTypeNumber  ScorerVersionNewParamsValueType = "number"
	ScorerVersionNewParamsValueTypeString  ScorerVersionNewParamsValueType = "string"
	ScorerVersionNewParamsValueTypeJson    ScorerVersionNewParamsValueType = "json"
)

func (r ScorerVersionNewParamsValueType) IsKnown() bool {
	switch r {
	case ScorerVersionNewParamsValueTypeNull,
		ScorerVersionNewParamsValueTypeBoolean,
		ScorerVersionNewParamsValueTypeInteger,
		ScorerVersionNewParamsValueTypeNumber,
		ScorerVersionNewParamsValueTypeString,
		ScorerVersionNewParamsValueTypeJson:
		return true
	}
	return false
}

type ScorerVersionListParams struct {
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

// URLQuery serializes [ScorerVersionListParams]'s query parameters as
// `url.Values`.
func (r ScorerVersionListParams) URLQuery() (v url.Values) {
	return apiquery.MarshalWithSettings(r, apiquery.QuerySettings{
		ArrayFormat:  apiquery.ArrayQueryFormatComma,
		NestedFormat: apiquery.NestedQueryFormatBrackets,
	})
}

type ScorerVersionGetParams struct {
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
