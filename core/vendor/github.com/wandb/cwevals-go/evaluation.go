// File generated from our OpenAPI spec by Stainless.

package cwevals

import (
	"context"
	"errors"
	"fmt"
	"net/http"
	"net/url"
	"reflect"
	"slices"

	"github.com/tidwall/gjson"
	"github.com/wandb/cwevals-go/internal/apijson"
	"github.com/wandb/cwevals-go/internal/apiquery"
	"github.com/wandb/cwevals-go/internal/param"
	"github.com/wandb/cwevals-go/internal/requestconfig"
	"github.com/wandb/cwevals-go/option"
)

// EvaluationService contains methods and other services that help with interacting
// with the CoreWeave Evaluations API.
//
// Note, unlike clients, this service does not read variables from the environment
// automatically. You should not instantiate this service directly, and instead use
// the [NewEvaluationService] method instead.
type EvaluationService struct {
	Options  []option.RequestOption
	Metrics  *EvaluationMetricService
	Rows     *EvaluationRowService
	Scorers  *EvaluationScorerService
	Queries  *EvaluationQueryService
	Versions *EvaluationVersionService
}

// NewEvaluationService generates a new service that applies the given options to
// each request. These options are applied after the parent client's options (if
// there is one), and before any request-specific options.
func NewEvaluationService(opts ...option.RequestOption) (r *EvaluationService) {
	r = &EvaluationService{}
	r.Options = opts
	r.Metrics = NewEvaluationMetricService(opts...)
	r.Rows = NewEvaluationRowService(opts...)
	r.Scorers = NewEvaluationScorerService(opts...)
	r.Queries = NewEvaluationQueryService(opts...)
	r.Versions = NewEvaluationVersionService(opts...)
	return
}

// Defines which data and target kind an evaluation uses. This operation stores a
// definition. It does not run a model or calculate scores.
//
// Choose one source:
//
//   - **Fixed:** Set `source.kind` to `fixed` and provide
//     `source.dataset_version_id` to evaluate a specific dataset version.
//   - **Live:** Set `source.kind` to `live` and provide `source.dataset_id` to
//     follow a dataset's current head.
//
// Provide only the ID for the selected source kind. A source outside the requested
// scope returns 404. Attributes are stored as canonical JSON. An exact retry with
// the same idempotency key returns the original response.
//
// Request bodies must be at most 1 MiB. Bodies larger than the limit are rejected
// with 413 Request Entity Too Large.
func (r *EvaluationService) New(
	ctx context.Context,
	params EvaluationNewParams,
	opts ...option.RequestOption,
) (res *EvaluationNewResponse, err error) {
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
	path := fmt.Sprintf("v1/namespaces/%s/scopes/%s/evaluations", params.Namespace, params.ScopeID)
	err = requestconfig.ExecuteNewRequest(ctx, http.MethodPost, path, params, &res, opts...)
	return res, err
}

// Replaces the Evaluation's name, attributes, or both. Omitted fields keep their
// values, and attributes are replaced as a whole object. A body without either
// field is rejected. The source, primary target kind, EvaluationVersions, saved
// queries, and metrics are unchanged. Concurrent updates are last-writer-wins. A
// retry with the same Idempotency-Key replays the first response.
//
// Request bodies must be at most 1 MiB. Bodies larger than the limit are rejected
// with 413 Request Entity Too Large.
func (r *EvaluationService) Update(
	ctx context.Context,
	evaluationID string,
	params EvaluationUpdateParams,
	opts ...option.RequestOption,
) (res *EvaluationUpdateResponse, err error) {
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
	path := fmt.Sprintf("v1/namespaces/%s/scopes/%s/evaluations/%s", params.Namespace, params.ScopeID, evaluationID)
	err = requestconfig.ExecuteNewRequest(ctx, http.MethodPatch, path, params, &res, opts...)
	return res, err
}

// Returns evaluations in creation order, including evaluations created through the
// evaluation table API. A scope with no evaluations returns an empty page.
func (r *EvaluationService) List(
	ctx context.Context,
	params EvaluationListParams,
	opts ...option.RequestOption,
) (res *EvaluationListResponse, err error) {
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
	path := fmt.Sprintf("v1/namespaces/%s/scopes/%s/evaluations", params.Namespace, params.ScopeID)
	err = requestconfig.ExecuteNewRequest(ctx, http.MethodGet, path, params, &res, opts...)
	return res, err
}

// Soft-deletes the Evaluation. It, its EvaluationVersions, saved queries, query
// results, and metrics then return 404, and writes to them are rejected with 404.
// Its source Dataset and its Scores are unchanged. An absent or already deleted
// Evaluation returns 404. A retry with the same Idempotency-Key replays the first
// response.
func (r *EvaluationService) Delete(
	ctx context.Context,
	evaluationID string,
	body EvaluationDeleteParams,
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
	if evaluationID == "" {
		err = errors.New("missing required evaluation_id parameter")
		return err
	}
	path := fmt.Sprintf("v1/namespaces/%s/scopes/%s/evaluations/%s", body.Namespace, body.ScopeID, evaluationID)
	err = requestconfig.ExecuteNewRequest(ctx, http.MethodDelete, path, nil, nil, opts...)
	return err
}

// Returns the immutable evaluation definition in the same form as the create
// response. An evaluation that does not exist or is outside the requested scope
// returns 404.
func (r *EvaluationService) Get(
	ctx context.Context,
	evaluationID string,
	query EvaluationGetParams,
	opts ...option.RequestOption,
) (res *EvaluationGetResponse, err error) {
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
	if evaluationID == "" {
		err = errors.New("missing required evaluation_id parameter")
		return nil, err
	}
	path := fmt.Sprintf("v1/namespaces/%s/scopes/%s/evaluations/%s", query.Namespace, query.ScopeID, evaluationID)
	err = requestconfig.ExecuteNewRequest(ctx, http.MethodGet, path, nil, &res, opts...)
	return res, err
}

type EvaluationNewResponse struct {
	Attributes   map[string]interface{} `json:"attributes"    api:"required"`
	EvaluationID string                 `json:"evaluation_id" api:"required" format:"uuid"`
	Name         string                 `json:"name"          api:"required"`
	// Namespace that assigned the scope reference.
	Namespace         EvaluationNewResponseNamespace         `json:"namespace"           api:"required"`
	PrimaryTargetKind EvaluationNewResponsePrimaryTargetKind `json:"primary_target_kind" api:"required"`
	ScopeRef          string                                 `json:"scope_ref"           api:"required"`
	Source            EvaluationNewResponseSource            `json:"source"              api:"required"`
	JSON              evaluationNewResponseJSON              `json:"-"`
}

// evaluationNewResponseJSON contains the JSON metadata for the struct
// [EvaluationNewResponse]
type evaluationNewResponseJSON struct {
	Attributes        apijson.Field
	EvaluationID      apijson.Field
	Name              apijson.Field
	Namespace         apijson.Field
	PrimaryTargetKind apijson.Field
	ScopeRef          apijson.Field
	Source            apijson.Field
	raw               string
	ExtraFields       map[string]apijson.Field
}

func (r *EvaluationNewResponse) UnmarshalJSON(data []byte) (err error) {
	return apijson.UnmarshalRoot(data, r)
}

func (r evaluationNewResponseJSON) RawJSON() string {
	return r.raw
}

// Namespace that assigned the scope reference.
type EvaluationNewResponseNamespace string

const (
	EvaluationNewResponseNamespaceWandb EvaluationNewResponseNamespace = "wandb"
)

func (r EvaluationNewResponseNamespace) IsKnown() bool {
	switch r {
	case EvaluationNewResponseNamespaceWandb:
		return true
	}
	return false
}

type EvaluationNewResponsePrimaryTargetKind string

const (
	EvaluationNewResponsePrimaryTargetKindCase       EvaluationNewResponsePrimaryTargetKind = "case"
	EvaluationNewResponsePrimaryTargetKindTrajectory EvaluationNewResponsePrimaryTargetKind = "trajectory"
)

func (r EvaluationNewResponsePrimaryTargetKind) IsKnown() bool {
	switch r {
	case EvaluationNewResponsePrimaryTargetKindCase, EvaluationNewResponsePrimaryTargetKindTrajectory:
		return true
	}
	return false
}

type EvaluationNewResponseSource struct {
	Kind             EvaluationNewResponseSourceKind `json:"kind"               api:"required"`
	DatasetID        string                          `json:"dataset_id"                        format:"uuid"`
	DatasetVersionID string                          `json:"dataset_version_id"                format:"uuid"`
	JSON             evaluationNewResponseSourceJSON `json:"-"`
	union            EvaluationNewResponseSourceUnion
}

// evaluationNewResponseSourceJSON contains the JSON metadata for the struct
// [EvaluationNewResponseSource]
type evaluationNewResponseSourceJSON struct {
	Kind             apijson.Field
	DatasetID        apijson.Field
	DatasetVersionID apijson.Field
	raw              string
	ExtraFields      map[string]apijson.Field
}

func (r evaluationNewResponseSourceJSON) RawJSON() string {
	return r.raw
}

func (r *EvaluationNewResponseSource) UnmarshalJSON(data []byte) (err error) {
	*r = EvaluationNewResponseSource{}
	err = apijson.UnmarshalRoot(data, &r.union)
	if err != nil {
		return err
	}
	return apijson.Port(r.union, &r)
}

// AsUnion returns a [EvaluationNewResponseSourceUnion] interface which you can
// cast to the specific types for more type safety.
//
// Possible runtime types of the union are
// [EvaluationNewResponseSourceFixedEvaluationSource],
// [EvaluationNewResponseSourceLiveEvaluationSource].
func (r EvaluationNewResponseSource) AsUnion() EvaluationNewResponseSourceUnion {
	return r.union
}

// Union satisfied by [EvaluationNewResponseSourceFixedEvaluationSource] or
// [EvaluationNewResponseSourceLiveEvaluationSource].
type EvaluationNewResponseSourceUnion interface {
	implementsEvaluationNewResponseSource()
}

func init() {
	apijson.RegisterUnion(
		reflect.TypeOf((*EvaluationNewResponseSourceUnion)(nil)).Elem(),
		"kind",
		apijson.UnionVariant{
			TypeFilter:         gjson.JSON,
			Type:               reflect.TypeOf(EvaluationNewResponseSourceFixedEvaluationSource{}),
			DiscriminatorValue: "fixed",
		},
		apijson.UnionVariant{
			TypeFilter:         gjson.JSON,
			Type:               reflect.TypeOf(EvaluationNewResponseSourceLiveEvaluationSource{}),
			DiscriminatorValue: "live",
		},
	)
}

type EvaluationNewResponseSourceFixedEvaluationSource struct {
	DatasetVersionID string                                               `json:"dataset_version_id" api:"required" format:"uuid"`
	Kind             EvaluationNewResponseSourceFixedEvaluationSourceKind `json:"kind"               api:"required"`
	JSON             evaluationNewResponseSourceFixedEvaluationSourceJSON `json:"-"`
}

// evaluationNewResponseSourceFixedEvaluationSourceJSON contains the JSON metadata
// for the struct [EvaluationNewResponseSourceFixedEvaluationSource]
type evaluationNewResponseSourceFixedEvaluationSourceJSON struct {
	DatasetVersionID apijson.Field
	Kind             apijson.Field
	raw              string
	ExtraFields      map[string]apijson.Field
}

func (r *EvaluationNewResponseSourceFixedEvaluationSource) UnmarshalJSON(data []byte) (err error) {
	return apijson.UnmarshalRoot(data, r)
}

func (r evaluationNewResponseSourceFixedEvaluationSourceJSON) RawJSON() string {
	return r.raw
}

func (r EvaluationNewResponseSourceFixedEvaluationSource) implementsEvaluationNewResponseSource() {}

type EvaluationNewResponseSourceFixedEvaluationSourceKind string

const (
	EvaluationNewResponseSourceFixedEvaluationSourceKindFixed EvaluationNewResponseSourceFixedEvaluationSourceKind = "fixed"
)

func (r EvaluationNewResponseSourceFixedEvaluationSourceKind) IsKnown() bool {
	switch r {
	case EvaluationNewResponseSourceFixedEvaluationSourceKindFixed:
		return true
	}
	return false
}

type EvaluationNewResponseSourceLiveEvaluationSource struct {
	DatasetID string                                              `json:"dataset_id" api:"required" format:"uuid"`
	Kind      EvaluationNewResponseSourceLiveEvaluationSourceKind `json:"kind"       api:"required"`
	JSON      evaluationNewResponseSourceLiveEvaluationSourceJSON `json:"-"`
}

// evaluationNewResponseSourceLiveEvaluationSourceJSON contains the JSON metadata
// for the struct [EvaluationNewResponseSourceLiveEvaluationSource]
type evaluationNewResponseSourceLiveEvaluationSourceJSON struct {
	DatasetID   apijson.Field
	Kind        apijson.Field
	raw         string
	ExtraFields map[string]apijson.Field
}

func (r *EvaluationNewResponseSourceLiveEvaluationSource) UnmarshalJSON(data []byte) (err error) {
	return apijson.UnmarshalRoot(data, r)
}

func (r evaluationNewResponseSourceLiveEvaluationSourceJSON) RawJSON() string {
	return r.raw
}

func (r EvaluationNewResponseSourceLiveEvaluationSource) implementsEvaluationNewResponseSource() {}

type EvaluationNewResponseSourceLiveEvaluationSourceKind string

const (
	EvaluationNewResponseSourceLiveEvaluationSourceKindLive EvaluationNewResponseSourceLiveEvaluationSourceKind = "live"
)

func (r EvaluationNewResponseSourceLiveEvaluationSourceKind) IsKnown() bool {
	switch r {
	case EvaluationNewResponseSourceLiveEvaluationSourceKindLive:
		return true
	}
	return false
}

type EvaluationNewResponseSourceKind string

const (
	EvaluationNewResponseSourceKindFixed EvaluationNewResponseSourceKind = "fixed"
	EvaluationNewResponseSourceKindLive  EvaluationNewResponseSourceKind = "live"
)

func (r EvaluationNewResponseSourceKind) IsKnown() bool {
	switch r {
	case EvaluationNewResponseSourceKindFixed, EvaluationNewResponseSourceKindLive:
		return true
	}
	return false
}

type EvaluationUpdateResponse struct {
	Attributes   map[string]interface{} `json:"attributes"    api:"required"`
	EvaluationID string                 `json:"evaluation_id" api:"required" format:"uuid"`
	Name         string                 `json:"name"          api:"required"`
	// Namespace that assigned the scope reference.
	Namespace         EvaluationUpdateResponseNamespace         `json:"namespace"           api:"required"`
	PrimaryTargetKind EvaluationUpdateResponsePrimaryTargetKind `json:"primary_target_kind" api:"required"`
	ScopeRef          string                                    `json:"scope_ref"           api:"required"`
	Source            EvaluationUpdateResponseSource            `json:"source"              api:"required"`
	JSON              evaluationUpdateResponseJSON              `json:"-"`
}

// evaluationUpdateResponseJSON contains the JSON metadata for the struct
// [EvaluationUpdateResponse]
type evaluationUpdateResponseJSON struct {
	Attributes        apijson.Field
	EvaluationID      apijson.Field
	Name              apijson.Field
	Namespace         apijson.Field
	PrimaryTargetKind apijson.Field
	ScopeRef          apijson.Field
	Source            apijson.Field
	raw               string
	ExtraFields       map[string]apijson.Field
}

func (r *EvaluationUpdateResponse) UnmarshalJSON(data []byte) (err error) {
	return apijson.UnmarshalRoot(data, r)
}

func (r evaluationUpdateResponseJSON) RawJSON() string {
	return r.raw
}

// Namespace that assigned the scope reference.
type EvaluationUpdateResponseNamespace string

const (
	EvaluationUpdateResponseNamespaceWandb EvaluationUpdateResponseNamespace = "wandb"
)

func (r EvaluationUpdateResponseNamespace) IsKnown() bool {
	switch r {
	case EvaluationUpdateResponseNamespaceWandb:
		return true
	}
	return false
}

type EvaluationUpdateResponsePrimaryTargetKind string

const (
	EvaluationUpdateResponsePrimaryTargetKindCase       EvaluationUpdateResponsePrimaryTargetKind = "case"
	EvaluationUpdateResponsePrimaryTargetKindTrajectory EvaluationUpdateResponsePrimaryTargetKind = "trajectory"
)

func (r EvaluationUpdateResponsePrimaryTargetKind) IsKnown() bool {
	switch r {
	case EvaluationUpdateResponsePrimaryTargetKindCase, EvaluationUpdateResponsePrimaryTargetKindTrajectory:
		return true
	}
	return false
}

type EvaluationUpdateResponseSource struct {
	Kind             EvaluationUpdateResponseSourceKind `json:"kind"               api:"required"`
	DatasetID        string                             `json:"dataset_id"                        format:"uuid"`
	DatasetVersionID string                             `json:"dataset_version_id"                format:"uuid"`
	JSON             evaluationUpdateResponseSourceJSON `json:"-"`
	union            EvaluationUpdateResponseSourceUnion
}

// evaluationUpdateResponseSourceJSON contains the JSON metadata for the struct
// [EvaluationUpdateResponseSource]
type evaluationUpdateResponseSourceJSON struct {
	Kind             apijson.Field
	DatasetID        apijson.Field
	DatasetVersionID apijson.Field
	raw              string
	ExtraFields      map[string]apijson.Field
}

func (r evaluationUpdateResponseSourceJSON) RawJSON() string {
	return r.raw
}

func (r *EvaluationUpdateResponseSource) UnmarshalJSON(data []byte) (err error) {
	*r = EvaluationUpdateResponseSource{}
	err = apijson.UnmarshalRoot(data, &r.union)
	if err != nil {
		return err
	}
	return apijson.Port(r.union, &r)
}

// AsUnion returns a [EvaluationUpdateResponseSourceUnion] interface which you can
// cast to the specific types for more type safety.
//
// Possible runtime types of the union are
// [EvaluationUpdateResponseSourceFixedEvaluationSource],
// [EvaluationUpdateResponseSourceLiveEvaluationSource].
func (r EvaluationUpdateResponseSource) AsUnion() EvaluationUpdateResponseSourceUnion {
	return r.union
}

// Union satisfied by [EvaluationUpdateResponseSourceFixedEvaluationSource] or
// [EvaluationUpdateResponseSourceLiveEvaluationSource].
type EvaluationUpdateResponseSourceUnion interface {
	implementsEvaluationUpdateResponseSource()
}

func init() {
	apijson.RegisterUnion(
		reflect.TypeOf((*EvaluationUpdateResponseSourceUnion)(nil)).Elem(),
		"kind",
		apijson.UnionVariant{
			TypeFilter:         gjson.JSON,
			Type:               reflect.TypeOf(EvaluationUpdateResponseSourceFixedEvaluationSource{}),
			DiscriminatorValue: "fixed",
		},
		apijson.UnionVariant{
			TypeFilter:         gjson.JSON,
			Type:               reflect.TypeOf(EvaluationUpdateResponseSourceLiveEvaluationSource{}),
			DiscriminatorValue: "live",
		},
	)
}

type EvaluationUpdateResponseSourceFixedEvaluationSource struct {
	DatasetVersionID string                                                  `json:"dataset_version_id" api:"required" format:"uuid"`
	Kind             EvaluationUpdateResponseSourceFixedEvaluationSourceKind `json:"kind"               api:"required"`
	JSON             evaluationUpdateResponseSourceFixedEvaluationSourceJSON `json:"-"`
}

// evaluationUpdateResponseSourceFixedEvaluationSourceJSON contains the JSON
// metadata for the struct [EvaluationUpdateResponseSourceFixedEvaluationSource]
type evaluationUpdateResponseSourceFixedEvaluationSourceJSON struct {
	DatasetVersionID apijson.Field
	Kind             apijson.Field
	raw              string
	ExtraFields      map[string]apijson.Field
}

func (r *EvaluationUpdateResponseSourceFixedEvaluationSource) UnmarshalJSON(data []byte) (err error) {
	return apijson.UnmarshalRoot(data, r)
}

func (r evaluationUpdateResponseSourceFixedEvaluationSourceJSON) RawJSON() string {
	return r.raw
}

func (r EvaluationUpdateResponseSourceFixedEvaluationSource) implementsEvaluationUpdateResponseSource() {
}

type EvaluationUpdateResponseSourceFixedEvaluationSourceKind string

const (
	EvaluationUpdateResponseSourceFixedEvaluationSourceKindFixed EvaluationUpdateResponseSourceFixedEvaluationSourceKind = "fixed"
)

func (r EvaluationUpdateResponseSourceFixedEvaluationSourceKind) IsKnown() bool {
	switch r {
	case EvaluationUpdateResponseSourceFixedEvaluationSourceKindFixed:
		return true
	}
	return false
}

type EvaluationUpdateResponseSourceLiveEvaluationSource struct {
	DatasetID string                                                 `json:"dataset_id" api:"required" format:"uuid"`
	Kind      EvaluationUpdateResponseSourceLiveEvaluationSourceKind `json:"kind"       api:"required"`
	JSON      evaluationUpdateResponseSourceLiveEvaluationSourceJSON `json:"-"`
}

// evaluationUpdateResponseSourceLiveEvaluationSourceJSON contains the JSON
// metadata for the struct [EvaluationUpdateResponseSourceLiveEvaluationSource]
type evaluationUpdateResponseSourceLiveEvaluationSourceJSON struct {
	DatasetID   apijson.Field
	Kind        apijson.Field
	raw         string
	ExtraFields map[string]apijson.Field
}

func (r *EvaluationUpdateResponseSourceLiveEvaluationSource) UnmarshalJSON(data []byte) (err error) {
	return apijson.UnmarshalRoot(data, r)
}

func (r evaluationUpdateResponseSourceLiveEvaluationSourceJSON) RawJSON() string {
	return r.raw
}

func (r EvaluationUpdateResponseSourceLiveEvaluationSource) implementsEvaluationUpdateResponseSource() {
}

type EvaluationUpdateResponseSourceLiveEvaluationSourceKind string

const (
	EvaluationUpdateResponseSourceLiveEvaluationSourceKindLive EvaluationUpdateResponseSourceLiveEvaluationSourceKind = "live"
)

func (r EvaluationUpdateResponseSourceLiveEvaluationSourceKind) IsKnown() bool {
	switch r {
	case EvaluationUpdateResponseSourceLiveEvaluationSourceKindLive:
		return true
	}
	return false
}

type EvaluationUpdateResponseSourceKind string

const (
	EvaluationUpdateResponseSourceKindFixed EvaluationUpdateResponseSourceKind = "fixed"
	EvaluationUpdateResponseSourceKindLive  EvaluationUpdateResponseSourceKind = "live"
)

func (r EvaluationUpdateResponseSourceKind) IsKnown() bool {
	switch r {
	case EvaluationUpdateResponseSourceKindFixed, EvaluationUpdateResponseSourceKindLive:
		return true
	}
	return false
}

type EvaluationListResponse struct {
	Evaluations []EvaluationListResponseEvaluation `json:"evaluations" api:"required"`
	NextCursor  string                             `json:"next_cursor"`
	JSON        evaluationListResponseJSON         `json:"-"`
}

// evaluationListResponseJSON contains the JSON metadata for the struct
// [EvaluationListResponse]
type evaluationListResponseJSON struct {
	Evaluations apijson.Field
	NextCursor  apijson.Field
	raw         string
	ExtraFields map[string]apijson.Field
}

func (r *EvaluationListResponse) UnmarshalJSON(data []byte) (err error) {
	return apijson.UnmarshalRoot(data, r)
}

func (r evaluationListResponseJSON) RawJSON() string {
	return r.raw
}

type EvaluationListResponseEvaluation struct {
	Attributes   map[string]interface{} `json:"attributes"    api:"required"`
	EvaluationID string                 `json:"evaluation_id" api:"required" format:"uuid"`
	Name         string                 `json:"name"          api:"required"`
	// Namespace that assigned the scope reference.
	Namespace         EvaluationListResponseEvaluationsNamespace         `json:"namespace"           api:"required"`
	PrimaryTargetKind EvaluationListResponseEvaluationsPrimaryTargetKind `json:"primary_target_kind" api:"required"`
	ScopeRef          string                                             `json:"scope_ref"           api:"required"`
	Source            EvaluationListResponseEvaluationsSource            `json:"source"              api:"required"`
	JSON              evaluationListResponseEvaluationJSON               `json:"-"`
}

// evaluationListResponseEvaluationJSON contains the JSON metadata for the struct
// [EvaluationListResponseEvaluation]
type evaluationListResponseEvaluationJSON struct {
	Attributes        apijson.Field
	EvaluationID      apijson.Field
	Name              apijson.Field
	Namespace         apijson.Field
	PrimaryTargetKind apijson.Field
	ScopeRef          apijson.Field
	Source            apijson.Field
	raw               string
	ExtraFields       map[string]apijson.Field
}

func (r *EvaluationListResponseEvaluation) UnmarshalJSON(data []byte) (err error) {
	return apijson.UnmarshalRoot(data, r)
}

func (r evaluationListResponseEvaluationJSON) RawJSON() string {
	return r.raw
}

// Namespace that assigned the scope reference.
type EvaluationListResponseEvaluationsNamespace string

const (
	EvaluationListResponseEvaluationsNamespaceWandb EvaluationListResponseEvaluationsNamespace = "wandb"
)

func (r EvaluationListResponseEvaluationsNamespace) IsKnown() bool {
	switch r {
	case EvaluationListResponseEvaluationsNamespaceWandb:
		return true
	}
	return false
}

type EvaluationListResponseEvaluationsPrimaryTargetKind string

const (
	EvaluationListResponseEvaluationsPrimaryTargetKindCase       EvaluationListResponseEvaluationsPrimaryTargetKind = "case"
	EvaluationListResponseEvaluationsPrimaryTargetKindTrajectory EvaluationListResponseEvaluationsPrimaryTargetKind = "trajectory"
)

func (r EvaluationListResponseEvaluationsPrimaryTargetKind) IsKnown() bool {
	switch r {
	case EvaluationListResponseEvaluationsPrimaryTargetKindCase,
		EvaluationListResponseEvaluationsPrimaryTargetKindTrajectory:
		return true
	}
	return false
}

type EvaluationListResponseEvaluationsSource struct {
	Kind             EvaluationListResponseEvaluationsSourceKind `json:"kind"               api:"required"`
	DatasetID        string                                      `json:"dataset_id"                        format:"uuid"`
	DatasetVersionID string                                      `json:"dataset_version_id"                format:"uuid"`
	JSON             evaluationListResponseEvaluationsSourceJSON `json:"-"`
	union            EvaluationListResponseEvaluationsSourceUnion
}

// evaluationListResponseEvaluationsSourceJSON contains the JSON metadata for the
// struct [EvaluationListResponseEvaluationsSource]
type evaluationListResponseEvaluationsSourceJSON struct {
	Kind             apijson.Field
	DatasetID        apijson.Field
	DatasetVersionID apijson.Field
	raw              string
	ExtraFields      map[string]apijson.Field
}

func (r evaluationListResponseEvaluationsSourceJSON) RawJSON() string {
	return r.raw
}

func (r *EvaluationListResponseEvaluationsSource) UnmarshalJSON(data []byte) (err error) {
	*r = EvaluationListResponseEvaluationsSource{}
	err = apijson.UnmarshalRoot(data, &r.union)
	if err != nil {
		return err
	}
	return apijson.Port(r.union, &r)
}

// AsUnion returns a [EvaluationListResponseEvaluationsSourceUnion] interface which
// you can cast to the specific types for more type safety.
//
// Possible runtime types of the union are
// [EvaluationListResponseEvaluationsSourceFixedEvaluationSource],
// [EvaluationListResponseEvaluationsSourceLiveEvaluationSource].
func (r EvaluationListResponseEvaluationsSource) AsUnion() EvaluationListResponseEvaluationsSourceUnion {
	return r.union
}

// Union satisfied by
// [EvaluationListResponseEvaluationsSourceFixedEvaluationSource] or
// [EvaluationListResponseEvaluationsSourceLiveEvaluationSource].
type EvaluationListResponseEvaluationsSourceUnion interface {
	implementsEvaluationListResponseEvaluationsSource()
}

func init() {
	apijson.RegisterUnion(
		reflect.TypeOf((*EvaluationListResponseEvaluationsSourceUnion)(nil)).Elem(),
		"kind",
		apijson.UnionVariant{
			TypeFilter:         gjson.JSON,
			Type:               reflect.TypeOf(EvaluationListResponseEvaluationsSourceFixedEvaluationSource{}),
			DiscriminatorValue: "fixed",
		},
		apijson.UnionVariant{
			TypeFilter:         gjson.JSON,
			Type:               reflect.TypeOf(EvaluationListResponseEvaluationsSourceLiveEvaluationSource{}),
			DiscriminatorValue: "live",
		},
	)
}

type EvaluationListResponseEvaluationsSourceFixedEvaluationSource struct {
	DatasetVersionID string                                                           `json:"dataset_version_id" api:"required" format:"uuid"`
	Kind             EvaluationListResponseEvaluationsSourceFixedEvaluationSourceKind `json:"kind"               api:"required"`
	JSON             evaluationListResponseEvaluationsSourceFixedEvaluationSourceJSON `json:"-"`
}

// evaluationListResponseEvaluationsSourceFixedEvaluationSourceJSON contains the
// JSON metadata for the struct
// [EvaluationListResponseEvaluationsSourceFixedEvaluationSource]
type evaluationListResponseEvaluationsSourceFixedEvaluationSourceJSON struct {
	DatasetVersionID apijson.Field
	Kind             apijson.Field
	raw              string
	ExtraFields      map[string]apijson.Field
}

func (r *EvaluationListResponseEvaluationsSourceFixedEvaluationSource) UnmarshalJSON(data []byte) (err error) {
	return apijson.UnmarshalRoot(data, r)
}

func (r evaluationListResponseEvaluationsSourceFixedEvaluationSourceJSON) RawJSON() string {
	return r.raw
}

func (r EvaluationListResponseEvaluationsSourceFixedEvaluationSource) implementsEvaluationListResponseEvaluationsSource() {
}

type EvaluationListResponseEvaluationsSourceFixedEvaluationSourceKind string

const (
	EvaluationListResponseEvaluationsSourceFixedEvaluationSourceKindFixed EvaluationListResponseEvaluationsSourceFixedEvaluationSourceKind = "fixed"
)

func (r EvaluationListResponseEvaluationsSourceFixedEvaluationSourceKind) IsKnown() bool {
	switch r {
	case EvaluationListResponseEvaluationsSourceFixedEvaluationSourceKindFixed:
		return true
	}
	return false
}

type EvaluationListResponseEvaluationsSourceLiveEvaluationSource struct {
	DatasetID string                                                          `json:"dataset_id" api:"required" format:"uuid"`
	Kind      EvaluationListResponseEvaluationsSourceLiveEvaluationSourceKind `json:"kind"       api:"required"`
	JSON      evaluationListResponseEvaluationsSourceLiveEvaluationSourceJSON `json:"-"`
}

// evaluationListResponseEvaluationsSourceLiveEvaluationSourceJSON contains the
// JSON metadata for the struct
// [EvaluationListResponseEvaluationsSourceLiveEvaluationSource]
type evaluationListResponseEvaluationsSourceLiveEvaluationSourceJSON struct {
	DatasetID   apijson.Field
	Kind        apijson.Field
	raw         string
	ExtraFields map[string]apijson.Field
}

func (r *EvaluationListResponseEvaluationsSourceLiveEvaluationSource) UnmarshalJSON(data []byte) (err error) {
	return apijson.UnmarshalRoot(data, r)
}

func (r evaluationListResponseEvaluationsSourceLiveEvaluationSourceJSON) RawJSON() string {
	return r.raw
}

func (r EvaluationListResponseEvaluationsSourceLiveEvaluationSource) implementsEvaluationListResponseEvaluationsSource() {
}

type EvaluationListResponseEvaluationsSourceLiveEvaluationSourceKind string

const (
	EvaluationListResponseEvaluationsSourceLiveEvaluationSourceKindLive EvaluationListResponseEvaluationsSourceLiveEvaluationSourceKind = "live"
)

func (r EvaluationListResponseEvaluationsSourceLiveEvaluationSourceKind) IsKnown() bool {
	switch r {
	case EvaluationListResponseEvaluationsSourceLiveEvaluationSourceKindLive:
		return true
	}
	return false
}

type EvaluationListResponseEvaluationsSourceKind string

const (
	EvaluationListResponseEvaluationsSourceKindFixed EvaluationListResponseEvaluationsSourceKind = "fixed"
	EvaluationListResponseEvaluationsSourceKindLive  EvaluationListResponseEvaluationsSourceKind = "live"
)

func (r EvaluationListResponseEvaluationsSourceKind) IsKnown() bool {
	switch r {
	case EvaluationListResponseEvaluationsSourceKindFixed, EvaluationListResponseEvaluationsSourceKindLive:
		return true
	}
	return false
}

type EvaluationGetResponse struct {
	Attributes   map[string]interface{} `json:"attributes"    api:"required"`
	EvaluationID string                 `json:"evaluation_id" api:"required" format:"uuid"`
	Name         string                 `json:"name"          api:"required"`
	// Namespace that assigned the scope reference.
	Namespace         EvaluationGetResponseNamespace         `json:"namespace"           api:"required"`
	PrimaryTargetKind EvaluationGetResponsePrimaryTargetKind `json:"primary_target_kind" api:"required"`
	ScopeRef          string                                 `json:"scope_ref"           api:"required"`
	Source            EvaluationGetResponseSource            `json:"source"              api:"required"`
	JSON              evaluationGetResponseJSON              `json:"-"`
}

// evaluationGetResponseJSON contains the JSON metadata for the struct
// [EvaluationGetResponse]
type evaluationGetResponseJSON struct {
	Attributes        apijson.Field
	EvaluationID      apijson.Field
	Name              apijson.Field
	Namespace         apijson.Field
	PrimaryTargetKind apijson.Field
	ScopeRef          apijson.Field
	Source            apijson.Field
	raw               string
	ExtraFields       map[string]apijson.Field
}

func (r *EvaluationGetResponse) UnmarshalJSON(data []byte) (err error) {
	return apijson.UnmarshalRoot(data, r)
}

func (r evaluationGetResponseJSON) RawJSON() string {
	return r.raw
}

// Namespace that assigned the scope reference.
type EvaluationGetResponseNamespace string

const (
	EvaluationGetResponseNamespaceWandb EvaluationGetResponseNamespace = "wandb"
)

func (r EvaluationGetResponseNamespace) IsKnown() bool {
	switch r {
	case EvaluationGetResponseNamespaceWandb:
		return true
	}
	return false
}

type EvaluationGetResponsePrimaryTargetKind string

const (
	EvaluationGetResponsePrimaryTargetKindCase       EvaluationGetResponsePrimaryTargetKind = "case"
	EvaluationGetResponsePrimaryTargetKindTrajectory EvaluationGetResponsePrimaryTargetKind = "trajectory"
)

func (r EvaluationGetResponsePrimaryTargetKind) IsKnown() bool {
	switch r {
	case EvaluationGetResponsePrimaryTargetKindCase, EvaluationGetResponsePrimaryTargetKindTrajectory:
		return true
	}
	return false
}

type EvaluationGetResponseSource struct {
	Kind             EvaluationGetResponseSourceKind `json:"kind"               api:"required"`
	DatasetID        string                          `json:"dataset_id"                        format:"uuid"`
	DatasetVersionID string                          `json:"dataset_version_id"                format:"uuid"`
	JSON             evaluationGetResponseSourceJSON `json:"-"`
	union            EvaluationGetResponseSourceUnion
}

// evaluationGetResponseSourceJSON contains the JSON metadata for the struct
// [EvaluationGetResponseSource]
type evaluationGetResponseSourceJSON struct {
	Kind             apijson.Field
	DatasetID        apijson.Field
	DatasetVersionID apijson.Field
	raw              string
	ExtraFields      map[string]apijson.Field
}

func (r evaluationGetResponseSourceJSON) RawJSON() string {
	return r.raw
}

func (r *EvaluationGetResponseSource) UnmarshalJSON(data []byte) (err error) {
	*r = EvaluationGetResponseSource{}
	err = apijson.UnmarshalRoot(data, &r.union)
	if err != nil {
		return err
	}
	return apijson.Port(r.union, &r)
}

// AsUnion returns a [EvaluationGetResponseSourceUnion] interface which you can
// cast to the specific types for more type safety.
//
// Possible runtime types of the union are
// [EvaluationGetResponseSourceFixedEvaluationSource],
// [EvaluationGetResponseSourceLiveEvaluationSource].
func (r EvaluationGetResponseSource) AsUnion() EvaluationGetResponseSourceUnion {
	return r.union
}

// Union satisfied by [EvaluationGetResponseSourceFixedEvaluationSource] or
// [EvaluationGetResponseSourceLiveEvaluationSource].
type EvaluationGetResponseSourceUnion interface {
	implementsEvaluationGetResponseSource()
}

func init() {
	apijson.RegisterUnion(
		reflect.TypeOf((*EvaluationGetResponseSourceUnion)(nil)).Elem(),
		"kind",
		apijson.UnionVariant{
			TypeFilter:         gjson.JSON,
			Type:               reflect.TypeOf(EvaluationGetResponseSourceFixedEvaluationSource{}),
			DiscriminatorValue: "fixed",
		},
		apijson.UnionVariant{
			TypeFilter:         gjson.JSON,
			Type:               reflect.TypeOf(EvaluationGetResponseSourceLiveEvaluationSource{}),
			DiscriminatorValue: "live",
		},
	)
}

type EvaluationGetResponseSourceFixedEvaluationSource struct {
	DatasetVersionID string                                               `json:"dataset_version_id" api:"required" format:"uuid"`
	Kind             EvaluationGetResponseSourceFixedEvaluationSourceKind `json:"kind"               api:"required"`
	JSON             evaluationGetResponseSourceFixedEvaluationSourceJSON `json:"-"`
}

// evaluationGetResponseSourceFixedEvaluationSourceJSON contains the JSON metadata
// for the struct [EvaluationGetResponseSourceFixedEvaluationSource]
type evaluationGetResponseSourceFixedEvaluationSourceJSON struct {
	DatasetVersionID apijson.Field
	Kind             apijson.Field
	raw              string
	ExtraFields      map[string]apijson.Field
}

func (r *EvaluationGetResponseSourceFixedEvaluationSource) UnmarshalJSON(data []byte) (err error) {
	return apijson.UnmarshalRoot(data, r)
}

func (r evaluationGetResponseSourceFixedEvaluationSourceJSON) RawJSON() string {
	return r.raw
}

func (r EvaluationGetResponseSourceFixedEvaluationSource) implementsEvaluationGetResponseSource() {}

type EvaluationGetResponseSourceFixedEvaluationSourceKind string

const (
	EvaluationGetResponseSourceFixedEvaluationSourceKindFixed EvaluationGetResponseSourceFixedEvaluationSourceKind = "fixed"
)

func (r EvaluationGetResponseSourceFixedEvaluationSourceKind) IsKnown() bool {
	switch r {
	case EvaluationGetResponseSourceFixedEvaluationSourceKindFixed:
		return true
	}
	return false
}

type EvaluationGetResponseSourceLiveEvaluationSource struct {
	DatasetID string                                              `json:"dataset_id" api:"required" format:"uuid"`
	Kind      EvaluationGetResponseSourceLiveEvaluationSourceKind `json:"kind"       api:"required"`
	JSON      evaluationGetResponseSourceLiveEvaluationSourceJSON `json:"-"`
}

// evaluationGetResponseSourceLiveEvaluationSourceJSON contains the JSON metadata
// for the struct [EvaluationGetResponseSourceLiveEvaluationSource]
type evaluationGetResponseSourceLiveEvaluationSourceJSON struct {
	DatasetID   apijson.Field
	Kind        apijson.Field
	raw         string
	ExtraFields map[string]apijson.Field
}

func (r *EvaluationGetResponseSourceLiveEvaluationSource) UnmarshalJSON(data []byte) (err error) {
	return apijson.UnmarshalRoot(data, r)
}

func (r evaluationGetResponseSourceLiveEvaluationSourceJSON) RawJSON() string {
	return r.raw
}

func (r EvaluationGetResponseSourceLiveEvaluationSource) implementsEvaluationGetResponseSource() {}

type EvaluationGetResponseSourceLiveEvaluationSourceKind string

const (
	EvaluationGetResponseSourceLiveEvaluationSourceKindLive EvaluationGetResponseSourceLiveEvaluationSourceKind = "live"
)

func (r EvaluationGetResponseSourceLiveEvaluationSourceKind) IsKnown() bool {
	switch r {
	case EvaluationGetResponseSourceLiveEvaluationSourceKindLive:
		return true
	}
	return false
}

type EvaluationGetResponseSourceKind string

const (
	EvaluationGetResponseSourceKindFixed EvaluationGetResponseSourceKind = "fixed"
	EvaluationGetResponseSourceKindLive  EvaluationGetResponseSourceKind = "live"
)

func (r EvaluationGetResponseSourceKind) IsKnown() bool {
	switch r {
	case EvaluationGetResponseSourceKindFixed, EvaluationGetResponseSourceKindLive:
		return true
	}
	return false
}

type EvaluationNewParams struct {
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
	Name    param.Field[string] `                api:"required" json:"name"`
	// Whether this evaluation reads individual cases or trajectories from its source.
	PrimaryTargetKind param.Field[EvaluationNewParamsPrimaryTargetKind] `json:"primary_target_kind" api:"required"`
	Source            param.Field[EvaluationNewParamsSourceUnion]       `json:"source"              api:"required"`
	Attributes        param.Field[map[string]interface{}]               `json:"attributes"`
}

func (r EvaluationNewParams) MarshalJSON() (data []byte, err error) {
	return apijson.MarshalRoot(r)
}

// Whether this evaluation reads individual cases or trajectories from its source.
type EvaluationNewParamsPrimaryTargetKind string

const (
	EvaluationNewParamsPrimaryTargetKindCase       EvaluationNewParamsPrimaryTargetKind = "case"
	EvaluationNewParamsPrimaryTargetKindTrajectory EvaluationNewParamsPrimaryTargetKind = "trajectory"
)

func (r EvaluationNewParamsPrimaryTargetKind) IsKnown() bool {
	switch r {
	case EvaluationNewParamsPrimaryTargetKindCase, EvaluationNewParamsPrimaryTargetKindTrajectory:
		return true
	}
	return false
}

type EvaluationNewParamsSource struct {
	Kind             param.Field[EvaluationNewParamsSourceKind] `json:"kind"               api:"required"`
	DatasetID        param.Field[string]                        `json:"dataset_id"                        format:"uuid"`
	DatasetVersionID param.Field[string]                        `json:"dataset_version_id"                format:"uuid"`
}

func (r EvaluationNewParamsSource) MarshalJSON() (data []byte, err error) {
	return apijson.MarshalRoot(r)
}

func (r EvaluationNewParamsSource) implementsEvaluationNewParamsSourceUnion() {}

// Satisfied by [EvaluationNewParamsSourceFixedEvaluationSource],
// [EvaluationNewParamsSourceLiveEvaluationSource], [EvaluationNewParamsSource].
type EvaluationNewParamsSourceUnion interface {
	implementsEvaluationNewParamsSourceUnion()
}

type EvaluationNewParamsSourceFixedEvaluationSource struct {
	DatasetVersionID param.Field[string]                                             `json:"dataset_version_id" api:"required" format:"uuid"`
	Kind             param.Field[EvaluationNewParamsSourceFixedEvaluationSourceKind] `json:"kind"               api:"required"`
}

func (r EvaluationNewParamsSourceFixedEvaluationSource) MarshalJSON() (data []byte, err error) {
	return apijson.MarshalRoot(r)
}

func (r EvaluationNewParamsSourceFixedEvaluationSource) implementsEvaluationNewParamsSourceUnion() {}

type EvaluationNewParamsSourceFixedEvaluationSourceKind string

const (
	EvaluationNewParamsSourceFixedEvaluationSourceKindFixed EvaluationNewParamsSourceFixedEvaluationSourceKind = "fixed"
)

func (r EvaluationNewParamsSourceFixedEvaluationSourceKind) IsKnown() bool {
	switch r {
	case EvaluationNewParamsSourceFixedEvaluationSourceKindFixed:
		return true
	}
	return false
}

type EvaluationNewParamsSourceLiveEvaluationSource struct {
	DatasetID param.Field[string]                                            `json:"dataset_id" api:"required" format:"uuid"`
	Kind      param.Field[EvaluationNewParamsSourceLiveEvaluationSourceKind] `json:"kind"       api:"required"`
}

func (r EvaluationNewParamsSourceLiveEvaluationSource) MarshalJSON() (data []byte, err error) {
	return apijson.MarshalRoot(r)
}

func (r EvaluationNewParamsSourceLiveEvaluationSource) implementsEvaluationNewParamsSourceUnion() {}

type EvaluationNewParamsSourceLiveEvaluationSourceKind string

const (
	EvaluationNewParamsSourceLiveEvaluationSourceKindLive EvaluationNewParamsSourceLiveEvaluationSourceKind = "live"
)

func (r EvaluationNewParamsSourceLiveEvaluationSourceKind) IsKnown() bool {
	switch r {
	case EvaluationNewParamsSourceLiveEvaluationSourceKindLive:
		return true
	}
	return false
}

type EvaluationNewParamsSourceKind string

const (
	EvaluationNewParamsSourceKindFixed EvaluationNewParamsSourceKind = "fixed"
	EvaluationNewParamsSourceKindLive  EvaluationNewParamsSourceKind = "live"
)

func (r EvaluationNewParamsSourceKind) IsKnown() bool {
	switch r {
	case EvaluationNewParamsSourceKindFixed, EvaluationNewParamsSourceKindLive:
		return true
	}
	return false
}

type EvaluationUpdateParams struct {
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
	// Replaces the attributes as a whole object. Omit to keep them.
	Attributes param.Field[map[string]interface{}] `json:"attributes"`
	// Replaces the name. Omit to keep it.
	Name param.Field[string] `json:"name"`
}

func (r EvaluationUpdateParams) MarshalJSON() (data []byte, err error) {
	return apijson.MarshalRoot(r)
}

type EvaluationListParams struct {
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
	// Return only evaluations with exactly this name, including evaluation tables.
	// Omit to list all evaluations in the scope.
	Name param.Field[string] `query:"name"`
}

// URLQuery serializes [EvaluationListParams]'s query parameters as `url.Values`.
func (r EvaluationListParams) URLQuery() (v url.Values) {
	return apiquery.MarshalWithSettings(r, apiquery.QuerySettings{
		ArrayFormat:  apiquery.ArrayQueryFormatComma,
		NestedFormat: apiquery.NestedQueryFormatBrackets,
	})
}

type EvaluationDeleteParams struct {
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

type EvaluationGetParams struct {
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
