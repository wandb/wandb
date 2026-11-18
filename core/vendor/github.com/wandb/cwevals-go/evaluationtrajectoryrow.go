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

// EvaluationTrajectoryRowService contains methods and other services that help
// with interacting with the CoreWeave Evaluations API.
//
// Note, unlike clients, this service does not read variables from the environment
// automatically. You should not instantiate this service directly, and instead use
// the [NewEvaluationTrajectoryRowService] method instead.
type EvaluationTrajectoryRowService struct {
	Options []option.RequestOption
}

// NewEvaluationTrajectoryRowService generates a new service that applies the given
// options to each request. These options are applied after the parent client's
// options (if there is one), and before any request-specific options.
func NewEvaluationTrajectoryRowService(opts ...option.RequestOption) (r *EvaluationTrajectoryRowService) {
	r = &EvaluationTrajectoryRowService{}
	r.Options = opts
	return
}

// Reads the evaluation's latest data without cutting an evaluation version. The
// rows are the trajectories published to a live evaluation's dataset head, or in a
// fixed evaluation's dataset version, that match `filter`, in `order_by` order or
// else in the order the trajectories were created. Child trajectories are rows
// too. Each row holds the trajectory, its root case, and the newest published
// score of each scorer the evaluation selects. The evaluation's
// `primary_target_kind` must be `trajectory`.
//
// Use these column names in `filter` and `order_by`:
//
//   - `name`, `depth`, or `parent_trajectory_id` for the trajectory's own fields.
//     `parent_trajectory_id` is null for a top-level trajectory. Compare it with a
//     whole trajectory ID in either letter case. Any other string, including a
//     wildcard pattern, returns 400.
//   - `variant`, `i.<name>`, or `o.<name>` for the root case's variant or one of its
//     input or output fields.
//   - `s.<name>` for the trajectory's score from a selected scorer.
//
// `input`, `output`, and `score` are also accepted as the longer forms of `i`,
// `o`, and `s`. Filtering and sorting happen before pagination.
//
// Pass the returned `next_cursor` as `cursor`, with the same `filter` and
// `order_by`, to read the next page. The last page has no `next_cursor`. The first
// page pins that data, and later pages read the same trajectories and scores. If
// the evaluation's scorer selection changes between pages, a continuation returns
// 400 and the read must start again without a cursor.
//
// The encoded request target (path and query string) must be at most 8000 bytes.
// Larger requests return 414 URI Too Long with error code `request_uri_too_long`.
// Retry the same parameters through the corresponding POST
// `/trajectory-rows/search` operation.
func (r *EvaluationTrajectoryRowService) List(
	ctx context.Context,
	evaluationID string,
	params EvaluationTrajectoryRowListParams,
	opts ...option.RequestOption,
) (res *EvaluationTrajectoryRowListResponse, err error) {
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
		"v1/namespaces/%s/scopes/%s/evaluations/%s/trajectory-rows",
		params.Namespace,
		params.ScopeID,
		evaluationID,
	)
	err = requestconfig.ExecuteNewRequest(ctx, http.MethodGet, path, params, &res, opts...)
	return res, err
}

// Returns the trajectory's row as a new list-trajectory-rows read returns it. Each
// read sees the scores published by then, so two reads can differ. The trajectory
// must be in the evaluation's dataset: published to a live evaluation's dataset
// head, or in a fixed evaluation's dataset version. Child trajectories are rows
// too. Any other trajectory returns 404. The evaluation's `primary_target_kind`
// must be `trajectory`.
func (r *EvaluationTrajectoryRowService) Get(
	ctx context.Context,
	evaluationID string,
	trajectoryID string,
	query EvaluationTrajectoryRowGetParams,
	opts ...option.RequestOption,
) (res *EvaluationTrajectoryRowGetResponse, err error) {
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
	if evaluationID == "" {
		err = errors.New("missing required evaluation_id parameter")
		return nil, err
	}
	if trajectoryID == "" {
		err = errors.New("missing required trajectory_id parameter")
		return nil, err
	}
	path := fmt.Sprintf(
		"v1/namespaces/%s/scopes/%s/evaluations/%s/trajectory-rows/%s",
		query.Namespace,
		query.ScopeID,
		evaluationID,
		trajectoryID,
	)
	err = requestconfig.ExecuteNewRequest(ctx, http.MethodGet, path, nil, &res, opts...)
	return res, err
}

// Reads the same latest trajectory rows as list-trajectory-rows, with `filter`,
// `order_by`, `limit`, and `cursor` in a JSON body. `filter` and `order_by` take
// the same columns, and a `next_cursor` from either operation continues on the
// other with the same `filter` and `order_by`. Filtering and sorting happen before
// pagination.
//
// Request bodies must be at most 1 MiB. Bodies larger than the limit are rejected
// with 413 Request Entity Too Large.
func (r *EvaluationTrajectoryRowService) Search(
	ctx context.Context,
	evaluationID string,
	params EvaluationTrajectoryRowSearchParams,
	opts ...option.RequestOption,
) (res *EvaluationTrajectoryRowSearchResponse, err error) {
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
		"v1/namespaces/%s/scopes/%s/evaluations/%s/trajectory-rows/search",
		params.Namespace,
		params.ScopeID,
		evaluationID,
	)
	err = requestconfig.ExecuteNewRequest(ctx, http.MethodPost, path, params, &res, opts...)
	return res, err
}

type EvaluationTrajectoryRowListResponse struct {
	Rows       []EvaluationTrajectoryRowListResponseRow `json:"rows"        api:"required"`
	NextCursor string                                   `json:"next_cursor"`
	JSON       evaluationTrajectoryRowListResponseJSON  `json:"-"`
}

// evaluationTrajectoryRowListResponseJSON contains the JSON metadata for the
// struct [EvaluationTrajectoryRowListResponse]
type evaluationTrajectoryRowListResponseJSON struct {
	Rows        apijson.Field
	NextCursor  apijson.Field
	raw         string
	ExtraFields map[string]apijson.Field
}

func (r *EvaluationTrajectoryRowListResponse) UnmarshalJSON(data []byte) (err error) {
	return apijson.UnmarshalRoot(data, r)
}

func (r evaluationTrajectoryRowListResponseJSON) RawJSON() string {
	return r.raw
}

type EvaluationTrajectoryRowListResponseRow struct {
	// The case the trajectory starts from.
	RootCase EvaluationTrajectoryRowListResponseRowsRootCase `json:"root_case" api:"required"`
	// The newest score of each scorer the evaluation selects, in selection order. A
	// scorer with no score on this trajectory is left out.
	Scores     []EvaluationTrajectoryRowListResponseRowsScore    `json:"scores"     api:"required"`
	Trajectory EvaluationTrajectoryRowListResponseRowsTrajectory `json:"trajectory" api:"required"`
	JSON       evaluationTrajectoryRowListResponseRowJSON        `json:"-"`
}

// evaluationTrajectoryRowListResponseRowJSON contains the JSON metadata for the
// struct [EvaluationTrajectoryRowListResponseRow]
type evaluationTrajectoryRowListResponseRowJSON struct {
	RootCase    apijson.Field
	Scores      apijson.Field
	Trajectory  apijson.Field
	raw         string
	ExtraFields map[string]apijson.Field
}

func (r *EvaluationTrajectoryRowListResponseRow) UnmarshalJSON(data []byte) (err error) {
	return apijson.UnmarshalRoot(data, r)
}

func (r evaluationTrajectoryRowListResponseRowJSON) RawJSON() string {
	return r.raw
}

// The case the trajectory starts from.
type EvaluationTrajectoryRowListResponseRowsRootCase struct {
	Attributes map[string]interface{} `json:"attributes"  api:"required"`
	CaseID     string                 `json:"case_id"     api:"required"          format:"uuid"`
	CommitID   int64                  `json:"commit_id"   api:"required"`
	ExampleKey string                 `json:"example_key" api:"required,nullable"`
	Input      interface{}            `json:"input"       api:"required"`
	Output     interface{}            `json:"output"      api:"required"`
	// Tag names on this case, sorted.
	Tags    []string                                            `json:"tags"    api:"required"`
	Variant string                                              `json:"variant" api:"required,nullable"`
	JSON    evaluationTrajectoryRowListResponseRowsRootCaseJSON `json:"-"`
}

// evaluationTrajectoryRowListResponseRowsRootCaseJSON contains the JSON metadata
// for the struct [EvaluationTrajectoryRowListResponseRowsRootCase]
type evaluationTrajectoryRowListResponseRowsRootCaseJSON struct {
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

func (r *EvaluationTrajectoryRowListResponseRowsRootCase) UnmarshalJSON(data []byte) (err error) {
	return apijson.UnmarshalRoot(data, r)
}

func (r evaluationTrajectoryRowListResponseRowsRootCaseJSON) RawJSON() string {
	return r.raw
}

type EvaluationTrajectoryRowListResponseRowsScore struct {
	ScoreID         string                                           `json:"score_id"          api:"required" format:"uuid"`
	ScorerID        string                                           `json:"scorer_id"         api:"required" format:"uuid"`
	ScorerVersionID string                                           `json:"scorer_version_id" api:"required" format:"uuid"`
	Value           interface{}                                      `json:"value"             api:"required"`
	JSON            evaluationTrajectoryRowListResponseRowsScoreJSON `json:"-"`
}

// evaluationTrajectoryRowListResponseRowsScoreJSON contains the JSON metadata for
// the struct [EvaluationTrajectoryRowListResponseRowsScore]
type evaluationTrajectoryRowListResponseRowsScoreJSON struct {
	ScoreID         apijson.Field
	ScorerID        apijson.Field
	ScorerVersionID apijson.Field
	Value           apijson.Field
	raw             string
	ExtraFields     map[string]apijson.Field
}

func (r *EvaluationTrajectoryRowListResponseRowsScore) UnmarshalJSON(data []byte) (err error) {
	return apijson.UnmarshalRoot(data, r)
}

func (r evaluationTrajectoryRowListResponseRowsScoreJSON) RawJSON() string {
	return r.raw
}

type EvaluationTrajectoryRowListResponseRowsTrajectory struct {
	CommitID  int64  `json:"commit_id"  api:"required"`
	DatasetID string `json:"dataset_id" api:"required" format:"uuid"`
	// 0 for a top-level trajectory, otherwise one more than its parent's.
	Depth int64  `json:"depth" api:"required"`
	Name  string `json:"name"  api:"required"`
	// Null for a top-level trajectory.
	ParentTrajectoryID string                                                `json:"parent_trajectory_id" api:"required,nullable" format:"uuid"`
	RootCaseID         string                                                `json:"root_case_id"         api:"required"          format:"uuid"`
	TrajectoryID       string                                                `json:"trajectory_id"        api:"required"          format:"uuid"`
	JSON               evaluationTrajectoryRowListResponseRowsTrajectoryJSON `json:"-"`
}

// evaluationTrajectoryRowListResponseRowsTrajectoryJSON contains the JSON metadata
// for the struct [EvaluationTrajectoryRowListResponseRowsTrajectory]
type evaluationTrajectoryRowListResponseRowsTrajectoryJSON struct {
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

func (r *EvaluationTrajectoryRowListResponseRowsTrajectory) UnmarshalJSON(data []byte) (err error) {
	return apijson.UnmarshalRoot(data, r)
}

func (r evaluationTrajectoryRowListResponseRowsTrajectoryJSON) RawJSON() string {
	return r.raw
}

type EvaluationTrajectoryRowGetResponse struct {
	// The case the trajectory starts from.
	RootCase EvaluationTrajectoryRowGetResponseRootCase `json:"root_case" api:"required"`
	// The newest score of each scorer the evaluation selects, in selection order. A
	// scorer with no score on this trajectory is left out.
	Scores     []EvaluationTrajectoryRowGetResponseScore    `json:"scores"     api:"required"`
	Trajectory EvaluationTrajectoryRowGetResponseTrajectory `json:"trajectory" api:"required"`
	JSON       evaluationTrajectoryRowGetResponseJSON       `json:"-"`
}

// evaluationTrajectoryRowGetResponseJSON contains the JSON metadata for the struct
// [EvaluationTrajectoryRowGetResponse]
type evaluationTrajectoryRowGetResponseJSON struct {
	RootCase    apijson.Field
	Scores      apijson.Field
	Trajectory  apijson.Field
	raw         string
	ExtraFields map[string]apijson.Field
}

func (r *EvaluationTrajectoryRowGetResponse) UnmarshalJSON(data []byte) (err error) {
	return apijson.UnmarshalRoot(data, r)
}

func (r evaluationTrajectoryRowGetResponseJSON) RawJSON() string {
	return r.raw
}

// The case the trajectory starts from.
type EvaluationTrajectoryRowGetResponseRootCase struct {
	Attributes map[string]interface{} `json:"attributes"  api:"required"`
	CaseID     string                 `json:"case_id"     api:"required"          format:"uuid"`
	CommitID   int64                  `json:"commit_id"   api:"required"`
	ExampleKey string                 `json:"example_key" api:"required,nullable"`
	Input      interface{}            `json:"input"       api:"required"`
	Output     interface{}            `json:"output"      api:"required"`
	// Tag names on this case, sorted.
	Tags    []string                                       `json:"tags"    api:"required"`
	Variant string                                         `json:"variant" api:"required,nullable"`
	JSON    evaluationTrajectoryRowGetResponseRootCaseJSON `json:"-"`
}

// evaluationTrajectoryRowGetResponseRootCaseJSON contains the JSON metadata for
// the struct [EvaluationTrajectoryRowGetResponseRootCase]
type evaluationTrajectoryRowGetResponseRootCaseJSON struct {
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

func (r *EvaluationTrajectoryRowGetResponseRootCase) UnmarshalJSON(data []byte) (err error) {
	return apijson.UnmarshalRoot(data, r)
}

func (r evaluationTrajectoryRowGetResponseRootCaseJSON) RawJSON() string {
	return r.raw
}

type EvaluationTrajectoryRowGetResponseScore struct {
	ScoreID         string                                      `json:"score_id"          api:"required" format:"uuid"`
	ScorerID        string                                      `json:"scorer_id"         api:"required" format:"uuid"`
	ScorerVersionID string                                      `json:"scorer_version_id" api:"required" format:"uuid"`
	Value           interface{}                                 `json:"value"             api:"required"`
	JSON            evaluationTrajectoryRowGetResponseScoreJSON `json:"-"`
}

// evaluationTrajectoryRowGetResponseScoreJSON contains the JSON metadata for the
// struct [EvaluationTrajectoryRowGetResponseScore]
type evaluationTrajectoryRowGetResponseScoreJSON struct {
	ScoreID         apijson.Field
	ScorerID        apijson.Field
	ScorerVersionID apijson.Field
	Value           apijson.Field
	raw             string
	ExtraFields     map[string]apijson.Field
}

func (r *EvaluationTrajectoryRowGetResponseScore) UnmarshalJSON(data []byte) (err error) {
	return apijson.UnmarshalRoot(data, r)
}

func (r evaluationTrajectoryRowGetResponseScoreJSON) RawJSON() string {
	return r.raw
}

type EvaluationTrajectoryRowGetResponseTrajectory struct {
	CommitID  int64  `json:"commit_id"  api:"required"`
	DatasetID string `json:"dataset_id" api:"required" format:"uuid"`
	// 0 for a top-level trajectory, otherwise one more than its parent's.
	Depth int64  `json:"depth" api:"required"`
	Name  string `json:"name"  api:"required"`
	// Null for a top-level trajectory.
	ParentTrajectoryID string                                           `json:"parent_trajectory_id" api:"required,nullable" format:"uuid"`
	RootCaseID         string                                           `json:"root_case_id"         api:"required"          format:"uuid"`
	TrajectoryID       string                                           `json:"trajectory_id"        api:"required"          format:"uuid"`
	JSON               evaluationTrajectoryRowGetResponseTrajectoryJSON `json:"-"`
}

// evaluationTrajectoryRowGetResponseTrajectoryJSON contains the JSON metadata for
// the struct [EvaluationTrajectoryRowGetResponseTrajectory]
type evaluationTrajectoryRowGetResponseTrajectoryJSON struct {
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

func (r *EvaluationTrajectoryRowGetResponseTrajectory) UnmarshalJSON(data []byte) (err error) {
	return apijson.UnmarshalRoot(data, r)
}

func (r evaluationTrajectoryRowGetResponseTrajectoryJSON) RawJSON() string {
	return r.raw
}

type EvaluationTrajectoryRowSearchResponse struct {
	Rows       []EvaluationTrajectoryRowSearchResponseRow `json:"rows"        api:"required"`
	NextCursor string                                     `json:"next_cursor"`
	JSON       evaluationTrajectoryRowSearchResponseJSON  `json:"-"`
}

// evaluationTrajectoryRowSearchResponseJSON contains the JSON metadata for the
// struct [EvaluationTrajectoryRowSearchResponse]
type evaluationTrajectoryRowSearchResponseJSON struct {
	Rows        apijson.Field
	NextCursor  apijson.Field
	raw         string
	ExtraFields map[string]apijson.Field
}

func (r *EvaluationTrajectoryRowSearchResponse) UnmarshalJSON(data []byte) (err error) {
	return apijson.UnmarshalRoot(data, r)
}

func (r evaluationTrajectoryRowSearchResponseJSON) RawJSON() string {
	return r.raw
}

type EvaluationTrajectoryRowSearchResponseRow struct {
	// The case the trajectory starts from.
	RootCase EvaluationTrajectoryRowSearchResponseRowsRootCase `json:"root_case" api:"required"`
	// The newest score of each scorer the evaluation selects, in selection order. A
	// scorer with no score on this trajectory is left out.
	Scores     []EvaluationTrajectoryRowSearchResponseRowsScore    `json:"scores"     api:"required"`
	Trajectory EvaluationTrajectoryRowSearchResponseRowsTrajectory `json:"trajectory" api:"required"`
	JSON       evaluationTrajectoryRowSearchResponseRowJSON        `json:"-"`
}

// evaluationTrajectoryRowSearchResponseRowJSON contains the JSON metadata for the
// struct [EvaluationTrajectoryRowSearchResponseRow]
type evaluationTrajectoryRowSearchResponseRowJSON struct {
	RootCase    apijson.Field
	Scores      apijson.Field
	Trajectory  apijson.Field
	raw         string
	ExtraFields map[string]apijson.Field
}

func (r *EvaluationTrajectoryRowSearchResponseRow) UnmarshalJSON(data []byte) (err error) {
	return apijson.UnmarshalRoot(data, r)
}

func (r evaluationTrajectoryRowSearchResponseRowJSON) RawJSON() string {
	return r.raw
}

// The case the trajectory starts from.
type EvaluationTrajectoryRowSearchResponseRowsRootCase struct {
	Attributes map[string]interface{} `json:"attributes"  api:"required"`
	CaseID     string                 `json:"case_id"     api:"required"          format:"uuid"`
	CommitID   int64                  `json:"commit_id"   api:"required"`
	ExampleKey string                 `json:"example_key" api:"required,nullable"`
	Input      interface{}            `json:"input"       api:"required"`
	Output     interface{}            `json:"output"      api:"required"`
	// Tag names on this case, sorted.
	Tags    []string                                              `json:"tags"    api:"required"`
	Variant string                                                `json:"variant" api:"required,nullable"`
	JSON    evaluationTrajectoryRowSearchResponseRowsRootCaseJSON `json:"-"`
}

// evaluationTrajectoryRowSearchResponseRowsRootCaseJSON contains the JSON metadata
// for the struct [EvaluationTrajectoryRowSearchResponseRowsRootCase]
type evaluationTrajectoryRowSearchResponseRowsRootCaseJSON struct {
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

func (r *EvaluationTrajectoryRowSearchResponseRowsRootCase) UnmarshalJSON(data []byte) (err error) {
	return apijson.UnmarshalRoot(data, r)
}

func (r evaluationTrajectoryRowSearchResponseRowsRootCaseJSON) RawJSON() string {
	return r.raw
}

type EvaluationTrajectoryRowSearchResponseRowsScore struct {
	ScoreID         string                                             `json:"score_id"          api:"required" format:"uuid"`
	ScorerID        string                                             `json:"scorer_id"         api:"required" format:"uuid"`
	ScorerVersionID string                                             `json:"scorer_version_id" api:"required" format:"uuid"`
	Value           interface{}                                        `json:"value"             api:"required"`
	JSON            evaluationTrajectoryRowSearchResponseRowsScoreJSON `json:"-"`
}

// evaluationTrajectoryRowSearchResponseRowsScoreJSON contains the JSON metadata
// for the struct [EvaluationTrajectoryRowSearchResponseRowsScore]
type evaluationTrajectoryRowSearchResponseRowsScoreJSON struct {
	ScoreID         apijson.Field
	ScorerID        apijson.Field
	ScorerVersionID apijson.Field
	Value           apijson.Field
	raw             string
	ExtraFields     map[string]apijson.Field
}

func (r *EvaluationTrajectoryRowSearchResponseRowsScore) UnmarshalJSON(data []byte) (err error) {
	return apijson.UnmarshalRoot(data, r)
}

func (r evaluationTrajectoryRowSearchResponseRowsScoreJSON) RawJSON() string {
	return r.raw
}

type EvaluationTrajectoryRowSearchResponseRowsTrajectory struct {
	CommitID  int64  `json:"commit_id"  api:"required"`
	DatasetID string `json:"dataset_id" api:"required" format:"uuid"`
	// 0 for a top-level trajectory, otherwise one more than its parent's.
	Depth int64  `json:"depth" api:"required"`
	Name  string `json:"name"  api:"required"`
	// Null for a top-level trajectory.
	ParentTrajectoryID string                                                  `json:"parent_trajectory_id" api:"required,nullable" format:"uuid"`
	RootCaseID         string                                                  `json:"root_case_id"         api:"required"          format:"uuid"`
	TrajectoryID       string                                                  `json:"trajectory_id"        api:"required"          format:"uuid"`
	JSON               evaluationTrajectoryRowSearchResponseRowsTrajectoryJSON `json:"-"`
}

// evaluationTrajectoryRowSearchResponseRowsTrajectoryJSON contains the JSON
// metadata for the struct [EvaluationTrajectoryRowSearchResponseRowsTrajectory]
type evaluationTrajectoryRowSearchResponseRowsTrajectoryJSON struct {
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

func (r *EvaluationTrajectoryRowSearchResponseRowsTrajectory) UnmarshalJSON(data []byte) (err error) {
	return apijson.UnmarshalRoot(data, r)
}

func (r evaluationTrajectoryRowSearchResponseRowsTrajectoryJSON) RawJSON() string {
	return r.raw
}

type EvaluationTrajectoryRowListParams struct {
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

// URLQuery serializes [EvaluationTrajectoryRowListParams]'s query parameters as
// `url.Values`.
func (r EvaluationTrajectoryRowListParams) URLQuery() (v url.Values) {
	return apiquery.MarshalWithSettings(r, apiquery.QuerySettings{
		ArrayFormat:  apiquery.ArrayQueryFormatComma,
		NestedFormat: apiquery.NestedQueryFormatBrackets,
	})
}

type EvaluationTrajectoryRowGetParams struct {
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

type EvaluationTrajectoryRowSearchParams struct {
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

func (r EvaluationTrajectoryRowSearchParams) MarshalJSON() (data []byte, err error) {
	return apijson.MarshalRoot(r)
}
