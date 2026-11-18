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

// DatasetCaseTagService contains methods and other services that help with
// interacting with the CoreWeave Evaluations API.
//
// Note, unlike clients, this service does not read variables from the environment
// automatically. You should not instantiate this service directly, and instead use
// the [NewDatasetCaseTagService] method instead.
type DatasetCaseTagService struct {
	Options []option.RequestOption
}

// NewDatasetCaseTagService generates a new service that applies the given options
// to each request. These options are applied after the parent client's options (if
// there is one), and before any request-specific options.
func NewDatasetCaseTagService(opts ...option.RequestOption) (r *DatasetCaseTagService) {
	r = &DatasetCaseTagService{}
	r.Options = opts
	return
}

// Atomically adds tags to and removes tags from cases in the dataset's pending
// version. Published dataset versions keep their tags. The response lists cases in
// request order, each with its tags after the edit sorted by name.
//
// Concurrent writes to the same dataset apply in turn. A case that is not in the
// dataset returns 404. A case that would hold more than 10 tags returns 400.
// Adding a tag a case already has, or removing one it lacks, changes nothing. If
// any item is invalid, no tags change. A retry with the same Idempotency-Key
// replays the first response.
//
// Request bodies must be at most 16 MiB. Bodies larger than the limit are rejected
// with 413 Request Entity Too Large.
func (r *DatasetCaseTagService) Update(
	ctx context.Context,
	datasetID string,
	params DatasetCaseTagUpdateParams,
	opts ...option.RequestOption,
) (res *DatasetCaseTagUpdateResponse, err error) {
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
		"v1/namespaces/%s/scopes/%s/datasets/%s/cases/tags",
		params.Namespace,
		params.ScopeID,
		datasetID,
	)
	err = requestconfig.ExecuteNewRequest(ctx, http.MethodPatch, path, params, &res, opts...)
	return res, err
}

type DatasetCaseTagUpdateResponse struct {
	Cases              []DatasetCaseTagUpdateResponseCase `json:"cases"                api:"required"`
	CommitID           int64                              `json:"commit_id"            api:"required"`
	PublishOperationID string                             `json:"publish_operation_id" api:"required" format:"uuid"`
	JSON               datasetCaseTagUpdateResponseJSON   `json:"-"`
}

// datasetCaseTagUpdateResponseJSON contains the JSON metadata for the struct
// [DatasetCaseTagUpdateResponse]
type datasetCaseTagUpdateResponseJSON struct {
	Cases              apijson.Field
	CommitID           apijson.Field
	PublishOperationID apijson.Field
	raw                string
	ExtraFields        map[string]apijson.Field
}

func (r *DatasetCaseTagUpdateResponse) UnmarshalJSON(data []byte) (err error) {
	return apijson.UnmarshalRoot(data, r)
}

func (r datasetCaseTagUpdateResponseJSON) RawJSON() string {
	return r.raw
}

type DatasetCaseTagUpdateResponseCase struct {
	CaseID string                               `json:"case_id" api:"required" format:"uuid"`
	Tags   []string                             `json:"tags"    api:"required"`
	JSON   datasetCaseTagUpdateResponseCaseJSON `json:"-"`
}

// datasetCaseTagUpdateResponseCaseJSON contains the JSON metadata for the struct
// [DatasetCaseTagUpdateResponseCase]
type datasetCaseTagUpdateResponseCaseJSON struct {
	CaseID      apijson.Field
	Tags        apijson.Field
	raw         string
	ExtraFields map[string]apijson.Field
}

func (r *DatasetCaseTagUpdateResponseCase) UnmarshalJSON(data []byte) (err error) {
	return apijson.UnmarshalRoot(data, r)
}

func (r datasetCaseTagUpdateResponseCaseJSON) RawJSON() string {
	return r.raw
}

type DatasetCaseTagUpdateParams struct {
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
	// Tag edits to apply. Each case ID must be unique.
	Cases param.Field[[]DatasetCaseTagUpdateParamsCase] `json:"cases" api:"required"`
}

func (r DatasetCaseTagUpdateParams) MarshalJSON() (data []byte, err error) {
	return apijson.MarshalRoot(r)
}

type DatasetCaseTagUpdateParamsCase struct {
	CaseID param.Field[string] `json:"case_id" api:"required" format:"uuid"`
	// Tag names to add to this case. The service trims each name, drops repeats, and
	// matches names case-sensitively.
	Add param.Field[[]string] `json:"add"`
	// Tag names to remove from this case. The service trims each name, drops repeats,
	// and matches names case-sensitively.
	Remove param.Field[[]string] `json:"remove"`
}

func (r DatasetCaseTagUpdateParamsCase) MarshalJSON() (data []byte, err error) {
	return apijson.MarshalRoot(r)
}
