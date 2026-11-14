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

// DatasetVersionService contains methods and other services that help with
// interacting with the CoreWeave Evaluations API.
//
// Note, unlike clients, this service does not read variables from the environment
// automatically. You should not instantiate this service directly, and instead use
// the [NewDatasetVersionService] method instead.
type DatasetVersionService struct {
	Options []option.RequestOption
	Cases   *DatasetVersionCaseService
	Fields  *DatasetVersionFieldService
}

// NewDatasetVersionService generates a new service that applies the given options
// to each request. These options are applied after the parent client's options (if
// there is one), and before any request-specific options.
func NewDatasetVersionService(opts ...option.RequestOption) (r *DatasetVersionService) {
	r = &DatasetVersionService{}
	r.Options = opts
	r.Cases = NewDatasetVersionCaseService(opts...)
	r.Fields = NewDatasetVersionFieldService(opts...)
	return
}

// Freezes the dataset's current pending version, including its cases, fields, and
// publication cutoff. The published version is immutable. The dataset gets a new
// pending version for later writes.
//
// Request bodies must be at most 1 MiB. Bodies larger than the limit are rejected
// with 413 Request Entity Too Large.
func (r *DatasetVersionService) New(
	ctx context.Context,
	datasetID string,
	params DatasetVersionNewParams,
	opts ...option.RequestOption,
) (res *DatasetVersionNewResponse, err error) {
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
	if datasetID == "" {
		err = errors.New("missing required dataset_id parameter")
		return nil, err
	}
	path := fmt.Sprintf("v1/namespaces/%s/scopes/%s/datasets/%s/versions", params.Namespace, params.ScopeID, datasetID)
	err = requestconfig.ExecuteNewRequest(ctx, http.MethodPost, path, params, &res, opts...)
	return res, err
}

// Pages the Dataset's published DatasetVersions in the order they were published,
// each shaped like get-dataset-version. The pending head is not listed. Read it
// through the Dataset's head_version_id. An absent Dataset or one outside the
// requested scope returns 404.
func (r *DatasetVersionService) List(
	ctx context.Context,
	datasetID string,
	params DatasetVersionListParams,
	opts ...option.RequestOption,
) (res *DatasetVersionListResponse, err error) {
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
	if datasetID == "" {
		err = errors.New("missing required dataset_id parameter")
		return nil, err
	}
	path := fmt.Sprintf("v1/namespaces/%s/scopes/%s/datasets/%s/versions", params.Namespace, params.ScopeID, datasetID)
	err = requestconfig.ExecuteNewRequest(ctx, http.MethodGet, path, params, &res, opts...)
	return res, err
}

// Returns a dataset version's metadata, publication status, and case and
// trajectory counts. A `pending` version can still change. A `published` version
// is an immutable snapshot.
func (r *DatasetVersionService) Get(
	ctx context.Context,
	datasetVersionID string,
	query DatasetVersionGetParams,
	opts ...option.RequestOption,
) (res *DatasetVersionGetResponse, err error) {
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
	if datasetVersionID == "" {
		err = errors.New("missing required dataset_version_id parameter")
		return nil, err
	}
	path := fmt.Sprintf(
		"v1/namespaces/%s/scopes/%s/dataset-versions/%s",
		query.Namespace,
		query.ScopeID,
		datasetVersionID,
	)
	err = requestconfig.ExecuteNewRequest(ctx, http.MethodGet, path, nil, &res, opts...)
	return res, err
}

type DatasetVersionNewResponse struct {
	CaseCount        int64     `json:"case_count"         api:"required"`
	CreatedAt        time.Time `json:"created_at"         api:"required" format:"date-time"`
	DatasetID        string    `json:"dataset_id"         api:"required" format:"uuid"`
	DatasetVersionID string    `json:"dataset_version_id" api:"required" format:"uuid"`
	// Publication cutoff used to read this version. A published snapshot excludes
	// later writes.
	LastCommitID int64 `json:"last_commit_id" api:"required"`
	// Namespace that assigned the scope reference.
	Namespace DatasetVersionNewResponseNamespace `json:"namespace" api:"required"`
	ScopeRef  string                             `json:"scope_ref" api:"required"`
	// pending means this version can still change. published means its contents are
	// frozen.
	Status          DatasetVersionNewResponseStatus `json:"status"            api:"required"`
	TrajectoryCount int64                           `json:"trajectory_count"  api:"required"`
	Uri             string                          `json:"uri"               api:"required,nullable"`
	VersionSequence int64                           `json:"version_sequence"  api:"required"`
	ParentVersionID string                          `json:"parent_version_id"                         format:"uuid"`
	JSON            datasetVersionNewResponseJSON   `json:"-"`
}

// datasetVersionNewResponseJSON contains the JSON metadata for the struct
// [DatasetVersionNewResponse]
type datasetVersionNewResponseJSON struct {
	CaseCount        apijson.Field
	CreatedAt        apijson.Field
	DatasetID        apijson.Field
	DatasetVersionID apijson.Field
	LastCommitID     apijson.Field
	Namespace        apijson.Field
	ScopeRef         apijson.Field
	Status           apijson.Field
	TrajectoryCount  apijson.Field
	Uri              apijson.Field
	VersionSequence  apijson.Field
	ParentVersionID  apijson.Field
	raw              string
	ExtraFields      map[string]apijson.Field
}

func (r *DatasetVersionNewResponse) UnmarshalJSON(data []byte) (err error) {
	return apijson.UnmarshalRoot(data, r)
}

func (r datasetVersionNewResponseJSON) RawJSON() string {
	return r.raw
}

// Namespace that assigned the scope reference.
type DatasetVersionNewResponseNamespace string

const (
	DatasetVersionNewResponseNamespaceWandb DatasetVersionNewResponseNamespace = "wandb"
)

func (r DatasetVersionNewResponseNamespace) IsKnown() bool {
	switch r {
	case DatasetVersionNewResponseNamespaceWandb:
		return true
	}
	return false
}

// pending means this version can still change. published means its contents are
// frozen.
type DatasetVersionNewResponseStatus string

const (
	DatasetVersionNewResponseStatusPending   DatasetVersionNewResponseStatus = "pending"
	DatasetVersionNewResponseStatusPublished DatasetVersionNewResponseStatus = "published"
)

func (r DatasetVersionNewResponseStatus) IsKnown() bool {
	switch r {
	case DatasetVersionNewResponseStatusPending, DatasetVersionNewResponseStatusPublished:
		return true
	}
	return false
}

type DatasetVersionListResponse struct {
	DatasetVersions []DatasetVersionListResponseDatasetVersion `json:"dataset_versions" api:"required"`
	NextCursor      string                                     `json:"next_cursor"`
	JSON            datasetVersionListResponseJSON             `json:"-"`
}

// datasetVersionListResponseJSON contains the JSON metadata for the struct
// [DatasetVersionListResponse]
type datasetVersionListResponseJSON struct {
	DatasetVersions apijson.Field
	NextCursor      apijson.Field
	raw             string
	ExtraFields     map[string]apijson.Field
}

func (r *DatasetVersionListResponse) UnmarshalJSON(data []byte) (err error) {
	return apijson.UnmarshalRoot(data, r)
}

func (r datasetVersionListResponseJSON) RawJSON() string {
	return r.raw
}

type DatasetVersionListResponseDatasetVersion struct {
	CaseCount        int64     `json:"case_count"         api:"required"`
	CreatedAt        time.Time `json:"created_at"         api:"required" format:"date-time"`
	DatasetID        string    `json:"dataset_id"         api:"required" format:"uuid"`
	DatasetVersionID string    `json:"dataset_version_id" api:"required" format:"uuid"`
	// Publication cutoff used to read this version. A published snapshot excludes
	// later writes.
	LastCommitID int64 `json:"last_commit_id" api:"required"`
	// Namespace that assigned the scope reference.
	Namespace DatasetVersionListResponseDatasetVersionsNamespace `json:"namespace" api:"required"`
	ScopeRef  string                                             `json:"scope_ref" api:"required"`
	// pending means this version can still change. published means its contents are
	// frozen.
	Status          DatasetVersionListResponseDatasetVersionsStatus `json:"status"            api:"required"`
	TrajectoryCount int64                                           `json:"trajectory_count"  api:"required"`
	Uri             string                                          `json:"uri"               api:"required,nullable"`
	VersionSequence int64                                           `json:"version_sequence"  api:"required"`
	ParentVersionID string                                          `json:"parent_version_id"                         format:"uuid"`
	JSON            datasetVersionListResponseDatasetVersionJSON    `json:"-"`
}

// datasetVersionListResponseDatasetVersionJSON contains the JSON metadata for the
// struct [DatasetVersionListResponseDatasetVersion]
type datasetVersionListResponseDatasetVersionJSON struct {
	CaseCount        apijson.Field
	CreatedAt        apijson.Field
	DatasetID        apijson.Field
	DatasetVersionID apijson.Field
	LastCommitID     apijson.Field
	Namespace        apijson.Field
	ScopeRef         apijson.Field
	Status           apijson.Field
	TrajectoryCount  apijson.Field
	Uri              apijson.Field
	VersionSequence  apijson.Field
	ParentVersionID  apijson.Field
	raw              string
	ExtraFields      map[string]apijson.Field
}

func (r *DatasetVersionListResponseDatasetVersion) UnmarshalJSON(data []byte) (err error) {
	return apijson.UnmarshalRoot(data, r)
}

func (r datasetVersionListResponseDatasetVersionJSON) RawJSON() string {
	return r.raw
}

// Namespace that assigned the scope reference.
type DatasetVersionListResponseDatasetVersionsNamespace string

const (
	DatasetVersionListResponseDatasetVersionsNamespaceWandb DatasetVersionListResponseDatasetVersionsNamespace = "wandb"
)

func (r DatasetVersionListResponseDatasetVersionsNamespace) IsKnown() bool {
	switch r {
	case DatasetVersionListResponseDatasetVersionsNamespaceWandb:
		return true
	}
	return false
}

// pending means this version can still change. published means its contents are
// frozen.
type DatasetVersionListResponseDatasetVersionsStatus string

const (
	DatasetVersionListResponseDatasetVersionsStatusPending   DatasetVersionListResponseDatasetVersionsStatus = "pending"
	DatasetVersionListResponseDatasetVersionsStatusPublished DatasetVersionListResponseDatasetVersionsStatus = "published"
)

func (r DatasetVersionListResponseDatasetVersionsStatus) IsKnown() bool {
	switch r {
	case DatasetVersionListResponseDatasetVersionsStatusPending,
		DatasetVersionListResponseDatasetVersionsStatusPublished:
		return true
	}
	return false
}

type DatasetVersionGetResponse struct {
	CaseCount        int64     `json:"case_count"         api:"required"`
	CreatedAt        time.Time `json:"created_at"         api:"required" format:"date-time"`
	DatasetID        string    `json:"dataset_id"         api:"required" format:"uuid"`
	DatasetVersionID string    `json:"dataset_version_id" api:"required" format:"uuid"`
	// Publication cutoff used to read this version. A published snapshot excludes
	// later writes.
	LastCommitID int64 `json:"last_commit_id" api:"required"`
	// Namespace that assigned the scope reference.
	Namespace DatasetVersionGetResponseNamespace `json:"namespace" api:"required"`
	ScopeRef  string                             `json:"scope_ref" api:"required"`
	// pending means this version can still change. published means its contents are
	// frozen.
	Status          DatasetVersionGetResponseStatus `json:"status"            api:"required"`
	TrajectoryCount int64                           `json:"trajectory_count"  api:"required"`
	Uri             string                          `json:"uri"               api:"required,nullable"`
	VersionSequence int64                           `json:"version_sequence"  api:"required"`
	ParentVersionID string                          `json:"parent_version_id"                         format:"uuid"`
	JSON            datasetVersionGetResponseJSON   `json:"-"`
}

// datasetVersionGetResponseJSON contains the JSON metadata for the struct
// [DatasetVersionGetResponse]
type datasetVersionGetResponseJSON struct {
	CaseCount        apijson.Field
	CreatedAt        apijson.Field
	DatasetID        apijson.Field
	DatasetVersionID apijson.Field
	LastCommitID     apijson.Field
	Namespace        apijson.Field
	ScopeRef         apijson.Field
	Status           apijson.Field
	TrajectoryCount  apijson.Field
	Uri              apijson.Field
	VersionSequence  apijson.Field
	ParentVersionID  apijson.Field
	raw              string
	ExtraFields      map[string]apijson.Field
}

func (r *DatasetVersionGetResponse) UnmarshalJSON(data []byte) (err error) {
	return apijson.UnmarshalRoot(data, r)
}

func (r datasetVersionGetResponseJSON) RawJSON() string {
	return r.raw
}

// Namespace that assigned the scope reference.
type DatasetVersionGetResponseNamespace string

const (
	DatasetVersionGetResponseNamespaceWandb DatasetVersionGetResponseNamespace = "wandb"
)

func (r DatasetVersionGetResponseNamespace) IsKnown() bool {
	switch r {
	case DatasetVersionGetResponseNamespaceWandb:
		return true
	}
	return false
}

// pending means this version can still change. published means its contents are
// frozen.
type DatasetVersionGetResponseStatus string

const (
	DatasetVersionGetResponseStatusPending   DatasetVersionGetResponseStatus = "pending"
	DatasetVersionGetResponseStatusPublished DatasetVersionGetResponseStatus = "published"
)

func (r DatasetVersionGetResponseStatus) IsKnown() bool {
	switch r {
	case DatasetVersionGetResponseStatusPending, DatasetVersionGetResponseStatusPublished:
		return true
	}
	return false
}

type DatasetVersionNewParams struct {
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
	// Location of this version's externally stored data, such as
	// hf://datasets/org/name@revision. The service stores this URI as metadata and
	// does not read from it.
	//
	//   - Omit or send null to keep the current dataset head's URI.
	//   - Supplying a URI replaces it for this version, and later versions inherit the
	//     replacement.
	//   - This operation cannot clear an existing URI.
	Uri param.Field[string] `json:"uri" format:"uri"`
}

func (r DatasetVersionNewParams) MarshalJSON() (data []byte, err error) {
	return apijson.MarshalRoot(r)
}

type DatasetVersionListParams struct {
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

// URLQuery serializes [DatasetVersionListParams]'s query parameters as
// `url.Values`.
func (r DatasetVersionListParams) URLQuery() (v url.Values) {
	return apiquery.MarshalWithSettings(r, apiquery.QuerySettings{
		ArrayFormat:  apiquery.ArrayQueryFormatComma,
		NestedFormat: apiquery.NestedQueryFormatBrackets,
	})
}

type DatasetVersionGetParams struct {
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
