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

// EvalTableVersionRowCompareService contains methods and other services that help
// with interacting with the CoreWeave Evaluations API.
//
// Note, unlike clients, this service does not read variables from the environment
// automatically. You should not instantiate this service directly, and instead use
// the [NewEvalTableVersionRowCompareService] method instead.
type EvalTableVersionRowCompareService struct {
	Options []option.RequestOption
}

// NewEvalTableVersionRowCompareService generates a new service that applies the
// given options to each request. These options are applied after the parent
// client's options (if there is one), and before any request-specific options.
func NewEvalTableVersionRowCompareService(opts ...option.RequestOption) (r *EvalTableVersionRowCompareService) {
	r = &EvalTableVersionRowCompareService{}
	r.Options = opts
	return
}

// Matches the reference version's rows with each compared version's rows by
// example key, and pages through the union. A case logged without an example key
// but with an input matches by the key derived from that input when it was
// appended as an eval table row or written with `example_key_fields`. Any other
// case without an example key matches only itself, in versions that read its
// dataset. The k-th copy of an example key in one version matches the k-th copy in
// another. Each version reads its cases and selected scores at its own cutoff. A
// row written before the service hashed example keys matches no other row.
//
// `filter` uses the rows operations' columns, without a version qualifier. Each
// version's row is tested on its own, and a row is kept, with every version's
// values, when any version's row passes. A version without a filter column reads
// as null in it.
//
// `order_by` names one column of one compared version, as in
// `v."<evaluation_version_id>".s.accuracy desc` or
// `v."<evaluation_version_id>".example_key`. Rows without that version sort last.
// Without `order_by`, rows follow the reference's order, then each later version's
// rows that earlier versions lack. Filtering and ordering apply before pagination,
// and every page reports the total.
//
// The encoded request target (path and query string) must be at most 8000 bytes.
// Larger requests return 414 URI Too Long with error code `request_uri_too_long`.
// Retry the same parameters through the corresponding POST `/rows/compare/search`
// operation.
func (r *EvalTableVersionRowCompareService) List(
	ctx context.Context,
	evaluationVersionID string,
	params EvalTableVersionRowCompareListParams,
	opts ...option.RequestOption,
) (res *EvalTableVersionRowCompareListResponse, err error) {
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
		"v1/namespaces/%s/scopes/%s/eval-table-versions/%s/rows/compare",
		params.Namespace,
		params.ScopeID,
		evaluationVersionID,
	)
	err = requestconfig.ExecuteNewRequest(ctx, http.MethodGet, path, params, &res, opts...)
	return res, err
}

// Returns the same comparison as compare-eval-table-version-rows, with the
// parameters supplied in a JSON body. Use this operation when the parameters are
// too large for a URL.
//
// Request bodies must be at most 1 MiB. Bodies larger than the limit are rejected
// with 413 Request Entity Too Large.
func (r *EvalTableVersionRowCompareService) Search(
	ctx context.Context,
	evaluationVersionID string,
	params EvalTableVersionRowCompareSearchParams,
	opts ...option.RequestOption,
) (res *EvalTableVersionRowCompareSearchResponse, err error) {
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
		"v1/namespaces/%s/scopes/%s/eval-table-versions/%s/rows/compare/search",
		params.Namespace,
		params.ScopeID,
		evaluationVersionID,
	)
	err = requestconfig.ExecuteNewRequest(ctx, http.MethodPost, path, params, &res, opts...)
	return res, err
}

type EvalTableVersionRowCompareListResponse struct {
	Rows []EvalTableVersionRowCompareListResponseRow `json:"rows" api:"required"`
	// Matched rows across every page.
	TotalRows  int64                                      `json:"total_rows"  api:"required"`
	NextCursor string                                     `json:"next_cursor"`
	JSON       evalTableVersionRowCompareListResponseJSON `json:"-"`
}

// evalTableVersionRowCompareListResponseJSON contains the JSON metadata for the
// struct [EvalTableVersionRowCompareListResponse]
type evalTableVersionRowCompareListResponseJSON struct {
	Rows        apijson.Field
	TotalRows   apijson.Field
	NextCursor  apijson.Field
	raw         string
	ExtraFields map[string]apijson.Field
}

func (r *EvalTableVersionRowCompareListResponse) UnmarshalJSON(data []byte) (err error) {
	return apijson.UnmarshalRoot(data, r)
}

func (r evalTableVersionRowCompareListResponseJSON) RawJSON() string {
	return r.raw
}

type EvalTableVersionRowCompareListResponseRow struct {
	// Identifies the matched row within this comparison: the hash of its example key
	// in hex, a colon, and its occurrence within each version, counted from 0. A row
	// written before the service hashed example keys has its Case ID, a colon, and its
	// version's index in evaluations instead.
	ID string `json:"id" api:"required"`
	// One entry per compared version, reference first.
	Evaluations []EvalTableVersionRowCompareListResponseRowsEvaluation `json:"evaluations" api:"required"`
	// The input of the first version with the row. Rows matched by a client example
	// key can differ in input.
	Input interface{}                                   `json:"input" api:"required"`
	JSON  evalTableVersionRowCompareListResponseRowJSON `json:"-"`
}

// evalTableVersionRowCompareListResponseRowJSON contains the JSON metadata for the
// struct [EvalTableVersionRowCompareListResponseRow]
type evalTableVersionRowCompareListResponseRowJSON struct {
	ID          apijson.Field
	Evaluations apijson.Field
	Input       apijson.Field
	raw         string
	ExtraFields map[string]apijson.Field
}

func (r *EvalTableVersionRowCompareListResponseRow) UnmarshalJSON(data []byte) (err error) {
	return apijson.UnmarshalRoot(data, r)
}

func (r evalTableVersionRowCompareListResponseRowJSON) RawJSON() string {
	return r.raw
}

type EvalTableVersionRowCompareListResponseRowsEvaluation struct {
	EvaluationVersionID string `json:"evaluation_version_id" api:"required" format:"uuid"`
	// Absent when this version has no row with the example key.
	Row  EvalTableVersionRowCompareListResponseRowsEvaluationsRow `json:"row"`
	JSON evalTableVersionRowCompareListResponseRowsEvaluationJSON `json:"-"`
}

// evalTableVersionRowCompareListResponseRowsEvaluationJSON contains the JSON
// metadata for the struct [EvalTableVersionRowCompareListResponseRowsEvaluation]
type evalTableVersionRowCompareListResponseRowsEvaluationJSON struct {
	EvaluationVersionID apijson.Field
	Row                 apijson.Field
	raw                 string
	ExtraFields         map[string]apijson.Field
}

func (r *EvalTableVersionRowCompareListResponseRowsEvaluation) UnmarshalJSON(data []byte) (err error) {
	return apijson.UnmarshalRoot(data, r)
}

func (r evalTableVersionRowCompareListResponseRowsEvaluationJSON) RawJSON() string {
	return r.raw
}

// Absent when this version has no row with the example key.
type EvalTableVersionRowCompareListResponseRowsEvaluationsRow struct {
	Attributes map[string]interface{}                                          `json:"attributes"  api:"required"`
	CaseID     string                                                          `json:"case_id"     api:"required"          format:"uuid"`
	ExampleKey string                                                          `json:"example_key" api:"required,nullable"`
	Output     interface{}                                                     `json:"output"      api:"required"`
	Scores     []EvalTableVersionRowCompareListResponseRowsEvaluationsRowScore `json:"scores"      api:"required"`
	Variant    string                                                          `json:"variant"     api:"required,nullable"`
	JSON       evalTableVersionRowCompareListResponseRowsEvaluationsRowJSON    `json:"-"`
}

// evalTableVersionRowCompareListResponseRowsEvaluationsRowJSON contains the JSON
// metadata for the struct
// [EvalTableVersionRowCompareListResponseRowsEvaluationsRow]
type evalTableVersionRowCompareListResponseRowsEvaluationsRowJSON struct {
	Attributes  apijson.Field
	CaseID      apijson.Field
	ExampleKey  apijson.Field
	Output      apijson.Field
	Scores      apijson.Field
	Variant     apijson.Field
	raw         string
	ExtraFields map[string]apijson.Field
}

func (r *EvalTableVersionRowCompareListResponseRowsEvaluationsRow) UnmarshalJSON(data []byte) (err error) {
	return apijson.UnmarshalRoot(data, r)
}

func (r evalTableVersionRowCompareListResponseRowsEvaluationsRowJSON) RawJSON() string {
	return r.raw
}

type EvalTableVersionRowCompareListResponseRowsEvaluationsRowScore struct {
	ID              string                                                            `json:"id"                api:"required" format:"uuid"`
	ScorerID        string                                                            `json:"scorer_id"         api:"required" format:"uuid"`
	ScorerVersionID string                                                            `json:"scorer_version_id" api:"required" format:"uuid"`
	Value           interface{}                                                       `json:"value"             api:"required"`
	JSON            evalTableVersionRowCompareListResponseRowsEvaluationsRowScoreJSON `json:"-"`
}

// evalTableVersionRowCompareListResponseRowsEvaluationsRowScoreJSON contains the
// JSON metadata for the struct
// [EvalTableVersionRowCompareListResponseRowsEvaluationsRowScore]
type evalTableVersionRowCompareListResponseRowsEvaluationsRowScoreJSON struct {
	ID              apijson.Field
	ScorerID        apijson.Field
	ScorerVersionID apijson.Field
	Value           apijson.Field
	raw             string
	ExtraFields     map[string]apijson.Field
}

func (r *EvalTableVersionRowCompareListResponseRowsEvaluationsRowScore) UnmarshalJSON(data []byte) (err error) {
	return apijson.UnmarshalRoot(data, r)
}

func (r evalTableVersionRowCompareListResponseRowsEvaluationsRowScoreJSON) RawJSON() string {
	return r.raw
}

type EvalTableVersionRowCompareSearchResponse struct {
	Rows []EvalTableVersionRowCompareSearchResponseRow `json:"rows" api:"required"`
	// Matched rows across every page.
	TotalRows  int64                                        `json:"total_rows"  api:"required"`
	NextCursor string                                       `json:"next_cursor"`
	JSON       evalTableVersionRowCompareSearchResponseJSON `json:"-"`
}

// evalTableVersionRowCompareSearchResponseJSON contains the JSON metadata for the
// struct [EvalTableVersionRowCompareSearchResponse]
type evalTableVersionRowCompareSearchResponseJSON struct {
	Rows        apijson.Field
	TotalRows   apijson.Field
	NextCursor  apijson.Field
	raw         string
	ExtraFields map[string]apijson.Field
}

func (r *EvalTableVersionRowCompareSearchResponse) UnmarshalJSON(data []byte) (err error) {
	return apijson.UnmarshalRoot(data, r)
}

func (r evalTableVersionRowCompareSearchResponseJSON) RawJSON() string {
	return r.raw
}

type EvalTableVersionRowCompareSearchResponseRow struct {
	// Identifies the matched row within this comparison: the hash of its example key
	// in hex, a colon, and its occurrence within each version, counted from 0. A row
	// written before the service hashed example keys has its Case ID, a colon, and its
	// version's index in evaluations instead.
	ID string `json:"id" api:"required"`
	// One entry per compared version, reference first.
	Evaluations []EvalTableVersionRowCompareSearchResponseRowsEvaluation `json:"evaluations" api:"required"`
	// The input of the first version with the row. Rows matched by a client example
	// key can differ in input.
	Input interface{}                                     `json:"input" api:"required"`
	JSON  evalTableVersionRowCompareSearchResponseRowJSON `json:"-"`
}

// evalTableVersionRowCompareSearchResponseRowJSON contains the JSON metadata for
// the struct [EvalTableVersionRowCompareSearchResponseRow]
type evalTableVersionRowCompareSearchResponseRowJSON struct {
	ID          apijson.Field
	Evaluations apijson.Field
	Input       apijson.Field
	raw         string
	ExtraFields map[string]apijson.Field
}

func (r *EvalTableVersionRowCompareSearchResponseRow) UnmarshalJSON(data []byte) (err error) {
	return apijson.UnmarshalRoot(data, r)
}

func (r evalTableVersionRowCompareSearchResponseRowJSON) RawJSON() string {
	return r.raw
}

type EvalTableVersionRowCompareSearchResponseRowsEvaluation struct {
	EvaluationVersionID string `json:"evaluation_version_id" api:"required" format:"uuid"`
	// Absent when this version has no row with the example key.
	Row  EvalTableVersionRowCompareSearchResponseRowsEvaluationsRow `json:"row"`
	JSON evalTableVersionRowCompareSearchResponseRowsEvaluationJSON `json:"-"`
}

// evalTableVersionRowCompareSearchResponseRowsEvaluationJSON contains the JSON
// metadata for the struct [EvalTableVersionRowCompareSearchResponseRowsEvaluation]
type evalTableVersionRowCompareSearchResponseRowsEvaluationJSON struct {
	EvaluationVersionID apijson.Field
	Row                 apijson.Field
	raw                 string
	ExtraFields         map[string]apijson.Field
}

func (r *EvalTableVersionRowCompareSearchResponseRowsEvaluation) UnmarshalJSON(data []byte) (err error) {
	return apijson.UnmarshalRoot(data, r)
}

func (r evalTableVersionRowCompareSearchResponseRowsEvaluationJSON) RawJSON() string {
	return r.raw
}

// Absent when this version has no row with the example key.
type EvalTableVersionRowCompareSearchResponseRowsEvaluationsRow struct {
	Attributes map[string]interface{}                                            `json:"attributes"  api:"required"`
	CaseID     string                                                            `json:"case_id"     api:"required"          format:"uuid"`
	ExampleKey string                                                            `json:"example_key" api:"required,nullable"`
	Output     interface{}                                                       `json:"output"      api:"required"`
	Scores     []EvalTableVersionRowCompareSearchResponseRowsEvaluationsRowScore `json:"scores"      api:"required"`
	Variant    string                                                            `json:"variant"     api:"required,nullable"`
	JSON       evalTableVersionRowCompareSearchResponseRowsEvaluationsRowJSON    `json:"-"`
}

// evalTableVersionRowCompareSearchResponseRowsEvaluationsRowJSON contains the JSON
// metadata for the struct
// [EvalTableVersionRowCompareSearchResponseRowsEvaluationsRow]
type evalTableVersionRowCompareSearchResponseRowsEvaluationsRowJSON struct {
	Attributes  apijson.Field
	CaseID      apijson.Field
	ExampleKey  apijson.Field
	Output      apijson.Field
	Scores      apijson.Field
	Variant     apijson.Field
	raw         string
	ExtraFields map[string]apijson.Field
}

func (r *EvalTableVersionRowCompareSearchResponseRowsEvaluationsRow) UnmarshalJSON(data []byte) (err error) {
	return apijson.UnmarshalRoot(data, r)
}

func (r evalTableVersionRowCompareSearchResponseRowsEvaluationsRowJSON) RawJSON() string {
	return r.raw
}

type EvalTableVersionRowCompareSearchResponseRowsEvaluationsRowScore struct {
	ID              string                                                              `json:"id"                api:"required" format:"uuid"`
	ScorerID        string                                                              `json:"scorer_id"         api:"required" format:"uuid"`
	ScorerVersionID string                                                              `json:"scorer_version_id" api:"required" format:"uuid"`
	Value           interface{}                                                         `json:"value"             api:"required"`
	JSON            evalTableVersionRowCompareSearchResponseRowsEvaluationsRowScoreJSON `json:"-"`
}

// evalTableVersionRowCompareSearchResponseRowsEvaluationsRowScoreJSON contains the
// JSON metadata for the struct
// [EvalTableVersionRowCompareSearchResponseRowsEvaluationsRowScore]
type evalTableVersionRowCompareSearchResponseRowsEvaluationsRowScoreJSON struct {
	ID              apijson.Field
	ScorerID        apijson.Field
	ScorerVersionID apijson.Field
	Value           apijson.Field
	raw             string
	ExtraFields     map[string]apijson.Field
}

func (r *EvalTableVersionRowCompareSearchResponseRowsEvaluationsRowScore) UnmarshalJSON(data []byte) (err error) {
	return apijson.UnmarshalRoot(data, r)
}

func (r evalTableVersionRowCompareSearchResponseRowsEvaluationsRowScoreJSON) RawJSON() string {
	return r.raw
}

type EvalTableVersionRowCompareListParams struct {
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
	// Comma-separated EvaluationVersion IDs to compare with the reference, in result
	// order.
	CompareTo param.Field[[]string] `query:"compare_to" api:"required"`
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

// URLQuery serializes [EvalTableVersionRowCompareListParams]'s query parameters as
// `url.Values`.
func (r EvalTableVersionRowCompareListParams) URLQuery() (v url.Values) {
	return apiquery.MarshalWithSettings(r, apiquery.QuerySettings{
		ArrayFormat:  apiquery.ArrayQueryFormatComma,
		NestedFormat: apiquery.NestedQueryFormatBrackets,
	})
}

type EvalTableVersionRowCompareSearchParams struct {
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
	// EvaluationVersion IDs to compare with the reference, in result order.
	CompareTo param.Field[[]string] `json:"compare_to" api:"required" format:"uuid"`
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

func (r EvalTableVersionRowCompareSearchParams) MarshalJSON() (data []byte, err error) {
	return apijson.MarshalRoot(r)
}
