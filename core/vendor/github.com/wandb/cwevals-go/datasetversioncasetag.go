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

// DatasetVersionCaseTagService contains methods and other services that help with
// interacting with the CoreWeave Evaluations API.
//
// Note, unlike clients, this service does not read variables from the environment
// automatically. You should not instantiate this service directly, and instead use
// the [NewDatasetVersionCaseTagService] method instead.
type DatasetVersionCaseTagService struct {
	Options []option.RequestOption
}

// NewDatasetVersionCaseTagService generates a new service that applies the given
// options to each request. These options are applied after the parent client's
// options (if there is one), and before any request-specific options.
func NewDatasetVersionCaseTagService(opts ...option.RequestOption) (r *DatasetVersionCaseTagService) {
	r = &DatasetVersionCaseTagService{}
	r.Options = opts
	return
}

// Returns every tag on at least one of this version's cases and the number of
// cases that have it, most-used first. Tags with equal `count` are sorted by name.
//
//   - A published version uses its recorded publication cutoff.
//   - A pending version uses the scope's latest published commit at the first page.
//     Later pages read at that same commit, so counts from cases published since
//     then are not included. If the version is published before the listing ends, a
//     later page can return 400. Restart the listing without a cursor.
//
// Pass the returned `next_cursor` as `cursor` to read the next page. The last page
// has no `next_cursor`.
func (r *DatasetVersionCaseTagService) List(
	ctx context.Context,
	datasetVersionID string,
	params DatasetVersionCaseTagListParams,
	opts ...option.RequestOption,
) (res *DatasetVersionCaseTagListResponse, err error) {
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
	if datasetVersionID == "" {
		err = errors.New("missing required dataset_version_id parameter")
		return nil, err
	}
	path := fmt.Sprintf(
		"v1/namespaces/%s/scopes/%s/dataset-versions/%s/cases/tags",
		params.Namespace,
		params.ScopeID,
		datasetVersionID,
	)
	err = requestconfig.ExecuteNewRequest(ctx, http.MethodGet, path, params, &res, opts...)
	return res, err
}

type DatasetVersionCaseTagListResponse struct {
	Tags       []DatasetVersionCaseTagListResponseTag `json:"tags"        api:"required"`
	NextCursor string                                 `json:"next_cursor"`
	JSON       datasetVersionCaseTagListResponseJSON  `json:"-"`
}

// datasetVersionCaseTagListResponseJSON contains the JSON metadata for the struct
// [DatasetVersionCaseTagListResponse]
type datasetVersionCaseTagListResponseJSON struct {
	Tags        apijson.Field
	NextCursor  apijson.Field
	raw         string
	ExtraFields map[string]apijson.Field
}

func (r *DatasetVersionCaseTagListResponse) UnmarshalJSON(data []byte) (err error) {
	return apijson.UnmarshalRoot(data, r)
}

func (r datasetVersionCaseTagListResponseJSON) RawJSON() string {
	return r.raw
}

type DatasetVersionCaseTagListResponseTag struct {
	// Number of cases in this dataset version that have this tag.
	Count int64                                    `json:"count" api:"required"`
	Name  string                                   `json:"name"  api:"required"`
	JSON  datasetVersionCaseTagListResponseTagJSON `json:"-"`
}

// datasetVersionCaseTagListResponseTagJSON contains the JSON metadata for the
// struct [DatasetVersionCaseTagListResponseTag]
type datasetVersionCaseTagListResponseTagJSON struct {
	Count       apijson.Field
	Name        apijson.Field
	raw         string
	ExtraFields map[string]apijson.Field
}

func (r *DatasetVersionCaseTagListResponseTag) UnmarshalJSON(data []byte) (err error) {
	return apijson.UnmarshalRoot(data, r)
}

func (r datasetVersionCaseTagListResponseTagJSON) RawJSON() string {
	return r.raw
}

type DatasetVersionCaseTagListParams struct {
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

// URLQuery serializes [DatasetVersionCaseTagListParams]'s query parameters as
// `url.Values`.
func (r DatasetVersionCaseTagListParams) URLQuery() (v url.Values) {
	return apiquery.MarshalWithSettings(r, apiquery.QuerySettings{
		ArrayFormat:  apiquery.ArrayQueryFormatComma,
		NestedFormat: apiquery.NestedQueryFormatBrackets,
	})
}
