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

// DatasetVersionCaseService contains methods and other services that help with
// interacting with the CoreWeave Evaluations API.
//
// Note, unlike clients, this service does not read variables from the environment
// automatically. You should not instantiate this service directly, and instead use
// the [NewDatasetVersionCaseService] method instead.
type DatasetVersionCaseService struct {
	Options []option.RequestOption
	Tags    *DatasetVersionCaseTagService
}

// NewDatasetVersionCaseService generates a new service that applies the given
// options to each request. These options are applied after the parent client's
// options (if there is one), and before any request-specific options.
func NewDatasetVersionCaseService(opts ...option.RequestOption) (r *DatasetVersionCaseService) {
	r = &DatasetVersionCaseService{}
	r.Options = opts
	r.Tags = NewDatasetVersionCaseTagService(opts...)
	return
}

// Returns cases in dataset position order unless `order_by` is set.
//
//   - A published version uses its recorded publication cutoff. Cases added later
//     are not included.
//   - A pending version uses the scope's latest published commit on each request.
//     Later pages can include newly published cases.
//
// `filter` and `order_by` use the same syntax as list-eval-table-version-rows,
// without Score columns. Cases with equal sort values stay in dataset position
// order.
//
// Pass the returned `next_cursor` as `cursor` to read the next page, with the same
// `filter` and `order_by`. The last page has no `next_cursor`.
//
// The encoded request target (path and query string) must be at most 8000 bytes.
// Larger requests return 414 URI Too Long with error code `request_uri_too_long`.
// Retry the same parameters through the corresponding POST `/cases/search`
// operation.
func (r *DatasetVersionCaseService) List(
	ctx context.Context,
	datasetVersionID string,
	params DatasetVersionCaseListParams,
	opts ...option.RequestOption,
) (res *DatasetVersionCaseListResponse, err error) {
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
		"v1/namespaces/%s/scopes/%s/dataset-versions/%s/cases",
		params.Namespace,
		params.ScopeID,
		datasetVersionID,
	)
	err = requestconfig.ExecuteNewRequest(ctx, http.MethodGet, path, params, &res, opts...)
	return res, err
}

// Returns the same cases as list-dataset-version-cases, with the filter, sort
// order, and pagination parameters supplied in a JSON body. Use this operation
// when the parameters are too large for a URL.
//
// Request bodies must be at most 1 MiB. Bodies larger than the limit are rejected
// with 413 Request Entity Too Large.
func (r *DatasetVersionCaseService) Search(
	ctx context.Context,
	datasetVersionID string,
	params DatasetVersionCaseSearchParams,
	opts ...option.RequestOption,
) (res *DatasetVersionCaseSearchResponse, err error) {
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
		"v1/namespaces/%s/scopes/%s/dataset-versions/%s/cases/search",
		params.Namespace,
		params.ScopeID,
		datasetVersionID,
	)
	err = requestconfig.ExecuteNewRequest(ctx, http.MethodPost, path, params, &res, opts...)
	return res, err
}

type DatasetVersionCaseListResponse struct {
	Cases      []DatasetVersionCaseListResponseCase `json:"cases"       api:"required"`
	NextCursor string                               `json:"next_cursor"`
	JSON       datasetVersionCaseListResponseJSON   `json:"-"`
}

// datasetVersionCaseListResponseJSON contains the JSON metadata for the struct
// [DatasetVersionCaseListResponse]
type datasetVersionCaseListResponseJSON struct {
	Cases       apijson.Field
	NextCursor  apijson.Field
	raw         string
	ExtraFields map[string]apijson.Field
}

func (r *DatasetVersionCaseListResponse) UnmarshalJSON(data []byte) (err error) {
	return apijson.UnmarshalRoot(data, r)
}

func (r datasetVersionCaseListResponseJSON) RawJSON() string {
	return r.raw
}

type DatasetVersionCaseListResponseCase struct {
	Attributes map[string]interface{} `json:"attributes"  api:"required"`
	CaseID     string                 `json:"case_id"     api:"required"          format:"uuid"`
	CommitID   int64                  `json:"commit_id"   api:"required"`
	ExampleKey string                 `json:"example_key" api:"required,nullable"`
	Input      interface{}            `json:"input"       api:"required"`
	Output     interface{}            `json:"output"      api:"required"`
	// Tag names on this case, sorted.
	Tags    []string                               `json:"tags"    api:"required"`
	Variant string                                 `json:"variant" api:"required,nullable"`
	JSON    datasetVersionCaseListResponseCaseJSON `json:"-"`
}

// datasetVersionCaseListResponseCaseJSON contains the JSON metadata for the struct
// [DatasetVersionCaseListResponseCase]
type datasetVersionCaseListResponseCaseJSON struct {
	Attributes  apijson.Field
	CaseID      apijson.Field
	CommitID    apijson.Field
	ExampleKey  apijson.Field
	Input       apijson.Field
	Output      apijson.Field
	Tags        apijson.Field
	Variant     apijson.Field
	raw         string
	ExtraFields map[string]apijson.Field
}

func (r *DatasetVersionCaseListResponseCase) UnmarshalJSON(data []byte) (err error) {
	return apijson.UnmarshalRoot(data, r)
}

func (r datasetVersionCaseListResponseCaseJSON) RawJSON() string {
	return r.raw
}

type DatasetVersionCaseSearchResponse struct {
	Cases      []DatasetVersionCaseSearchResponseCase `json:"cases"       api:"required"`
	NextCursor string                                 `json:"next_cursor"`
	JSON       datasetVersionCaseSearchResponseJSON   `json:"-"`
}

// datasetVersionCaseSearchResponseJSON contains the JSON metadata for the struct
// [DatasetVersionCaseSearchResponse]
type datasetVersionCaseSearchResponseJSON struct {
	Cases       apijson.Field
	NextCursor  apijson.Field
	raw         string
	ExtraFields map[string]apijson.Field
}

func (r *DatasetVersionCaseSearchResponse) UnmarshalJSON(data []byte) (err error) {
	return apijson.UnmarshalRoot(data, r)
}

func (r datasetVersionCaseSearchResponseJSON) RawJSON() string {
	return r.raw
}

type DatasetVersionCaseSearchResponseCase struct {
	Attributes map[string]interface{} `json:"attributes"  api:"required"`
	CaseID     string                 `json:"case_id"     api:"required"          format:"uuid"`
	CommitID   int64                  `json:"commit_id"   api:"required"`
	ExampleKey string                 `json:"example_key" api:"required,nullable"`
	Input      interface{}            `json:"input"       api:"required"`
	Output     interface{}            `json:"output"      api:"required"`
	// Tag names on this case, sorted.
	Tags    []string                                 `json:"tags"    api:"required"`
	Variant string                                   `json:"variant" api:"required,nullable"`
	JSON    datasetVersionCaseSearchResponseCaseJSON `json:"-"`
}

// datasetVersionCaseSearchResponseCaseJSON contains the JSON metadata for the
// struct [DatasetVersionCaseSearchResponseCase]
type datasetVersionCaseSearchResponseCaseJSON struct {
	Attributes  apijson.Field
	CaseID      apijson.Field
	CommitID    apijson.Field
	ExampleKey  apijson.Field
	Input       apijson.Field
	Output      apijson.Field
	Tags        apijson.Field
	Variant     apijson.Field
	raw         string
	ExtraFields map[string]apijson.Field
}

func (r *DatasetVersionCaseSearchResponseCase) UnmarshalJSON(data []byte) (err error) {
	return apijson.UnmarshalRoot(data, r)
}

func (r datasetVersionCaseSearchResponseCaseJSON) RawJSON() string {
	return r.raw
}

type DatasetVersionCaseListParams struct {
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
	// Selects rows using column comparisons joined with AND, OR, and NOT. Parentheses
	// group expressions. NOT and - bind tighter than AND and OR, and mixing AND and OR
	// at one level needs parentheses. Parentheses nest at most 32 deep.
	//
	// For string comparisons with = or !=, use these patterns:
	//
	//   - matches zero or more characters
	//
	// - matches a literal asterisk \\ matches a literal backslash
	//
	// When rows are cases, the predicate tags:"<name>" matches a case that has that
	// tag.
	//
	// A filter can contain at most 100 predicates and 65,536 bytes of normalized JSON
	// literals in total.
	//
	// Example:
	//
	//	variant = "model-a" AND i.split = "test"
	Filter param.Field[string] `query:"filter"`
	// Maximum number of results to return in one page.
	Limit param.Field[int64] `query:"limit"`
	// Column to sort by, optionally followed by desc for descending order. Without
	// desc, sorting is ascending. Rows cannot be sorted by tags. Omit to use the
	// operation's standard order.
	OrderBy param.Field[string] `query:"order_by"`
}

// URLQuery serializes [DatasetVersionCaseListParams]'s query parameters as
// `url.Values`.
func (r DatasetVersionCaseListParams) URLQuery() (v url.Values) {
	return apiquery.MarshalWithSettings(r, apiquery.QuerySettings{
		ArrayFormat:  apiquery.ArrayQueryFormatComma,
		NestedFormat: apiquery.NestedQueryFormatBrackets,
	})
}

type DatasetVersionCaseSearchParams struct {
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
	Cursor param.Field[string] `json:"cursor"`
	// Selects rows using column comparisons joined with AND, OR, and NOT. Parentheses
	// group expressions. NOT and - bind tighter than AND and OR, and mixing AND and OR
	// at one level needs parentheses. Parentheses nest at most 32 deep.
	//
	// For string comparisons with = or !=, use these patterns:
	//
	//   - matches zero or more characters
	//
	// - matches a literal asterisk \\ matches a literal backslash
	//
	// When rows are cases, the predicate tags:"<name>" matches a case that has that
	// tag.
	//
	// A filter can contain at most 100 predicates and 65,536 bytes of normalized JSON
	// literals in total.
	//
	// Example:
	//
	//	variant = "model-a" AND i.split = "test"
	Filter param.Field[string] `json:"filter"`
	// Maximum number of results to return in one page.
	Limit param.Field[int64] `json:"limit"`
	// Column to sort by, optionally followed by desc for descending order. Without
	// desc, sorting is ascending. Rows cannot be sorted by tags. Omit to use the
	// operation's standard order.
	OrderBy param.Field[string] `json:"order_by"`
}

func (r DatasetVersionCaseSearchParams) MarshalJSON() (data []byte, err error) {
	return apijson.MarshalRoot(r)
}
