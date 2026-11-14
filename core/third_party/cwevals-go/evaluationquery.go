// File generated from our OpenAPI spec by Stainless.

package cwevals

import (
	"context"
	"errors"
	"fmt"
	"net/http"
	"net/url"
	"reflect"
	"slices"

	"github.com/tidwall/gjson"
	"github.com/wandb/cwevals-go/internal/apijson"
	"github.com/wandb/cwevals-go/internal/apiquery"
	"github.com/wandb/cwevals-go/internal/param"
	"github.com/wandb/cwevals-go/internal/requestconfig"
	"github.com/wandb/cwevals-go/option"
)

// EvaluationQueryService contains methods and other services that help with
// interacting with the CoreWeave Evaluations API.
//
// Note, unlike clients, this service does not read variables from the environment
// automatically. You should not instantiate this service directly, and instead use
// the [NewEvaluationQueryService] method instead.
type EvaluationQueryService struct {
	Options []option.RequestOption
	Results *EvaluationQueryResultService
}

// NewEvaluationQueryService generates a new service that applies the given options
// to each request. These options are applied after the parent client's options (if
// there is one), and before any request-specific options.
func NewEvaluationQueryService(opts ...option.RequestOption) (r *EvaluationQueryService) {
	r = &EvaluationQueryService{}
	r.Options = opts
	r.Results = NewEvaluationQueryResultService(opts...)
	return
}

// Saves a query definition that groups cases or trajectories and aggregates their
// scores. For example, you can group by model variant and calculate a mean score
// for each variant.
//
// The evaluation must target cases, and the definition must match its latest data.
// Every scorer the query reads, in a metric, a group_by column, or a pass_at_k per
// column, must allow the query's target_kind, or the request returns 400. Saving
// the query does not calculate results. Use the query's results operation to run
// it.
//
// Request bodies must be at most 1 MiB. Bodies larger than the limit are rejected
// with 413 Request Entity Too Large.
func (r *EvaluationQueryService) New(
	ctx context.Context,
	evaluationID string,
	params EvaluationQueryNewParams,
	opts ...option.RequestOption,
) (res *EvaluationQueryNewResponse, err error) {
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
		"v1/namespaces/%s/scopes/%s/evaluations/%s/queries",
		params.Namespace,
		params.ScopeID,
		evaluationID,
	)
	err = requestconfig.ExecuteNewRequest(ctx, http.MethodPost, path, params, &res, opts...)
	return res, err
}

// Returns an evaluation's saved query definitions in query ID order. This
// operation does not run the queries.
func (r *EvaluationQueryService) List(
	ctx context.Context,
	evaluationID string,
	params EvaluationQueryListParams,
	opts ...option.RequestOption,
) (res *EvaluationQueryListResponse, err error) {
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
		"v1/namespaces/%s/scopes/%s/evaluations/%s/queries",
		params.Namespace,
		params.ScopeID,
		evaluationID,
	)
	err = requestconfig.ExecuteNewRequest(ctx, http.MethodGet, path, params, &res, opts...)
	return res, err
}

// Returns the saved query definition without running it. A query belonging to
// another evaluation or scope returns 404.
func (r *EvaluationQueryService) Get(
	ctx context.Context,
	evaluationID string,
	evaluationQueryID string,
	query EvaluationQueryGetParams,
	opts ...option.RequestOption,
) (res *EvaluationQueryGetResponse, err error) {
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
	if evaluationQueryID == "" {
		err = errors.New("missing required evaluation_query_id parameter")
		return nil, err
	}
	path := fmt.Sprintf(
		"v1/namespaces/%s/scopes/%s/evaluations/%s/queries/%s",
		query.Namespace,
		query.ScopeID,
		evaluationID,
		evaluationQueryID,
	)
	err = requestconfig.ExecuteNewRequest(ctx, http.MethodGet, path, nil, &res, opts...)
	return res, err
}

type EvaluationQueryNewResponse struct {
	Definition        EvaluationQueryNewResponseDefinition `json:"definition"          api:"required"`
	EvaluationID      string                               `json:"evaluation_id"       api:"required" format:"uuid"`
	EvaluationQueryID string                               `json:"evaluation_query_id" api:"required" format:"uuid"`
	Name              string                               `json:"name"                api:"required"`
	// Namespace that assigned the scope reference.
	Namespace EvaluationQueryNewResponseNamespace `json:"namespace" api:"required"`
	ScopeRef  string                              `json:"scope_ref" api:"required"`
	JSON      evaluationQueryNewResponseJSON      `json:"-"`
}

// evaluationQueryNewResponseJSON contains the JSON metadata for the struct
// [EvaluationQueryNewResponse]
type evaluationQueryNewResponseJSON struct {
	Definition        apijson.Field
	EvaluationID      apijson.Field
	EvaluationQueryID apijson.Field
	Name              apijson.Field
	Namespace         apijson.Field
	ScopeRef          apijson.Field
	raw               string
	ExtraFields       map[string]apijson.Field
}

func (r *EvaluationQueryNewResponse) UnmarshalJSON(data []byte) (err error) {
	return apijson.UnmarshalRoot(data, r)
}

func (r evaluationQueryNewResponseJSON) RawJSON() string {
	return r.raw
}

type EvaluationQueryNewResponseDefinition struct {
	Metrics []EvaluationQueryNewResponseDefinitionMetric `json:"metrics" api:"required"`
	// Stored definition version. Always present in responses.
	V       int64                                         `json:"v"        api:"required"`
	GroupBy []EvaluationQueryNewResponseDefinitionGroupBy `json:"group_by"`
	// Absent for a query over cases.
	TargetKind EvaluationQueryNewResponseDefinitionTargetKind `json:"target_kind"`
	JSON       evaluationQueryNewResponseDefinitionJSON       `json:"-"`
}

// evaluationQueryNewResponseDefinitionJSON contains the JSON metadata for the
// struct [EvaluationQueryNewResponseDefinition]
type evaluationQueryNewResponseDefinitionJSON struct {
	Metrics     apijson.Field
	V           apijson.Field
	GroupBy     apijson.Field
	TargetKind  apijson.Field
	raw         string
	ExtraFields map[string]apijson.Field
}

func (r *EvaluationQueryNewResponseDefinition) UnmarshalJSON(data []byte) (err error) {
	return apijson.UnmarshalRoot(data, r)
}

func (r evaluationQueryNewResponseDefinitionJSON) RawJSON() string {
	return r.raw
}

type EvaluationQueryNewResponseDefinitionMetric struct {
	// Calculation to apply to the latest visible score for each case, or for each
	// trajectory in a trajectory query.
	//
	//   - **mean**: Average of integer or number scores, or the fraction of true boolean
	//     scores.
	//   - **sum**: Sum of integer or number scores, or the number of true boolean
	//     scores.
	//   - **min / max**: Smallest or largest integer, number, boolean, or string score.
	//     Strings compare lexicographically.
	//   - **count**: Number of non-null integer, number, boolean, or string scores. Zero
	//     and false are counted.
	//   - **pass_at_k**: Estimated probability that at least one of k attempts at a task
	//     succeeds. Requires boolean scores, k, and per.
	//
	// For pass_at_k, per identifies each task. A task with n attempts and c true
	// scores contributes 1 - C(n-c, k) / C(n, k), and the result averages the tasks.
	// The result is null when a task has fewer than k attempts.
	Aggregation EvaluationQueryNewResponseDefinitionMetricsAggregation `json:"aggregation" api:"required"`
	// Unique name for this metric within the query. Result cells use this name.
	Name string `json:"name" api:"required"`
	// Version of the scorer whose values this metric aggregates. It must be registered
	// on the evaluation.
	ScorerVersionID string `json:"scorer_version_id" api:"required" format:"uuid"`
	// Number of attempts per task for pass_at_k. Required for pass_at_k and rejected
	// for other aggregations.
	K int64 `json:"k"`
	// How to handle a target with no non-null latest visible score. A target is a
	// case, or a trajectory in a trajectory query.
	//
	//   - **skip**: Exclude the target. A mean divides by the number of scored targets,
	//     and pass_at_k does not count it as an attempt. This also applies when missing
	//     is omitted.
	//   - **zero**: Include the target as 0, or false for boolean scores. A mean divides
	//     by every target in the group, and pass_at_k counts it as a failed attempt.
	//
	// Only mean, sum, and pass_at_k support zero. min, max, and count accept only
	// skip.
	Missing EvaluationQueryNewResponseDefinitionMetricsMissing `json:"missing"`
	// Column that identifies the task for each case, or for each trajectory in a
	// trajectory query, such as an input task field.
	//
	//   - Required for pass_at_k and rejected for other aggregations.
	//   - Must not also appear in group_by, and must not be depth or
	//     parent_trajectory_id.
	//   - Targets with no value in this column form one task.
	//   - A page returns 400 if the number of groups multiplied by their tasks exceeds
	//     the result row limit.
	Per  EvaluationQueryNewResponseDefinitionMetricsPer `json:"per"`
	JSON evaluationQueryNewResponseDefinitionMetricJSON `json:"-"`
}

// evaluationQueryNewResponseDefinitionMetricJSON contains the JSON metadata for
// the struct [EvaluationQueryNewResponseDefinitionMetric]
type evaluationQueryNewResponseDefinitionMetricJSON struct {
	Aggregation     apijson.Field
	Name            apijson.Field
	ScorerVersionID apijson.Field
	K               apijson.Field
	Missing         apijson.Field
	Per             apijson.Field
	raw             string
	ExtraFields     map[string]apijson.Field
}

func (r *EvaluationQueryNewResponseDefinitionMetric) UnmarshalJSON(data []byte) (err error) {
	return apijson.UnmarshalRoot(data, r)
}

func (r evaluationQueryNewResponseDefinitionMetricJSON) RawJSON() string {
	return r.raw
}

// Calculation to apply to the latest visible score for each case, or for each
// trajectory in a trajectory query.
//
//   - **mean**: Average of integer or number scores, or the fraction of true boolean
//     scores.
//   - **sum**: Sum of integer or number scores, or the number of true boolean
//     scores.
//   - **min / max**: Smallest or largest integer, number, boolean, or string score.
//     Strings compare lexicographically.
//   - **count**: Number of non-null integer, number, boolean, or string scores. Zero
//     and false are counted.
//   - **pass_at_k**: Estimated probability that at least one of k attempts at a task
//     succeeds. Requires boolean scores, k, and per.
//
// For pass_at_k, per identifies each task. A task with n attempts and c true
// scores contributes 1 - C(n-c, k) / C(n, k), and the result averages the tasks.
// The result is null when a task has fewer than k attempts.
type EvaluationQueryNewResponseDefinitionMetricsAggregation string

const (
	EvaluationQueryNewResponseDefinitionMetricsAggregationMean    EvaluationQueryNewResponseDefinitionMetricsAggregation = "mean"
	EvaluationQueryNewResponseDefinitionMetricsAggregationSum     EvaluationQueryNewResponseDefinitionMetricsAggregation = "sum"
	EvaluationQueryNewResponseDefinitionMetricsAggregationMin     EvaluationQueryNewResponseDefinitionMetricsAggregation = "min"
	EvaluationQueryNewResponseDefinitionMetricsAggregationMax     EvaluationQueryNewResponseDefinitionMetricsAggregation = "max"
	EvaluationQueryNewResponseDefinitionMetricsAggregationCount   EvaluationQueryNewResponseDefinitionMetricsAggregation = "count"
	EvaluationQueryNewResponseDefinitionMetricsAggregationPassAtK EvaluationQueryNewResponseDefinitionMetricsAggregation = "pass_at_k"
)

func (r EvaluationQueryNewResponseDefinitionMetricsAggregation) IsKnown() bool {
	switch r {
	case EvaluationQueryNewResponseDefinitionMetricsAggregationMean,
		EvaluationQueryNewResponseDefinitionMetricsAggregationSum,
		EvaluationQueryNewResponseDefinitionMetricsAggregationMin,
		EvaluationQueryNewResponseDefinitionMetricsAggregationMax,
		EvaluationQueryNewResponseDefinitionMetricsAggregationCount,
		EvaluationQueryNewResponseDefinitionMetricsAggregationPassAtK:
		return true
	}
	return false
}

// How to handle a target with no non-null latest visible score. A target is a
// case, or a trajectory in a trajectory query.
//
//   - **skip**: Exclude the target. A mean divides by the number of scored targets,
//     and pass_at_k does not count it as an attempt. This also applies when missing
//     is omitted.
//   - **zero**: Include the target as 0, or false for boolean scores. A mean divides
//     by every target in the group, and pass_at_k counts it as a failed attempt.
//
// Only mean, sum, and pass_at_k support zero. min, max, and count accept only
// skip.
type EvaluationQueryNewResponseDefinitionMetricsMissing string

const (
	EvaluationQueryNewResponseDefinitionMetricsMissingSkip EvaluationQueryNewResponseDefinitionMetricsMissing = "skip"
	EvaluationQueryNewResponseDefinitionMetricsMissingZero EvaluationQueryNewResponseDefinitionMetricsMissing = "zero"
)

func (r EvaluationQueryNewResponseDefinitionMetricsMissing) IsKnown() bool {
	switch r {
	case EvaluationQueryNewResponseDefinitionMetricsMissingSkip, EvaluationQueryNewResponseDefinitionMetricsMissingZero:
		return true
	}
	return false
}

// Column that identifies the task for each case, or for each trajectory in a
// trajectory query, such as an input task field.
//
//   - Required for pass_at_k and rejected for other aggregations.
//   - Must not also appear in group_by, and must not be depth or
//     parent_trajectory_id.
//   - Targets with no value in this column form one task.
//   - A page returns 400 if the number of groups multiplied by their tasks exceeds
//     the result row limit.
type EvaluationQueryNewResponseDefinitionMetricsPer struct {
	Kind EvaluationQueryNewResponseDefinitionMetricsPerKind `json:"kind" api:"required"`
	// Name of the input or output field to use as a column.
	Name string `json:"name"`
	// Whether the field belongs to the case's input or output.
	Source EvaluationQueryNewResponseDefinitionMetricsPerSource `json:"source"`
	JSON   evaluationQueryNewResponseDefinitionMetricsPerJSON   `json:"-"`
	union  EvaluationQueryNewResponseDefinitionMetricsPerUnion
}

// evaluationQueryNewResponseDefinitionMetricsPerJSON contains the JSON metadata
// for the struct [EvaluationQueryNewResponseDefinitionMetricsPer]
type evaluationQueryNewResponseDefinitionMetricsPerJSON struct {
	Kind        apijson.Field
	Name        apijson.Field
	Source      apijson.Field
	raw         string
	ExtraFields map[string]apijson.Field
}

func (r evaluationQueryNewResponseDefinitionMetricsPerJSON) RawJSON() string {
	return r.raw
}

func (r *EvaluationQueryNewResponseDefinitionMetricsPer) UnmarshalJSON(data []byte) (err error) {
	*r = EvaluationQueryNewResponseDefinitionMetricsPer{}
	err = apijson.UnmarshalRoot(data, &r.union)
	if err != nil {
		return err
	}
	return apijson.Port(r.union, &r)
}

// AsUnion returns a [EvaluationQueryNewResponseDefinitionMetricsPerUnion]
// interface which you can cast to the specific types for more type safety.
//
// Possible runtime types of the union are
// [EvaluationQueryNewResponseDefinitionMetricsPerVariantEvaluationColumn],
// [EvaluationQueryNewResponseDefinitionMetricsPerDatasetFieldEvaluationColumn],
// [EvaluationQueryNewResponseDefinitionMetricsPerScoreEvaluationColumn],
// [EvaluationQueryNewResponseDefinitionMetricsPerDepthEvaluationColumn],
// [EvaluationQueryNewResponseDefinitionMetricsPerParentTrajectoryIDEvaluationColumn].
func (r EvaluationQueryNewResponseDefinitionMetricsPer) AsUnion() EvaluationQueryNewResponseDefinitionMetricsPerUnion {
	return r.union
}

// Column that identifies the task for each case, or for each trajectory in a
// trajectory query, such as an input task field.
//
//   - Required for pass_at_k and rejected for other aggregations.
//   - Must not also appear in group_by, and must not be depth or
//     parent_trajectory_id.
//   - Targets with no value in this column form one task.
//   - A page returns 400 if the number of groups multiplied by their tasks exceeds
//     the result row limit.
//
// Union satisfied by
// [EvaluationQueryNewResponseDefinitionMetricsPerVariantEvaluationColumn],
// [EvaluationQueryNewResponseDefinitionMetricsPerDatasetFieldEvaluationColumn],
// [EvaluationQueryNewResponseDefinitionMetricsPerScoreEvaluationColumn],
// [EvaluationQueryNewResponseDefinitionMetricsPerDepthEvaluationColumn] or
// [EvaluationQueryNewResponseDefinitionMetricsPerParentTrajectoryIDEvaluationColumn].
type EvaluationQueryNewResponseDefinitionMetricsPerUnion interface {
	implementsEvaluationQueryNewResponseDefinitionMetricsPer()
}

func init() {
	apijson.RegisterUnion(
		reflect.TypeOf((*EvaluationQueryNewResponseDefinitionMetricsPerUnion)(nil)).Elem(),
		"kind",
		apijson.UnionVariant{
			TypeFilter:         gjson.JSON,
			Type:               reflect.TypeOf(EvaluationQueryNewResponseDefinitionMetricsPerVariantEvaluationColumn{}),
			DiscriminatorValue: "variant",
		},
		apijson.UnionVariant{
			TypeFilter: gjson.JSON,
			Type: reflect.TypeOf(
				EvaluationQueryNewResponseDefinitionMetricsPerDatasetFieldEvaluationColumn{},
			),
			DiscriminatorValue: "dataset_field",
		},
		apijson.UnionVariant{
			TypeFilter:         gjson.JSON,
			Type:               reflect.TypeOf(EvaluationQueryNewResponseDefinitionMetricsPerScoreEvaluationColumn{}),
			DiscriminatorValue: "score",
		},
		apijson.UnionVariant{
			TypeFilter:         gjson.JSON,
			Type:               reflect.TypeOf(EvaluationQueryNewResponseDefinitionMetricsPerDepthEvaluationColumn{}),
			DiscriminatorValue: "depth",
		},
		apijson.UnionVariant{
			TypeFilter: gjson.JSON,
			Type: reflect.TypeOf(
				EvaluationQueryNewResponseDefinitionMetricsPerParentTrajectoryIDEvaluationColumn{},
			),
			DiscriminatorValue: "parent_trajectory_id",
		},
	)
}

type EvaluationQueryNewResponseDefinitionMetricsPerVariantEvaluationColumn struct {
	Kind EvaluationQueryNewResponseDefinitionMetricsPerVariantEvaluationColumnKind `json:"kind" api:"required"`
	JSON evaluationQueryNewResponseDefinitionMetricsPerVariantEvaluationColumnJSON `json:"-"`
}

// evaluationQueryNewResponseDefinitionMetricsPerVariantEvaluationColumnJSON
// contains the JSON metadata for the struct
// [EvaluationQueryNewResponseDefinitionMetricsPerVariantEvaluationColumn]
type evaluationQueryNewResponseDefinitionMetricsPerVariantEvaluationColumnJSON struct {
	Kind        apijson.Field
	raw         string
	ExtraFields map[string]apijson.Field
}

func (r *EvaluationQueryNewResponseDefinitionMetricsPerVariantEvaluationColumn) UnmarshalJSON(data []byte) (err error) {
	return apijson.UnmarshalRoot(data, r)
}

func (r evaluationQueryNewResponseDefinitionMetricsPerVariantEvaluationColumnJSON) RawJSON() string {
	return r.raw
}

func (r EvaluationQueryNewResponseDefinitionMetricsPerVariantEvaluationColumn) implementsEvaluationQueryNewResponseDefinitionMetricsPer() {
}

type EvaluationQueryNewResponseDefinitionMetricsPerVariantEvaluationColumnKind string

const (
	EvaluationQueryNewResponseDefinitionMetricsPerVariantEvaluationColumnKindVariant EvaluationQueryNewResponseDefinitionMetricsPerVariantEvaluationColumnKind = "variant"
)

func (r EvaluationQueryNewResponseDefinitionMetricsPerVariantEvaluationColumnKind) IsKnown() bool {
	switch r {
	case EvaluationQueryNewResponseDefinitionMetricsPerVariantEvaluationColumnKindVariant:
		return true
	}
	return false
}

type EvaluationQueryNewResponseDefinitionMetricsPerDatasetFieldEvaluationColumn struct {
	Kind EvaluationQueryNewResponseDefinitionMetricsPerDatasetFieldEvaluationColumnKind `json:"kind" api:"required"`
	// Name of the input or output field to use as a column.
	Name string `json:"name" api:"required"`
	// Whether the field belongs to the case's input or output.
	Source EvaluationQueryNewResponseDefinitionMetricsPerDatasetFieldEvaluationColumnSource `json:"source" api:"required"`
	JSON   evaluationQueryNewResponseDefinitionMetricsPerDatasetFieldEvaluationColumnJSON   `json:"-"`
}

// evaluationQueryNewResponseDefinitionMetricsPerDatasetFieldEvaluationColumnJSON
// contains the JSON metadata for the struct
// [EvaluationQueryNewResponseDefinitionMetricsPerDatasetFieldEvaluationColumn]
type evaluationQueryNewResponseDefinitionMetricsPerDatasetFieldEvaluationColumnJSON struct {
	Kind        apijson.Field
	Name        apijson.Field
	Source      apijson.Field
	raw         string
	ExtraFields map[string]apijson.Field
}

func (r *EvaluationQueryNewResponseDefinitionMetricsPerDatasetFieldEvaluationColumn) UnmarshalJSON(
	data []byte,
) (err error) {
	return apijson.UnmarshalRoot(data, r)
}

func (r evaluationQueryNewResponseDefinitionMetricsPerDatasetFieldEvaluationColumnJSON) RawJSON() string {
	return r.raw
}

func (r EvaluationQueryNewResponseDefinitionMetricsPerDatasetFieldEvaluationColumn) implementsEvaluationQueryNewResponseDefinitionMetricsPer() {
}

type EvaluationQueryNewResponseDefinitionMetricsPerDatasetFieldEvaluationColumnKind string

const (
	EvaluationQueryNewResponseDefinitionMetricsPerDatasetFieldEvaluationColumnKindDatasetField EvaluationQueryNewResponseDefinitionMetricsPerDatasetFieldEvaluationColumnKind = "dataset_field"
)

func (r EvaluationQueryNewResponseDefinitionMetricsPerDatasetFieldEvaluationColumnKind) IsKnown() bool {
	switch r {
	case EvaluationQueryNewResponseDefinitionMetricsPerDatasetFieldEvaluationColumnKindDatasetField:
		return true
	}
	return false
}

// Whether the field belongs to the case's input or output.
type EvaluationQueryNewResponseDefinitionMetricsPerDatasetFieldEvaluationColumnSource string

const (
	EvaluationQueryNewResponseDefinitionMetricsPerDatasetFieldEvaluationColumnSourceInput  EvaluationQueryNewResponseDefinitionMetricsPerDatasetFieldEvaluationColumnSource = "input"
	EvaluationQueryNewResponseDefinitionMetricsPerDatasetFieldEvaluationColumnSourceOutput EvaluationQueryNewResponseDefinitionMetricsPerDatasetFieldEvaluationColumnSource = "output"
)

func (r EvaluationQueryNewResponseDefinitionMetricsPerDatasetFieldEvaluationColumnSource) IsKnown() bool {
	switch r {
	case EvaluationQueryNewResponseDefinitionMetricsPerDatasetFieldEvaluationColumnSourceInput,
		EvaluationQueryNewResponseDefinitionMetricsPerDatasetFieldEvaluationColumnSourceOutput:
		return true
	}
	return false
}

type EvaluationQueryNewResponseDefinitionMetricsPerScoreEvaluationColumn struct {
	Kind EvaluationQueryNewResponseDefinitionMetricsPerScoreEvaluationColumnKind `json:"kind" api:"required"`
	// Name of the scorer whose score supplies this column.
	Name string                                                                  `json:"name" api:"required"`
	JSON evaluationQueryNewResponseDefinitionMetricsPerScoreEvaluationColumnJSON `json:"-"`
}

// evaluationQueryNewResponseDefinitionMetricsPerScoreEvaluationColumnJSON contains
// the JSON metadata for the struct
// [EvaluationQueryNewResponseDefinitionMetricsPerScoreEvaluationColumn]
type evaluationQueryNewResponseDefinitionMetricsPerScoreEvaluationColumnJSON struct {
	Kind        apijson.Field
	Name        apijson.Field
	raw         string
	ExtraFields map[string]apijson.Field
}

func (r *EvaluationQueryNewResponseDefinitionMetricsPerScoreEvaluationColumn) UnmarshalJSON(data []byte) (err error) {
	return apijson.UnmarshalRoot(data, r)
}

func (r evaluationQueryNewResponseDefinitionMetricsPerScoreEvaluationColumnJSON) RawJSON() string {
	return r.raw
}

func (r EvaluationQueryNewResponseDefinitionMetricsPerScoreEvaluationColumn) implementsEvaluationQueryNewResponseDefinitionMetricsPer() {
}

type EvaluationQueryNewResponseDefinitionMetricsPerScoreEvaluationColumnKind string

const (
	EvaluationQueryNewResponseDefinitionMetricsPerScoreEvaluationColumnKindScore EvaluationQueryNewResponseDefinitionMetricsPerScoreEvaluationColumnKind = "score"
)

func (r EvaluationQueryNewResponseDefinitionMetricsPerScoreEvaluationColumnKind) IsKnown() bool {
	switch r {
	case EvaluationQueryNewResponseDefinitionMetricsPerScoreEvaluationColumnKindScore:
		return true
	}
	return false
}

// Trajectory queries only. Groups by depth, an integer that is 0 for a top-level
// trajectory.
type EvaluationQueryNewResponseDefinitionMetricsPerDepthEvaluationColumn struct {
	Kind EvaluationQueryNewResponseDefinitionMetricsPerDepthEvaluationColumnKind `json:"kind" api:"required"`
	JSON evaluationQueryNewResponseDefinitionMetricsPerDepthEvaluationColumnJSON `json:"-"`
}

// evaluationQueryNewResponseDefinitionMetricsPerDepthEvaluationColumnJSON contains
// the JSON metadata for the struct
// [EvaluationQueryNewResponseDefinitionMetricsPerDepthEvaluationColumn]
type evaluationQueryNewResponseDefinitionMetricsPerDepthEvaluationColumnJSON struct {
	Kind        apijson.Field
	raw         string
	ExtraFields map[string]apijson.Field
}

func (r *EvaluationQueryNewResponseDefinitionMetricsPerDepthEvaluationColumn) UnmarshalJSON(data []byte) (err error) {
	return apijson.UnmarshalRoot(data, r)
}

func (r evaluationQueryNewResponseDefinitionMetricsPerDepthEvaluationColumnJSON) RawJSON() string {
	return r.raw
}

func (r EvaluationQueryNewResponseDefinitionMetricsPerDepthEvaluationColumn) implementsEvaluationQueryNewResponseDefinitionMetricsPer() {
}

type EvaluationQueryNewResponseDefinitionMetricsPerDepthEvaluationColumnKind string

const (
	EvaluationQueryNewResponseDefinitionMetricsPerDepthEvaluationColumnKindDepth EvaluationQueryNewResponseDefinitionMetricsPerDepthEvaluationColumnKind = "depth"
)

func (r EvaluationQueryNewResponseDefinitionMetricsPerDepthEvaluationColumnKind) IsKnown() bool {
	switch r {
	case EvaluationQueryNewResponseDefinitionMetricsPerDepthEvaluationColumnKindDepth:
		return true
	}
	return false
}

// Trajectory queries only. Groups by the parent trajectory's ID. Top-level
// trajectories form the null group.
type EvaluationQueryNewResponseDefinitionMetricsPerParentTrajectoryIDEvaluationColumn struct {
	Kind EvaluationQueryNewResponseDefinitionMetricsPerParentTrajectoryIDEvaluationColumnKind `json:"kind" api:"required"`
	JSON evaluationQueryNewResponseDefinitionMetricsPerParentTrajectoryIDEvaluationColumnJSON `json:"-"`
}

// evaluationQueryNewResponseDefinitionMetricsPerParentTrajectoryIDEvaluationColumnJSON
// contains the JSON metadata for the struct
// [EvaluationQueryNewResponseDefinitionMetricsPerParentTrajectoryIDEvaluationColumn]
type evaluationQueryNewResponseDefinitionMetricsPerParentTrajectoryIDEvaluationColumnJSON struct {
	Kind        apijson.Field
	raw         string
	ExtraFields map[string]apijson.Field
}

func (r *EvaluationQueryNewResponseDefinitionMetricsPerParentTrajectoryIDEvaluationColumn) UnmarshalJSON(
	data []byte,
) (err error) {
	return apijson.UnmarshalRoot(data, r)
}

func (r evaluationQueryNewResponseDefinitionMetricsPerParentTrajectoryIDEvaluationColumnJSON) RawJSON() string {
	return r.raw
}

func (r EvaluationQueryNewResponseDefinitionMetricsPerParentTrajectoryIDEvaluationColumn) implementsEvaluationQueryNewResponseDefinitionMetricsPer() {
}

type EvaluationQueryNewResponseDefinitionMetricsPerParentTrajectoryIDEvaluationColumnKind string

const (
	EvaluationQueryNewResponseDefinitionMetricsPerParentTrajectoryIDEvaluationColumnKindParentTrajectoryID EvaluationQueryNewResponseDefinitionMetricsPerParentTrajectoryIDEvaluationColumnKind = "parent_trajectory_id"
)

func (r EvaluationQueryNewResponseDefinitionMetricsPerParentTrajectoryIDEvaluationColumnKind) IsKnown() bool {
	switch r {
	case EvaluationQueryNewResponseDefinitionMetricsPerParentTrajectoryIDEvaluationColumnKindParentTrajectoryID:
		return true
	}
	return false
}

type EvaluationQueryNewResponseDefinitionMetricsPerKind string

const (
	EvaluationQueryNewResponseDefinitionMetricsPerKindVariant            EvaluationQueryNewResponseDefinitionMetricsPerKind = "variant"
	EvaluationQueryNewResponseDefinitionMetricsPerKindDatasetField       EvaluationQueryNewResponseDefinitionMetricsPerKind = "dataset_field"
	EvaluationQueryNewResponseDefinitionMetricsPerKindScore              EvaluationQueryNewResponseDefinitionMetricsPerKind = "score"
	EvaluationQueryNewResponseDefinitionMetricsPerKindDepth              EvaluationQueryNewResponseDefinitionMetricsPerKind = "depth"
	EvaluationQueryNewResponseDefinitionMetricsPerKindParentTrajectoryID EvaluationQueryNewResponseDefinitionMetricsPerKind = "parent_trajectory_id"
)

func (r EvaluationQueryNewResponseDefinitionMetricsPerKind) IsKnown() bool {
	switch r {
	case EvaluationQueryNewResponseDefinitionMetricsPerKindVariant,
		EvaluationQueryNewResponseDefinitionMetricsPerKindDatasetField,
		EvaluationQueryNewResponseDefinitionMetricsPerKindScore,
		EvaluationQueryNewResponseDefinitionMetricsPerKindDepth,
		EvaluationQueryNewResponseDefinitionMetricsPerKindParentTrajectoryID:
		return true
	}
	return false
}

// Whether the field belongs to the case's input or output.
type EvaluationQueryNewResponseDefinitionMetricsPerSource string

const (
	EvaluationQueryNewResponseDefinitionMetricsPerSourceInput  EvaluationQueryNewResponseDefinitionMetricsPerSource = "input"
	EvaluationQueryNewResponseDefinitionMetricsPerSourceOutput EvaluationQueryNewResponseDefinitionMetricsPerSource = "output"
)

func (r EvaluationQueryNewResponseDefinitionMetricsPerSource) IsKnown() bool {
	switch r {
	case EvaluationQueryNewResponseDefinitionMetricsPerSourceInput,
		EvaluationQueryNewResponseDefinitionMetricsPerSourceOutput:
		return true
	}
	return false
}

// Trajectory queries only. Groups by depth, an integer that is 0 for a top-level
// trajectory.
type EvaluationQueryNewResponseDefinitionGroupBy struct {
	Kind EvaluationQueryNewResponseDefinitionGroupByKind `json:"kind" api:"required"`
	// Name of the input or output field to use as a column.
	Name string `json:"name"`
	// Whether the field belongs to the case's input or output.
	Source EvaluationQueryNewResponseDefinitionGroupBySource `json:"source"`
	JSON   evaluationQueryNewResponseDefinitionGroupByJSON   `json:"-"`
	union  EvaluationQueryNewResponseDefinitionGroupByUnion
}

// evaluationQueryNewResponseDefinitionGroupByJSON contains the JSON metadata for
// the struct [EvaluationQueryNewResponseDefinitionGroupBy]
type evaluationQueryNewResponseDefinitionGroupByJSON struct {
	Kind        apijson.Field
	Name        apijson.Field
	Source      apijson.Field
	raw         string
	ExtraFields map[string]apijson.Field
}

func (r evaluationQueryNewResponseDefinitionGroupByJSON) RawJSON() string {
	return r.raw
}

func (r *EvaluationQueryNewResponseDefinitionGroupBy) UnmarshalJSON(data []byte) (err error) {
	*r = EvaluationQueryNewResponseDefinitionGroupBy{}
	err = apijson.UnmarshalRoot(data, &r.union)
	if err != nil {
		return err
	}
	return apijson.Port(r.union, &r)
}

// AsUnion returns a [EvaluationQueryNewResponseDefinitionGroupByUnion] interface
// which you can cast to the specific types for more type safety.
//
// Possible runtime types of the union are
// [EvaluationQueryNewResponseDefinitionGroupByVariantEvaluationColumn],
// [EvaluationQueryNewResponseDefinitionGroupByDatasetFieldEvaluationColumn],
// [EvaluationQueryNewResponseDefinitionGroupByScoreEvaluationColumn],
// [EvaluationQueryNewResponseDefinitionGroupByDepthEvaluationColumn],
// [EvaluationQueryNewResponseDefinitionGroupByParentTrajectoryIDEvaluationColumn].
func (r EvaluationQueryNewResponseDefinitionGroupBy) AsUnion() EvaluationQueryNewResponseDefinitionGroupByUnion {
	return r.union
}

// Trajectory queries only. Groups by depth, an integer that is 0 for a top-level
// trajectory.
//
// Union satisfied by
// [EvaluationQueryNewResponseDefinitionGroupByVariantEvaluationColumn],
// [EvaluationQueryNewResponseDefinitionGroupByDatasetFieldEvaluationColumn],
// [EvaluationQueryNewResponseDefinitionGroupByScoreEvaluationColumn],
// [EvaluationQueryNewResponseDefinitionGroupByDepthEvaluationColumn] or
// [EvaluationQueryNewResponseDefinitionGroupByParentTrajectoryIDEvaluationColumn].
type EvaluationQueryNewResponseDefinitionGroupByUnion interface {
	implementsEvaluationQueryNewResponseDefinitionGroupBy()
}

func init() {
	apijson.RegisterUnion(
		reflect.TypeOf((*EvaluationQueryNewResponseDefinitionGroupByUnion)(nil)).Elem(),
		"kind",
		apijson.UnionVariant{
			TypeFilter:         gjson.JSON,
			Type:               reflect.TypeOf(EvaluationQueryNewResponseDefinitionGroupByVariantEvaluationColumn{}),
			DiscriminatorValue: "variant",
		},
		apijson.UnionVariant{
			TypeFilter: gjson.JSON,
			Type: reflect.TypeOf(
				EvaluationQueryNewResponseDefinitionGroupByDatasetFieldEvaluationColumn{},
			),
			DiscriminatorValue: "dataset_field",
		},
		apijson.UnionVariant{
			TypeFilter:         gjson.JSON,
			Type:               reflect.TypeOf(EvaluationQueryNewResponseDefinitionGroupByScoreEvaluationColumn{}),
			DiscriminatorValue: "score",
		},
		apijson.UnionVariant{
			TypeFilter:         gjson.JSON,
			Type:               reflect.TypeOf(EvaluationQueryNewResponseDefinitionGroupByDepthEvaluationColumn{}),
			DiscriminatorValue: "depth",
		},
		apijson.UnionVariant{
			TypeFilter: gjson.JSON,
			Type: reflect.TypeOf(
				EvaluationQueryNewResponseDefinitionGroupByParentTrajectoryIDEvaluationColumn{},
			),
			DiscriminatorValue: "parent_trajectory_id",
		},
	)
}

type EvaluationQueryNewResponseDefinitionGroupByVariantEvaluationColumn struct {
	Kind EvaluationQueryNewResponseDefinitionGroupByVariantEvaluationColumnKind `json:"kind" api:"required"`
	JSON evaluationQueryNewResponseDefinitionGroupByVariantEvaluationColumnJSON `json:"-"`
}

// evaluationQueryNewResponseDefinitionGroupByVariantEvaluationColumnJSON contains
// the JSON metadata for the struct
// [EvaluationQueryNewResponseDefinitionGroupByVariantEvaluationColumn]
type evaluationQueryNewResponseDefinitionGroupByVariantEvaluationColumnJSON struct {
	Kind        apijson.Field
	raw         string
	ExtraFields map[string]apijson.Field
}

func (r *EvaluationQueryNewResponseDefinitionGroupByVariantEvaluationColumn) UnmarshalJSON(data []byte) (err error) {
	return apijson.UnmarshalRoot(data, r)
}

func (r evaluationQueryNewResponseDefinitionGroupByVariantEvaluationColumnJSON) RawJSON() string {
	return r.raw
}

func (r EvaluationQueryNewResponseDefinitionGroupByVariantEvaluationColumn) implementsEvaluationQueryNewResponseDefinitionGroupBy() {
}

type EvaluationQueryNewResponseDefinitionGroupByVariantEvaluationColumnKind string

const (
	EvaluationQueryNewResponseDefinitionGroupByVariantEvaluationColumnKindVariant EvaluationQueryNewResponseDefinitionGroupByVariantEvaluationColumnKind = "variant"
)

func (r EvaluationQueryNewResponseDefinitionGroupByVariantEvaluationColumnKind) IsKnown() bool {
	switch r {
	case EvaluationQueryNewResponseDefinitionGroupByVariantEvaluationColumnKindVariant:
		return true
	}
	return false
}

type EvaluationQueryNewResponseDefinitionGroupByDatasetFieldEvaluationColumn struct {
	Kind EvaluationQueryNewResponseDefinitionGroupByDatasetFieldEvaluationColumnKind `json:"kind" api:"required"`
	// Name of the input or output field to use as a column.
	Name string `json:"name" api:"required"`
	// Whether the field belongs to the case's input or output.
	Source EvaluationQueryNewResponseDefinitionGroupByDatasetFieldEvaluationColumnSource `json:"source" api:"required"`
	JSON   evaluationQueryNewResponseDefinitionGroupByDatasetFieldEvaluationColumnJSON   `json:"-"`
}

// evaluationQueryNewResponseDefinitionGroupByDatasetFieldEvaluationColumnJSON
// contains the JSON metadata for the struct
// [EvaluationQueryNewResponseDefinitionGroupByDatasetFieldEvaluationColumn]
type evaluationQueryNewResponseDefinitionGroupByDatasetFieldEvaluationColumnJSON struct {
	Kind        apijson.Field
	Name        apijson.Field
	Source      apijson.Field
	raw         string
	ExtraFields map[string]apijson.Field
}

func (r *EvaluationQueryNewResponseDefinitionGroupByDatasetFieldEvaluationColumn) UnmarshalJSON(
	data []byte,
) (err error) {
	return apijson.UnmarshalRoot(data, r)
}

func (r evaluationQueryNewResponseDefinitionGroupByDatasetFieldEvaluationColumnJSON) RawJSON() string {
	return r.raw
}

func (r EvaluationQueryNewResponseDefinitionGroupByDatasetFieldEvaluationColumn) implementsEvaluationQueryNewResponseDefinitionGroupBy() {
}

type EvaluationQueryNewResponseDefinitionGroupByDatasetFieldEvaluationColumnKind string

const (
	EvaluationQueryNewResponseDefinitionGroupByDatasetFieldEvaluationColumnKindDatasetField EvaluationQueryNewResponseDefinitionGroupByDatasetFieldEvaluationColumnKind = "dataset_field"
)

func (r EvaluationQueryNewResponseDefinitionGroupByDatasetFieldEvaluationColumnKind) IsKnown() bool {
	switch r {
	case EvaluationQueryNewResponseDefinitionGroupByDatasetFieldEvaluationColumnKindDatasetField:
		return true
	}
	return false
}

// Whether the field belongs to the case's input or output.
type EvaluationQueryNewResponseDefinitionGroupByDatasetFieldEvaluationColumnSource string

const (
	EvaluationQueryNewResponseDefinitionGroupByDatasetFieldEvaluationColumnSourceInput  EvaluationQueryNewResponseDefinitionGroupByDatasetFieldEvaluationColumnSource = "input"
	EvaluationQueryNewResponseDefinitionGroupByDatasetFieldEvaluationColumnSourceOutput EvaluationQueryNewResponseDefinitionGroupByDatasetFieldEvaluationColumnSource = "output"
)

func (r EvaluationQueryNewResponseDefinitionGroupByDatasetFieldEvaluationColumnSource) IsKnown() bool {
	switch r {
	case EvaluationQueryNewResponseDefinitionGroupByDatasetFieldEvaluationColumnSourceInput,
		EvaluationQueryNewResponseDefinitionGroupByDatasetFieldEvaluationColumnSourceOutput:
		return true
	}
	return false
}

type EvaluationQueryNewResponseDefinitionGroupByScoreEvaluationColumn struct {
	Kind EvaluationQueryNewResponseDefinitionGroupByScoreEvaluationColumnKind `json:"kind" api:"required"`
	// Name of the scorer whose score supplies this column.
	Name string                                                               `json:"name" api:"required"`
	JSON evaluationQueryNewResponseDefinitionGroupByScoreEvaluationColumnJSON `json:"-"`
}

// evaluationQueryNewResponseDefinitionGroupByScoreEvaluationColumnJSON contains
// the JSON metadata for the struct
// [EvaluationQueryNewResponseDefinitionGroupByScoreEvaluationColumn]
type evaluationQueryNewResponseDefinitionGroupByScoreEvaluationColumnJSON struct {
	Kind        apijson.Field
	Name        apijson.Field
	raw         string
	ExtraFields map[string]apijson.Field
}

func (r *EvaluationQueryNewResponseDefinitionGroupByScoreEvaluationColumn) UnmarshalJSON(data []byte) (err error) {
	return apijson.UnmarshalRoot(data, r)
}

func (r evaluationQueryNewResponseDefinitionGroupByScoreEvaluationColumnJSON) RawJSON() string {
	return r.raw
}

func (r EvaluationQueryNewResponseDefinitionGroupByScoreEvaluationColumn) implementsEvaluationQueryNewResponseDefinitionGroupBy() {
}

type EvaluationQueryNewResponseDefinitionGroupByScoreEvaluationColumnKind string

const (
	EvaluationQueryNewResponseDefinitionGroupByScoreEvaluationColumnKindScore EvaluationQueryNewResponseDefinitionGroupByScoreEvaluationColumnKind = "score"
)

func (r EvaluationQueryNewResponseDefinitionGroupByScoreEvaluationColumnKind) IsKnown() bool {
	switch r {
	case EvaluationQueryNewResponseDefinitionGroupByScoreEvaluationColumnKindScore:
		return true
	}
	return false
}

// Trajectory queries only. Groups by depth, an integer that is 0 for a top-level
// trajectory.
type EvaluationQueryNewResponseDefinitionGroupByDepthEvaluationColumn struct {
	Kind EvaluationQueryNewResponseDefinitionGroupByDepthEvaluationColumnKind `json:"kind" api:"required"`
	JSON evaluationQueryNewResponseDefinitionGroupByDepthEvaluationColumnJSON `json:"-"`
}

// evaluationQueryNewResponseDefinitionGroupByDepthEvaluationColumnJSON contains
// the JSON metadata for the struct
// [EvaluationQueryNewResponseDefinitionGroupByDepthEvaluationColumn]
type evaluationQueryNewResponseDefinitionGroupByDepthEvaluationColumnJSON struct {
	Kind        apijson.Field
	raw         string
	ExtraFields map[string]apijson.Field
}

func (r *EvaluationQueryNewResponseDefinitionGroupByDepthEvaluationColumn) UnmarshalJSON(data []byte) (err error) {
	return apijson.UnmarshalRoot(data, r)
}

func (r evaluationQueryNewResponseDefinitionGroupByDepthEvaluationColumnJSON) RawJSON() string {
	return r.raw
}

func (r EvaluationQueryNewResponseDefinitionGroupByDepthEvaluationColumn) implementsEvaluationQueryNewResponseDefinitionGroupBy() {
}

type EvaluationQueryNewResponseDefinitionGroupByDepthEvaluationColumnKind string

const (
	EvaluationQueryNewResponseDefinitionGroupByDepthEvaluationColumnKindDepth EvaluationQueryNewResponseDefinitionGroupByDepthEvaluationColumnKind = "depth"
)

func (r EvaluationQueryNewResponseDefinitionGroupByDepthEvaluationColumnKind) IsKnown() bool {
	switch r {
	case EvaluationQueryNewResponseDefinitionGroupByDepthEvaluationColumnKindDepth:
		return true
	}
	return false
}

// Trajectory queries only. Groups by the parent trajectory's ID. Top-level
// trajectories form the null group.
type EvaluationQueryNewResponseDefinitionGroupByParentTrajectoryIDEvaluationColumn struct {
	Kind EvaluationQueryNewResponseDefinitionGroupByParentTrajectoryIDEvaluationColumnKind `json:"kind" api:"required"`
	JSON evaluationQueryNewResponseDefinitionGroupByParentTrajectoryIDEvaluationColumnJSON `json:"-"`
}

// evaluationQueryNewResponseDefinitionGroupByParentTrajectoryIDEvaluationColumnJSON
// contains the JSON metadata for the struct
// [EvaluationQueryNewResponseDefinitionGroupByParentTrajectoryIDEvaluationColumn]
type evaluationQueryNewResponseDefinitionGroupByParentTrajectoryIDEvaluationColumnJSON struct {
	Kind        apijson.Field
	raw         string
	ExtraFields map[string]apijson.Field
}

func (r *EvaluationQueryNewResponseDefinitionGroupByParentTrajectoryIDEvaluationColumn) UnmarshalJSON(
	data []byte,
) (err error) {
	return apijson.UnmarshalRoot(data, r)
}

func (r evaluationQueryNewResponseDefinitionGroupByParentTrajectoryIDEvaluationColumnJSON) RawJSON() string {
	return r.raw
}

func (r EvaluationQueryNewResponseDefinitionGroupByParentTrajectoryIDEvaluationColumn) implementsEvaluationQueryNewResponseDefinitionGroupBy() {
}

type EvaluationQueryNewResponseDefinitionGroupByParentTrajectoryIDEvaluationColumnKind string

const (
	EvaluationQueryNewResponseDefinitionGroupByParentTrajectoryIDEvaluationColumnKindParentTrajectoryID EvaluationQueryNewResponseDefinitionGroupByParentTrajectoryIDEvaluationColumnKind = "parent_trajectory_id"
)

func (r EvaluationQueryNewResponseDefinitionGroupByParentTrajectoryIDEvaluationColumnKind) IsKnown() bool {
	switch r {
	case EvaluationQueryNewResponseDefinitionGroupByParentTrajectoryIDEvaluationColumnKindParentTrajectoryID:
		return true
	}
	return false
}

type EvaluationQueryNewResponseDefinitionGroupByKind string

const (
	EvaluationQueryNewResponseDefinitionGroupByKindVariant            EvaluationQueryNewResponseDefinitionGroupByKind = "variant"
	EvaluationQueryNewResponseDefinitionGroupByKindDatasetField       EvaluationQueryNewResponseDefinitionGroupByKind = "dataset_field"
	EvaluationQueryNewResponseDefinitionGroupByKindScore              EvaluationQueryNewResponseDefinitionGroupByKind = "score"
	EvaluationQueryNewResponseDefinitionGroupByKindDepth              EvaluationQueryNewResponseDefinitionGroupByKind = "depth"
	EvaluationQueryNewResponseDefinitionGroupByKindParentTrajectoryID EvaluationQueryNewResponseDefinitionGroupByKind = "parent_trajectory_id"
)

func (r EvaluationQueryNewResponseDefinitionGroupByKind) IsKnown() bool {
	switch r {
	case EvaluationQueryNewResponseDefinitionGroupByKindVariant,
		EvaluationQueryNewResponseDefinitionGroupByKindDatasetField,
		EvaluationQueryNewResponseDefinitionGroupByKindScore,
		EvaluationQueryNewResponseDefinitionGroupByKindDepth,
		EvaluationQueryNewResponseDefinitionGroupByKindParentTrajectoryID:
		return true
	}
	return false
}

// Whether the field belongs to the case's input or output.
type EvaluationQueryNewResponseDefinitionGroupBySource string

const (
	EvaluationQueryNewResponseDefinitionGroupBySourceInput  EvaluationQueryNewResponseDefinitionGroupBySource = "input"
	EvaluationQueryNewResponseDefinitionGroupBySourceOutput EvaluationQueryNewResponseDefinitionGroupBySource = "output"
)

func (r EvaluationQueryNewResponseDefinitionGroupBySource) IsKnown() bool {
	switch r {
	case EvaluationQueryNewResponseDefinitionGroupBySourceInput,
		EvaluationQueryNewResponseDefinitionGroupBySourceOutput:
		return true
	}
	return false
}

// Absent for a query over cases.
type EvaluationQueryNewResponseDefinitionTargetKind string

const (
	EvaluationQueryNewResponseDefinitionTargetKindTrajectory EvaluationQueryNewResponseDefinitionTargetKind = "trajectory"
)

func (r EvaluationQueryNewResponseDefinitionTargetKind) IsKnown() bool {
	switch r {
	case EvaluationQueryNewResponseDefinitionTargetKindTrajectory:
		return true
	}
	return false
}

// Namespace that assigned the scope reference.
type EvaluationQueryNewResponseNamespace string

const (
	EvaluationQueryNewResponseNamespaceWandb EvaluationQueryNewResponseNamespace = "wandb"
)

func (r EvaluationQueryNewResponseNamespace) IsKnown() bool {
	switch r {
	case EvaluationQueryNewResponseNamespaceWandb:
		return true
	}
	return false
}

type EvaluationQueryListResponse struct {
	EvaluationQueries []EvaluationQueryListResponseEvaluationQuery `json:"evaluation_queries" api:"required"`
	NextCursor        string                                       `json:"next_cursor"`
	JSON              evaluationQueryListResponseJSON              `json:"-"`
}

// evaluationQueryListResponseJSON contains the JSON metadata for the struct
// [EvaluationQueryListResponse]
type evaluationQueryListResponseJSON struct {
	EvaluationQueries apijson.Field
	NextCursor        apijson.Field
	raw               string
	ExtraFields       map[string]apijson.Field
}

func (r *EvaluationQueryListResponse) UnmarshalJSON(data []byte) (err error) {
	return apijson.UnmarshalRoot(data, r)
}

func (r evaluationQueryListResponseJSON) RawJSON() string {
	return r.raw
}

type EvaluationQueryListResponseEvaluationQuery struct {
	Definition        EvaluationQueryListResponseEvaluationQueriesDefinition `json:"definition"          api:"required"`
	EvaluationID      string                                                 `json:"evaluation_id"       api:"required" format:"uuid"`
	EvaluationQueryID string                                                 `json:"evaluation_query_id" api:"required" format:"uuid"`
	Name              string                                                 `json:"name"                api:"required"`
	// Namespace that assigned the scope reference.
	Namespace EvaluationQueryListResponseEvaluationQueriesNamespace `json:"namespace" api:"required"`
	ScopeRef  string                                                `json:"scope_ref" api:"required"`
	JSON      evaluationQueryListResponseEvaluationQueryJSON        `json:"-"`
}

// evaluationQueryListResponseEvaluationQueryJSON contains the JSON metadata for
// the struct [EvaluationQueryListResponseEvaluationQuery]
type evaluationQueryListResponseEvaluationQueryJSON struct {
	Definition        apijson.Field
	EvaluationID      apijson.Field
	EvaluationQueryID apijson.Field
	Name              apijson.Field
	Namespace         apijson.Field
	ScopeRef          apijson.Field
	raw               string
	ExtraFields       map[string]apijson.Field
}

func (r *EvaluationQueryListResponseEvaluationQuery) UnmarshalJSON(data []byte) (err error) {
	return apijson.UnmarshalRoot(data, r)
}

func (r evaluationQueryListResponseEvaluationQueryJSON) RawJSON() string {
	return r.raw
}

type EvaluationQueryListResponseEvaluationQueriesDefinition struct {
	Metrics []EvaluationQueryListResponseEvaluationQueriesDefinitionMetric `json:"metrics" api:"required"`
	// Stored definition version. Always present in responses.
	V       int64                                                           `json:"v"        api:"required"`
	GroupBy []EvaluationQueryListResponseEvaluationQueriesDefinitionGroupBy `json:"group_by"`
	// Absent for a query over cases.
	TargetKind EvaluationQueryListResponseEvaluationQueriesDefinitionTargetKind `json:"target_kind"`
	JSON       evaluationQueryListResponseEvaluationQueriesDefinitionJSON       `json:"-"`
}

// evaluationQueryListResponseEvaluationQueriesDefinitionJSON contains the JSON
// metadata for the struct [EvaluationQueryListResponseEvaluationQueriesDefinition]
type evaluationQueryListResponseEvaluationQueriesDefinitionJSON struct {
	Metrics     apijson.Field
	V           apijson.Field
	GroupBy     apijson.Field
	TargetKind  apijson.Field
	raw         string
	ExtraFields map[string]apijson.Field
}

func (r *EvaluationQueryListResponseEvaluationQueriesDefinition) UnmarshalJSON(data []byte) (err error) {
	return apijson.UnmarshalRoot(data, r)
}

func (r evaluationQueryListResponseEvaluationQueriesDefinitionJSON) RawJSON() string {
	return r.raw
}

type EvaluationQueryListResponseEvaluationQueriesDefinitionMetric struct {
	// Calculation to apply to the latest visible score for each case, or for each
	// trajectory in a trajectory query.
	//
	//   - **mean**: Average of integer or number scores, or the fraction of true boolean
	//     scores.
	//   - **sum**: Sum of integer or number scores, or the number of true boolean
	//     scores.
	//   - **min / max**: Smallest or largest integer, number, boolean, or string score.
	//     Strings compare lexicographically.
	//   - **count**: Number of non-null integer, number, boolean, or string scores. Zero
	//     and false are counted.
	//   - **pass_at_k**: Estimated probability that at least one of k attempts at a task
	//     succeeds. Requires boolean scores, k, and per.
	//
	// For pass_at_k, per identifies each task. A task with n attempts and c true
	// scores contributes 1 - C(n-c, k) / C(n, k), and the result averages the tasks.
	// The result is null when a task has fewer than k attempts.
	Aggregation EvaluationQueryListResponseEvaluationQueriesDefinitionMetricsAggregation `json:"aggregation" api:"required"`
	// Unique name for this metric within the query. Result cells use this name.
	Name string `json:"name" api:"required"`
	// Version of the scorer whose values this metric aggregates. It must be registered
	// on the evaluation.
	ScorerVersionID string `json:"scorer_version_id" api:"required" format:"uuid"`
	// Number of attempts per task for pass_at_k. Required for pass_at_k and rejected
	// for other aggregations.
	K int64 `json:"k"`
	// How to handle a target with no non-null latest visible score. A target is a
	// case, or a trajectory in a trajectory query.
	//
	//   - **skip**: Exclude the target. A mean divides by the number of scored targets,
	//     and pass_at_k does not count it as an attempt. This also applies when missing
	//     is omitted.
	//   - **zero**: Include the target as 0, or false for boolean scores. A mean divides
	//     by every target in the group, and pass_at_k counts it as a failed attempt.
	//
	// Only mean, sum, and pass_at_k support zero. min, max, and count accept only
	// skip.
	Missing EvaluationQueryListResponseEvaluationQueriesDefinitionMetricsMissing `json:"missing"`
	// Column that identifies the task for each case, or for each trajectory in a
	// trajectory query, such as an input task field.
	//
	//   - Required for pass_at_k and rejected for other aggregations.
	//   - Must not also appear in group_by, and must not be depth or
	//     parent_trajectory_id.
	//   - Targets with no value in this column form one task.
	//   - A page returns 400 if the number of groups multiplied by their tasks exceeds
	//     the result row limit.
	Per  EvaluationQueryListResponseEvaluationQueriesDefinitionMetricsPer `json:"per"`
	JSON evaluationQueryListResponseEvaluationQueriesDefinitionMetricJSON `json:"-"`
}

// evaluationQueryListResponseEvaluationQueriesDefinitionMetricJSON contains the
// JSON metadata for the struct
// [EvaluationQueryListResponseEvaluationQueriesDefinitionMetric]
type evaluationQueryListResponseEvaluationQueriesDefinitionMetricJSON struct {
	Aggregation     apijson.Field
	Name            apijson.Field
	ScorerVersionID apijson.Field
	K               apijson.Field
	Missing         apijson.Field
	Per             apijson.Field
	raw             string
	ExtraFields     map[string]apijson.Field
}

func (r *EvaluationQueryListResponseEvaluationQueriesDefinitionMetric) UnmarshalJSON(data []byte) (err error) {
	return apijson.UnmarshalRoot(data, r)
}

func (r evaluationQueryListResponseEvaluationQueriesDefinitionMetricJSON) RawJSON() string {
	return r.raw
}

// Calculation to apply to the latest visible score for each case, or for each
// trajectory in a trajectory query.
//
//   - **mean**: Average of integer or number scores, or the fraction of true boolean
//     scores.
//   - **sum**: Sum of integer or number scores, or the number of true boolean
//     scores.
//   - **min / max**: Smallest or largest integer, number, boolean, or string score.
//     Strings compare lexicographically.
//   - **count**: Number of non-null integer, number, boolean, or string scores. Zero
//     and false are counted.
//   - **pass_at_k**: Estimated probability that at least one of k attempts at a task
//     succeeds. Requires boolean scores, k, and per.
//
// For pass_at_k, per identifies each task. A task with n attempts and c true
// scores contributes 1 - C(n-c, k) / C(n, k), and the result averages the tasks.
// The result is null when a task has fewer than k attempts.
type EvaluationQueryListResponseEvaluationQueriesDefinitionMetricsAggregation string

const (
	EvaluationQueryListResponseEvaluationQueriesDefinitionMetricsAggregationMean    EvaluationQueryListResponseEvaluationQueriesDefinitionMetricsAggregation = "mean"
	EvaluationQueryListResponseEvaluationQueriesDefinitionMetricsAggregationSum     EvaluationQueryListResponseEvaluationQueriesDefinitionMetricsAggregation = "sum"
	EvaluationQueryListResponseEvaluationQueriesDefinitionMetricsAggregationMin     EvaluationQueryListResponseEvaluationQueriesDefinitionMetricsAggregation = "min"
	EvaluationQueryListResponseEvaluationQueriesDefinitionMetricsAggregationMax     EvaluationQueryListResponseEvaluationQueriesDefinitionMetricsAggregation = "max"
	EvaluationQueryListResponseEvaluationQueriesDefinitionMetricsAggregationCount   EvaluationQueryListResponseEvaluationQueriesDefinitionMetricsAggregation = "count"
	EvaluationQueryListResponseEvaluationQueriesDefinitionMetricsAggregationPassAtK EvaluationQueryListResponseEvaluationQueriesDefinitionMetricsAggregation = "pass_at_k"
)

func (r EvaluationQueryListResponseEvaluationQueriesDefinitionMetricsAggregation) IsKnown() bool {
	switch r {
	case EvaluationQueryListResponseEvaluationQueriesDefinitionMetricsAggregationMean,
		EvaluationQueryListResponseEvaluationQueriesDefinitionMetricsAggregationSum,
		EvaluationQueryListResponseEvaluationQueriesDefinitionMetricsAggregationMin,
		EvaluationQueryListResponseEvaluationQueriesDefinitionMetricsAggregationMax,
		EvaluationQueryListResponseEvaluationQueriesDefinitionMetricsAggregationCount,
		EvaluationQueryListResponseEvaluationQueriesDefinitionMetricsAggregationPassAtK:
		return true
	}
	return false
}

// How to handle a target with no non-null latest visible score. A target is a
// case, or a trajectory in a trajectory query.
//
//   - **skip**: Exclude the target. A mean divides by the number of scored targets,
//     and pass_at_k does not count it as an attempt. This also applies when missing
//     is omitted.
//   - **zero**: Include the target as 0, or false for boolean scores. A mean divides
//     by every target in the group, and pass_at_k counts it as a failed attempt.
//
// Only mean, sum, and pass_at_k support zero. min, max, and count accept only
// skip.
type EvaluationQueryListResponseEvaluationQueriesDefinitionMetricsMissing string

const (
	EvaluationQueryListResponseEvaluationQueriesDefinitionMetricsMissingSkip EvaluationQueryListResponseEvaluationQueriesDefinitionMetricsMissing = "skip"
	EvaluationQueryListResponseEvaluationQueriesDefinitionMetricsMissingZero EvaluationQueryListResponseEvaluationQueriesDefinitionMetricsMissing = "zero"
)

func (r EvaluationQueryListResponseEvaluationQueriesDefinitionMetricsMissing) IsKnown() bool {
	switch r {
	case EvaluationQueryListResponseEvaluationQueriesDefinitionMetricsMissingSkip,
		EvaluationQueryListResponseEvaluationQueriesDefinitionMetricsMissingZero:
		return true
	}
	return false
}

// Column that identifies the task for each case, or for each trajectory in a
// trajectory query, such as an input task field.
//
//   - Required for pass_at_k and rejected for other aggregations.
//   - Must not also appear in group_by, and must not be depth or
//     parent_trajectory_id.
//   - Targets with no value in this column form one task.
//   - A page returns 400 if the number of groups multiplied by their tasks exceeds
//     the result row limit.
type EvaluationQueryListResponseEvaluationQueriesDefinitionMetricsPer struct {
	Kind EvaluationQueryListResponseEvaluationQueriesDefinitionMetricsPerKind `json:"kind" api:"required"`
	// Name of the input or output field to use as a column.
	Name string `json:"name"`
	// Whether the field belongs to the case's input or output.
	Source EvaluationQueryListResponseEvaluationQueriesDefinitionMetricsPerSource `json:"source"`
	JSON   evaluationQueryListResponseEvaluationQueriesDefinitionMetricsPerJSON   `json:"-"`
	union  EvaluationQueryListResponseEvaluationQueriesDefinitionMetricsPerUnion
}

// evaluationQueryListResponseEvaluationQueriesDefinitionMetricsPerJSON contains
// the JSON metadata for the struct
// [EvaluationQueryListResponseEvaluationQueriesDefinitionMetricsPer]
type evaluationQueryListResponseEvaluationQueriesDefinitionMetricsPerJSON struct {
	Kind        apijson.Field
	Name        apijson.Field
	Source      apijson.Field
	raw         string
	ExtraFields map[string]apijson.Field
}

func (r evaluationQueryListResponseEvaluationQueriesDefinitionMetricsPerJSON) RawJSON() string {
	return r.raw
}

func (r *EvaluationQueryListResponseEvaluationQueriesDefinitionMetricsPer) UnmarshalJSON(data []byte) (err error) {
	*r = EvaluationQueryListResponseEvaluationQueriesDefinitionMetricsPer{}
	err = apijson.UnmarshalRoot(data, &r.union)
	if err != nil {
		return err
	}
	return apijson.Port(r.union, &r)
}

// AsUnion returns a
// [EvaluationQueryListResponseEvaluationQueriesDefinitionMetricsPerUnion]
// interface which you can cast to the specific types for more type safety.
//
// Possible runtime types of the union are
// [EvaluationQueryListResponseEvaluationQueriesDefinitionMetricsPerVariantEvaluationColumn],
// [EvaluationQueryListResponseEvaluationQueriesDefinitionMetricsPerDatasetFieldEvaluationColumn],
// [EvaluationQueryListResponseEvaluationQueriesDefinitionMetricsPerScoreEvaluationColumn],
// [EvaluationQueryListResponseEvaluationQueriesDefinitionMetricsPerDepthEvaluationColumn],
// [EvaluationQueryListResponseEvaluationQueriesDefinitionMetricsPerParentTrajectoryIDEvaluationColumn].
func (r EvaluationQueryListResponseEvaluationQueriesDefinitionMetricsPer) AsUnion() EvaluationQueryListResponseEvaluationQueriesDefinitionMetricsPerUnion {
	return r.union
}

// Column that identifies the task for each case, or for each trajectory in a
// trajectory query, such as an input task field.
//
//   - Required for pass_at_k and rejected for other aggregations.
//   - Must not also appear in group_by, and must not be depth or
//     parent_trajectory_id.
//   - Targets with no value in this column form one task.
//   - A page returns 400 if the number of groups multiplied by their tasks exceeds
//     the result row limit.
//
// Union satisfied by
// [EvaluationQueryListResponseEvaluationQueriesDefinitionMetricsPerVariantEvaluationColumn],
// [EvaluationQueryListResponseEvaluationQueriesDefinitionMetricsPerDatasetFieldEvaluationColumn],
// [EvaluationQueryListResponseEvaluationQueriesDefinitionMetricsPerScoreEvaluationColumn],
// [EvaluationQueryListResponseEvaluationQueriesDefinitionMetricsPerDepthEvaluationColumn]
// or
// [EvaluationQueryListResponseEvaluationQueriesDefinitionMetricsPerParentTrajectoryIDEvaluationColumn].
type EvaluationQueryListResponseEvaluationQueriesDefinitionMetricsPerUnion interface {
	implementsEvaluationQueryListResponseEvaluationQueriesDefinitionMetricsPer()
}

func init() {
	apijson.RegisterUnion(
		reflect.TypeOf((*EvaluationQueryListResponseEvaluationQueriesDefinitionMetricsPerUnion)(nil)).Elem(),
		"kind",
		apijson.UnionVariant{
			TypeFilter: gjson.JSON,
			Type: reflect.TypeOf(
				EvaluationQueryListResponseEvaluationQueriesDefinitionMetricsPerVariantEvaluationColumn{},
			),
			DiscriminatorValue: "variant",
		},
		apijson.UnionVariant{
			TypeFilter: gjson.JSON,
			Type: reflect.TypeOf(
				EvaluationQueryListResponseEvaluationQueriesDefinitionMetricsPerDatasetFieldEvaluationColumn{},
			),
			DiscriminatorValue: "dataset_field",
		},
		apijson.UnionVariant{
			TypeFilter: gjson.JSON,
			Type: reflect.TypeOf(
				EvaluationQueryListResponseEvaluationQueriesDefinitionMetricsPerScoreEvaluationColumn{},
			),
			DiscriminatorValue: "score",
		},
		apijson.UnionVariant{
			TypeFilter: gjson.JSON,
			Type: reflect.TypeOf(
				EvaluationQueryListResponseEvaluationQueriesDefinitionMetricsPerDepthEvaluationColumn{},
			),
			DiscriminatorValue: "depth",
		},
		apijson.UnionVariant{
			TypeFilter: gjson.JSON,
			Type: reflect.TypeOf(
				EvaluationQueryListResponseEvaluationQueriesDefinitionMetricsPerParentTrajectoryIDEvaluationColumn{},
			),
			DiscriminatorValue: "parent_trajectory_id",
		},
	)
}

type EvaluationQueryListResponseEvaluationQueriesDefinitionMetricsPerVariantEvaluationColumn struct {
	Kind EvaluationQueryListResponseEvaluationQueriesDefinitionMetricsPerVariantEvaluationColumnKind `json:"kind" api:"required"`
	JSON evaluationQueryListResponseEvaluationQueriesDefinitionMetricsPerVariantEvaluationColumnJSON `json:"-"`
}

// evaluationQueryListResponseEvaluationQueriesDefinitionMetricsPerVariantEvaluationColumnJSON
// contains the JSON metadata for the struct
// [EvaluationQueryListResponseEvaluationQueriesDefinitionMetricsPerVariantEvaluationColumn]
type evaluationQueryListResponseEvaluationQueriesDefinitionMetricsPerVariantEvaluationColumnJSON struct {
	Kind        apijson.Field
	raw         string
	ExtraFields map[string]apijson.Field
}

func (r *EvaluationQueryListResponseEvaluationQueriesDefinitionMetricsPerVariantEvaluationColumn) UnmarshalJSON(
	data []byte,
) (err error) {
	return apijson.UnmarshalRoot(data, r)
}

func (r evaluationQueryListResponseEvaluationQueriesDefinitionMetricsPerVariantEvaluationColumnJSON) RawJSON() string {
	return r.raw
}

func (r EvaluationQueryListResponseEvaluationQueriesDefinitionMetricsPerVariantEvaluationColumn) implementsEvaluationQueryListResponseEvaluationQueriesDefinitionMetricsPer() {
}

type EvaluationQueryListResponseEvaluationQueriesDefinitionMetricsPerVariantEvaluationColumnKind string

const (
	EvaluationQueryListResponseEvaluationQueriesDefinitionMetricsPerVariantEvaluationColumnKindVariant EvaluationQueryListResponseEvaluationQueriesDefinitionMetricsPerVariantEvaluationColumnKind = "variant"
)

func (r EvaluationQueryListResponseEvaluationQueriesDefinitionMetricsPerVariantEvaluationColumnKind) IsKnown() bool {
	switch r {
	case EvaluationQueryListResponseEvaluationQueriesDefinitionMetricsPerVariantEvaluationColumnKindVariant:
		return true
	}
	return false
}

type EvaluationQueryListResponseEvaluationQueriesDefinitionMetricsPerDatasetFieldEvaluationColumn struct {
	Kind EvaluationQueryListResponseEvaluationQueriesDefinitionMetricsPerDatasetFieldEvaluationColumnKind `json:"kind" api:"required"`
	// Name of the input or output field to use as a column.
	Name string `json:"name" api:"required"`
	// Whether the field belongs to the case's input or output.
	Source EvaluationQueryListResponseEvaluationQueriesDefinitionMetricsPerDatasetFieldEvaluationColumnSource `json:"source" api:"required"`
	JSON   evaluationQueryListResponseEvaluationQueriesDefinitionMetricsPerDatasetFieldEvaluationColumnJSON   `json:"-"`
}

// evaluationQueryListResponseEvaluationQueriesDefinitionMetricsPerDatasetFieldEvaluationColumnJSON
// contains the JSON metadata for the struct
// [EvaluationQueryListResponseEvaluationQueriesDefinitionMetricsPerDatasetFieldEvaluationColumn]
type evaluationQueryListResponseEvaluationQueriesDefinitionMetricsPerDatasetFieldEvaluationColumnJSON struct {
	Kind        apijson.Field
	Name        apijson.Field
	Source      apijson.Field
	raw         string
	ExtraFields map[string]apijson.Field
}

func (r *EvaluationQueryListResponseEvaluationQueriesDefinitionMetricsPerDatasetFieldEvaluationColumn) UnmarshalJSON(
	data []byte,
) (err error) {
	return apijson.UnmarshalRoot(data, r)
}

func (r evaluationQueryListResponseEvaluationQueriesDefinitionMetricsPerDatasetFieldEvaluationColumnJSON) RawJSON() string {
	return r.raw
}

func (r EvaluationQueryListResponseEvaluationQueriesDefinitionMetricsPerDatasetFieldEvaluationColumn) implementsEvaluationQueryListResponseEvaluationQueriesDefinitionMetricsPer() {
}

type EvaluationQueryListResponseEvaluationQueriesDefinitionMetricsPerDatasetFieldEvaluationColumnKind string

const (
	EvaluationQueryListResponseEvaluationQueriesDefinitionMetricsPerDatasetFieldEvaluationColumnKindDatasetField EvaluationQueryListResponseEvaluationQueriesDefinitionMetricsPerDatasetFieldEvaluationColumnKind = "dataset_field"
)

func (r EvaluationQueryListResponseEvaluationQueriesDefinitionMetricsPerDatasetFieldEvaluationColumnKind) IsKnown() bool {
	switch r {
	case EvaluationQueryListResponseEvaluationQueriesDefinitionMetricsPerDatasetFieldEvaluationColumnKindDatasetField:
		return true
	}
	return false
}

// Whether the field belongs to the case's input or output.
type EvaluationQueryListResponseEvaluationQueriesDefinitionMetricsPerDatasetFieldEvaluationColumnSource string

const (
	EvaluationQueryListResponseEvaluationQueriesDefinitionMetricsPerDatasetFieldEvaluationColumnSourceInput  EvaluationQueryListResponseEvaluationQueriesDefinitionMetricsPerDatasetFieldEvaluationColumnSource = "input"
	EvaluationQueryListResponseEvaluationQueriesDefinitionMetricsPerDatasetFieldEvaluationColumnSourceOutput EvaluationQueryListResponseEvaluationQueriesDefinitionMetricsPerDatasetFieldEvaluationColumnSource = "output"
)

func (r EvaluationQueryListResponseEvaluationQueriesDefinitionMetricsPerDatasetFieldEvaluationColumnSource) IsKnown() bool {
	switch r {
	case EvaluationQueryListResponseEvaluationQueriesDefinitionMetricsPerDatasetFieldEvaluationColumnSourceInput,
		EvaluationQueryListResponseEvaluationQueriesDefinitionMetricsPerDatasetFieldEvaluationColumnSourceOutput:
		return true
	}
	return false
}

type EvaluationQueryListResponseEvaluationQueriesDefinitionMetricsPerScoreEvaluationColumn struct {
	Kind EvaluationQueryListResponseEvaluationQueriesDefinitionMetricsPerScoreEvaluationColumnKind `json:"kind" api:"required"`
	// Name of the scorer whose score supplies this column.
	Name string                                                                                    `json:"name" api:"required"`
	JSON evaluationQueryListResponseEvaluationQueriesDefinitionMetricsPerScoreEvaluationColumnJSON `json:"-"`
}

// evaluationQueryListResponseEvaluationQueriesDefinitionMetricsPerScoreEvaluationColumnJSON
// contains the JSON metadata for the struct
// [EvaluationQueryListResponseEvaluationQueriesDefinitionMetricsPerScoreEvaluationColumn]
type evaluationQueryListResponseEvaluationQueriesDefinitionMetricsPerScoreEvaluationColumnJSON struct {
	Kind        apijson.Field
	Name        apijson.Field
	raw         string
	ExtraFields map[string]apijson.Field
}

func (r *EvaluationQueryListResponseEvaluationQueriesDefinitionMetricsPerScoreEvaluationColumn) UnmarshalJSON(
	data []byte,
) (err error) {
	return apijson.UnmarshalRoot(data, r)
}

func (r evaluationQueryListResponseEvaluationQueriesDefinitionMetricsPerScoreEvaluationColumnJSON) RawJSON() string {
	return r.raw
}

func (r EvaluationQueryListResponseEvaluationQueriesDefinitionMetricsPerScoreEvaluationColumn) implementsEvaluationQueryListResponseEvaluationQueriesDefinitionMetricsPer() {
}

type EvaluationQueryListResponseEvaluationQueriesDefinitionMetricsPerScoreEvaluationColumnKind string

const (
	EvaluationQueryListResponseEvaluationQueriesDefinitionMetricsPerScoreEvaluationColumnKindScore EvaluationQueryListResponseEvaluationQueriesDefinitionMetricsPerScoreEvaluationColumnKind = "score"
)

func (r EvaluationQueryListResponseEvaluationQueriesDefinitionMetricsPerScoreEvaluationColumnKind) IsKnown() bool {
	switch r {
	case EvaluationQueryListResponseEvaluationQueriesDefinitionMetricsPerScoreEvaluationColumnKindScore:
		return true
	}
	return false
}

// Trajectory queries only. Groups by depth, an integer that is 0 for a top-level
// trajectory.
type EvaluationQueryListResponseEvaluationQueriesDefinitionMetricsPerDepthEvaluationColumn struct {
	Kind EvaluationQueryListResponseEvaluationQueriesDefinitionMetricsPerDepthEvaluationColumnKind `json:"kind" api:"required"`
	JSON evaluationQueryListResponseEvaluationQueriesDefinitionMetricsPerDepthEvaluationColumnJSON `json:"-"`
}

// evaluationQueryListResponseEvaluationQueriesDefinitionMetricsPerDepthEvaluationColumnJSON
// contains the JSON metadata for the struct
// [EvaluationQueryListResponseEvaluationQueriesDefinitionMetricsPerDepthEvaluationColumn]
type evaluationQueryListResponseEvaluationQueriesDefinitionMetricsPerDepthEvaluationColumnJSON struct {
	Kind        apijson.Field
	raw         string
	ExtraFields map[string]apijson.Field
}

func (r *EvaluationQueryListResponseEvaluationQueriesDefinitionMetricsPerDepthEvaluationColumn) UnmarshalJSON(
	data []byte,
) (err error) {
	return apijson.UnmarshalRoot(data, r)
}

func (r evaluationQueryListResponseEvaluationQueriesDefinitionMetricsPerDepthEvaluationColumnJSON) RawJSON() string {
	return r.raw
}

func (r EvaluationQueryListResponseEvaluationQueriesDefinitionMetricsPerDepthEvaluationColumn) implementsEvaluationQueryListResponseEvaluationQueriesDefinitionMetricsPer() {
}

type EvaluationQueryListResponseEvaluationQueriesDefinitionMetricsPerDepthEvaluationColumnKind string

const (
	EvaluationQueryListResponseEvaluationQueriesDefinitionMetricsPerDepthEvaluationColumnKindDepth EvaluationQueryListResponseEvaluationQueriesDefinitionMetricsPerDepthEvaluationColumnKind = "depth"
)

func (r EvaluationQueryListResponseEvaluationQueriesDefinitionMetricsPerDepthEvaluationColumnKind) IsKnown() bool {
	switch r {
	case EvaluationQueryListResponseEvaluationQueriesDefinitionMetricsPerDepthEvaluationColumnKindDepth:
		return true
	}
	return false
}

// Trajectory queries only. Groups by the parent trajectory's ID. Top-level
// trajectories form the null group.
type EvaluationQueryListResponseEvaluationQueriesDefinitionMetricsPerParentTrajectoryIDEvaluationColumn struct {
	Kind EvaluationQueryListResponseEvaluationQueriesDefinitionMetricsPerParentTrajectoryIDEvaluationColumnKind `json:"kind" api:"required"`
	JSON evaluationQueryListResponseEvaluationQueriesDefinitionMetricsPerParentTrajectoryIDEvaluationColumnJSON `json:"-"`
}

// evaluationQueryListResponseEvaluationQueriesDefinitionMetricsPerParentTrajectoryIDEvaluationColumnJSON
// contains the JSON metadata for the struct
// [EvaluationQueryListResponseEvaluationQueriesDefinitionMetricsPerParentTrajectoryIDEvaluationColumn]
type evaluationQueryListResponseEvaluationQueriesDefinitionMetricsPerParentTrajectoryIDEvaluationColumnJSON struct {
	Kind        apijson.Field
	raw         string
	ExtraFields map[string]apijson.Field
}

func (r *EvaluationQueryListResponseEvaluationQueriesDefinitionMetricsPerParentTrajectoryIDEvaluationColumn) UnmarshalJSON(
	data []byte,
) (err error) {
	return apijson.UnmarshalRoot(data, r)
}

func (r evaluationQueryListResponseEvaluationQueriesDefinitionMetricsPerParentTrajectoryIDEvaluationColumnJSON) RawJSON() string {
	return r.raw
}

func (r EvaluationQueryListResponseEvaluationQueriesDefinitionMetricsPerParentTrajectoryIDEvaluationColumn) implementsEvaluationQueryListResponseEvaluationQueriesDefinitionMetricsPer() {
}

type EvaluationQueryListResponseEvaluationQueriesDefinitionMetricsPerParentTrajectoryIDEvaluationColumnKind string

const (
	EvaluationQueryListResponseEvaluationQueriesDefinitionMetricsPerParentTrajectoryIDEvaluationColumnKindParentTrajectoryID EvaluationQueryListResponseEvaluationQueriesDefinitionMetricsPerParentTrajectoryIDEvaluationColumnKind = "parent_trajectory_id"
)

func (r EvaluationQueryListResponseEvaluationQueriesDefinitionMetricsPerParentTrajectoryIDEvaluationColumnKind) IsKnown() bool {
	switch r {
	case EvaluationQueryListResponseEvaluationQueriesDefinitionMetricsPerParentTrajectoryIDEvaluationColumnKindParentTrajectoryID:
		return true
	}
	return false
}

type EvaluationQueryListResponseEvaluationQueriesDefinitionMetricsPerKind string

const (
	EvaluationQueryListResponseEvaluationQueriesDefinitionMetricsPerKindVariant            EvaluationQueryListResponseEvaluationQueriesDefinitionMetricsPerKind = "variant"
	EvaluationQueryListResponseEvaluationQueriesDefinitionMetricsPerKindDatasetField       EvaluationQueryListResponseEvaluationQueriesDefinitionMetricsPerKind = "dataset_field"
	EvaluationQueryListResponseEvaluationQueriesDefinitionMetricsPerKindScore              EvaluationQueryListResponseEvaluationQueriesDefinitionMetricsPerKind = "score"
	EvaluationQueryListResponseEvaluationQueriesDefinitionMetricsPerKindDepth              EvaluationQueryListResponseEvaluationQueriesDefinitionMetricsPerKind = "depth"
	EvaluationQueryListResponseEvaluationQueriesDefinitionMetricsPerKindParentTrajectoryID EvaluationQueryListResponseEvaluationQueriesDefinitionMetricsPerKind = "parent_trajectory_id"
)

func (r EvaluationQueryListResponseEvaluationQueriesDefinitionMetricsPerKind) IsKnown() bool {
	switch r {
	case EvaluationQueryListResponseEvaluationQueriesDefinitionMetricsPerKindVariant,
		EvaluationQueryListResponseEvaluationQueriesDefinitionMetricsPerKindDatasetField,
		EvaluationQueryListResponseEvaluationQueriesDefinitionMetricsPerKindScore,
		EvaluationQueryListResponseEvaluationQueriesDefinitionMetricsPerKindDepth,
		EvaluationQueryListResponseEvaluationQueriesDefinitionMetricsPerKindParentTrajectoryID:
		return true
	}
	return false
}

// Whether the field belongs to the case's input or output.
type EvaluationQueryListResponseEvaluationQueriesDefinitionMetricsPerSource string

const (
	EvaluationQueryListResponseEvaluationQueriesDefinitionMetricsPerSourceInput  EvaluationQueryListResponseEvaluationQueriesDefinitionMetricsPerSource = "input"
	EvaluationQueryListResponseEvaluationQueriesDefinitionMetricsPerSourceOutput EvaluationQueryListResponseEvaluationQueriesDefinitionMetricsPerSource = "output"
)

func (r EvaluationQueryListResponseEvaluationQueriesDefinitionMetricsPerSource) IsKnown() bool {
	switch r {
	case EvaluationQueryListResponseEvaluationQueriesDefinitionMetricsPerSourceInput,
		EvaluationQueryListResponseEvaluationQueriesDefinitionMetricsPerSourceOutput:
		return true
	}
	return false
}

// Trajectory queries only. Groups by depth, an integer that is 0 for a top-level
// trajectory.
type EvaluationQueryListResponseEvaluationQueriesDefinitionGroupBy struct {
	Kind EvaluationQueryListResponseEvaluationQueriesDefinitionGroupByKind `json:"kind" api:"required"`
	// Name of the input or output field to use as a column.
	Name string `json:"name"`
	// Whether the field belongs to the case's input or output.
	Source EvaluationQueryListResponseEvaluationQueriesDefinitionGroupBySource `json:"source"`
	JSON   evaluationQueryListResponseEvaluationQueriesDefinitionGroupByJSON   `json:"-"`
	union  EvaluationQueryListResponseEvaluationQueriesDefinitionGroupByUnion
}

// evaluationQueryListResponseEvaluationQueriesDefinitionGroupByJSON contains the
// JSON metadata for the struct
// [EvaluationQueryListResponseEvaluationQueriesDefinitionGroupBy]
type evaluationQueryListResponseEvaluationQueriesDefinitionGroupByJSON struct {
	Kind        apijson.Field
	Name        apijson.Field
	Source      apijson.Field
	raw         string
	ExtraFields map[string]apijson.Field
}

func (r evaluationQueryListResponseEvaluationQueriesDefinitionGroupByJSON) RawJSON() string {
	return r.raw
}

func (r *EvaluationQueryListResponseEvaluationQueriesDefinitionGroupBy) UnmarshalJSON(data []byte) (err error) {
	*r = EvaluationQueryListResponseEvaluationQueriesDefinitionGroupBy{}
	err = apijson.UnmarshalRoot(data, &r.union)
	if err != nil {
		return err
	}
	return apijson.Port(r.union, &r)
}

// AsUnion returns a
// [EvaluationQueryListResponseEvaluationQueriesDefinitionGroupByUnion] interface
// which you can cast to the specific types for more type safety.
//
// Possible runtime types of the union are
// [EvaluationQueryListResponseEvaluationQueriesDefinitionGroupByVariantEvaluationColumn],
// [EvaluationQueryListResponseEvaluationQueriesDefinitionGroupByDatasetFieldEvaluationColumn],
// [EvaluationQueryListResponseEvaluationQueriesDefinitionGroupByScoreEvaluationColumn],
// [EvaluationQueryListResponseEvaluationQueriesDefinitionGroupByDepthEvaluationColumn],
// [EvaluationQueryListResponseEvaluationQueriesDefinitionGroupByParentTrajectoryIDEvaluationColumn].
func (r EvaluationQueryListResponseEvaluationQueriesDefinitionGroupBy) AsUnion() EvaluationQueryListResponseEvaluationQueriesDefinitionGroupByUnion {
	return r.union
}

// Trajectory queries only. Groups by depth, an integer that is 0 for a top-level
// trajectory.
//
// Union satisfied by
// [EvaluationQueryListResponseEvaluationQueriesDefinitionGroupByVariantEvaluationColumn],
// [EvaluationQueryListResponseEvaluationQueriesDefinitionGroupByDatasetFieldEvaluationColumn],
// [EvaluationQueryListResponseEvaluationQueriesDefinitionGroupByScoreEvaluationColumn],
// [EvaluationQueryListResponseEvaluationQueriesDefinitionGroupByDepthEvaluationColumn]
// or
// [EvaluationQueryListResponseEvaluationQueriesDefinitionGroupByParentTrajectoryIDEvaluationColumn].
type EvaluationQueryListResponseEvaluationQueriesDefinitionGroupByUnion interface {
	implementsEvaluationQueryListResponseEvaluationQueriesDefinitionGroupBy()
}

func init() {
	apijson.RegisterUnion(
		reflect.TypeOf((*EvaluationQueryListResponseEvaluationQueriesDefinitionGroupByUnion)(nil)).Elem(),
		"kind",
		apijson.UnionVariant{
			TypeFilter: gjson.JSON,
			Type: reflect.TypeOf(
				EvaluationQueryListResponseEvaluationQueriesDefinitionGroupByVariantEvaluationColumn{},
			),
			DiscriminatorValue: "variant",
		},
		apijson.UnionVariant{
			TypeFilter: gjson.JSON,
			Type: reflect.TypeOf(
				EvaluationQueryListResponseEvaluationQueriesDefinitionGroupByDatasetFieldEvaluationColumn{},
			),
			DiscriminatorValue: "dataset_field",
		},
		apijson.UnionVariant{
			TypeFilter: gjson.JSON,
			Type: reflect.TypeOf(
				EvaluationQueryListResponseEvaluationQueriesDefinitionGroupByScoreEvaluationColumn{},
			),
			DiscriminatorValue: "score",
		},
		apijson.UnionVariant{
			TypeFilter: gjson.JSON,
			Type: reflect.TypeOf(
				EvaluationQueryListResponseEvaluationQueriesDefinitionGroupByDepthEvaluationColumn{},
			),
			DiscriminatorValue: "depth",
		},
		apijson.UnionVariant{
			TypeFilter: gjson.JSON,
			Type: reflect.TypeOf(
				EvaluationQueryListResponseEvaluationQueriesDefinitionGroupByParentTrajectoryIDEvaluationColumn{},
			),
			DiscriminatorValue: "parent_trajectory_id",
		},
	)
}

type EvaluationQueryListResponseEvaluationQueriesDefinitionGroupByVariantEvaluationColumn struct {
	Kind EvaluationQueryListResponseEvaluationQueriesDefinitionGroupByVariantEvaluationColumnKind `json:"kind" api:"required"`
	JSON evaluationQueryListResponseEvaluationQueriesDefinitionGroupByVariantEvaluationColumnJSON `json:"-"`
}

// evaluationQueryListResponseEvaluationQueriesDefinitionGroupByVariantEvaluationColumnJSON
// contains the JSON metadata for the struct
// [EvaluationQueryListResponseEvaluationQueriesDefinitionGroupByVariantEvaluationColumn]
type evaluationQueryListResponseEvaluationQueriesDefinitionGroupByVariantEvaluationColumnJSON struct {
	Kind        apijson.Field
	raw         string
	ExtraFields map[string]apijson.Field
}

func (r *EvaluationQueryListResponseEvaluationQueriesDefinitionGroupByVariantEvaluationColumn) UnmarshalJSON(
	data []byte,
) (err error) {
	return apijson.UnmarshalRoot(data, r)
}

func (r evaluationQueryListResponseEvaluationQueriesDefinitionGroupByVariantEvaluationColumnJSON) RawJSON() string {
	return r.raw
}

func (r EvaluationQueryListResponseEvaluationQueriesDefinitionGroupByVariantEvaluationColumn) implementsEvaluationQueryListResponseEvaluationQueriesDefinitionGroupBy() {
}

type EvaluationQueryListResponseEvaluationQueriesDefinitionGroupByVariantEvaluationColumnKind string

const (
	EvaluationQueryListResponseEvaluationQueriesDefinitionGroupByVariantEvaluationColumnKindVariant EvaluationQueryListResponseEvaluationQueriesDefinitionGroupByVariantEvaluationColumnKind = "variant"
)

func (r EvaluationQueryListResponseEvaluationQueriesDefinitionGroupByVariantEvaluationColumnKind) IsKnown() bool {
	switch r {
	case EvaluationQueryListResponseEvaluationQueriesDefinitionGroupByVariantEvaluationColumnKindVariant:
		return true
	}
	return false
}

type EvaluationQueryListResponseEvaluationQueriesDefinitionGroupByDatasetFieldEvaluationColumn struct {
	Kind EvaluationQueryListResponseEvaluationQueriesDefinitionGroupByDatasetFieldEvaluationColumnKind `json:"kind" api:"required"`
	// Name of the input or output field to use as a column.
	Name string `json:"name" api:"required"`
	// Whether the field belongs to the case's input or output.
	Source EvaluationQueryListResponseEvaluationQueriesDefinitionGroupByDatasetFieldEvaluationColumnSource `json:"source" api:"required"`
	JSON   evaluationQueryListResponseEvaluationQueriesDefinitionGroupByDatasetFieldEvaluationColumnJSON   `json:"-"`
}

// evaluationQueryListResponseEvaluationQueriesDefinitionGroupByDatasetFieldEvaluationColumnJSON
// contains the JSON metadata for the struct
// [EvaluationQueryListResponseEvaluationQueriesDefinitionGroupByDatasetFieldEvaluationColumn]
type evaluationQueryListResponseEvaluationQueriesDefinitionGroupByDatasetFieldEvaluationColumnJSON struct {
	Kind        apijson.Field
	Name        apijson.Field
	Source      apijson.Field
	raw         string
	ExtraFields map[string]apijson.Field
}

func (r *EvaluationQueryListResponseEvaluationQueriesDefinitionGroupByDatasetFieldEvaluationColumn) UnmarshalJSON(
	data []byte,
) (err error) {
	return apijson.UnmarshalRoot(data, r)
}

func (r evaluationQueryListResponseEvaluationQueriesDefinitionGroupByDatasetFieldEvaluationColumnJSON) RawJSON() string {
	return r.raw
}

func (r EvaluationQueryListResponseEvaluationQueriesDefinitionGroupByDatasetFieldEvaluationColumn) implementsEvaluationQueryListResponseEvaluationQueriesDefinitionGroupBy() {
}

type EvaluationQueryListResponseEvaluationQueriesDefinitionGroupByDatasetFieldEvaluationColumnKind string

const (
	EvaluationQueryListResponseEvaluationQueriesDefinitionGroupByDatasetFieldEvaluationColumnKindDatasetField EvaluationQueryListResponseEvaluationQueriesDefinitionGroupByDatasetFieldEvaluationColumnKind = "dataset_field"
)

func (r EvaluationQueryListResponseEvaluationQueriesDefinitionGroupByDatasetFieldEvaluationColumnKind) IsKnown() bool {
	switch r {
	case EvaluationQueryListResponseEvaluationQueriesDefinitionGroupByDatasetFieldEvaluationColumnKindDatasetField:
		return true
	}
	return false
}

// Whether the field belongs to the case's input or output.
type EvaluationQueryListResponseEvaluationQueriesDefinitionGroupByDatasetFieldEvaluationColumnSource string

const (
	EvaluationQueryListResponseEvaluationQueriesDefinitionGroupByDatasetFieldEvaluationColumnSourceInput  EvaluationQueryListResponseEvaluationQueriesDefinitionGroupByDatasetFieldEvaluationColumnSource = "input"
	EvaluationQueryListResponseEvaluationQueriesDefinitionGroupByDatasetFieldEvaluationColumnSourceOutput EvaluationQueryListResponseEvaluationQueriesDefinitionGroupByDatasetFieldEvaluationColumnSource = "output"
)

func (r EvaluationQueryListResponseEvaluationQueriesDefinitionGroupByDatasetFieldEvaluationColumnSource) IsKnown() bool {
	switch r {
	case EvaluationQueryListResponseEvaluationQueriesDefinitionGroupByDatasetFieldEvaluationColumnSourceInput,
		EvaluationQueryListResponseEvaluationQueriesDefinitionGroupByDatasetFieldEvaluationColumnSourceOutput:
		return true
	}
	return false
}

type EvaluationQueryListResponseEvaluationQueriesDefinitionGroupByScoreEvaluationColumn struct {
	Kind EvaluationQueryListResponseEvaluationQueriesDefinitionGroupByScoreEvaluationColumnKind `json:"kind" api:"required"`
	// Name of the scorer whose score supplies this column.
	Name string                                                                                 `json:"name" api:"required"`
	JSON evaluationQueryListResponseEvaluationQueriesDefinitionGroupByScoreEvaluationColumnJSON `json:"-"`
}

// evaluationQueryListResponseEvaluationQueriesDefinitionGroupByScoreEvaluationColumnJSON
// contains the JSON metadata for the struct
// [EvaluationQueryListResponseEvaluationQueriesDefinitionGroupByScoreEvaluationColumn]
type evaluationQueryListResponseEvaluationQueriesDefinitionGroupByScoreEvaluationColumnJSON struct {
	Kind        apijson.Field
	Name        apijson.Field
	raw         string
	ExtraFields map[string]apijson.Field
}

func (r *EvaluationQueryListResponseEvaluationQueriesDefinitionGroupByScoreEvaluationColumn) UnmarshalJSON(
	data []byte,
) (err error) {
	return apijson.UnmarshalRoot(data, r)
}

func (r evaluationQueryListResponseEvaluationQueriesDefinitionGroupByScoreEvaluationColumnJSON) RawJSON() string {
	return r.raw
}

func (r EvaluationQueryListResponseEvaluationQueriesDefinitionGroupByScoreEvaluationColumn) implementsEvaluationQueryListResponseEvaluationQueriesDefinitionGroupBy() {
}

type EvaluationQueryListResponseEvaluationQueriesDefinitionGroupByScoreEvaluationColumnKind string

const (
	EvaluationQueryListResponseEvaluationQueriesDefinitionGroupByScoreEvaluationColumnKindScore EvaluationQueryListResponseEvaluationQueriesDefinitionGroupByScoreEvaluationColumnKind = "score"
)

func (r EvaluationQueryListResponseEvaluationQueriesDefinitionGroupByScoreEvaluationColumnKind) IsKnown() bool {
	switch r {
	case EvaluationQueryListResponseEvaluationQueriesDefinitionGroupByScoreEvaluationColumnKindScore:
		return true
	}
	return false
}

// Trajectory queries only. Groups by depth, an integer that is 0 for a top-level
// trajectory.
type EvaluationQueryListResponseEvaluationQueriesDefinitionGroupByDepthEvaluationColumn struct {
	Kind EvaluationQueryListResponseEvaluationQueriesDefinitionGroupByDepthEvaluationColumnKind `json:"kind" api:"required"`
	JSON evaluationQueryListResponseEvaluationQueriesDefinitionGroupByDepthEvaluationColumnJSON `json:"-"`
}

// evaluationQueryListResponseEvaluationQueriesDefinitionGroupByDepthEvaluationColumnJSON
// contains the JSON metadata for the struct
// [EvaluationQueryListResponseEvaluationQueriesDefinitionGroupByDepthEvaluationColumn]
type evaluationQueryListResponseEvaluationQueriesDefinitionGroupByDepthEvaluationColumnJSON struct {
	Kind        apijson.Field
	raw         string
	ExtraFields map[string]apijson.Field
}

func (r *EvaluationQueryListResponseEvaluationQueriesDefinitionGroupByDepthEvaluationColumn) UnmarshalJSON(
	data []byte,
) (err error) {
	return apijson.UnmarshalRoot(data, r)
}

func (r evaluationQueryListResponseEvaluationQueriesDefinitionGroupByDepthEvaluationColumnJSON) RawJSON() string {
	return r.raw
}

func (r EvaluationQueryListResponseEvaluationQueriesDefinitionGroupByDepthEvaluationColumn) implementsEvaluationQueryListResponseEvaluationQueriesDefinitionGroupBy() {
}

type EvaluationQueryListResponseEvaluationQueriesDefinitionGroupByDepthEvaluationColumnKind string

const (
	EvaluationQueryListResponseEvaluationQueriesDefinitionGroupByDepthEvaluationColumnKindDepth EvaluationQueryListResponseEvaluationQueriesDefinitionGroupByDepthEvaluationColumnKind = "depth"
)

func (r EvaluationQueryListResponseEvaluationQueriesDefinitionGroupByDepthEvaluationColumnKind) IsKnown() bool {
	switch r {
	case EvaluationQueryListResponseEvaluationQueriesDefinitionGroupByDepthEvaluationColumnKindDepth:
		return true
	}
	return false
}

// Trajectory queries only. Groups by the parent trajectory's ID. Top-level
// trajectories form the null group.
type EvaluationQueryListResponseEvaluationQueriesDefinitionGroupByParentTrajectoryIDEvaluationColumn struct {
	Kind EvaluationQueryListResponseEvaluationQueriesDefinitionGroupByParentTrajectoryIDEvaluationColumnKind `json:"kind" api:"required"`
	JSON evaluationQueryListResponseEvaluationQueriesDefinitionGroupByParentTrajectoryIDEvaluationColumnJSON `json:"-"`
}

// evaluationQueryListResponseEvaluationQueriesDefinitionGroupByParentTrajectoryIDEvaluationColumnJSON
// contains the JSON metadata for the struct
// [EvaluationQueryListResponseEvaluationQueriesDefinitionGroupByParentTrajectoryIDEvaluationColumn]
type evaluationQueryListResponseEvaluationQueriesDefinitionGroupByParentTrajectoryIDEvaluationColumnJSON struct {
	Kind        apijson.Field
	raw         string
	ExtraFields map[string]apijson.Field
}

func (r *EvaluationQueryListResponseEvaluationQueriesDefinitionGroupByParentTrajectoryIDEvaluationColumn) UnmarshalJSON(
	data []byte,
) (err error) {
	return apijson.UnmarshalRoot(data, r)
}

func (r evaluationQueryListResponseEvaluationQueriesDefinitionGroupByParentTrajectoryIDEvaluationColumnJSON) RawJSON() string {
	return r.raw
}

func (r EvaluationQueryListResponseEvaluationQueriesDefinitionGroupByParentTrajectoryIDEvaluationColumn) implementsEvaluationQueryListResponseEvaluationQueriesDefinitionGroupBy() {
}

type EvaluationQueryListResponseEvaluationQueriesDefinitionGroupByParentTrajectoryIDEvaluationColumnKind string

const (
	EvaluationQueryListResponseEvaluationQueriesDefinitionGroupByParentTrajectoryIDEvaluationColumnKindParentTrajectoryID EvaluationQueryListResponseEvaluationQueriesDefinitionGroupByParentTrajectoryIDEvaluationColumnKind = "parent_trajectory_id"
)

func (r EvaluationQueryListResponseEvaluationQueriesDefinitionGroupByParentTrajectoryIDEvaluationColumnKind) IsKnown() bool {
	switch r {
	case EvaluationQueryListResponseEvaluationQueriesDefinitionGroupByParentTrajectoryIDEvaluationColumnKindParentTrajectoryID:
		return true
	}
	return false
}

type EvaluationQueryListResponseEvaluationQueriesDefinitionGroupByKind string

const (
	EvaluationQueryListResponseEvaluationQueriesDefinitionGroupByKindVariant            EvaluationQueryListResponseEvaluationQueriesDefinitionGroupByKind = "variant"
	EvaluationQueryListResponseEvaluationQueriesDefinitionGroupByKindDatasetField       EvaluationQueryListResponseEvaluationQueriesDefinitionGroupByKind = "dataset_field"
	EvaluationQueryListResponseEvaluationQueriesDefinitionGroupByKindScore              EvaluationQueryListResponseEvaluationQueriesDefinitionGroupByKind = "score"
	EvaluationQueryListResponseEvaluationQueriesDefinitionGroupByKindDepth              EvaluationQueryListResponseEvaluationQueriesDefinitionGroupByKind = "depth"
	EvaluationQueryListResponseEvaluationQueriesDefinitionGroupByKindParentTrajectoryID EvaluationQueryListResponseEvaluationQueriesDefinitionGroupByKind = "parent_trajectory_id"
)

func (r EvaluationQueryListResponseEvaluationQueriesDefinitionGroupByKind) IsKnown() bool {
	switch r {
	case EvaluationQueryListResponseEvaluationQueriesDefinitionGroupByKindVariant,
		EvaluationQueryListResponseEvaluationQueriesDefinitionGroupByKindDatasetField,
		EvaluationQueryListResponseEvaluationQueriesDefinitionGroupByKindScore,
		EvaluationQueryListResponseEvaluationQueriesDefinitionGroupByKindDepth,
		EvaluationQueryListResponseEvaluationQueriesDefinitionGroupByKindParentTrajectoryID:
		return true
	}
	return false
}

// Whether the field belongs to the case's input or output.
type EvaluationQueryListResponseEvaluationQueriesDefinitionGroupBySource string

const (
	EvaluationQueryListResponseEvaluationQueriesDefinitionGroupBySourceInput  EvaluationQueryListResponseEvaluationQueriesDefinitionGroupBySource = "input"
	EvaluationQueryListResponseEvaluationQueriesDefinitionGroupBySourceOutput EvaluationQueryListResponseEvaluationQueriesDefinitionGroupBySource = "output"
)

func (r EvaluationQueryListResponseEvaluationQueriesDefinitionGroupBySource) IsKnown() bool {
	switch r {
	case EvaluationQueryListResponseEvaluationQueriesDefinitionGroupBySourceInput,
		EvaluationQueryListResponseEvaluationQueriesDefinitionGroupBySourceOutput:
		return true
	}
	return false
}

// Absent for a query over cases.
type EvaluationQueryListResponseEvaluationQueriesDefinitionTargetKind string

const (
	EvaluationQueryListResponseEvaluationQueriesDefinitionTargetKindTrajectory EvaluationQueryListResponseEvaluationQueriesDefinitionTargetKind = "trajectory"
)

func (r EvaluationQueryListResponseEvaluationQueriesDefinitionTargetKind) IsKnown() bool {
	switch r {
	case EvaluationQueryListResponseEvaluationQueriesDefinitionTargetKindTrajectory:
		return true
	}
	return false
}

// Namespace that assigned the scope reference.
type EvaluationQueryListResponseEvaluationQueriesNamespace string

const (
	EvaluationQueryListResponseEvaluationQueriesNamespaceWandb EvaluationQueryListResponseEvaluationQueriesNamespace = "wandb"
)

func (r EvaluationQueryListResponseEvaluationQueriesNamespace) IsKnown() bool {
	switch r {
	case EvaluationQueryListResponseEvaluationQueriesNamespaceWandb:
		return true
	}
	return false
}

type EvaluationQueryGetResponse struct {
	Definition        EvaluationQueryGetResponseDefinition `json:"definition"          api:"required"`
	EvaluationID      string                               `json:"evaluation_id"       api:"required" format:"uuid"`
	EvaluationQueryID string                               `json:"evaluation_query_id" api:"required" format:"uuid"`
	Name              string                               `json:"name"                api:"required"`
	// Namespace that assigned the scope reference.
	Namespace EvaluationQueryGetResponseNamespace `json:"namespace" api:"required"`
	ScopeRef  string                              `json:"scope_ref" api:"required"`
	JSON      evaluationQueryGetResponseJSON      `json:"-"`
}

// evaluationQueryGetResponseJSON contains the JSON metadata for the struct
// [EvaluationQueryGetResponse]
type evaluationQueryGetResponseJSON struct {
	Definition        apijson.Field
	EvaluationID      apijson.Field
	EvaluationQueryID apijson.Field
	Name              apijson.Field
	Namespace         apijson.Field
	ScopeRef          apijson.Field
	raw               string
	ExtraFields       map[string]apijson.Field
}

func (r *EvaluationQueryGetResponse) UnmarshalJSON(data []byte) (err error) {
	return apijson.UnmarshalRoot(data, r)
}

func (r evaluationQueryGetResponseJSON) RawJSON() string {
	return r.raw
}

type EvaluationQueryGetResponseDefinition struct {
	Metrics []EvaluationQueryGetResponseDefinitionMetric `json:"metrics" api:"required"`
	// Stored definition version. Always present in responses.
	V       int64                                         `json:"v"        api:"required"`
	GroupBy []EvaluationQueryGetResponseDefinitionGroupBy `json:"group_by"`
	// Absent for a query over cases.
	TargetKind EvaluationQueryGetResponseDefinitionTargetKind `json:"target_kind"`
	JSON       evaluationQueryGetResponseDefinitionJSON       `json:"-"`
}

// evaluationQueryGetResponseDefinitionJSON contains the JSON metadata for the
// struct [EvaluationQueryGetResponseDefinition]
type evaluationQueryGetResponseDefinitionJSON struct {
	Metrics     apijson.Field
	V           apijson.Field
	GroupBy     apijson.Field
	TargetKind  apijson.Field
	raw         string
	ExtraFields map[string]apijson.Field
}

func (r *EvaluationQueryGetResponseDefinition) UnmarshalJSON(data []byte) (err error) {
	return apijson.UnmarshalRoot(data, r)
}

func (r evaluationQueryGetResponseDefinitionJSON) RawJSON() string {
	return r.raw
}

type EvaluationQueryGetResponseDefinitionMetric struct {
	// Calculation to apply to the latest visible score for each case, or for each
	// trajectory in a trajectory query.
	//
	//   - **mean**: Average of integer or number scores, or the fraction of true boolean
	//     scores.
	//   - **sum**: Sum of integer or number scores, or the number of true boolean
	//     scores.
	//   - **min / max**: Smallest or largest integer, number, boolean, or string score.
	//     Strings compare lexicographically.
	//   - **count**: Number of non-null integer, number, boolean, or string scores. Zero
	//     and false are counted.
	//   - **pass_at_k**: Estimated probability that at least one of k attempts at a task
	//     succeeds. Requires boolean scores, k, and per.
	//
	// For pass_at_k, per identifies each task. A task with n attempts and c true
	// scores contributes 1 - C(n-c, k) / C(n, k), and the result averages the tasks.
	// The result is null when a task has fewer than k attempts.
	Aggregation EvaluationQueryGetResponseDefinitionMetricsAggregation `json:"aggregation" api:"required"`
	// Unique name for this metric within the query. Result cells use this name.
	Name string `json:"name" api:"required"`
	// Version of the scorer whose values this metric aggregates. It must be registered
	// on the evaluation.
	ScorerVersionID string `json:"scorer_version_id" api:"required" format:"uuid"`
	// Number of attempts per task for pass_at_k. Required for pass_at_k and rejected
	// for other aggregations.
	K int64 `json:"k"`
	// How to handle a target with no non-null latest visible score. A target is a
	// case, or a trajectory in a trajectory query.
	//
	//   - **skip**: Exclude the target. A mean divides by the number of scored targets,
	//     and pass_at_k does not count it as an attempt. This also applies when missing
	//     is omitted.
	//   - **zero**: Include the target as 0, or false for boolean scores. A mean divides
	//     by every target in the group, and pass_at_k counts it as a failed attempt.
	//
	// Only mean, sum, and pass_at_k support zero. min, max, and count accept only
	// skip.
	Missing EvaluationQueryGetResponseDefinitionMetricsMissing `json:"missing"`
	// Column that identifies the task for each case, or for each trajectory in a
	// trajectory query, such as an input task field.
	//
	//   - Required for pass_at_k and rejected for other aggregations.
	//   - Must not also appear in group_by, and must not be depth or
	//     parent_trajectory_id.
	//   - Targets with no value in this column form one task.
	//   - A page returns 400 if the number of groups multiplied by their tasks exceeds
	//     the result row limit.
	Per  EvaluationQueryGetResponseDefinitionMetricsPer `json:"per"`
	JSON evaluationQueryGetResponseDefinitionMetricJSON `json:"-"`
}

// evaluationQueryGetResponseDefinitionMetricJSON contains the JSON metadata for
// the struct [EvaluationQueryGetResponseDefinitionMetric]
type evaluationQueryGetResponseDefinitionMetricJSON struct {
	Aggregation     apijson.Field
	Name            apijson.Field
	ScorerVersionID apijson.Field
	K               apijson.Field
	Missing         apijson.Field
	Per             apijson.Field
	raw             string
	ExtraFields     map[string]apijson.Field
}

func (r *EvaluationQueryGetResponseDefinitionMetric) UnmarshalJSON(data []byte) (err error) {
	return apijson.UnmarshalRoot(data, r)
}

func (r evaluationQueryGetResponseDefinitionMetricJSON) RawJSON() string {
	return r.raw
}

// Calculation to apply to the latest visible score for each case, or for each
// trajectory in a trajectory query.
//
//   - **mean**: Average of integer or number scores, or the fraction of true boolean
//     scores.
//   - **sum**: Sum of integer or number scores, or the number of true boolean
//     scores.
//   - **min / max**: Smallest or largest integer, number, boolean, or string score.
//     Strings compare lexicographically.
//   - **count**: Number of non-null integer, number, boolean, or string scores. Zero
//     and false are counted.
//   - **pass_at_k**: Estimated probability that at least one of k attempts at a task
//     succeeds. Requires boolean scores, k, and per.
//
// For pass_at_k, per identifies each task. A task with n attempts and c true
// scores contributes 1 - C(n-c, k) / C(n, k), and the result averages the tasks.
// The result is null when a task has fewer than k attempts.
type EvaluationQueryGetResponseDefinitionMetricsAggregation string

const (
	EvaluationQueryGetResponseDefinitionMetricsAggregationMean    EvaluationQueryGetResponseDefinitionMetricsAggregation = "mean"
	EvaluationQueryGetResponseDefinitionMetricsAggregationSum     EvaluationQueryGetResponseDefinitionMetricsAggregation = "sum"
	EvaluationQueryGetResponseDefinitionMetricsAggregationMin     EvaluationQueryGetResponseDefinitionMetricsAggregation = "min"
	EvaluationQueryGetResponseDefinitionMetricsAggregationMax     EvaluationQueryGetResponseDefinitionMetricsAggregation = "max"
	EvaluationQueryGetResponseDefinitionMetricsAggregationCount   EvaluationQueryGetResponseDefinitionMetricsAggregation = "count"
	EvaluationQueryGetResponseDefinitionMetricsAggregationPassAtK EvaluationQueryGetResponseDefinitionMetricsAggregation = "pass_at_k"
)

func (r EvaluationQueryGetResponseDefinitionMetricsAggregation) IsKnown() bool {
	switch r {
	case EvaluationQueryGetResponseDefinitionMetricsAggregationMean,
		EvaluationQueryGetResponseDefinitionMetricsAggregationSum,
		EvaluationQueryGetResponseDefinitionMetricsAggregationMin,
		EvaluationQueryGetResponseDefinitionMetricsAggregationMax,
		EvaluationQueryGetResponseDefinitionMetricsAggregationCount,
		EvaluationQueryGetResponseDefinitionMetricsAggregationPassAtK:
		return true
	}
	return false
}

// How to handle a target with no non-null latest visible score. A target is a
// case, or a trajectory in a trajectory query.
//
//   - **skip**: Exclude the target. A mean divides by the number of scored targets,
//     and pass_at_k does not count it as an attempt. This also applies when missing
//     is omitted.
//   - **zero**: Include the target as 0, or false for boolean scores. A mean divides
//     by every target in the group, and pass_at_k counts it as a failed attempt.
//
// Only mean, sum, and pass_at_k support zero. min, max, and count accept only
// skip.
type EvaluationQueryGetResponseDefinitionMetricsMissing string

const (
	EvaluationQueryGetResponseDefinitionMetricsMissingSkip EvaluationQueryGetResponseDefinitionMetricsMissing = "skip"
	EvaluationQueryGetResponseDefinitionMetricsMissingZero EvaluationQueryGetResponseDefinitionMetricsMissing = "zero"
)

func (r EvaluationQueryGetResponseDefinitionMetricsMissing) IsKnown() bool {
	switch r {
	case EvaluationQueryGetResponseDefinitionMetricsMissingSkip, EvaluationQueryGetResponseDefinitionMetricsMissingZero:
		return true
	}
	return false
}

// Column that identifies the task for each case, or for each trajectory in a
// trajectory query, such as an input task field.
//
//   - Required for pass_at_k and rejected for other aggregations.
//   - Must not also appear in group_by, and must not be depth or
//     parent_trajectory_id.
//   - Targets with no value in this column form one task.
//   - A page returns 400 if the number of groups multiplied by their tasks exceeds
//     the result row limit.
type EvaluationQueryGetResponseDefinitionMetricsPer struct {
	Kind EvaluationQueryGetResponseDefinitionMetricsPerKind `json:"kind" api:"required"`
	// Name of the input or output field to use as a column.
	Name string `json:"name"`
	// Whether the field belongs to the case's input or output.
	Source EvaluationQueryGetResponseDefinitionMetricsPerSource `json:"source"`
	JSON   evaluationQueryGetResponseDefinitionMetricsPerJSON   `json:"-"`
	union  EvaluationQueryGetResponseDefinitionMetricsPerUnion
}

// evaluationQueryGetResponseDefinitionMetricsPerJSON contains the JSON metadata
// for the struct [EvaluationQueryGetResponseDefinitionMetricsPer]
type evaluationQueryGetResponseDefinitionMetricsPerJSON struct {
	Kind        apijson.Field
	Name        apijson.Field
	Source      apijson.Field
	raw         string
	ExtraFields map[string]apijson.Field
}

func (r evaluationQueryGetResponseDefinitionMetricsPerJSON) RawJSON() string {
	return r.raw
}

func (r *EvaluationQueryGetResponseDefinitionMetricsPer) UnmarshalJSON(data []byte) (err error) {
	*r = EvaluationQueryGetResponseDefinitionMetricsPer{}
	err = apijson.UnmarshalRoot(data, &r.union)
	if err != nil {
		return err
	}
	return apijson.Port(r.union, &r)
}

// AsUnion returns a [EvaluationQueryGetResponseDefinitionMetricsPerUnion]
// interface which you can cast to the specific types for more type safety.
//
// Possible runtime types of the union are
// [EvaluationQueryGetResponseDefinitionMetricsPerVariantEvaluationColumn],
// [EvaluationQueryGetResponseDefinitionMetricsPerDatasetFieldEvaluationColumn],
// [EvaluationQueryGetResponseDefinitionMetricsPerScoreEvaluationColumn],
// [EvaluationQueryGetResponseDefinitionMetricsPerDepthEvaluationColumn],
// [EvaluationQueryGetResponseDefinitionMetricsPerParentTrajectoryIDEvaluationColumn].
func (r EvaluationQueryGetResponseDefinitionMetricsPer) AsUnion() EvaluationQueryGetResponseDefinitionMetricsPerUnion {
	return r.union
}

// Column that identifies the task for each case, or for each trajectory in a
// trajectory query, such as an input task field.
//
//   - Required for pass_at_k and rejected for other aggregations.
//   - Must not also appear in group_by, and must not be depth or
//     parent_trajectory_id.
//   - Targets with no value in this column form one task.
//   - A page returns 400 if the number of groups multiplied by their tasks exceeds
//     the result row limit.
//
// Union satisfied by
// [EvaluationQueryGetResponseDefinitionMetricsPerVariantEvaluationColumn],
// [EvaluationQueryGetResponseDefinitionMetricsPerDatasetFieldEvaluationColumn],
// [EvaluationQueryGetResponseDefinitionMetricsPerScoreEvaluationColumn],
// [EvaluationQueryGetResponseDefinitionMetricsPerDepthEvaluationColumn] or
// [EvaluationQueryGetResponseDefinitionMetricsPerParentTrajectoryIDEvaluationColumn].
type EvaluationQueryGetResponseDefinitionMetricsPerUnion interface {
	implementsEvaluationQueryGetResponseDefinitionMetricsPer()
}

func init() {
	apijson.RegisterUnion(
		reflect.TypeOf((*EvaluationQueryGetResponseDefinitionMetricsPerUnion)(nil)).Elem(),
		"kind",
		apijson.UnionVariant{
			TypeFilter:         gjson.JSON,
			Type:               reflect.TypeOf(EvaluationQueryGetResponseDefinitionMetricsPerVariantEvaluationColumn{}),
			DiscriminatorValue: "variant",
		},
		apijson.UnionVariant{
			TypeFilter: gjson.JSON,
			Type: reflect.TypeOf(
				EvaluationQueryGetResponseDefinitionMetricsPerDatasetFieldEvaluationColumn{},
			),
			DiscriminatorValue: "dataset_field",
		},
		apijson.UnionVariant{
			TypeFilter:         gjson.JSON,
			Type:               reflect.TypeOf(EvaluationQueryGetResponseDefinitionMetricsPerScoreEvaluationColumn{}),
			DiscriminatorValue: "score",
		},
		apijson.UnionVariant{
			TypeFilter:         gjson.JSON,
			Type:               reflect.TypeOf(EvaluationQueryGetResponseDefinitionMetricsPerDepthEvaluationColumn{}),
			DiscriminatorValue: "depth",
		},
		apijson.UnionVariant{
			TypeFilter: gjson.JSON,
			Type: reflect.TypeOf(
				EvaluationQueryGetResponseDefinitionMetricsPerParentTrajectoryIDEvaluationColumn{},
			),
			DiscriminatorValue: "parent_trajectory_id",
		},
	)
}

type EvaluationQueryGetResponseDefinitionMetricsPerVariantEvaluationColumn struct {
	Kind EvaluationQueryGetResponseDefinitionMetricsPerVariantEvaluationColumnKind `json:"kind" api:"required"`
	JSON evaluationQueryGetResponseDefinitionMetricsPerVariantEvaluationColumnJSON `json:"-"`
}

// evaluationQueryGetResponseDefinitionMetricsPerVariantEvaluationColumnJSON
// contains the JSON metadata for the struct
// [EvaluationQueryGetResponseDefinitionMetricsPerVariantEvaluationColumn]
type evaluationQueryGetResponseDefinitionMetricsPerVariantEvaluationColumnJSON struct {
	Kind        apijson.Field
	raw         string
	ExtraFields map[string]apijson.Field
}

func (r *EvaluationQueryGetResponseDefinitionMetricsPerVariantEvaluationColumn) UnmarshalJSON(data []byte) (err error) {
	return apijson.UnmarshalRoot(data, r)
}

func (r evaluationQueryGetResponseDefinitionMetricsPerVariantEvaluationColumnJSON) RawJSON() string {
	return r.raw
}

func (r EvaluationQueryGetResponseDefinitionMetricsPerVariantEvaluationColumn) implementsEvaluationQueryGetResponseDefinitionMetricsPer() {
}

type EvaluationQueryGetResponseDefinitionMetricsPerVariantEvaluationColumnKind string

const (
	EvaluationQueryGetResponseDefinitionMetricsPerVariantEvaluationColumnKindVariant EvaluationQueryGetResponseDefinitionMetricsPerVariantEvaluationColumnKind = "variant"
)

func (r EvaluationQueryGetResponseDefinitionMetricsPerVariantEvaluationColumnKind) IsKnown() bool {
	switch r {
	case EvaluationQueryGetResponseDefinitionMetricsPerVariantEvaluationColumnKindVariant:
		return true
	}
	return false
}

type EvaluationQueryGetResponseDefinitionMetricsPerDatasetFieldEvaluationColumn struct {
	Kind EvaluationQueryGetResponseDefinitionMetricsPerDatasetFieldEvaluationColumnKind `json:"kind" api:"required"`
	// Name of the input or output field to use as a column.
	Name string `json:"name" api:"required"`
	// Whether the field belongs to the case's input or output.
	Source EvaluationQueryGetResponseDefinitionMetricsPerDatasetFieldEvaluationColumnSource `json:"source" api:"required"`
	JSON   evaluationQueryGetResponseDefinitionMetricsPerDatasetFieldEvaluationColumnJSON   `json:"-"`
}

// evaluationQueryGetResponseDefinitionMetricsPerDatasetFieldEvaluationColumnJSON
// contains the JSON metadata for the struct
// [EvaluationQueryGetResponseDefinitionMetricsPerDatasetFieldEvaluationColumn]
type evaluationQueryGetResponseDefinitionMetricsPerDatasetFieldEvaluationColumnJSON struct {
	Kind        apijson.Field
	Name        apijson.Field
	Source      apijson.Field
	raw         string
	ExtraFields map[string]apijson.Field
}

func (r *EvaluationQueryGetResponseDefinitionMetricsPerDatasetFieldEvaluationColumn) UnmarshalJSON(
	data []byte,
) (err error) {
	return apijson.UnmarshalRoot(data, r)
}

func (r evaluationQueryGetResponseDefinitionMetricsPerDatasetFieldEvaluationColumnJSON) RawJSON() string {
	return r.raw
}

func (r EvaluationQueryGetResponseDefinitionMetricsPerDatasetFieldEvaluationColumn) implementsEvaluationQueryGetResponseDefinitionMetricsPer() {
}

type EvaluationQueryGetResponseDefinitionMetricsPerDatasetFieldEvaluationColumnKind string

const (
	EvaluationQueryGetResponseDefinitionMetricsPerDatasetFieldEvaluationColumnKindDatasetField EvaluationQueryGetResponseDefinitionMetricsPerDatasetFieldEvaluationColumnKind = "dataset_field"
)

func (r EvaluationQueryGetResponseDefinitionMetricsPerDatasetFieldEvaluationColumnKind) IsKnown() bool {
	switch r {
	case EvaluationQueryGetResponseDefinitionMetricsPerDatasetFieldEvaluationColumnKindDatasetField:
		return true
	}
	return false
}

// Whether the field belongs to the case's input or output.
type EvaluationQueryGetResponseDefinitionMetricsPerDatasetFieldEvaluationColumnSource string

const (
	EvaluationQueryGetResponseDefinitionMetricsPerDatasetFieldEvaluationColumnSourceInput  EvaluationQueryGetResponseDefinitionMetricsPerDatasetFieldEvaluationColumnSource = "input"
	EvaluationQueryGetResponseDefinitionMetricsPerDatasetFieldEvaluationColumnSourceOutput EvaluationQueryGetResponseDefinitionMetricsPerDatasetFieldEvaluationColumnSource = "output"
)

func (r EvaluationQueryGetResponseDefinitionMetricsPerDatasetFieldEvaluationColumnSource) IsKnown() bool {
	switch r {
	case EvaluationQueryGetResponseDefinitionMetricsPerDatasetFieldEvaluationColumnSourceInput,
		EvaluationQueryGetResponseDefinitionMetricsPerDatasetFieldEvaluationColumnSourceOutput:
		return true
	}
	return false
}

type EvaluationQueryGetResponseDefinitionMetricsPerScoreEvaluationColumn struct {
	Kind EvaluationQueryGetResponseDefinitionMetricsPerScoreEvaluationColumnKind `json:"kind" api:"required"`
	// Name of the scorer whose score supplies this column.
	Name string                                                                  `json:"name" api:"required"`
	JSON evaluationQueryGetResponseDefinitionMetricsPerScoreEvaluationColumnJSON `json:"-"`
}

// evaluationQueryGetResponseDefinitionMetricsPerScoreEvaluationColumnJSON contains
// the JSON metadata for the struct
// [EvaluationQueryGetResponseDefinitionMetricsPerScoreEvaluationColumn]
type evaluationQueryGetResponseDefinitionMetricsPerScoreEvaluationColumnJSON struct {
	Kind        apijson.Field
	Name        apijson.Field
	raw         string
	ExtraFields map[string]apijson.Field
}

func (r *EvaluationQueryGetResponseDefinitionMetricsPerScoreEvaluationColumn) UnmarshalJSON(data []byte) (err error) {
	return apijson.UnmarshalRoot(data, r)
}

func (r evaluationQueryGetResponseDefinitionMetricsPerScoreEvaluationColumnJSON) RawJSON() string {
	return r.raw
}

func (r EvaluationQueryGetResponseDefinitionMetricsPerScoreEvaluationColumn) implementsEvaluationQueryGetResponseDefinitionMetricsPer() {
}

type EvaluationQueryGetResponseDefinitionMetricsPerScoreEvaluationColumnKind string

const (
	EvaluationQueryGetResponseDefinitionMetricsPerScoreEvaluationColumnKindScore EvaluationQueryGetResponseDefinitionMetricsPerScoreEvaluationColumnKind = "score"
)

func (r EvaluationQueryGetResponseDefinitionMetricsPerScoreEvaluationColumnKind) IsKnown() bool {
	switch r {
	case EvaluationQueryGetResponseDefinitionMetricsPerScoreEvaluationColumnKindScore:
		return true
	}
	return false
}

// Trajectory queries only. Groups by depth, an integer that is 0 for a top-level
// trajectory.
type EvaluationQueryGetResponseDefinitionMetricsPerDepthEvaluationColumn struct {
	Kind EvaluationQueryGetResponseDefinitionMetricsPerDepthEvaluationColumnKind `json:"kind" api:"required"`
	JSON evaluationQueryGetResponseDefinitionMetricsPerDepthEvaluationColumnJSON `json:"-"`
}

// evaluationQueryGetResponseDefinitionMetricsPerDepthEvaluationColumnJSON contains
// the JSON metadata for the struct
// [EvaluationQueryGetResponseDefinitionMetricsPerDepthEvaluationColumn]
type evaluationQueryGetResponseDefinitionMetricsPerDepthEvaluationColumnJSON struct {
	Kind        apijson.Field
	raw         string
	ExtraFields map[string]apijson.Field
}

func (r *EvaluationQueryGetResponseDefinitionMetricsPerDepthEvaluationColumn) UnmarshalJSON(data []byte) (err error) {
	return apijson.UnmarshalRoot(data, r)
}

func (r evaluationQueryGetResponseDefinitionMetricsPerDepthEvaluationColumnJSON) RawJSON() string {
	return r.raw
}

func (r EvaluationQueryGetResponseDefinitionMetricsPerDepthEvaluationColumn) implementsEvaluationQueryGetResponseDefinitionMetricsPer() {
}

type EvaluationQueryGetResponseDefinitionMetricsPerDepthEvaluationColumnKind string

const (
	EvaluationQueryGetResponseDefinitionMetricsPerDepthEvaluationColumnKindDepth EvaluationQueryGetResponseDefinitionMetricsPerDepthEvaluationColumnKind = "depth"
)

func (r EvaluationQueryGetResponseDefinitionMetricsPerDepthEvaluationColumnKind) IsKnown() bool {
	switch r {
	case EvaluationQueryGetResponseDefinitionMetricsPerDepthEvaluationColumnKindDepth:
		return true
	}
	return false
}

// Trajectory queries only. Groups by the parent trajectory's ID. Top-level
// trajectories form the null group.
type EvaluationQueryGetResponseDefinitionMetricsPerParentTrajectoryIDEvaluationColumn struct {
	Kind EvaluationQueryGetResponseDefinitionMetricsPerParentTrajectoryIDEvaluationColumnKind `json:"kind" api:"required"`
	JSON evaluationQueryGetResponseDefinitionMetricsPerParentTrajectoryIDEvaluationColumnJSON `json:"-"`
}

// evaluationQueryGetResponseDefinitionMetricsPerParentTrajectoryIDEvaluationColumnJSON
// contains the JSON metadata for the struct
// [EvaluationQueryGetResponseDefinitionMetricsPerParentTrajectoryIDEvaluationColumn]
type evaluationQueryGetResponseDefinitionMetricsPerParentTrajectoryIDEvaluationColumnJSON struct {
	Kind        apijson.Field
	raw         string
	ExtraFields map[string]apijson.Field
}

func (r *EvaluationQueryGetResponseDefinitionMetricsPerParentTrajectoryIDEvaluationColumn) UnmarshalJSON(
	data []byte,
) (err error) {
	return apijson.UnmarshalRoot(data, r)
}

func (r evaluationQueryGetResponseDefinitionMetricsPerParentTrajectoryIDEvaluationColumnJSON) RawJSON() string {
	return r.raw
}

func (r EvaluationQueryGetResponseDefinitionMetricsPerParentTrajectoryIDEvaluationColumn) implementsEvaluationQueryGetResponseDefinitionMetricsPer() {
}

type EvaluationQueryGetResponseDefinitionMetricsPerParentTrajectoryIDEvaluationColumnKind string

const (
	EvaluationQueryGetResponseDefinitionMetricsPerParentTrajectoryIDEvaluationColumnKindParentTrajectoryID EvaluationQueryGetResponseDefinitionMetricsPerParentTrajectoryIDEvaluationColumnKind = "parent_trajectory_id"
)

func (r EvaluationQueryGetResponseDefinitionMetricsPerParentTrajectoryIDEvaluationColumnKind) IsKnown() bool {
	switch r {
	case EvaluationQueryGetResponseDefinitionMetricsPerParentTrajectoryIDEvaluationColumnKindParentTrajectoryID:
		return true
	}
	return false
}

type EvaluationQueryGetResponseDefinitionMetricsPerKind string

const (
	EvaluationQueryGetResponseDefinitionMetricsPerKindVariant            EvaluationQueryGetResponseDefinitionMetricsPerKind = "variant"
	EvaluationQueryGetResponseDefinitionMetricsPerKindDatasetField       EvaluationQueryGetResponseDefinitionMetricsPerKind = "dataset_field"
	EvaluationQueryGetResponseDefinitionMetricsPerKindScore              EvaluationQueryGetResponseDefinitionMetricsPerKind = "score"
	EvaluationQueryGetResponseDefinitionMetricsPerKindDepth              EvaluationQueryGetResponseDefinitionMetricsPerKind = "depth"
	EvaluationQueryGetResponseDefinitionMetricsPerKindParentTrajectoryID EvaluationQueryGetResponseDefinitionMetricsPerKind = "parent_trajectory_id"
)

func (r EvaluationQueryGetResponseDefinitionMetricsPerKind) IsKnown() bool {
	switch r {
	case EvaluationQueryGetResponseDefinitionMetricsPerKindVariant,
		EvaluationQueryGetResponseDefinitionMetricsPerKindDatasetField,
		EvaluationQueryGetResponseDefinitionMetricsPerKindScore,
		EvaluationQueryGetResponseDefinitionMetricsPerKindDepth,
		EvaluationQueryGetResponseDefinitionMetricsPerKindParentTrajectoryID:
		return true
	}
	return false
}

// Whether the field belongs to the case's input or output.
type EvaluationQueryGetResponseDefinitionMetricsPerSource string

const (
	EvaluationQueryGetResponseDefinitionMetricsPerSourceInput  EvaluationQueryGetResponseDefinitionMetricsPerSource = "input"
	EvaluationQueryGetResponseDefinitionMetricsPerSourceOutput EvaluationQueryGetResponseDefinitionMetricsPerSource = "output"
)

func (r EvaluationQueryGetResponseDefinitionMetricsPerSource) IsKnown() bool {
	switch r {
	case EvaluationQueryGetResponseDefinitionMetricsPerSourceInput,
		EvaluationQueryGetResponseDefinitionMetricsPerSourceOutput:
		return true
	}
	return false
}

// Trajectory queries only. Groups by depth, an integer that is 0 for a top-level
// trajectory.
type EvaluationQueryGetResponseDefinitionGroupBy struct {
	Kind EvaluationQueryGetResponseDefinitionGroupByKind `json:"kind" api:"required"`
	// Name of the input or output field to use as a column.
	Name string `json:"name"`
	// Whether the field belongs to the case's input or output.
	Source EvaluationQueryGetResponseDefinitionGroupBySource `json:"source"`
	JSON   evaluationQueryGetResponseDefinitionGroupByJSON   `json:"-"`
	union  EvaluationQueryGetResponseDefinitionGroupByUnion
}

// evaluationQueryGetResponseDefinitionGroupByJSON contains the JSON metadata for
// the struct [EvaluationQueryGetResponseDefinitionGroupBy]
type evaluationQueryGetResponseDefinitionGroupByJSON struct {
	Kind        apijson.Field
	Name        apijson.Field
	Source      apijson.Field
	raw         string
	ExtraFields map[string]apijson.Field
}

func (r evaluationQueryGetResponseDefinitionGroupByJSON) RawJSON() string {
	return r.raw
}

func (r *EvaluationQueryGetResponseDefinitionGroupBy) UnmarshalJSON(data []byte) (err error) {
	*r = EvaluationQueryGetResponseDefinitionGroupBy{}
	err = apijson.UnmarshalRoot(data, &r.union)
	if err != nil {
		return err
	}
	return apijson.Port(r.union, &r)
}

// AsUnion returns a [EvaluationQueryGetResponseDefinitionGroupByUnion] interface
// which you can cast to the specific types for more type safety.
//
// Possible runtime types of the union are
// [EvaluationQueryGetResponseDefinitionGroupByVariantEvaluationColumn],
// [EvaluationQueryGetResponseDefinitionGroupByDatasetFieldEvaluationColumn],
// [EvaluationQueryGetResponseDefinitionGroupByScoreEvaluationColumn],
// [EvaluationQueryGetResponseDefinitionGroupByDepthEvaluationColumn],
// [EvaluationQueryGetResponseDefinitionGroupByParentTrajectoryIDEvaluationColumn].
func (r EvaluationQueryGetResponseDefinitionGroupBy) AsUnion() EvaluationQueryGetResponseDefinitionGroupByUnion {
	return r.union
}

// Trajectory queries only. Groups by depth, an integer that is 0 for a top-level
// trajectory.
//
// Union satisfied by
// [EvaluationQueryGetResponseDefinitionGroupByVariantEvaluationColumn],
// [EvaluationQueryGetResponseDefinitionGroupByDatasetFieldEvaluationColumn],
// [EvaluationQueryGetResponseDefinitionGroupByScoreEvaluationColumn],
// [EvaluationQueryGetResponseDefinitionGroupByDepthEvaluationColumn] or
// [EvaluationQueryGetResponseDefinitionGroupByParentTrajectoryIDEvaluationColumn].
type EvaluationQueryGetResponseDefinitionGroupByUnion interface {
	implementsEvaluationQueryGetResponseDefinitionGroupBy()
}

func init() {
	apijson.RegisterUnion(
		reflect.TypeOf((*EvaluationQueryGetResponseDefinitionGroupByUnion)(nil)).Elem(),
		"kind",
		apijson.UnionVariant{
			TypeFilter:         gjson.JSON,
			Type:               reflect.TypeOf(EvaluationQueryGetResponseDefinitionGroupByVariantEvaluationColumn{}),
			DiscriminatorValue: "variant",
		},
		apijson.UnionVariant{
			TypeFilter: gjson.JSON,
			Type: reflect.TypeOf(
				EvaluationQueryGetResponseDefinitionGroupByDatasetFieldEvaluationColumn{},
			),
			DiscriminatorValue: "dataset_field",
		},
		apijson.UnionVariant{
			TypeFilter:         gjson.JSON,
			Type:               reflect.TypeOf(EvaluationQueryGetResponseDefinitionGroupByScoreEvaluationColumn{}),
			DiscriminatorValue: "score",
		},
		apijson.UnionVariant{
			TypeFilter:         gjson.JSON,
			Type:               reflect.TypeOf(EvaluationQueryGetResponseDefinitionGroupByDepthEvaluationColumn{}),
			DiscriminatorValue: "depth",
		},
		apijson.UnionVariant{
			TypeFilter: gjson.JSON,
			Type: reflect.TypeOf(
				EvaluationQueryGetResponseDefinitionGroupByParentTrajectoryIDEvaluationColumn{},
			),
			DiscriminatorValue: "parent_trajectory_id",
		},
	)
}

type EvaluationQueryGetResponseDefinitionGroupByVariantEvaluationColumn struct {
	Kind EvaluationQueryGetResponseDefinitionGroupByVariantEvaluationColumnKind `json:"kind" api:"required"`
	JSON evaluationQueryGetResponseDefinitionGroupByVariantEvaluationColumnJSON `json:"-"`
}

// evaluationQueryGetResponseDefinitionGroupByVariantEvaluationColumnJSON contains
// the JSON metadata for the struct
// [EvaluationQueryGetResponseDefinitionGroupByVariantEvaluationColumn]
type evaluationQueryGetResponseDefinitionGroupByVariantEvaluationColumnJSON struct {
	Kind        apijson.Field
	raw         string
	ExtraFields map[string]apijson.Field
}

func (r *EvaluationQueryGetResponseDefinitionGroupByVariantEvaluationColumn) UnmarshalJSON(data []byte) (err error) {
	return apijson.UnmarshalRoot(data, r)
}

func (r evaluationQueryGetResponseDefinitionGroupByVariantEvaluationColumnJSON) RawJSON() string {
	return r.raw
}

func (r EvaluationQueryGetResponseDefinitionGroupByVariantEvaluationColumn) implementsEvaluationQueryGetResponseDefinitionGroupBy() {
}

type EvaluationQueryGetResponseDefinitionGroupByVariantEvaluationColumnKind string

const (
	EvaluationQueryGetResponseDefinitionGroupByVariantEvaluationColumnKindVariant EvaluationQueryGetResponseDefinitionGroupByVariantEvaluationColumnKind = "variant"
)

func (r EvaluationQueryGetResponseDefinitionGroupByVariantEvaluationColumnKind) IsKnown() bool {
	switch r {
	case EvaluationQueryGetResponseDefinitionGroupByVariantEvaluationColumnKindVariant:
		return true
	}
	return false
}

type EvaluationQueryGetResponseDefinitionGroupByDatasetFieldEvaluationColumn struct {
	Kind EvaluationQueryGetResponseDefinitionGroupByDatasetFieldEvaluationColumnKind `json:"kind" api:"required"`
	// Name of the input or output field to use as a column.
	Name string `json:"name" api:"required"`
	// Whether the field belongs to the case's input or output.
	Source EvaluationQueryGetResponseDefinitionGroupByDatasetFieldEvaluationColumnSource `json:"source" api:"required"`
	JSON   evaluationQueryGetResponseDefinitionGroupByDatasetFieldEvaluationColumnJSON   `json:"-"`
}

// evaluationQueryGetResponseDefinitionGroupByDatasetFieldEvaluationColumnJSON
// contains the JSON metadata for the struct
// [EvaluationQueryGetResponseDefinitionGroupByDatasetFieldEvaluationColumn]
type evaluationQueryGetResponseDefinitionGroupByDatasetFieldEvaluationColumnJSON struct {
	Kind        apijson.Field
	Name        apijson.Field
	Source      apijson.Field
	raw         string
	ExtraFields map[string]apijson.Field
}

func (r *EvaluationQueryGetResponseDefinitionGroupByDatasetFieldEvaluationColumn) UnmarshalJSON(
	data []byte,
) (err error) {
	return apijson.UnmarshalRoot(data, r)
}

func (r evaluationQueryGetResponseDefinitionGroupByDatasetFieldEvaluationColumnJSON) RawJSON() string {
	return r.raw
}

func (r EvaluationQueryGetResponseDefinitionGroupByDatasetFieldEvaluationColumn) implementsEvaluationQueryGetResponseDefinitionGroupBy() {
}

type EvaluationQueryGetResponseDefinitionGroupByDatasetFieldEvaluationColumnKind string

const (
	EvaluationQueryGetResponseDefinitionGroupByDatasetFieldEvaluationColumnKindDatasetField EvaluationQueryGetResponseDefinitionGroupByDatasetFieldEvaluationColumnKind = "dataset_field"
)

func (r EvaluationQueryGetResponseDefinitionGroupByDatasetFieldEvaluationColumnKind) IsKnown() bool {
	switch r {
	case EvaluationQueryGetResponseDefinitionGroupByDatasetFieldEvaluationColumnKindDatasetField:
		return true
	}
	return false
}

// Whether the field belongs to the case's input or output.
type EvaluationQueryGetResponseDefinitionGroupByDatasetFieldEvaluationColumnSource string

const (
	EvaluationQueryGetResponseDefinitionGroupByDatasetFieldEvaluationColumnSourceInput  EvaluationQueryGetResponseDefinitionGroupByDatasetFieldEvaluationColumnSource = "input"
	EvaluationQueryGetResponseDefinitionGroupByDatasetFieldEvaluationColumnSourceOutput EvaluationQueryGetResponseDefinitionGroupByDatasetFieldEvaluationColumnSource = "output"
)

func (r EvaluationQueryGetResponseDefinitionGroupByDatasetFieldEvaluationColumnSource) IsKnown() bool {
	switch r {
	case EvaluationQueryGetResponseDefinitionGroupByDatasetFieldEvaluationColumnSourceInput,
		EvaluationQueryGetResponseDefinitionGroupByDatasetFieldEvaluationColumnSourceOutput:
		return true
	}
	return false
}

type EvaluationQueryGetResponseDefinitionGroupByScoreEvaluationColumn struct {
	Kind EvaluationQueryGetResponseDefinitionGroupByScoreEvaluationColumnKind `json:"kind" api:"required"`
	// Name of the scorer whose score supplies this column.
	Name string                                                               `json:"name" api:"required"`
	JSON evaluationQueryGetResponseDefinitionGroupByScoreEvaluationColumnJSON `json:"-"`
}

// evaluationQueryGetResponseDefinitionGroupByScoreEvaluationColumnJSON contains
// the JSON metadata for the struct
// [EvaluationQueryGetResponseDefinitionGroupByScoreEvaluationColumn]
type evaluationQueryGetResponseDefinitionGroupByScoreEvaluationColumnJSON struct {
	Kind        apijson.Field
	Name        apijson.Field
	raw         string
	ExtraFields map[string]apijson.Field
}

func (r *EvaluationQueryGetResponseDefinitionGroupByScoreEvaluationColumn) UnmarshalJSON(data []byte) (err error) {
	return apijson.UnmarshalRoot(data, r)
}

func (r evaluationQueryGetResponseDefinitionGroupByScoreEvaluationColumnJSON) RawJSON() string {
	return r.raw
}

func (r EvaluationQueryGetResponseDefinitionGroupByScoreEvaluationColumn) implementsEvaluationQueryGetResponseDefinitionGroupBy() {
}

type EvaluationQueryGetResponseDefinitionGroupByScoreEvaluationColumnKind string

const (
	EvaluationQueryGetResponseDefinitionGroupByScoreEvaluationColumnKindScore EvaluationQueryGetResponseDefinitionGroupByScoreEvaluationColumnKind = "score"
)

func (r EvaluationQueryGetResponseDefinitionGroupByScoreEvaluationColumnKind) IsKnown() bool {
	switch r {
	case EvaluationQueryGetResponseDefinitionGroupByScoreEvaluationColumnKindScore:
		return true
	}
	return false
}

// Trajectory queries only. Groups by depth, an integer that is 0 for a top-level
// trajectory.
type EvaluationQueryGetResponseDefinitionGroupByDepthEvaluationColumn struct {
	Kind EvaluationQueryGetResponseDefinitionGroupByDepthEvaluationColumnKind `json:"kind" api:"required"`
	JSON evaluationQueryGetResponseDefinitionGroupByDepthEvaluationColumnJSON `json:"-"`
}

// evaluationQueryGetResponseDefinitionGroupByDepthEvaluationColumnJSON contains
// the JSON metadata for the struct
// [EvaluationQueryGetResponseDefinitionGroupByDepthEvaluationColumn]
type evaluationQueryGetResponseDefinitionGroupByDepthEvaluationColumnJSON struct {
	Kind        apijson.Field
	raw         string
	ExtraFields map[string]apijson.Field
}

func (r *EvaluationQueryGetResponseDefinitionGroupByDepthEvaluationColumn) UnmarshalJSON(data []byte) (err error) {
	return apijson.UnmarshalRoot(data, r)
}

func (r evaluationQueryGetResponseDefinitionGroupByDepthEvaluationColumnJSON) RawJSON() string {
	return r.raw
}

func (r EvaluationQueryGetResponseDefinitionGroupByDepthEvaluationColumn) implementsEvaluationQueryGetResponseDefinitionGroupBy() {
}

type EvaluationQueryGetResponseDefinitionGroupByDepthEvaluationColumnKind string

const (
	EvaluationQueryGetResponseDefinitionGroupByDepthEvaluationColumnKindDepth EvaluationQueryGetResponseDefinitionGroupByDepthEvaluationColumnKind = "depth"
)

func (r EvaluationQueryGetResponseDefinitionGroupByDepthEvaluationColumnKind) IsKnown() bool {
	switch r {
	case EvaluationQueryGetResponseDefinitionGroupByDepthEvaluationColumnKindDepth:
		return true
	}
	return false
}

// Trajectory queries only. Groups by the parent trajectory's ID. Top-level
// trajectories form the null group.
type EvaluationQueryGetResponseDefinitionGroupByParentTrajectoryIDEvaluationColumn struct {
	Kind EvaluationQueryGetResponseDefinitionGroupByParentTrajectoryIDEvaluationColumnKind `json:"kind" api:"required"`
	JSON evaluationQueryGetResponseDefinitionGroupByParentTrajectoryIDEvaluationColumnJSON `json:"-"`
}

// evaluationQueryGetResponseDefinitionGroupByParentTrajectoryIDEvaluationColumnJSON
// contains the JSON metadata for the struct
// [EvaluationQueryGetResponseDefinitionGroupByParentTrajectoryIDEvaluationColumn]
type evaluationQueryGetResponseDefinitionGroupByParentTrajectoryIDEvaluationColumnJSON struct {
	Kind        apijson.Field
	raw         string
	ExtraFields map[string]apijson.Field
}

func (r *EvaluationQueryGetResponseDefinitionGroupByParentTrajectoryIDEvaluationColumn) UnmarshalJSON(
	data []byte,
) (err error) {
	return apijson.UnmarshalRoot(data, r)
}

func (r evaluationQueryGetResponseDefinitionGroupByParentTrajectoryIDEvaluationColumnJSON) RawJSON() string {
	return r.raw
}

func (r EvaluationQueryGetResponseDefinitionGroupByParentTrajectoryIDEvaluationColumn) implementsEvaluationQueryGetResponseDefinitionGroupBy() {
}

type EvaluationQueryGetResponseDefinitionGroupByParentTrajectoryIDEvaluationColumnKind string

const (
	EvaluationQueryGetResponseDefinitionGroupByParentTrajectoryIDEvaluationColumnKindParentTrajectoryID EvaluationQueryGetResponseDefinitionGroupByParentTrajectoryIDEvaluationColumnKind = "parent_trajectory_id"
)

func (r EvaluationQueryGetResponseDefinitionGroupByParentTrajectoryIDEvaluationColumnKind) IsKnown() bool {
	switch r {
	case EvaluationQueryGetResponseDefinitionGroupByParentTrajectoryIDEvaluationColumnKindParentTrajectoryID:
		return true
	}
	return false
}

type EvaluationQueryGetResponseDefinitionGroupByKind string

const (
	EvaluationQueryGetResponseDefinitionGroupByKindVariant            EvaluationQueryGetResponseDefinitionGroupByKind = "variant"
	EvaluationQueryGetResponseDefinitionGroupByKindDatasetField       EvaluationQueryGetResponseDefinitionGroupByKind = "dataset_field"
	EvaluationQueryGetResponseDefinitionGroupByKindScore              EvaluationQueryGetResponseDefinitionGroupByKind = "score"
	EvaluationQueryGetResponseDefinitionGroupByKindDepth              EvaluationQueryGetResponseDefinitionGroupByKind = "depth"
	EvaluationQueryGetResponseDefinitionGroupByKindParentTrajectoryID EvaluationQueryGetResponseDefinitionGroupByKind = "parent_trajectory_id"
)

func (r EvaluationQueryGetResponseDefinitionGroupByKind) IsKnown() bool {
	switch r {
	case EvaluationQueryGetResponseDefinitionGroupByKindVariant,
		EvaluationQueryGetResponseDefinitionGroupByKindDatasetField,
		EvaluationQueryGetResponseDefinitionGroupByKindScore,
		EvaluationQueryGetResponseDefinitionGroupByKindDepth,
		EvaluationQueryGetResponseDefinitionGroupByKindParentTrajectoryID:
		return true
	}
	return false
}

// Whether the field belongs to the case's input or output.
type EvaluationQueryGetResponseDefinitionGroupBySource string

const (
	EvaluationQueryGetResponseDefinitionGroupBySourceInput  EvaluationQueryGetResponseDefinitionGroupBySource = "input"
	EvaluationQueryGetResponseDefinitionGroupBySourceOutput EvaluationQueryGetResponseDefinitionGroupBySource = "output"
)

func (r EvaluationQueryGetResponseDefinitionGroupBySource) IsKnown() bool {
	switch r {
	case EvaluationQueryGetResponseDefinitionGroupBySourceInput,
		EvaluationQueryGetResponseDefinitionGroupBySourceOutput:
		return true
	}
	return false
}

// Absent for a query over cases.
type EvaluationQueryGetResponseDefinitionTargetKind string

const (
	EvaluationQueryGetResponseDefinitionTargetKindTrajectory EvaluationQueryGetResponseDefinitionTargetKind = "trajectory"
)

func (r EvaluationQueryGetResponseDefinitionTargetKind) IsKnown() bool {
	switch r {
	case EvaluationQueryGetResponseDefinitionTargetKindTrajectory:
		return true
	}
	return false
}

// Namespace that assigned the scope reference.
type EvaluationQueryGetResponseNamespace string

const (
	EvaluationQueryGetResponseNamespaceWandb EvaluationQueryGetResponseNamespace = "wandb"
)

func (r EvaluationQueryGetResponseNamespace) IsKnown() bool {
	switch r {
	case EvaluationQueryGetResponseNamespaceWandb:
		return true
	}
	return false
}

type EvaluationQueryNewParams struct {
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
	ScopeID    param.Field[string]                             `path:"scope_id" api:"required"`
	Definition param.Field[EvaluationQueryNewParamsDefinition] `                api:"required" json:"definition"`
	Name       param.Field[string]                             `                api:"required" json:"name"`
}

func (r EvaluationQueryNewParams) MarshalJSON() (data []byte, err error) {
	return apijson.MarshalRoot(r)
}

type EvaluationQueryNewParamsDefinition struct {
	// Calculations to run for each group. Metric names must be unique, and scorer
	// versions must be registered on the evaluation.
	Metrics param.Field[[]EvaluationQueryNewParamsDefinitionMetric] `json:"metrics" api:"required"`
	// Columns whose distinct value combinations form result groups. Choose variant,
	// dataset fields, or score columns. Result group values follow this column order.
	// Omit, send null, or use an empty list to calculate metrics across all targets. A
	// trajectory query reads dataset fields from each trajectory's root case and
	// scores from the trajectory, and can also group by the trajectory's depth and
	// parent_trajectory_id.
	GroupBy param.Field[[]EvaluationQueryNewParamsDefinitionGroupByUnion] `json:"group_by"`
	// Targets whose scores the query aggregates. Omit or use case to aggregate the
	// dataset's cases. trajectory aggregates scores on the dataset's trajectories and
	// groups each trajectory by its root case's variant and fields.
	TargetKind param.Field[EvaluationQueryNewParamsDefinitionTargetKind] `json:"target_kind"`
	// Definition version.
	V param.Field[int64] `json:"v"`
}

func (r EvaluationQueryNewParamsDefinition) MarshalJSON() (data []byte, err error) {
	return apijson.MarshalRoot(r)
}

type EvaluationQueryNewParamsDefinitionMetric struct {
	// Calculation to apply to the latest visible score for each case, or for each
	// trajectory in a trajectory query.
	//
	//   - **mean**: Average of integer or number scores, or the fraction of true boolean
	//     scores.
	//   - **sum**: Sum of integer or number scores, or the number of true boolean
	//     scores.
	//   - **min / max**: Smallest or largest integer, number, boolean, or string score.
	//     Strings compare lexicographically.
	//   - **count**: Number of non-null integer, number, boolean, or string scores. Zero
	//     and false are counted.
	//   - **pass_at_k**: Estimated probability that at least one of k attempts at a task
	//     succeeds. Requires boolean scores, k, and per.
	//
	// For pass_at_k, per identifies each task. A task with n attempts and c true
	// scores contributes 1 - C(n-c, k) / C(n, k), and the result averages the tasks.
	// The result is null when a task has fewer than k attempts.
	Aggregation param.Field[EvaluationQueryNewParamsDefinitionMetricsAggregation] `json:"aggregation" api:"required"`
	// Unique name for this metric within the query. Result cells use this name.
	Name param.Field[string] `json:"name" api:"required"`
	// Version of the scorer whose values this metric aggregates. It must be registered
	// on the evaluation.
	ScorerVersionID param.Field[string] `json:"scorer_version_id" api:"required" format:"uuid"`
	// Number of attempts per task for pass_at_k. Required for pass_at_k and rejected
	// for other aggregations.
	K param.Field[int64] `json:"k"`
	// How to handle a target with no non-null latest visible score. A target is a
	// case, or a trajectory in a trajectory query.
	//
	//   - **skip**: Exclude the target. A mean divides by the number of scored targets,
	//     and pass_at_k does not count it as an attempt. This also applies when missing
	//     is omitted.
	//   - **zero**: Include the target as 0, or false for boolean scores. A mean divides
	//     by every target in the group, and pass_at_k counts it as a failed attempt.
	//
	// Only mean, sum, and pass_at_k support zero. min, max, and count accept only
	// skip.
	Missing param.Field[EvaluationQueryNewParamsDefinitionMetricsMissing] `json:"missing"`
	// Column that identifies the task for each case, or for each trajectory in a
	// trajectory query, such as an input task field.
	//
	//   - Required for pass_at_k and rejected for other aggregations.
	//   - Must not also appear in group_by, and must not be depth or
	//     parent_trajectory_id.
	//   - Targets with no value in this column form one task.
	//   - A page returns 400 if the number of groups multiplied by their tasks exceeds
	//     the result row limit.
	Per param.Field[EvaluationQueryNewParamsDefinitionMetricsPerUnion] `json:"per"`
}

func (r EvaluationQueryNewParamsDefinitionMetric) MarshalJSON() (data []byte, err error) {
	return apijson.MarshalRoot(r)
}

// Calculation to apply to the latest visible score for each case, or for each
// trajectory in a trajectory query.
//
//   - **mean**: Average of integer or number scores, or the fraction of true boolean
//     scores.
//   - **sum**: Sum of integer or number scores, or the number of true boolean
//     scores.
//   - **min / max**: Smallest or largest integer, number, boolean, or string score.
//     Strings compare lexicographically.
//   - **count**: Number of non-null integer, number, boolean, or string scores. Zero
//     and false are counted.
//   - **pass_at_k**: Estimated probability that at least one of k attempts at a task
//     succeeds. Requires boolean scores, k, and per.
//
// For pass_at_k, per identifies each task. A task with n attempts and c true
// scores contributes 1 - C(n-c, k) / C(n, k), and the result averages the tasks.
// The result is null when a task has fewer than k attempts.
type EvaluationQueryNewParamsDefinitionMetricsAggregation string

const (
	EvaluationQueryNewParamsDefinitionMetricsAggregationMean    EvaluationQueryNewParamsDefinitionMetricsAggregation = "mean"
	EvaluationQueryNewParamsDefinitionMetricsAggregationSum     EvaluationQueryNewParamsDefinitionMetricsAggregation = "sum"
	EvaluationQueryNewParamsDefinitionMetricsAggregationMin     EvaluationQueryNewParamsDefinitionMetricsAggregation = "min"
	EvaluationQueryNewParamsDefinitionMetricsAggregationMax     EvaluationQueryNewParamsDefinitionMetricsAggregation = "max"
	EvaluationQueryNewParamsDefinitionMetricsAggregationCount   EvaluationQueryNewParamsDefinitionMetricsAggregation = "count"
	EvaluationQueryNewParamsDefinitionMetricsAggregationPassAtK EvaluationQueryNewParamsDefinitionMetricsAggregation = "pass_at_k"
)

func (r EvaluationQueryNewParamsDefinitionMetricsAggregation) IsKnown() bool {
	switch r {
	case EvaluationQueryNewParamsDefinitionMetricsAggregationMean,
		EvaluationQueryNewParamsDefinitionMetricsAggregationSum,
		EvaluationQueryNewParamsDefinitionMetricsAggregationMin,
		EvaluationQueryNewParamsDefinitionMetricsAggregationMax,
		EvaluationQueryNewParamsDefinitionMetricsAggregationCount,
		EvaluationQueryNewParamsDefinitionMetricsAggregationPassAtK:
		return true
	}
	return false
}

// How to handle a target with no non-null latest visible score. A target is a
// case, or a trajectory in a trajectory query.
//
//   - **skip**: Exclude the target. A mean divides by the number of scored targets,
//     and pass_at_k does not count it as an attempt. This also applies when missing
//     is omitted.
//   - **zero**: Include the target as 0, or false for boolean scores. A mean divides
//     by every target in the group, and pass_at_k counts it as a failed attempt.
//
// Only mean, sum, and pass_at_k support zero. min, max, and count accept only
// skip.
type EvaluationQueryNewParamsDefinitionMetricsMissing string

const (
	EvaluationQueryNewParamsDefinitionMetricsMissingSkip EvaluationQueryNewParamsDefinitionMetricsMissing = "skip"
	EvaluationQueryNewParamsDefinitionMetricsMissingZero EvaluationQueryNewParamsDefinitionMetricsMissing = "zero"
)

func (r EvaluationQueryNewParamsDefinitionMetricsMissing) IsKnown() bool {
	switch r {
	case EvaluationQueryNewParamsDefinitionMetricsMissingSkip, EvaluationQueryNewParamsDefinitionMetricsMissingZero:
		return true
	}
	return false
}

// Column that identifies the task for each case, or for each trajectory in a
// trajectory query, such as an input task field.
//
//   - Required for pass_at_k and rejected for other aggregations.
//   - Must not also appear in group_by, and must not be depth or
//     parent_trajectory_id.
//   - Targets with no value in this column form one task.
//   - A page returns 400 if the number of groups multiplied by their tasks exceeds
//     the result row limit.
type EvaluationQueryNewParamsDefinitionMetricsPer struct {
	Kind param.Field[EvaluationQueryNewParamsDefinitionMetricsPerKind] `json:"kind" api:"required"`
	// Name of the input or output field to use as a column.
	Name param.Field[string] `json:"name"`
	// Whether the field belongs to the case's input or output.
	Source param.Field[EvaluationQueryNewParamsDefinitionMetricsPerSource] `json:"source"`
}

func (r EvaluationQueryNewParamsDefinitionMetricsPer) MarshalJSON() (data []byte, err error) {
	return apijson.MarshalRoot(r)
}

func (r EvaluationQueryNewParamsDefinitionMetricsPer) implementsEvaluationQueryNewParamsDefinitionMetricsPerUnion() {
}

// Column that identifies the task for each case, or for each trajectory in a
// trajectory query, such as an input task field.
//
//   - Required for pass_at_k and rejected for other aggregations.
//   - Must not also appear in group_by, and must not be depth or
//     parent_trajectory_id.
//   - Targets with no value in this column form one task.
//   - A page returns 400 if the number of groups multiplied by their tasks exceeds
//     the result row limit.
//
// Satisfied by
// [EvaluationQueryNewParamsDefinitionMetricsPerVariantEvaluationColumn],
// [EvaluationQueryNewParamsDefinitionMetricsPerDatasetFieldEvaluationColumn],
// [EvaluationQueryNewParamsDefinitionMetricsPerScoreEvaluationColumn],
// [EvaluationQueryNewParamsDefinitionMetricsPerDepthEvaluationColumn],
// [EvaluationQueryNewParamsDefinitionMetricsPerParentTrajectoryIDEvaluationColumn],
// [EvaluationQueryNewParamsDefinitionMetricsPer].
type EvaluationQueryNewParamsDefinitionMetricsPerUnion interface {
	implementsEvaluationQueryNewParamsDefinitionMetricsPerUnion()
}

type EvaluationQueryNewParamsDefinitionMetricsPerVariantEvaluationColumn struct {
	Kind param.Field[EvaluationQueryNewParamsDefinitionMetricsPerVariantEvaluationColumnKind] `json:"kind" api:"required"`
}

func (r EvaluationQueryNewParamsDefinitionMetricsPerVariantEvaluationColumn) MarshalJSON() (data []byte, err error) {
	return apijson.MarshalRoot(r)
}

func (r EvaluationQueryNewParamsDefinitionMetricsPerVariantEvaluationColumn) implementsEvaluationQueryNewParamsDefinitionMetricsPerUnion() {
}

type EvaluationQueryNewParamsDefinitionMetricsPerVariantEvaluationColumnKind string

const (
	EvaluationQueryNewParamsDefinitionMetricsPerVariantEvaluationColumnKindVariant EvaluationQueryNewParamsDefinitionMetricsPerVariantEvaluationColumnKind = "variant"
)

func (r EvaluationQueryNewParamsDefinitionMetricsPerVariantEvaluationColumnKind) IsKnown() bool {
	switch r {
	case EvaluationQueryNewParamsDefinitionMetricsPerVariantEvaluationColumnKindVariant:
		return true
	}
	return false
}

type EvaluationQueryNewParamsDefinitionMetricsPerDatasetFieldEvaluationColumn struct {
	Kind param.Field[EvaluationQueryNewParamsDefinitionMetricsPerDatasetFieldEvaluationColumnKind] `json:"kind" api:"required"`
	// Name of the input or output field to use as a column.
	Name param.Field[string] `json:"name" api:"required"`
	// Whether the field belongs to the case's input or output.
	Source param.Field[EvaluationQueryNewParamsDefinitionMetricsPerDatasetFieldEvaluationColumnSource] `json:"source" api:"required"`
}

func (r EvaluationQueryNewParamsDefinitionMetricsPerDatasetFieldEvaluationColumn) MarshalJSON() (data []byte, err error) {
	return apijson.MarshalRoot(r)
}

func (r EvaluationQueryNewParamsDefinitionMetricsPerDatasetFieldEvaluationColumn) implementsEvaluationQueryNewParamsDefinitionMetricsPerUnion() {
}

type EvaluationQueryNewParamsDefinitionMetricsPerDatasetFieldEvaluationColumnKind string

const (
	EvaluationQueryNewParamsDefinitionMetricsPerDatasetFieldEvaluationColumnKindDatasetField EvaluationQueryNewParamsDefinitionMetricsPerDatasetFieldEvaluationColumnKind = "dataset_field"
)

func (r EvaluationQueryNewParamsDefinitionMetricsPerDatasetFieldEvaluationColumnKind) IsKnown() bool {
	switch r {
	case EvaluationQueryNewParamsDefinitionMetricsPerDatasetFieldEvaluationColumnKindDatasetField:
		return true
	}
	return false
}

// Whether the field belongs to the case's input or output.
type EvaluationQueryNewParamsDefinitionMetricsPerDatasetFieldEvaluationColumnSource string

const (
	EvaluationQueryNewParamsDefinitionMetricsPerDatasetFieldEvaluationColumnSourceInput  EvaluationQueryNewParamsDefinitionMetricsPerDatasetFieldEvaluationColumnSource = "input"
	EvaluationQueryNewParamsDefinitionMetricsPerDatasetFieldEvaluationColumnSourceOutput EvaluationQueryNewParamsDefinitionMetricsPerDatasetFieldEvaluationColumnSource = "output"
)

func (r EvaluationQueryNewParamsDefinitionMetricsPerDatasetFieldEvaluationColumnSource) IsKnown() bool {
	switch r {
	case EvaluationQueryNewParamsDefinitionMetricsPerDatasetFieldEvaluationColumnSourceInput,
		EvaluationQueryNewParamsDefinitionMetricsPerDatasetFieldEvaluationColumnSourceOutput:
		return true
	}
	return false
}

type EvaluationQueryNewParamsDefinitionMetricsPerScoreEvaluationColumn struct {
	Kind param.Field[EvaluationQueryNewParamsDefinitionMetricsPerScoreEvaluationColumnKind] `json:"kind" api:"required"`
	// Name of the scorer whose score supplies this column.
	Name param.Field[string] `json:"name" api:"required"`
}

func (r EvaluationQueryNewParamsDefinitionMetricsPerScoreEvaluationColumn) MarshalJSON() (data []byte, err error) {
	return apijson.MarshalRoot(r)
}

func (r EvaluationQueryNewParamsDefinitionMetricsPerScoreEvaluationColumn) implementsEvaluationQueryNewParamsDefinitionMetricsPerUnion() {
}

type EvaluationQueryNewParamsDefinitionMetricsPerScoreEvaluationColumnKind string

const (
	EvaluationQueryNewParamsDefinitionMetricsPerScoreEvaluationColumnKindScore EvaluationQueryNewParamsDefinitionMetricsPerScoreEvaluationColumnKind = "score"
)

func (r EvaluationQueryNewParamsDefinitionMetricsPerScoreEvaluationColumnKind) IsKnown() bool {
	switch r {
	case EvaluationQueryNewParamsDefinitionMetricsPerScoreEvaluationColumnKindScore:
		return true
	}
	return false
}

// Trajectory queries only. Groups by depth, an integer that is 0 for a top-level
// trajectory.
type EvaluationQueryNewParamsDefinitionMetricsPerDepthEvaluationColumn struct {
	Kind param.Field[EvaluationQueryNewParamsDefinitionMetricsPerDepthEvaluationColumnKind] `json:"kind" api:"required"`
}

func (r EvaluationQueryNewParamsDefinitionMetricsPerDepthEvaluationColumn) MarshalJSON() (data []byte, err error) {
	return apijson.MarshalRoot(r)
}

func (r EvaluationQueryNewParamsDefinitionMetricsPerDepthEvaluationColumn) implementsEvaluationQueryNewParamsDefinitionMetricsPerUnion() {
}

type EvaluationQueryNewParamsDefinitionMetricsPerDepthEvaluationColumnKind string

const (
	EvaluationQueryNewParamsDefinitionMetricsPerDepthEvaluationColumnKindDepth EvaluationQueryNewParamsDefinitionMetricsPerDepthEvaluationColumnKind = "depth"
)

func (r EvaluationQueryNewParamsDefinitionMetricsPerDepthEvaluationColumnKind) IsKnown() bool {
	switch r {
	case EvaluationQueryNewParamsDefinitionMetricsPerDepthEvaluationColumnKindDepth:
		return true
	}
	return false
}

// Trajectory queries only. Groups by the parent trajectory's ID. Top-level
// trajectories form the null group.
type EvaluationQueryNewParamsDefinitionMetricsPerParentTrajectoryIDEvaluationColumn struct {
	Kind param.Field[EvaluationQueryNewParamsDefinitionMetricsPerParentTrajectoryIDEvaluationColumnKind] `json:"kind" api:"required"`
}

func (r EvaluationQueryNewParamsDefinitionMetricsPerParentTrajectoryIDEvaluationColumn) MarshalJSON() (data []byte, err error) {
	return apijson.MarshalRoot(r)
}

func (r EvaluationQueryNewParamsDefinitionMetricsPerParentTrajectoryIDEvaluationColumn) implementsEvaluationQueryNewParamsDefinitionMetricsPerUnion() {
}

type EvaluationQueryNewParamsDefinitionMetricsPerParentTrajectoryIDEvaluationColumnKind string

const (
	EvaluationQueryNewParamsDefinitionMetricsPerParentTrajectoryIDEvaluationColumnKindParentTrajectoryID EvaluationQueryNewParamsDefinitionMetricsPerParentTrajectoryIDEvaluationColumnKind = "parent_trajectory_id"
)

func (r EvaluationQueryNewParamsDefinitionMetricsPerParentTrajectoryIDEvaluationColumnKind) IsKnown() bool {
	switch r {
	case EvaluationQueryNewParamsDefinitionMetricsPerParentTrajectoryIDEvaluationColumnKindParentTrajectoryID:
		return true
	}
	return false
}

type EvaluationQueryNewParamsDefinitionMetricsPerKind string

const (
	EvaluationQueryNewParamsDefinitionMetricsPerKindVariant            EvaluationQueryNewParamsDefinitionMetricsPerKind = "variant"
	EvaluationQueryNewParamsDefinitionMetricsPerKindDatasetField       EvaluationQueryNewParamsDefinitionMetricsPerKind = "dataset_field"
	EvaluationQueryNewParamsDefinitionMetricsPerKindScore              EvaluationQueryNewParamsDefinitionMetricsPerKind = "score"
	EvaluationQueryNewParamsDefinitionMetricsPerKindDepth              EvaluationQueryNewParamsDefinitionMetricsPerKind = "depth"
	EvaluationQueryNewParamsDefinitionMetricsPerKindParentTrajectoryID EvaluationQueryNewParamsDefinitionMetricsPerKind = "parent_trajectory_id"
)

func (r EvaluationQueryNewParamsDefinitionMetricsPerKind) IsKnown() bool {
	switch r {
	case EvaluationQueryNewParamsDefinitionMetricsPerKindVariant,
		EvaluationQueryNewParamsDefinitionMetricsPerKindDatasetField,
		EvaluationQueryNewParamsDefinitionMetricsPerKindScore,
		EvaluationQueryNewParamsDefinitionMetricsPerKindDepth,
		EvaluationQueryNewParamsDefinitionMetricsPerKindParentTrajectoryID:
		return true
	}
	return false
}

// Whether the field belongs to the case's input or output.
type EvaluationQueryNewParamsDefinitionMetricsPerSource string

const (
	EvaluationQueryNewParamsDefinitionMetricsPerSourceInput  EvaluationQueryNewParamsDefinitionMetricsPerSource = "input"
	EvaluationQueryNewParamsDefinitionMetricsPerSourceOutput EvaluationQueryNewParamsDefinitionMetricsPerSource = "output"
)

func (r EvaluationQueryNewParamsDefinitionMetricsPerSource) IsKnown() bool {
	switch r {
	case EvaluationQueryNewParamsDefinitionMetricsPerSourceInput,
		EvaluationQueryNewParamsDefinitionMetricsPerSourceOutput:
		return true
	}
	return false
}

// Trajectory queries only. Groups by depth, an integer that is 0 for a top-level
// trajectory.
type EvaluationQueryNewParamsDefinitionGroupBy struct {
	Kind param.Field[EvaluationQueryNewParamsDefinitionGroupByKind] `json:"kind" api:"required"`
	// Name of the input or output field to use as a column.
	Name param.Field[string] `json:"name"`
	// Whether the field belongs to the case's input or output.
	Source param.Field[EvaluationQueryNewParamsDefinitionGroupBySource] `json:"source"`
}

func (r EvaluationQueryNewParamsDefinitionGroupBy) MarshalJSON() (data []byte, err error) {
	return apijson.MarshalRoot(r)
}

func (r EvaluationQueryNewParamsDefinitionGroupBy) implementsEvaluationQueryNewParamsDefinitionGroupByUnion() {
}

// Trajectory queries only. Groups by depth, an integer that is 0 for a top-level
// trajectory.
//
// Satisfied by [EvaluationQueryNewParamsDefinitionGroupByVariantEvaluationColumn],
// [EvaluationQueryNewParamsDefinitionGroupByDatasetFieldEvaluationColumn],
// [EvaluationQueryNewParamsDefinitionGroupByScoreEvaluationColumn],
// [EvaluationQueryNewParamsDefinitionGroupByDepthEvaluationColumn],
// [EvaluationQueryNewParamsDefinitionGroupByParentTrajectoryIDEvaluationColumn],
// [EvaluationQueryNewParamsDefinitionGroupBy].
type EvaluationQueryNewParamsDefinitionGroupByUnion interface {
	implementsEvaluationQueryNewParamsDefinitionGroupByUnion()
}

type EvaluationQueryNewParamsDefinitionGroupByVariantEvaluationColumn struct {
	Kind param.Field[EvaluationQueryNewParamsDefinitionGroupByVariantEvaluationColumnKind] `json:"kind" api:"required"`
}

func (r EvaluationQueryNewParamsDefinitionGroupByVariantEvaluationColumn) MarshalJSON() (data []byte, err error) {
	return apijson.MarshalRoot(r)
}

func (r EvaluationQueryNewParamsDefinitionGroupByVariantEvaluationColumn) implementsEvaluationQueryNewParamsDefinitionGroupByUnion() {
}

type EvaluationQueryNewParamsDefinitionGroupByVariantEvaluationColumnKind string

const (
	EvaluationQueryNewParamsDefinitionGroupByVariantEvaluationColumnKindVariant EvaluationQueryNewParamsDefinitionGroupByVariantEvaluationColumnKind = "variant"
)

func (r EvaluationQueryNewParamsDefinitionGroupByVariantEvaluationColumnKind) IsKnown() bool {
	switch r {
	case EvaluationQueryNewParamsDefinitionGroupByVariantEvaluationColumnKindVariant:
		return true
	}
	return false
}

type EvaluationQueryNewParamsDefinitionGroupByDatasetFieldEvaluationColumn struct {
	Kind param.Field[EvaluationQueryNewParamsDefinitionGroupByDatasetFieldEvaluationColumnKind] `json:"kind" api:"required"`
	// Name of the input or output field to use as a column.
	Name param.Field[string] `json:"name" api:"required"`
	// Whether the field belongs to the case's input or output.
	Source param.Field[EvaluationQueryNewParamsDefinitionGroupByDatasetFieldEvaluationColumnSource] `json:"source" api:"required"`
}

func (r EvaluationQueryNewParamsDefinitionGroupByDatasetFieldEvaluationColumn) MarshalJSON() (data []byte, err error) {
	return apijson.MarshalRoot(r)
}

func (r EvaluationQueryNewParamsDefinitionGroupByDatasetFieldEvaluationColumn) implementsEvaluationQueryNewParamsDefinitionGroupByUnion() {
}

type EvaluationQueryNewParamsDefinitionGroupByDatasetFieldEvaluationColumnKind string

const (
	EvaluationQueryNewParamsDefinitionGroupByDatasetFieldEvaluationColumnKindDatasetField EvaluationQueryNewParamsDefinitionGroupByDatasetFieldEvaluationColumnKind = "dataset_field"
)

func (r EvaluationQueryNewParamsDefinitionGroupByDatasetFieldEvaluationColumnKind) IsKnown() bool {
	switch r {
	case EvaluationQueryNewParamsDefinitionGroupByDatasetFieldEvaluationColumnKindDatasetField:
		return true
	}
	return false
}

// Whether the field belongs to the case's input or output.
type EvaluationQueryNewParamsDefinitionGroupByDatasetFieldEvaluationColumnSource string

const (
	EvaluationQueryNewParamsDefinitionGroupByDatasetFieldEvaluationColumnSourceInput  EvaluationQueryNewParamsDefinitionGroupByDatasetFieldEvaluationColumnSource = "input"
	EvaluationQueryNewParamsDefinitionGroupByDatasetFieldEvaluationColumnSourceOutput EvaluationQueryNewParamsDefinitionGroupByDatasetFieldEvaluationColumnSource = "output"
)

func (r EvaluationQueryNewParamsDefinitionGroupByDatasetFieldEvaluationColumnSource) IsKnown() bool {
	switch r {
	case EvaluationQueryNewParamsDefinitionGroupByDatasetFieldEvaluationColumnSourceInput,
		EvaluationQueryNewParamsDefinitionGroupByDatasetFieldEvaluationColumnSourceOutput:
		return true
	}
	return false
}

type EvaluationQueryNewParamsDefinitionGroupByScoreEvaluationColumn struct {
	Kind param.Field[EvaluationQueryNewParamsDefinitionGroupByScoreEvaluationColumnKind] `json:"kind" api:"required"`
	// Name of the scorer whose score supplies this column.
	Name param.Field[string] `json:"name" api:"required"`
}

func (r EvaluationQueryNewParamsDefinitionGroupByScoreEvaluationColumn) MarshalJSON() (data []byte, err error) {
	return apijson.MarshalRoot(r)
}

func (r EvaluationQueryNewParamsDefinitionGroupByScoreEvaluationColumn) implementsEvaluationQueryNewParamsDefinitionGroupByUnion() {
}

type EvaluationQueryNewParamsDefinitionGroupByScoreEvaluationColumnKind string

const (
	EvaluationQueryNewParamsDefinitionGroupByScoreEvaluationColumnKindScore EvaluationQueryNewParamsDefinitionGroupByScoreEvaluationColumnKind = "score"
)

func (r EvaluationQueryNewParamsDefinitionGroupByScoreEvaluationColumnKind) IsKnown() bool {
	switch r {
	case EvaluationQueryNewParamsDefinitionGroupByScoreEvaluationColumnKindScore:
		return true
	}
	return false
}

// Trajectory queries only. Groups by depth, an integer that is 0 for a top-level
// trajectory.
type EvaluationQueryNewParamsDefinitionGroupByDepthEvaluationColumn struct {
	Kind param.Field[EvaluationQueryNewParamsDefinitionGroupByDepthEvaluationColumnKind] `json:"kind" api:"required"`
}

func (r EvaluationQueryNewParamsDefinitionGroupByDepthEvaluationColumn) MarshalJSON() (data []byte, err error) {
	return apijson.MarshalRoot(r)
}

func (r EvaluationQueryNewParamsDefinitionGroupByDepthEvaluationColumn) implementsEvaluationQueryNewParamsDefinitionGroupByUnion() {
}

type EvaluationQueryNewParamsDefinitionGroupByDepthEvaluationColumnKind string

const (
	EvaluationQueryNewParamsDefinitionGroupByDepthEvaluationColumnKindDepth EvaluationQueryNewParamsDefinitionGroupByDepthEvaluationColumnKind = "depth"
)

func (r EvaluationQueryNewParamsDefinitionGroupByDepthEvaluationColumnKind) IsKnown() bool {
	switch r {
	case EvaluationQueryNewParamsDefinitionGroupByDepthEvaluationColumnKindDepth:
		return true
	}
	return false
}

// Trajectory queries only. Groups by the parent trajectory's ID. Top-level
// trajectories form the null group.
type EvaluationQueryNewParamsDefinitionGroupByParentTrajectoryIDEvaluationColumn struct {
	Kind param.Field[EvaluationQueryNewParamsDefinitionGroupByParentTrajectoryIDEvaluationColumnKind] `json:"kind" api:"required"`
}

func (r EvaluationQueryNewParamsDefinitionGroupByParentTrajectoryIDEvaluationColumn) MarshalJSON() (data []byte, err error) {
	return apijson.MarshalRoot(r)
}

func (r EvaluationQueryNewParamsDefinitionGroupByParentTrajectoryIDEvaluationColumn) implementsEvaluationQueryNewParamsDefinitionGroupByUnion() {
}

type EvaluationQueryNewParamsDefinitionGroupByParentTrajectoryIDEvaluationColumnKind string

const (
	EvaluationQueryNewParamsDefinitionGroupByParentTrajectoryIDEvaluationColumnKindParentTrajectoryID EvaluationQueryNewParamsDefinitionGroupByParentTrajectoryIDEvaluationColumnKind = "parent_trajectory_id"
)

func (r EvaluationQueryNewParamsDefinitionGroupByParentTrajectoryIDEvaluationColumnKind) IsKnown() bool {
	switch r {
	case EvaluationQueryNewParamsDefinitionGroupByParentTrajectoryIDEvaluationColumnKindParentTrajectoryID:
		return true
	}
	return false
}

type EvaluationQueryNewParamsDefinitionGroupByKind string

const (
	EvaluationQueryNewParamsDefinitionGroupByKindVariant            EvaluationQueryNewParamsDefinitionGroupByKind = "variant"
	EvaluationQueryNewParamsDefinitionGroupByKindDatasetField       EvaluationQueryNewParamsDefinitionGroupByKind = "dataset_field"
	EvaluationQueryNewParamsDefinitionGroupByKindScore              EvaluationQueryNewParamsDefinitionGroupByKind = "score"
	EvaluationQueryNewParamsDefinitionGroupByKindDepth              EvaluationQueryNewParamsDefinitionGroupByKind = "depth"
	EvaluationQueryNewParamsDefinitionGroupByKindParentTrajectoryID EvaluationQueryNewParamsDefinitionGroupByKind = "parent_trajectory_id"
)

func (r EvaluationQueryNewParamsDefinitionGroupByKind) IsKnown() bool {
	switch r {
	case EvaluationQueryNewParamsDefinitionGroupByKindVariant,
		EvaluationQueryNewParamsDefinitionGroupByKindDatasetField,
		EvaluationQueryNewParamsDefinitionGroupByKindScore,
		EvaluationQueryNewParamsDefinitionGroupByKindDepth,
		EvaluationQueryNewParamsDefinitionGroupByKindParentTrajectoryID:
		return true
	}
	return false
}

// Whether the field belongs to the case's input or output.
type EvaluationQueryNewParamsDefinitionGroupBySource string

const (
	EvaluationQueryNewParamsDefinitionGroupBySourceInput  EvaluationQueryNewParamsDefinitionGroupBySource = "input"
	EvaluationQueryNewParamsDefinitionGroupBySourceOutput EvaluationQueryNewParamsDefinitionGroupBySource = "output"
)

func (r EvaluationQueryNewParamsDefinitionGroupBySource) IsKnown() bool {
	switch r {
	case EvaluationQueryNewParamsDefinitionGroupBySourceInput, EvaluationQueryNewParamsDefinitionGroupBySourceOutput:
		return true
	}
	return false
}

// Targets whose scores the query aggregates. Omit or use case to aggregate the
// dataset's cases. trajectory aggregates scores on the dataset's trajectories and
// groups each trajectory by its root case's variant and fields.
type EvaluationQueryNewParamsDefinitionTargetKind string

const (
	EvaluationQueryNewParamsDefinitionTargetKindCase       EvaluationQueryNewParamsDefinitionTargetKind = "case"
	EvaluationQueryNewParamsDefinitionTargetKindTrajectory EvaluationQueryNewParamsDefinitionTargetKind = "trajectory"
)

func (r EvaluationQueryNewParamsDefinitionTargetKind) IsKnown() bool {
	switch r {
	case EvaluationQueryNewParamsDefinitionTargetKindCase, EvaluationQueryNewParamsDefinitionTargetKindTrajectory:
		return true
	}
	return false
}

type EvaluationQueryListParams struct {
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

// URLQuery serializes [EvaluationQueryListParams]'s query parameters as
// `url.Values`.
func (r EvaluationQueryListParams) URLQuery() (v url.Values) {
	return apiquery.MarshalWithSettings(r, apiquery.QuerySettings{
		ArrayFormat:  apiquery.ArrayQueryFormatComma,
		NestedFormat: apiquery.NestedQueryFormatBrackets,
	})
}

type EvaluationQueryGetParams struct {
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
