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

// EvalTableRowService contains methods and other services that help with
// interacting with the CoreWeave Evaluations API.
//
// Note, unlike clients, this service does not read variables from the environment
// automatically. You should not instantiate this service directly, and instead use
// the [NewEvalTableRowService] method instead.
type EvalTableRowService struct {
	Options []option.RequestOption
}

// NewEvalTableRowService generates a new service that applies the given options to
// each request. These options are applied after the parent client's options (if
// there is one), and before any request-specific options.
func NewEvalTableRowService(opts ...option.RequestOption) (r *EvalTableRowService) {
	r = &EvalTableRowService{}
	r.Options = opts
	return
}

// Reads every row and Score published so far without cutting a version, so a
// client can read a table while it is still being written. The first page pins
// that data, and later pages read the same rows and Scores. If the Evaluation's
// Scorer selection changes between pages, such as when a new Score column appears,
// a continuation returns 400 and the read must start again without a cursor.
// `filter` and `order_by` use the same syntax as list-eval-table-version-rows.
//
// The encoded request target (path and query string) must be at most 8000 bytes.
// Larger requests return 414 URI Too Long with error code `request_uri_too_long`.
// Retry the same parameters through the corresponding POST `/rows/search`
// operation.
func (r *EvalTableRowService) List(
	ctx context.Context,
	evaluationID string,
	params EvalTableRowListParams,
	opts ...option.RequestOption,
) (res *EvalTableRowListResponse, err error) {
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
		"v1/namespaces/%s/scopes/%s/eval-tables/%s/rows",
		params.Namespace,
		params.ScopeID,
		evaluationID,
	)
	err = requestconfig.ExecuteNewRequest(ctx, http.MethodGet, path, params, &res, opts...)
	return res, err
}

// Stores rows with their inputs, outputs, and named scores. This operation adds
// data without creating a frozen version. A score column whose selected scorer
// version cannot score cases returns 400, and no case is stored.
//
// **Retrying an append:** Cases and scores are published separately. An error can
// occur after the cases have been stored. Retry with the same `Idempotency-Key`
// and the same rows to finish the append without duplicating those cases.
//
// Request bodies must be at most 16 MiB. Bodies larger than the limit are rejected
// with 413 Request Entity Too Large.
func (r *EvalTableRowService) Add(
	ctx context.Context,
	evaluationID string,
	params EvalTableRowAddParams,
	opts ...option.RequestOption,
) (res *EvalTableRowAddResponse, err error) {
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
		"v1/namespaces/%s/scopes/%s/eval-tables/%s/rows",
		params.Namespace,
		params.ScopeID,
		evaluationID,
	)
	err = requestconfig.ExecuteNewRequest(ctx, http.MethodPost, path, params, &res, opts...)
	return res, err
}

// Reads the same latest data as list-eval-table-rows. `filter` and `order_by` use
// the same AIP-style syntax as the GET route. Filtering and ordering apply before
// pagination.
//
// Request bodies must be at most 1 MiB. Bodies larger than the limit are rejected
// with 413 Request Entity Too Large.
func (r *EvalTableRowService) Search(
	ctx context.Context,
	evaluationID string,
	params EvalTableRowSearchParams,
	opts ...option.RequestOption,
) (res *EvalTableRowSearchResponse, err error) {
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
		"v1/namespaces/%s/scopes/%s/eval-tables/%s/rows/search",
		params.Namespace,
		params.ScopeID,
		evaluationID,
	)
	err = requestconfig.ExecuteNewRequest(ctx, http.MethodPost, path, params, &res, opts...)
	return res, err
}

type EvalTableRowListResponse struct {
	Rows       []EvalTableRowListResponseRow `json:"rows"        api:"required"`
	NextCursor string                        `json:"next_cursor"`
	JSON       evalTableRowListResponseJSON  `json:"-"`
}

// evalTableRowListResponseJSON contains the JSON metadata for the struct
// [EvalTableRowListResponse]
type evalTableRowListResponseJSON struct {
	Rows        apijson.Field
	NextCursor  apijson.Field
	raw         string
	ExtraFields map[string]apijson.Field
}

func (r *EvalTableRowListResponse) UnmarshalJSON(data []byte) (err error) {
	return apijson.UnmarshalRoot(data, r)
}

func (r evalTableRowListResponseJSON) RawJSON() string {
	return r.raw
}

type EvalTableRowListResponseRow struct {
	Attributes map[string]interface{}              `json:"attributes"  api:"required"`
	CaseID     string                              `json:"case_id"     api:"required"          format:"uuid"`
	ExampleKey string                              `json:"example_key" api:"required,nullable"`
	Input      interface{}                         `json:"input"       api:"required"`
	Output     interface{}                         `json:"output"      api:"required"`
	Scores     []EvalTableRowListResponseRowsScore `json:"scores"      api:"required"`
	Variant    string                              `json:"variant"     api:"required,nullable"`
	JSON       evalTableRowListResponseRowJSON     `json:"-"`
}

// evalTableRowListResponseRowJSON contains the JSON metadata for the struct
// [EvalTableRowListResponseRow]
type evalTableRowListResponseRowJSON struct {
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

func (r *EvalTableRowListResponseRow) UnmarshalJSON(data []byte) (err error) {
	return apijson.UnmarshalRoot(data, r)
}

func (r evalTableRowListResponseRowJSON) RawJSON() string {
	return r.raw
}

type EvalTableRowListResponseRowsScore struct {
	ID              string                                `json:"id"                api:"required" format:"uuid"`
	ScorerID        string                                `json:"scorer_id"         api:"required" format:"uuid"`
	ScorerVersionID string                                `json:"scorer_version_id" api:"required" format:"uuid"`
	Value           interface{}                           `json:"value"             api:"required"`
	JSON            evalTableRowListResponseRowsScoreJSON `json:"-"`
}

// evalTableRowListResponseRowsScoreJSON contains the JSON metadata for the struct
// [EvalTableRowListResponseRowsScore]
type evalTableRowListResponseRowsScoreJSON struct {
	ID              apijson.Field
	ScorerID        apijson.Field
	ScorerVersionID apijson.Field
	Value           apijson.Field
	raw             string
	ExtraFields     map[string]apijson.Field
}

func (r *EvalTableRowListResponseRowsScore) UnmarshalJSON(data []byte) (err error) {
	return apijson.UnmarshalRoot(data, r)
}

func (r evalTableRowListResponseRowsScoreJSON) RawJSON() string {
	return r.raw
}

type EvalTableRowAddResponse struct {
	CaseIDs  []string                    `json:"case_ids"  api:"required" format:"uuid"`
	ScoreIDs []string                    `json:"score_ids" api:"required" format:"uuid"`
	JSON     evalTableRowAddResponseJSON `json:"-"`
}

// evalTableRowAddResponseJSON contains the JSON metadata for the struct
// [EvalTableRowAddResponse]
type evalTableRowAddResponseJSON struct {
	CaseIDs     apijson.Field
	ScoreIDs    apijson.Field
	raw         string
	ExtraFields map[string]apijson.Field
}

func (r *EvalTableRowAddResponse) UnmarshalJSON(data []byte) (err error) {
	return apijson.UnmarshalRoot(data, r)
}

func (r evalTableRowAddResponseJSON) RawJSON() string {
	return r.raw
}

type EvalTableRowSearchResponse struct {
	Rows       []EvalTableRowSearchResponseRow `json:"rows"        api:"required"`
	NextCursor string                          `json:"next_cursor"`
	JSON       evalTableRowSearchResponseJSON  `json:"-"`
}

// evalTableRowSearchResponseJSON contains the JSON metadata for the struct
// [EvalTableRowSearchResponse]
type evalTableRowSearchResponseJSON struct {
	Rows        apijson.Field
	NextCursor  apijson.Field
	raw         string
	ExtraFields map[string]apijson.Field
}

func (r *EvalTableRowSearchResponse) UnmarshalJSON(data []byte) (err error) {
	return apijson.UnmarshalRoot(data, r)
}

func (r evalTableRowSearchResponseJSON) RawJSON() string {
	return r.raw
}

type EvalTableRowSearchResponseRow struct {
	Attributes map[string]interface{}                `json:"attributes"  api:"required"`
	CaseID     string                                `json:"case_id"     api:"required"          format:"uuid"`
	ExampleKey string                                `json:"example_key" api:"required,nullable"`
	Input      interface{}                           `json:"input"       api:"required"`
	Output     interface{}                           `json:"output"      api:"required"`
	Scores     []EvalTableRowSearchResponseRowsScore `json:"scores"      api:"required"`
	Variant    string                                `json:"variant"     api:"required,nullable"`
	JSON       evalTableRowSearchResponseRowJSON     `json:"-"`
}

// evalTableRowSearchResponseRowJSON contains the JSON metadata for the struct
// [EvalTableRowSearchResponseRow]
type evalTableRowSearchResponseRowJSON struct {
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

func (r *EvalTableRowSearchResponseRow) UnmarshalJSON(data []byte) (err error) {
	return apijson.UnmarshalRoot(data, r)
}

func (r evalTableRowSearchResponseRowJSON) RawJSON() string {
	return r.raw
}

type EvalTableRowSearchResponseRowsScore struct {
	ID              string                                  `json:"id"                api:"required" format:"uuid"`
	ScorerID        string                                  `json:"scorer_id"         api:"required" format:"uuid"`
	ScorerVersionID string                                  `json:"scorer_version_id" api:"required" format:"uuid"`
	Value           interface{}                             `json:"value"             api:"required"`
	JSON            evalTableRowSearchResponseRowsScoreJSON `json:"-"`
}

// evalTableRowSearchResponseRowsScoreJSON contains the JSON metadata for the
// struct [EvalTableRowSearchResponseRowsScore]
type evalTableRowSearchResponseRowsScoreJSON struct {
	ID              apijson.Field
	ScorerID        apijson.Field
	ScorerVersionID apijson.Field
	Value           apijson.Field
	raw             string
	ExtraFields     map[string]apijson.Field
}

func (r *EvalTableRowSearchResponseRowsScore) UnmarshalJSON(data []byte) (err error) {
	return apijson.UnmarshalRoot(data, r)
}

func (r evalTableRowSearchResponseRowsScoreJSON) RawJSON() string {
	return r.raw
}

type EvalTableRowListParams struct {
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

// URLQuery serializes [EvalTableRowListParams]'s query parameters as `url.Values`.
func (r EvalTableRowListParams) URLQuery() (v url.Values) {
	return apiquery.MarshalWithSettings(r, apiquery.QuerySettings{
		ArrayFormat:  apiquery.ArrayQueryFormatComma,
		NestedFormat: apiquery.NestedQueryFormatBrackets,
	})
}

type EvalTableRowAddParams struct {
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
	ScopeID param.Field[string]                     `path:"scope_id" api:"required"`
	Rows    param.Field[[]EvalTableRowAddParamsRow] `                api:"required" json:"rows"`
}

func (r EvalTableRowAddParams) MarshalJSON() (data []byte, err error) {
	return apijson.MarshalRoot(r)
}

type EvalTableRowAddParamsRow struct {
	// Score values keyed by scorer name. Use an empty object for a row with no scores.
	// Keys must not have leading or trailing whitespace.
	Scores     param.Field[map[string]interface{}] `json:"scores"     api:"required"`
	Attributes param.Field[map[string]interface{}] `json:"attributes"`
	// Reference to the row's example in external data, such as a row index, for a row
	// without input.
	//
	//   - The service stores the reference but does not fetch the example.
	//   - Example keys need not be unique. Row comparison matches rows by example key.
	//   - A row with an input must omit it. The service derives that row's example key
	//     from a hash of its input, so row comparison matches rows by input. Each
	//     top-level extension field hashes by its identity, which leaves out file
	//     locations. Numbers hash as float64, so integers that differ only beyond 2^53
	//     derive the same example key, and a number never matches a string. Log numeric
	//     identifiers as strings.
	//   - A row with neither matches only itself, in versions of the same eval table.
	//
	// Omit or send null when no example reference applies.
	ExampleKey param.Field[string] `json:"example_key"`
	// Input data for this case, such as a prompt or feature values.
	//
	// For JSON objects:
	//
	//   - Top-level field names must contain 1 to 512 Unicode characters, with no
	//     leading or trailing whitespace.
	//   - All numeric fields are inferred as number, even whole-valued literals.
	//   - Queries use float64 numbers, which can round integers beyond 2^53. The stored
	//     JSON remains exact.
	//
	// Omit to store null.
	Input param.Field[CaseValueUnionParam] `json:"input"`
	// Output recorded for this case, such as a model response.
	//
	// For JSON objects:
	//
	//   - Top-level field names must contain 1 to 512 Unicode characters, with no
	//     leading or trailing whitespace.
	//   - All numeric fields are inferred as number, even whole-valued literals.
	//   - Queries use float64 numbers, which can round integers beyond 2^53. The stored
	//     JSON remains exact.
	//
	// Omit to store null.
	Output param.Field[CaseValueUnionParam] `json:"output"`
	// Model, agent, prompt, or checkpoint this case evaluates. Leading and trailing
	// whitespace are not allowed. Omit or send null when no variant applies.
	Variant param.Field[string] `json:"variant"`
}

func (r EvalTableRowAddParamsRow) MarshalJSON() (data []byte, err error) {
	return apijson.MarshalRoot(r)
}

type EvalTableRowSearchParams struct {
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

func (r EvalTableRowSearchParams) MarshalJSON() (data []byte, err error) {
	return apijson.MarshalRoot(r)
}
