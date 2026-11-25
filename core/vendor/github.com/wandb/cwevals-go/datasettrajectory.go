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

// DatasetTrajectoryService contains methods and other services that help with
// interacting with the CoreWeave Evaluations API.
//
// Note, unlike clients, this service does not read variables from the environment
// automatically. You should not instantiate this service directly, and instead use
// the [NewDatasetTrajectoryService] method instead.
type DatasetTrajectoryService struct {
	Options []option.RequestOption
	Cases   *DatasetTrajectoryCaseService
}

// NewDatasetTrajectoryService generates a new service that applies the given
// options to each request. These options are applied after the parent client's
// options (if there is one), and before any request-specific options.
func NewDatasetTrajectoryService(opts ...option.RequestOption) (r *DatasetTrajectoryService) {
	r = &DatasetTrajectoryService{}
	r.Options = opts
	r.Cases = NewDatasetTrajectoryCaseService(opts...)
	return
}

// Creates trajectories, each a run of the dataset's cases that follows a root
// case. Add cases to a trajectory with create-cases. A trajectory that names a
// parent_trajectory_id must start from one of the parent's cases, and it is nested
// one level below the parent.
//
// Request bodies must be at most 16 MiB. Bodies larger than the limit are rejected
// with 413 Request Entity Too Large.
func (r *DatasetTrajectoryService) New(
	ctx context.Context,
	datasetID string,
	params DatasetTrajectoryNewParams,
	opts ...option.RequestOption,
) (res *DatasetTrajectoryNewResponse, err error) {
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
	path := fmt.Sprintf(
		"v1/namespaces/%s/scopes/%s/datasets/%s/trajectories",
		params.Namespace,
		params.ScopeID,
		datasetID,
	)
	err = requestconfig.ExecuteNewRequest(ctx, http.MethodPost, path, params, &res, opts...)
	return res, err
}

// Returns the dataset's published trajectories in the order they were created.
//
// Pass the returned `next_cursor` as `cursor` to read the next page. The last page
// has no `next_cursor`.
func (r *DatasetTrajectoryService) List(
	ctx context.Context,
	datasetID string,
	params DatasetTrajectoryListParams,
	opts ...option.RequestOption,
) (res *DatasetTrajectoryListResponse, err error) {
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
	path := fmt.Sprintf(
		"v1/namespaces/%s/scopes/%s/datasets/%s/trajectories",
		params.Namespace,
		params.ScopeID,
		datasetID,
	)
	err = requestconfig.ExecuteNewRequest(ctx, http.MethodGet, path, params, &res, opts...)
	return res, err
}

// Returns one published trajectory, including its dataset, its root case, and the
// commit that published it.
func (r *DatasetTrajectoryService) Get(
	ctx context.Context,
	trajectoryID string,
	query DatasetTrajectoryGetParams,
	opts ...option.RequestOption,
) (res *DatasetTrajectoryGetResponse, err error) {
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
	if trajectoryID == "" {
		err = errors.New("missing required trajectory_id parameter")
		return nil, err
	}
	path := fmt.Sprintf("v1/namespaces/%s/scopes/%s/trajectories/%s", query.Namespace, query.ScopeID, trajectoryID)
	err = requestconfig.ExecuteNewRequest(ctx, http.MethodGet, path, nil, &res, opts...)
	return res, err
}

type DatasetTrajectoryNewResponse struct {
	CommitID           int64                            `json:"commit_id"            api:"required"`
	PublishOperationID string                           `json:"publish_operation_id" api:"required" format:"uuid"`
	TrajectoryIDs      []string                         `json:"trajectory_ids"       api:"required" format:"uuid"`
	JSON               datasetTrajectoryNewResponseJSON `json:"-"`
}

// datasetTrajectoryNewResponseJSON contains the JSON metadata for the struct
// [DatasetTrajectoryNewResponse]
type datasetTrajectoryNewResponseJSON struct {
	CommitID           apijson.Field
	PublishOperationID apijson.Field
	TrajectoryIDs      apijson.Field
	raw                string
	ExtraFields        map[string]apijson.Field
}

func (r *DatasetTrajectoryNewResponse) UnmarshalJSON(data []byte) (err error) {
	return apijson.UnmarshalRoot(data, r)
}

func (r datasetTrajectoryNewResponseJSON) RawJSON() string {
	return r.raw
}

type DatasetTrajectoryListResponse struct {
	Trajectories []DatasetTrajectoryListResponseTrajectory `json:"trajectories" api:"required"`
	NextCursor   string                                    `json:"next_cursor"`
	JSON         datasetTrajectoryListResponseJSON         `json:"-"`
}

// datasetTrajectoryListResponseJSON contains the JSON metadata for the struct
// [DatasetTrajectoryListResponse]
type datasetTrajectoryListResponseJSON struct {
	Trajectories apijson.Field
	NextCursor   apijson.Field
	raw          string
	ExtraFields  map[string]apijson.Field
}

func (r *DatasetTrajectoryListResponse) UnmarshalJSON(data []byte) (err error) {
	return apijson.UnmarshalRoot(data, r)
}

func (r datasetTrajectoryListResponseJSON) RawJSON() string {
	return r.raw
}

type DatasetTrajectoryListResponseTrajectory struct {
	CommitID  int64  `json:"commit_id"  api:"required"`
	DatasetID string `json:"dataset_id" api:"required" format:"uuid"`
	// 0 for a top-level trajectory, otherwise one more than its parent's.
	Depth int64  `json:"depth" api:"required"`
	Name  string `json:"name"  api:"required"`
	// Null for a top-level trajectory.
	ParentTrajectoryID string                                      `json:"parent_trajectory_id" api:"required,nullable" format:"uuid"`
	RootCaseID         string                                      `json:"root_case_id"         api:"required"          format:"uuid"`
	TrajectoryID       string                                      `json:"trajectory_id"        api:"required"          format:"uuid"`
	JSON               datasetTrajectoryListResponseTrajectoryJSON `json:"-"`
}

// datasetTrajectoryListResponseTrajectoryJSON contains the JSON metadata for the
// struct [DatasetTrajectoryListResponseTrajectory]
type datasetTrajectoryListResponseTrajectoryJSON struct {
	CommitID           apijson.Field
	DatasetID          apijson.Field
	Depth              apijson.Field
	Name               apijson.Field
	ParentTrajectoryID apijson.Field
	RootCaseID         apijson.Field
	TrajectoryID       apijson.Field
	raw                string
	ExtraFields        map[string]apijson.Field
}

func (r *DatasetTrajectoryListResponseTrajectory) UnmarshalJSON(data []byte) (err error) {
	return apijson.UnmarshalRoot(data, r)
}

func (r datasetTrajectoryListResponseTrajectoryJSON) RawJSON() string {
	return r.raw
}

type DatasetTrajectoryGetResponse struct {
	CommitID  int64  `json:"commit_id"  api:"required"`
	DatasetID string `json:"dataset_id" api:"required" format:"uuid"`
	// 0 for a top-level trajectory, otherwise one more than its parent's.
	Depth int64  `json:"depth" api:"required"`
	Name  string `json:"name"  api:"required"`
	// Namespace that assigned the scope reference.
	Namespace DatasetTrajectoryGetResponseNamespace `json:"namespace" api:"required"`
	// Null for a top-level trajectory.
	ParentTrajectoryID string                           `json:"parent_trajectory_id" api:"required,nullable" format:"uuid"`
	RootCaseID         string                           `json:"root_case_id"         api:"required"          format:"uuid"`
	ScopeRef           string                           `json:"scope_ref"            api:"required"`
	TrajectoryID       string                           `json:"trajectory_id"        api:"required"          format:"uuid"`
	JSON               datasetTrajectoryGetResponseJSON `json:"-"`
}

// datasetTrajectoryGetResponseJSON contains the JSON metadata for the struct
// [DatasetTrajectoryGetResponse]
type datasetTrajectoryGetResponseJSON struct {
	CommitID           apijson.Field
	DatasetID          apijson.Field
	Depth              apijson.Field
	Name               apijson.Field
	Namespace          apijson.Field
	ParentTrajectoryID apijson.Field
	RootCaseID         apijson.Field
	ScopeRef           apijson.Field
	TrajectoryID       apijson.Field
	raw                string
	ExtraFields        map[string]apijson.Field
}

func (r *DatasetTrajectoryGetResponse) UnmarshalJSON(data []byte) (err error) {
	return apijson.UnmarshalRoot(data, r)
}

func (r datasetTrajectoryGetResponseJSON) RawJSON() string {
	return r.raw
}

// Namespace that assigned the scope reference.
type DatasetTrajectoryGetResponseNamespace string

const (
	DatasetTrajectoryGetResponseNamespaceWandb DatasetTrajectoryGetResponseNamespace = "wandb"
)

func (r DatasetTrajectoryGetResponseNamespace) IsKnown() bool {
	switch r {
	case DatasetTrajectoryGetResponseNamespaceWandb:
		return true
	}
	return false
}

type DatasetTrajectoryNewParams struct {
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
	ScopeID      param.Field[string]                                 `path:"scope_id" api:"required"`
	Trajectories param.Field[[]DatasetTrajectoryNewParamsTrajectory] `                api:"required" json:"trajectories"`
}

func (r DatasetTrajectoryNewParams) MarshalJSON() (data []byte, err error) {
	return apijson.MarshalRoot(r)
}

type DatasetTrajectoryNewParamsTrajectory struct {
	// Display name. It need not be unique.
	Name param.Field[string] `json:"name" api:"required"`
	// Case the trajectory starts from. It must be a published case of the same
	// dataset. Several trajectories can share a root.
	RootCaseID param.Field[string] `json:"root_case_id" api:"required" format:"uuid"`
	// Published trajectory of the same dataset to nest this trajectory under. Omit or
	// send null for a top-level trajectory.
	ParentTrajectoryID param.Field[string] `json:"parent_trajectory_id" format:"uuid"`
}

func (r DatasetTrajectoryNewParamsTrajectory) MarshalJSON() (data []byte, err error) {
	return apijson.MarshalRoot(r)
}

type DatasetTrajectoryListParams struct {
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

// URLQuery serializes [DatasetTrajectoryListParams]'s query parameters as
// `url.Values`.
func (r DatasetTrajectoryListParams) URLQuery() (v url.Values) {
	return apiquery.MarshalWithSettings(r, apiquery.QuerySettings{
		ArrayFormat:  apiquery.ArrayQueryFormatComma,
		NestedFormat: apiquery.NestedQueryFormatBrackets,
	})
}

type DatasetTrajectoryGetParams struct {
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
