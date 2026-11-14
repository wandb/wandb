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

// EvaluationVersionRowService contains methods and other services that help with
// interacting with the CoreWeave Evaluations API.
//
// Note, unlike clients, this service does not read variables from the environment
// automatically. You should not instantiate this service directly, and instead use
// the [NewEvaluationVersionRowService] method instead.
type EvaluationVersionRowService struct {
	Options []option.RequestOption
	Compare *EvaluationVersionRowCompareService
}

// NewEvaluationVersionRowService generates a new service that applies the given
// options to each request. These options are applied after the parent client's
// options (if there is one), and before any request-specific options.
func NewEvaluationVersionRowService(opts ...option.RequestOption) (r *EvaluationVersionRowService) {
	r = &EvaluationVersionRowService{}
	r.Options = opts
	r.Compare = NewEvaluationVersionRowCompareService(opts...)
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
// `o`, and `s`. Quote field names that are not identifiers and escape them as JSON
// strings.
//
// The encoded request target (path and query string) must be at most 8000 bytes.
// Larger requests return 414 URI Too Long with error code `request_uri_too_long`.
// Retry the same parameters through the corresponding POST `/rows/search`
// operation.
func (r *EvaluationVersionRowService) List(
	ctx context.Context,
	evaluationVersionID string,
	params EvaluationVersionRowListParams,
	opts ...option.RequestOption,
) (res *EvaluationVersionRowListResponse, err error) {
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
		"v1/namespaces/%s/scopes/%s/evaluation-versions/%s/rows",
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
// Filtering and sorting happen before pagination. This operation does not create a
// saved query.
//
// Request bodies must be at most 1 MiB. Bodies larger than the limit are rejected
// with 413 Request Entity Too Large.
func (r *EvaluationVersionRowService) Search(
	ctx context.Context,
	evaluationVersionID string,
	params EvaluationVersionRowSearchParams,
	opts ...option.RequestOption,
) (res *EvaluationVersionRowSearchResponse, err error) {
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
		"v1/namespaces/%s/scopes/%s/evaluation-versions/%s/rows/search",
		params.Namespace,
		params.ScopeID,
		evaluationVersionID,
	)
	err = requestconfig.ExecuteNewRequest(ctx, http.MethodPost, path, params, &res, opts...)
	return res, err
}

type EvaluationVersionRowListResponse struct {
	Rows       []EvaluationVersionRowListResponseRow `json:"rows"        api:"required"`
	NextCursor string                                `json:"next_cursor"`
	JSON       evaluationVersionRowListResponseJSON  `json:"-"`
}

// evaluationVersionRowListResponseJSON contains the JSON metadata for the struct
// [EvaluationVersionRowListResponse]
type evaluationVersionRowListResponseJSON struct {
	Rows        apijson.Field
	NextCursor  apijson.Field
	raw         string
	ExtraFields map[string]apijson.Field
}

func (r *EvaluationVersionRowListResponse) UnmarshalJSON(data []byte) (err error) {
	return apijson.UnmarshalRoot(data, r)
}

func (r evaluationVersionRowListResponseJSON) RawJSON() string {
	return r.raw
}

type EvaluationVersionRowListResponseRow struct {
	Attributes map[string]interface{}                      `json:"attributes"  api:"required"`
	CaseID     string                                      `json:"case_id"     api:"required"          format:"uuid"`
	ExampleKey string                                      `json:"example_key" api:"required,nullable"`
	Input      interface{}                                 `json:"input"       api:"required"`
	Output     interface{}                                 `json:"output"      api:"required"`
	Scores     []EvaluationVersionRowListResponseRowsScore `json:"scores"      api:"required"`
	Variant    string                                      `json:"variant"     api:"required,nullable"`
	JSON       evaluationVersionRowListResponseRowJSON     `json:"-"`
}

// evaluationVersionRowListResponseRowJSON contains the JSON metadata for the
// struct [EvaluationVersionRowListResponseRow]
type evaluationVersionRowListResponseRowJSON struct {
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

func (r *EvaluationVersionRowListResponseRow) UnmarshalJSON(data []byte) (err error) {
	return apijson.UnmarshalRoot(data, r)
}

func (r evaluationVersionRowListResponseRowJSON) RawJSON() string {
	return r.raw
}

type EvaluationVersionRowListResponseRowsScore struct {
	ScoreID         string                                        `json:"score_id"          api:"required" format:"uuid"`
	ScorerID        string                                        `json:"scorer_id"         api:"required" format:"uuid"`
	ScorerVersionID string                                        `json:"scorer_version_id" api:"required" format:"uuid"`
	Value           interface{}                                   `json:"value"             api:"required"`
	JSON            evaluationVersionRowListResponseRowsScoreJSON `json:"-"`
}

// evaluationVersionRowListResponseRowsScoreJSON contains the JSON metadata for the
// struct [EvaluationVersionRowListResponseRowsScore]
type evaluationVersionRowListResponseRowsScoreJSON struct {
	ScoreID         apijson.Field
	ScorerID        apijson.Field
	ScorerVersionID apijson.Field
	Value           apijson.Field
	raw             string
	ExtraFields     map[string]apijson.Field
}

func (r *EvaluationVersionRowListResponseRowsScore) UnmarshalJSON(data []byte) (err error) {
	return apijson.UnmarshalRoot(data, r)
}

func (r evaluationVersionRowListResponseRowsScoreJSON) RawJSON() string {
	return r.raw
}

type EvaluationVersionRowSearchResponse struct {
	Rows       []EvaluationVersionRowSearchResponseRow `json:"rows"        api:"required"`
	NextCursor string                                  `json:"next_cursor"`
	JSON       evaluationVersionRowSearchResponseJSON  `json:"-"`
}

// evaluationVersionRowSearchResponseJSON contains the JSON metadata for the struct
// [EvaluationVersionRowSearchResponse]
type evaluationVersionRowSearchResponseJSON struct {
	Rows        apijson.Field
	NextCursor  apijson.Field
	raw         string
	ExtraFields map[string]apijson.Field
}

func (r *EvaluationVersionRowSearchResponse) UnmarshalJSON(data []byte) (err error) {
	return apijson.UnmarshalRoot(data, r)
}

func (r evaluationVersionRowSearchResponseJSON) RawJSON() string {
	return r.raw
}

type EvaluationVersionRowSearchResponseRow struct {
	Attributes map[string]interface{}                        `json:"attributes"  api:"required"`
	CaseID     string                                        `json:"case_id"     api:"required"          format:"uuid"`
	ExampleKey string                                        `json:"example_key" api:"required,nullable"`
	Input      interface{}                                   `json:"input"       api:"required"`
	Output     interface{}                                   `json:"output"      api:"required"`
	Scores     []EvaluationVersionRowSearchResponseRowsScore `json:"scores"      api:"required"`
	Variant    string                                        `json:"variant"     api:"required,nullable"`
	JSON       evaluationVersionRowSearchResponseRowJSON     `json:"-"`
}

// evaluationVersionRowSearchResponseRowJSON contains the JSON metadata for the
// struct [EvaluationVersionRowSearchResponseRow]
type evaluationVersionRowSearchResponseRowJSON struct {
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

func (r *EvaluationVersionRowSearchResponseRow) UnmarshalJSON(data []byte) (err error) {
	return apijson.UnmarshalRoot(data, r)
}

func (r evaluationVersionRowSearchResponseRowJSON) RawJSON() string {
	return r.raw
}

type EvaluationVersionRowSearchResponseRowsScore struct {
	ScoreID         string                                          `json:"score_id"          api:"required" format:"uuid"`
	ScorerID        string                                          `json:"scorer_id"         api:"required" format:"uuid"`
	ScorerVersionID string                                          `json:"scorer_version_id" api:"required" format:"uuid"`
	Value           interface{}                                     `json:"value"             api:"required"`
	JSON            evaluationVersionRowSearchResponseRowsScoreJSON `json:"-"`
}

// evaluationVersionRowSearchResponseRowsScoreJSON contains the JSON metadata for
// the struct [EvaluationVersionRowSearchResponseRowsScore]
type evaluationVersionRowSearchResponseRowsScoreJSON struct {
	ScoreID         apijson.Field
	ScorerID        apijson.Field
	ScorerVersionID apijson.Field
	Value           apijson.Field
	raw             string
	ExtraFields     map[string]apijson.Field
}

func (r *EvaluationVersionRowSearchResponseRowsScore) UnmarshalJSON(data []byte) (err error) {
	return apijson.UnmarshalRoot(data, r)
}

func (r evaluationVersionRowSearchResponseRowsScoreJSON) RawJSON() string {
	return r.raw
}

type EvaluationVersionRowListParams struct {
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

// URLQuery serializes [EvaluationVersionRowListParams]'s query parameters as
// `url.Values`.
func (r EvaluationVersionRowListParams) URLQuery() (v url.Values) {
	return apiquery.MarshalWithSettings(r, apiquery.QuerySettings{
		ArrayFormat:  apiquery.ArrayQueryFormatComma,
		NestedFormat: apiquery.NestedQueryFormatBrackets,
	})
}

type EvaluationVersionRowSearchParams struct {
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

func (r EvaluationVersionRowSearchParams) MarshalJSON() (data []byte, err error) {
	return apijson.MarshalRoot(r)
}
