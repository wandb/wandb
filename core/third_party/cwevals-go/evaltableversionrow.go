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

// EvalTableVersionRowService contains methods and other services that help with
// interacting with the CoreWeave Evaluations API.
//
// Note, unlike clients, this service does not read variables from the environment
// automatically. You should not instantiate this service directly, and instead use
// the [NewEvalTableVersionRowService] method instead.
type EvalTableVersionRowService struct {
	Options []option.RequestOption
	Compare *EvalTableVersionRowCompareService
}

// NewEvalTableVersionRowService generates a new service that applies the given
// options to each request. These options are applied after the parent client's
// options (if there is one), and before any request-specific options.
func NewEvalTableVersionRowService(opts ...option.RequestOption) (r *EvalTableVersionRowService) {
	r = &EvalTableVersionRowService{}
	r.Options = opts
	r.Compare = NewEvalTableVersionRowCompareService(opts...)
	return
}

// Returns cases and their selected scores from the frozen evaluation version.
// Filtering and sorting happen before pagination.
//
// Use these column names in `filter` and `order_by`:
//
//   - `variant` or `example_key` for the row's model/checkpoint label or external
//     example reference.
//   - `i.<name>` for an input field.
//   - `o.<name>` for an output field.
//   - `s.<name>` for a score column.
//
// `input`, `output`, and `score` are also accepted as the longer forms of `i`,
// `o`, and `s`.
//
// The encoded request target (path and query string) must be at most 8000 bytes.
// Larger requests return 414 URI Too Long with error code `request_uri_too_long`.
// Retry the same parameters through the corresponding POST `/rows/search`
// operation.
func (r *EvalTableVersionRowService) List(
	ctx context.Context,
	evaluationVersionID string,
	params EvalTableVersionRowListParams,
	opts ...option.RequestOption,
) (res *EvalTableVersionRowListResponse, err error) {
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
	if evaluationVersionID == "" {
		err = errors.New("missing required evaluation_version_id parameter")
		return nil, err
	}
	path := fmt.Sprintf(
		"v1/namespaces/%s/scopes/%s/eval-table-versions/%s/rows",
		params.Namespace,
		params.ScopeID,
		evaluationVersionID,
	)
	err = requestconfig.ExecuteNewRequest(ctx, http.MethodGet, path, params, &res, opts...)
	return res, err
}

// Returns the same frozen rows as the GET rows operation, with the filter, sort
// order, and pagination parameters supplied in a JSON body.
//
// Filtering and sorting happen before pagination. Use this operation when the
// parameters are too large for a URL.
//
// Request bodies must be at most 1 MiB. Bodies larger than the limit are rejected
// with 413 Request Entity Too Large.
func (r *EvalTableVersionRowService) Search(
	ctx context.Context,
	evaluationVersionID string,
	params EvalTableVersionRowSearchParams,
	opts ...option.RequestOption,
) (res *EvalTableVersionRowSearchResponse, err error) {
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
	if evaluationVersionID == "" {
		err = errors.New("missing required evaluation_version_id parameter")
		return nil, err
	}
	path := fmt.Sprintf(
		"v1/namespaces/%s/scopes/%s/eval-table-versions/%s/rows/search",
		params.Namespace,
		params.ScopeID,
		evaluationVersionID,
	)
	err = requestconfig.ExecuteNewRequest(ctx, http.MethodPost, path, params, &res, opts...)
	return res, err
}

type EvalTableVersionRowListResponse struct {
	Rows       []EvalTableVersionRowListResponseRow `json:"rows"        api:"required"`
	NextCursor string                               `json:"next_cursor"`
	JSON       evalTableVersionRowListResponseJSON  `json:"-"`
}

// evalTableVersionRowListResponseJSON contains the JSON metadata for the struct
// [EvalTableVersionRowListResponse]
type evalTableVersionRowListResponseJSON struct {
	Rows        apijson.Field
	NextCursor  apijson.Field
	raw         string
	ExtraFields map[string]apijson.Field
}

func (r *EvalTableVersionRowListResponse) UnmarshalJSON(data []byte) (err error) {
	return apijson.UnmarshalRoot(data, r)
}

func (r evalTableVersionRowListResponseJSON) RawJSON() string {
	return r.raw
}

type EvalTableVersionRowListResponseRow struct {
	Attributes map[string]interface{}                     `json:"attributes"  api:"required"`
	CaseID     string                                     `json:"case_id"     api:"required"          format:"uuid"`
	ExampleKey string                                     `json:"example_key" api:"required,nullable"`
	Input      interface{}                                `json:"input"       api:"required"`
	Output     interface{}                                `json:"output"      api:"required"`
	Scores     []EvalTableVersionRowListResponseRowsScore `json:"scores"      api:"required"`
	Variant    string                                     `json:"variant"     api:"required,nullable"`
	JSON       evalTableVersionRowListResponseRowJSON     `json:"-"`
}

// evalTableVersionRowListResponseRowJSON contains the JSON metadata for the struct
// [EvalTableVersionRowListResponseRow]
type evalTableVersionRowListResponseRowJSON struct {
	Attributes  apijson.Field
	CaseID      apijson.Field
	ExampleKey  apijson.Field
	Input       apijson.Field
	Output      apijson.Field
	Scores      apijson.Field
	Variant     apijson.Field
	raw         string
	ExtraFields map[string]apijson.Field
}

func (r *EvalTableVersionRowListResponseRow) UnmarshalJSON(data []byte) (err error) {
	return apijson.UnmarshalRoot(data, r)
}

func (r evalTableVersionRowListResponseRowJSON) RawJSON() string {
	return r.raw
}

type EvalTableVersionRowListResponseRowsScore struct {
	ID              string                                       `json:"id"                api:"required" format:"uuid"`
	ScorerID        string                                       `json:"scorer_id"         api:"required" format:"uuid"`
	ScorerVersionID string                                       `json:"scorer_version_id" api:"required" format:"uuid"`
	Value           interface{}                                  `json:"value"             api:"required"`
	JSON            evalTableVersionRowListResponseRowsScoreJSON `json:"-"`
}

// evalTableVersionRowListResponseRowsScoreJSON contains the JSON metadata for the
// struct [EvalTableVersionRowListResponseRowsScore]
type evalTableVersionRowListResponseRowsScoreJSON struct {
	ID              apijson.Field
	ScorerID        apijson.Field
	ScorerVersionID apijson.Field
	Value           apijson.Field
	raw             string
	ExtraFields     map[string]apijson.Field
}

func (r *EvalTableVersionRowListResponseRowsScore) UnmarshalJSON(data []byte) (err error) {
	return apijson.UnmarshalRoot(data, r)
}

func (r evalTableVersionRowListResponseRowsScoreJSON) RawJSON() string {
	return r.raw
}

type EvalTableVersionRowSearchResponse struct {
	Rows       []EvalTableVersionRowSearchResponseRow `json:"rows"        api:"required"`
	NextCursor string                                 `json:"next_cursor"`
	JSON       evalTableVersionRowSearchResponseJSON  `json:"-"`
}

// evalTableVersionRowSearchResponseJSON contains the JSON metadata for the struct
// [EvalTableVersionRowSearchResponse]
type evalTableVersionRowSearchResponseJSON struct {
	Rows        apijson.Field
	NextCursor  apijson.Field
	raw         string
	ExtraFields map[string]apijson.Field
}

func (r *EvalTableVersionRowSearchResponse) UnmarshalJSON(data []byte) (err error) {
	return apijson.UnmarshalRoot(data, r)
}

func (r evalTableVersionRowSearchResponseJSON) RawJSON() string {
	return r.raw
}

type EvalTableVersionRowSearchResponseRow struct {
	Attributes map[string]interface{}                       `json:"attributes"  api:"required"`
	CaseID     string                                       `json:"case_id"     api:"required"          format:"uuid"`
	ExampleKey string                                       `json:"example_key" api:"required,nullable"`
	Input      interface{}                                  `json:"input"       api:"required"`
	Output     interface{}                                  `json:"output"      api:"required"`
	Scores     []EvalTableVersionRowSearchResponseRowsScore `json:"scores"      api:"required"`
	Variant    string                                       `json:"variant"     api:"required,nullable"`
	JSON       evalTableVersionRowSearchResponseRowJSON     `json:"-"`
}

// evalTableVersionRowSearchResponseRowJSON contains the JSON metadata for the
// struct [EvalTableVersionRowSearchResponseRow]
type evalTableVersionRowSearchResponseRowJSON struct {
	Attributes  apijson.Field
	CaseID      apijson.Field
	ExampleKey  apijson.Field
	Input       apijson.Field
	Output      apijson.Field
	Scores      apijson.Field
	Variant     apijson.Field
	raw         string
	ExtraFields map[string]apijson.Field
}

func (r *EvalTableVersionRowSearchResponseRow) UnmarshalJSON(data []byte) (err error) {
	return apijson.UnmarshalRoot(data, r)
}

func (r evalTableVersionRowSearchResponseRowJSON) RawJSON() string {
	return r.raw
}

type EvalTableVersionRowSearchResponseRowsScore struct {
	ID              string                                         `json:"id"                api:"required" format:"uuid"`
	ScorerID        string                                         `json:"scorer_id"         api:"required" format:"uuid"`
	ScorerVersionID string                                         `json:"scorer_version_id" api:"required" format:"uuid"`
	Value           interface{}                                    `json:"value"             api:"required"`
	JSON            evalTableVersionRowSearchResponseRowsScoreJSON `json:"-"`
}

// evalTableVersionRowSearchResponseRowsScoreJSON contains the JSON metadata for
// the struct [EvalTableVersionRowSearchResponseRowsScore]
type evalTableVersionRowSearchResponseRowsScoreJSON struct {
	ID              apijson.Field
	ScorerID        apijson.Field
	ScorerVersionID apijson.Field
	Value           apijson.Field
	raw             string
	ExtraFields     map[string]apijson.Field
}

func (r *EvalTableVersionRowSearchResponseRowsScore) UnmarshalJSON(data []byte) (err error) {
	return apijson.UnmarshalRoot(data, r)
}

func (r evalTableVersionRowSearchResponseRowsScoreJSON) RawJSON() string {
	return r.raw
}

type EvalTableVersionRowListParams struct {
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
	// A filter can contain at most 100 predicates and 65,536 bytes of normalized JSON
	// literals in total.
	//
	// Example for an evaluation with an accuracy score column:
	//
	//	variant = "model-a" AND s.accuracy >= 0.8
	Filter param.Field[string] `query:"filter"`
	// Maximum number of results to return in one page.
	Limit param.Field[int64] `query:"limit"`
	// Column to sort by, optionally followed by desc for descending order. Without
	// desc, sorting is ascending. Omit to use the operation's standard order.
	OrderBy param.Field[string] `query:"order_by"`
}

// URLQuery serializes [EvalTableVersionRowListParams]'s query parameters as
// `url.Values`.
func (r EvalTableVersionRowListParams) URLQuery() (v url.Values) {
	return apiquery.MarshalWithSettings(r, apiquery.QuerySettings{
		ArrayFormat:  apiquery.ArrayQueryFormatComma,
		NestedFormat: apiquery.NestedQueryFormatBrackets,
	})
}

type EvalTableVersionRowSearchParams struct {
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
	// A filter can contain at most 100 predicates and 65,536 bytes of normalized JSON
	// literals in total.
	//
	// Example for an evaluation with an accuracy score column:
	//
	//	variant = "model-a" AND s.accuracy >= 0.8
	Filter param.Field[string] `json:"filter"`
	// Maximum number of results to return in one page.
	Limit param.Field[int64] `json:"limit"`
	// Column to sort by, optionally followed by desc for descending order. Without
	// desc, sorting is ascending. Omit to use the operation's standard order.
	OrderBy param.Field[string] `json:"order_by"`
}

func (r EvalTableVersionRowSearchParams) MarshalJSON() (data []byte, err error) {
	return apijson.MarshalRoot(r)
}
