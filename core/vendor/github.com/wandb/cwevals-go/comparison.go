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

// ComparisonService contains methods and other services that help with interacting
// with the CoreWeave Evaluations API.
//
// Note, unlike clients, this service does not read variables from the environment
// automatically. You should not instantiate this service directly, and instead use
// the [NewComparisonService] method instead.
type ComparisonService struct {
	Options []option.RequestOption
}

// NewComparisonService generates a new service that applies the given options to
// each request. These options are applied after the parent client's options (if
// there is one), and before any request-specific options.
func NewComparisonService(opts ...option.RequestOption) (r *ComparisonService) {
	r = &ComparisonService{}
	r.Options = opts
	return
}

// Groups existing, published cases into comparisons that can be scored together.
// Each member can have a role label to distinguish its part in the comparison.
//
// The response returns comparison IDs in request order. Cases are grouped by
// explicit membership, not by matching `example_key` values.
//
// Request bodies must be at most 16 MiB. Bodies larger than the limit are rejected
// with 413 Request Entity Too Large.
func (r *ComparisonService) New(
	ctx context.Context,
	params ComparisonNewParams,
	opts ...option.RequestOption,
) (res *ComparisonNewResponse, err error) {
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
	path := fmt.Sprintf("v1/namespaces/%s/scopes/%s/comparisons", params.Namespace, params.ScopeID)
	err = requestconfig.ExecuteNewRequest(ctx, http.MethodPost, path, params, &res, opts...)
	return res, err
}

// Returns a published comparison, its member cases in submitted order, and any
// role labels and attributes.
func (r *ComparisonService) Get(
	ctx context.Context,
	comparisonID string,
	query ComparisonGetParams,
	opts ...option.RequestOption,
) (res *ComparisonGetResponse, err error) {
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
	if comparisonID == "" {
		err = errors.New("missing required comparison_id parameter")
		return nil, err
	}
	path := fmt.Sprintf("v1/namespaces/%s/scopes/%s/comparisons/%s", query.Namespace, query.ScopeID, comparisonID)
	err = requestconfig.ExecuteNewRequest(ctx, http.MethodGet, path, nil, &res, opts...)
	return res, err
}

type ComparisonNewResponse struct {
	CommitID           int64                     `json:"commit_id"            api:"required"`
	ComparisonIDs      []string                  `json:"comparison_ids"       api:"required" format:"uuid"`
	PublishOperationID string                    `json:"publish_operation_id" api:"required" format:"uuid"`
	JSON               comparisonNewResponseJSON `json:"-"`
}

// comparisonNewResponseJSON contains the JSON metadata for the struct
// [ComparisonNewResponse]
type comparisonNewResponseJSON struct {
	CommitID           apijson.Field
	ComparisonIDs      apijson.Field
	PublishOperationID apijson.Field
	raw                string
	ExtraFields        map[string]apijson.Field
}

func (r *ComparisonNewResponse) UnmarshalJSON(data []byte) (err error) {
	return apijson.UnmarshalRoot(data, r)
}

func (r comparisonNewResponseJSON) RawJSON() string {
	return r.raw
}

type ComparisonGetResponse struct {
	Attributes   map[string]interface{}        `json:"attributes"    api:"required"`
	CommitID     int64                         `json:"commit_id"     api:"required"`
	ComparisonID string                        `json:"comparison_id" api:"required" format:"uuid"`
	Members      []ComparisonGetResponseMember `json:"members"       api:"required"`
	// Namespace that assigned the scope reference.
	Namespace ComparisonGetResponseNamespace `json:"namespace" api:"required"`
	ScopeRef  string                         `json:"scope_ref" api:"required"`
	JSON      comparisonGetResponseJSON      `json:"-"`
}

// comparisonGetResponseJSON contains the JSON metadata for the struct
// [ComparisonGetResponse]
type comparisonGetResponseJSON struct {
	Attributes   apijson.Field
	CommitID     apijson.Field
	ComparisonID apijson.Field
	Members      apijson.Field
	Namespace    apijson.Field
	ScopeRef     apijson.Field
	raw          string
	ExtraFields  map[string]apijson.Field
}

func (r *ComparisonGetResponse) UnmarshalJSON(data []byte) (err error) {
	return apijson.UnmarshalRoot(data, r)
}

func (r comparisonGetResponseJSON) RawJSON() string {
	return r.raw
}

type ComparisonGetResponseMember struct {
	CaseID string                          `json:"case_id" api:"required" format:"uuid"`
	Role   string                          `json:"role"    api:"nullable"`
	JSON   comparisonGetResponseMemberJSON `json:"-"`
}

// comparisonGetResponseMemberJSON contains the JSON metadata for the struct
// [ComparisonGetResponseMember]
type comparisonGetResponseMemberJSON struct {
	CaseID      apijson.Field
	Role        apijson.Field
	raw         string
	ExtraFields map[string]apijson.Field
}

func (r *ComparisonGetResponseMember) UnmarshalJSON(data []byte) (err error) {
	return apijson.UnmarshalRoot(data, r)
}

func (r comparisonGetResponseMemberJSON) RawJSON() string {
	return r.raw
}

// Namespace that assigned the scope reference.
type ComparisonGetResponseNamespace string

const (
	ComparisonGetResponseNamespaceWandb ComparisonGetResponseNamespace = "wandb"
)

func (r ComparisonGetResponseNamespace) IsKnown() bool {
	switch r {
	case ComparisonGetResponseNamespaceWandb:
		return true
	}
	return false
}

type ComparisonNewParams struct {
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
	ScopeID     param.Field[string]                          `path:"scope_id" api:"required"`
	Comparisons param.Field[[]ComparisonNewParamsComparison] `                api:"required" json:"comparisons"`
}

func (r ComparisonNewParams) MarshalJSON() (data []byte, err error) {
	return apijson.MarshalRoot(r)
}

type ComparisonNewParamsComparison struct {
	Members    param.Field[[]ComparisonNewParamsComparisonsMember] `json:"members"    api:"required"`
	Attributes param.Field[map[string]interface{}]                 `json:"attributes"`
}

func (r ComparisonNewParamsComparison) MarshalJSON() (data []byte, err error) {
	return apijson.MarshalRoot(r)
}

type ComparisonNewParamsComparisonsMember struct {
	CaseID param.Field[string] `json:"case_id" api:"required" format:"uuid"`
	// Optional label for this case's role in the comparison. The service does not
	// impose a vocabulary for roles.
	Role param.Field[string] `json:"role"`
}

func (r ComparisonNewParamsComparisonsMember) MarshalJSON() (data []byte, err error) {
	return apijson.MarshalRoot(r)
}

type ComparisonGetParams struct {
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
