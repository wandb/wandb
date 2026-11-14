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

// EvaluationRowService contains methods and other services that help with
// interacting with the CoreWeave Evaluations API.
//
// Note, unlike clients, this service does not read variables from the environment
// automatically. You should not instantiate this service directly, and instead use
// the [NewEvaluationRowService] method instead.
type EvaluationRowService struct {
	Options []option.RequestOption
}

// NewEvaluationRowService generates a new service that applies the given options
// to each request. These options are applied after the parent client's options (if
// there is one), and before any request-specific options.
func NewEvaluationRowService(opts ...option.RequestOption) (r *EvaluationRowService) {
	r = &EvaluationRowService{}
	r.Options = opts
	return
}

// Reads the Evaluation's latest data without cutting an EvaluationVersion: the
// registered Scorers and every Score published so far, over the fixed
// DatasetVersion's Cases or every Case published to a live Evaluation's Dataset
// head. The first page pins that data, and later pages read the same Cases and
// Scores. If the Evaluation's Scorer selection changes between pages, such as when
// a new Score column appears, a continuation returns 400 and the read must start
// again without a cursor. `filter` and `order_by` use the same syntax as
// list-evaluation-version-rows.
//
// The encoded request target (path and query string) must be at most 8000 bytes.
// Larger requests return 414 URI Too Long with error code `request_uri_too_long`.
// Retry the same parameters through the corresponding POST `/rows/search`
// operation.
func (r *EvaluationRowService) List(
	ctx context.Context,
	evaluationID string,
	params EvaluationRowListParams,
	opts ...option.RequestOption,
) (res *EvaluationRowListResponse, err error) {
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
	path := fmt.Sprintf(
		"v1/namespaces/%s/scopes/%s/evaluations/%s/rows",
		params.Namespace,
		params.ScopeID,
		evaluationID,
	)
	err = requestconfig.ExecuteNewRequest(ctx, http.MethodGet, path, params, &res, opts...)
	return res, err
}

// Reads the same latest data as list-evaluation-rows. `filter` and `order_by` use
// the same AIP-style syntax as the GET route. Filtering and ordering apply before
// pagination.
//
// Request bodies must be at most 1 MiB. Bodies larger than the limit are rejected
// with 413 Request Entity Too Large.
func (r *EvaluationRowService) Search(
	ctx context.Context,
	evaluationID string,
	params EvaluationRowSearchParams,
	opts ...option.RequestOption,
) (res *EvaluationRowSearchResponse, err error) {
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
	path := fmt.Sprintf(
		"v1/namespaces/%s/scopes/%s/evaluations/%s/rows/search",
		params.Namespace,
		params.ScopeID,
		evaluationID,
	)
	err = requestconfig.ExecuteNewRequest(ctx, http.MethodPost, path, params, &res, opts...)
	return res, err
}

type EvaluationRowListResponse struct {
	Rows       []EvaluationRowListResponseRow `json:"rows"        api:"required"`
	NextCursor string                         `json:"next_cursor"`
	JSON       evaluationRowListResponseJSON  `json:"-"`
}

// evaluationRowListResponseJSON contains the JSON metadata for the struct
// [EvaluationRowListResponse]
type evaluationRowListResponseJSON struct {
	Rows        apijson.Field
	NextCursor  apijson.Field
	raw         string
	ExtraFields map[string]apijson.Field
}

func (r *EvaluationRowListResponse) UnmarshalJSON(data []byte) (err error) {
	return apijson.UnmarshalRoot(data, r)
}

func (r evaluationRowListResponseJSON) RawJSON() string {
	return r.raw
}

type EvaluationRowListResponseRow struct {
	Attributes map[string]interface{}               `json:"attributes"  api:"required"`
	CaseID     string                               `json:"case_id"     api:"required"          format:"uuid"`
	ExampleKey string                               `json:"example_key" api:"required,nullable"`
	Input      interface{}                          `json:"input"       api:"required"`
	Output     interface{}                          `json:"output"      api:"required"`
	Scores     []EvaluationRowListResponseRowsScore `json:"scores"      api:"required"`
	Variant    string                               `json:"variant"     api:"required,nullable"`
	JSON       evaluationRowListResponseRowJSON     `json:"-"`
}

// evaluationRowListResponseRowJSON contains the JSON metadata for the struct
// [EvaluationRowListResponseRow]
type evaluationRowListResponseRowJSON struct {
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

func (r *EvaluationRowListResponseRow) UnmarshalJSON(data []byte) (err error) {
	return apijson.UnmarshalRoot(data, r)
}

func (r evaluationRowListResponseRowJSON) RawJSON() string {
	return r.raw
}

type EvaluationRowListResponseRowsScore struct {
	ScoreID         string                                 `json:"score_id"          api:"required" format:"uuid"`
	ScorerID        string                                 `json:"scorer_id"         api:"required" format:"uuid"`
	ScorerVersionID string                                 `json:"scorer_version_id" api:"required" format:"uuid"`
	Value           interface{}                            `json:"value"             api:"required"`
	JSON            evaluationRowListResponseRowsScoreJSON `json:"-"`
}

// evaluationRowListResponseRowsScoreJSON contains the JSON metadata for the struct
// [EvaluationRowListResponseRowsScore]
type evaluationRowListResponseRowsScoreJSON struct {
	ScoreID         apijson.Field
	ScorerID        apijson.Field
	ScorerVersionID apijson.Field
	Value           apijson.Field
	raw             string
	ExtraFields     map[string]apijson.Field
}

func (r *EvaluationRowListResponseRowsScore) UnmarshalJSON(data []byte) (err error) {
	return apijson.UnmarshalRoot(data, r)
}

func (r evaluationRowListResponseRowsScoreJSON) RawJSON() string {
	return r.raw
}

type EvaluationRowSearchResponse struct {
	Rows       []EvaluationRowSearchResponseRow `json:"rows"        api:"required"`
	NextCursor string                           `json:"next_cursor"`
	JSON       evaluationRowSearchResponseJSON  `json:"-"`
}

// evaluationRowSearchResponseJSON contains the JSON metadata for the struct
// [EvaluationRowSearchResponse]
type evaluationRowSearchResponseJSON struct {
	Rows        apijson.Field
	NextCursor  apijson.Field
	raw         string
	ExtraFields map[string]apijson.Field
}

func (r *EvaluationRowSearchResponse) UnmarshalJSON(data []byte) (err error) {
	return apijson.UnmarshalRoot(data, r)
}

func (r evaluationRowSearchResponseJSON) RawJSON() string {
	return r.raw
}

type EvaluationRowSearchResponseRow struct {
	Attributes map[string]interface{}                 `json:"attributes"  api:"required"`
	CaseID     string                                 `json:"case_id"     api:"required"          format:"uuid"`
	ExampleKey string                                 `json:"example_key" api:"required,nullable"`
	Input      interface{}                            `json:"input"       api:"required"`
	Output     interface{}                            `json:"output"      api:"required"`
	Scores     []EvaluationRowSearchResponseRowsScore `json:"scores"      api:"required"`
	Variant    string                                 `json:"variant"     api:"required,nullable"`
	JSON       evaluationRowSearchResponseRowJSON     `json:"-"`
}

// evaluationRowSearchResponseRowJSON contains the JSON metadata for the struct
// [EvaluationRowSearchResponseRow]
type evaluationRowSearchResponseRowJSON struct {
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

func (r *EvaluationRowSearchResponseRow) UnmarshalJSON(data []byte) (err error) {
	return apijson.UnmarshalRoot(data, r)
}

func (r evaluationRowSearchResponseRowJSON) RawJSON() string {
	return r.raw
}

type EvaluationRowSearchResponseRowsScore struct {
	ScoreID         string                                   `json:"score_id"          api:"required" format:"uuid"`
	ScorerID        string                                   `json:"scorer_id"         api:"required" format:"uuid"`
	ScorerVersionID string                                   `json:"scorer_version_id" api:"required" format:"uuid"`
	Value           interface{}                              `json:"value"             api:"required"`
	JSON            evaluationRowSearchResponseRowsScoreJSON `json:"-"`
}

// evaluationRowSearchResponseRowsScoreJSON contains the JSON metadata for the
// struct [EvaluationRowSearchResponseRowsScore]
type evaluationRowSearchResponseRowsScoreJSON struct {
	ScoreID         apijson.Field
	ScorerID        apijson.Field
	ScorerVersionID apijson.Field
	Value           apijson.Field
	raw             string
	ExtraFields     map[string]apijson.Field
}

func (r *EvaluationRowSearchResponseRowsScore) UnmarshalJSON(data []byte) (err error) {
	return apijson.UnmarshalRoot(data, r)
}

func (r evaluationRowSearchResponseRowsScoreJSON) RawJSON() string {
	return r.raw
}

type EvaluationRowListParams struct {
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

// URLQuery serializes [EvaluationRowListParams]'s query parameters as
// `url.Values`.
func (r EvaluationRowListParams) URLQuery() (v url.Values) {
	return apiquery.MarshalWithSettings(r, apiquery.QuerySettings{
		ArrayFormat:  apiquery.ArrayQueryFormatComma,
		NestedFormat: apiquery.NestedQueryFormatBrackets,
	})
}

type EvaluationRowSearchParams struct {
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

func (r EvaluationRowSearchParams) MarshalJSON() (data []byte, err error) {
	return apijson.MarshalRoot(r)
}
