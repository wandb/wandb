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

// DatasetTrajectoryCaseService contains methods and other services that help with
// interacting with the CoreWeave Evaluations API.
//
// Note, unlike clients, this service does not read variables from the environment
// automatically. You should not instantiate this service directly, and instead use
// the [NewDatasetTrajectoryCaseService] method instead.
type DatasetTrajectoryCaseService struct {
	Options []option.RequestOption
}

// NewDatasetTrajectoryCaseService generates a new service that applies the given
// options to each request. These options are applied after the parent client's
// options (if there is one), and before any request-specific options.
func NewDatasetTrajectoryCaseService(opts ...option.RequestOption) (r *DatasetTrajectoryCaseService) {
	r = &DatasetTrajectoryCaseService{}
	r.Options = opts
	return
}

// Returns the trajectory's published cases in the order they were created. The
// root case is not listed.
//
// Pass the returned `next_cursor` as `cursor` to read the next page. The last page
// has no `next_cursor`.
func (r *DatasetTrajectoryCaseService) List(
	ctx context.Context,
	trajectoryID string,
	params DatasetTrajectoryCaseListParams,
	opts ...option.RequestOption,
) (res *DatasetTrajectoryCaseListResponse, err error) {
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
	if trajectoryID == "" {
		err = errors.New("missing required trajectory_id parameter")
		return nil, err
	}
	path := fmt.Sprintf(
		"v1/namespaces/%s/scopes/%s/trajectories/%s/cases",
		params.Namespace,
		params.ScopeID,
		trajectoryID,
	)
	err = requestconfig.ExecuteNewRequest(ctx, http.MethodGet, path, params, &res, opts...)
	return res, err
}

type DatasetTrajectoryCaseListResponse struct {
	Cases      []DatasetTrajectoryCaseListResponseCase `json:"cases"       api:"required"`
	NextCursor string                                  `json:"next_cursor"`
	JSON       datasetTrajectoryCaseListResponseJSON   `json:"-"`
}

// datasetTrajectoryCaseListResponseJSON contains the JSON metadata for the struct
// [DatasetTrajectoryCaseListResponse]
type datasetTrajectoryCaseListResponseJSON struct {
	Cases       apijson.Field
	NextCursor  apijson.Field
	raw         string
	ExtraFields map[string]apijson.Field
}

func (r *DatasetTrajectoryCaseListResponse) UnmarshalJSON(data []byte) (err error) {
	return apijson.UnmarshalRoot(data, r)
}

func (r datasetTrajectoryCaseListResponseJSON) RawJSON() string {
	return r.raw
}

type DatasetTrajectoryCaseListResponseCase struct {
	Attributes map[string]interface{} `json:"attributes" api:"required"`
	CaseID     string                 `json:"case_id"    api:"required" format:"uuid"`
	// Trajectories nested under this trajectory whose root is this case, in the order
	// they were created. Empty when there are none.
	ChildTrajectoryIDs []string                                  `json:"child_trajectory_ids" api:"required"          format:"uuid"`
	CommitID           int64                                     `json:"commit_id"            api:"required"`
	ExampleKey         string                                    `json:"example_key"          api:"required,nullable"`
	Input              interface{}                               `json:"input"                api:"required"`
	Output             interface{}                               `json:"output"               api:"required"`
	Variant            string                                    `json:"variant"              api:"required,nullable"`
	JSON               datasetTrajectoryCaseListResponseCaseJSON `json:"-"`
}

// datasetTrajectoryCaseListResponseCaseJSON contains the JSON metadata for the
// struct [DatasetTrajectoryCaseListResponseCase]
type datasetTrajectoryCaseListResponseCaseJSON struct {
	Attributes         apijson.Field
	CaseID             apijson.Field
	ChildTrajectoryIDs apijson.Field
	CommitID           apijson.Field
	ExampleKey         apijson.Field
	Input              apijson.Field
	Output             apijson.Field
	Variant            apijson.Field
	raw                string
	ExtraFields        map[string]apijson.Field
}

func (r *DatasetTrajectoryCaseListResponseCase) UnmarshalJSON(data []byte) (err error) {
	return apijson.UnmarshalRoot(data, r)
}

func (r datasetTrajectoryCaseListResponseCaseJSON) RawJSON() string {
	return r.raw
}

type DatasetTrajectoryCaseListParams struct {
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

// URLQuery serializes [DatasetTrajectoryCaseListParams]'s query parameters as
// `url.Values`.
func (r DatasetTrajectoryCaseListParams) URLQuery() (v url.Values) {
	return apiquery.MarshalWithSettings(r, apiquery.QuerySettings{
		ArrayFormat:  apiquery.ArrayQueryFormatComma,
		NestedFormat: apiquery.NestedQueryFormatBrackets,
	})
}
