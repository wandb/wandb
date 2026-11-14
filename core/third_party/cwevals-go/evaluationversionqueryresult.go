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
	"github.com/wandb/cwevals-go/shared"
)

// EvaluationVersionQueryResultService contains methods and other services that
// help with interacting with the CoreWeave Evaluations API.
//
// Note, unlike clients, this service does not read variables from the environment
// automatically. You should not instantiate this service directly, and instead use
// the [NewEvaluationVersionQueryResultService] method instead.
type EvaluationVersionQueryResultService struct {
	Options []option.RequestOption
}

// NewEvaluationVersionQueryResultService generates a new service that applies the
// given options to each request. These options are applied after the parent
// client's options (if there is one), and before any request-specific options.
func NewEvaluationVersionQueryResultService(opts ...option.RequestOption) (r *EvaluationVersionQueryResultService) {
	r = &EvaluationVersionQueryResultService{}
	r.Options = opts
	return
}

// Runs one of the evaluation's saved aggregation queries against the data and
// scores captured in this evaluation version.
//
// **Version compatibility**
//
// Returns 400 if the dataset snapshot lacks a grouping field, or if the evaluation
// version does not select a scorer used by a metric or score grouping.
//
// **Grouping and ordering**
//
//   - Rows sort by the `group_by` columns in order, ascending, with nulls last.
//   - A missing grouping value and an explicit null belong to the same group.
//   - Without grouping, the response has one row with an empty `group` array, even
//     for an empty dataset.
//   - With grouping, an empty dataset returns no rows.
func (r *EvaluationVersionQueryResultService) List(
	ctx context.Context,
	evaluationVersionID string,
	evaluationQueryID string,
	params EvaluationVersionQueryResultListParams,
	opts ...option.RequestOption,
) (res *EvaluationVersionQueryResultListResponse, err error) {
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
	if evaluationQueryID == "" {
		err = errors.New("missing required evaluation_query_id parameter")
		return nil, err
	}
	path := fmt.Sprintf(
		"v1/namespaces/%s/scopes/%s/evaluation-versions/%s/queries/%s/results",
		params.Namespace,
		params.ScopeID,
		evaluationVersionID,
		evaluationQueryID,
	)
	err = requestconfig.ExecuteNewRequest(ctx, http.MethodGet, path, params, &res, opts...)
	return res, err
}

type EvaluationVersionQueryResultListResponse struct {
	// Dataset version supplying the cases or trajectories. For a live evaluation
	// queried on latest data, this is the dataset head selected for the first page.
	DatasetVersionID  string                                            `json:"dataset_version_id"  api:"required" format:"uuid"`
	EvaluationID      string                                            `json:"evaluation_id"       api:"required" format:"uuid"`
	EvaluationQueryID string                                            `json:"evaluation_query_id" api:"required" format:"uuid"`
	GroupBy           []EvaluationVersionQueryResultListResponseGroupBy `json:"group_by"            api:"required"`
	Metrics           []EvaluationVersionQueryResultListResponseMetric  `json:"metrics"             api:"required"`
	// Namespace that assigned the scope reference.
	Namespace EvaluationVersionQueryResultListResponseNamespace `json:"namespace" api:"required"`
	// Publication cutoff shared by every page of these results. Scores published later
	// are excluded. For a live evaluation's latest data, cases and trajectories
	// published later are also excluded.
	PublishedCommitID int64                                         `json:"published_commit_id" api:"required"`
	Rows              []EvaluationVersionQueryResultListResponseRow `json:"rows"                api:"required"`
	ScopeRef          string                                        `json:"scope_ref"           api:"required"`
	// Kind of target that each row's targets field counts.
	TargetKind EvaluationVersionQueryResultListResponseTargetKind `json:"target_kind" api:"required"`
	// Frozen evaluation version supplying the data. Omitted when querying the
	// evaluation's latest data.
	EvaluationVersionID string `json:"evaluation_version_id" format:"uuid"`
	// Cursor for the next page. Absent on the last page.
	NextCursor string                                       `json:"next_cursor"`
	JSON       evaluationVersionQueryResultListResponseJSON `json:"-"`
}

// evaluationVersionQueryResultListResponseJSON contains the JSON metadata for the
// struct [EvaluationVersionQueryResultListResponse]
type evaluationVersionQueryResultListResponseJSON struct {
	DatasetVersionID    apijson.Field
	EvaluationID        apijson.Field
	EvaluationQueryID   apijson.Field
	GroupBy             apijson.Field
	Metrics             apijson.Field
	Namespace           apijson.Field
	PublishedCommitID   apijson.Field
	Rows                apijson.Field
	ScopeRef            apijson.Field
	TargetKind          apijson.Field
	EvaluationVersionID apijson.Field
	NextCursor          apijson.Field
	raw                 string
	ExtraFields         map[string]apijson.Field
}

func (r *EvaluationVersionQueryResultListResponse) UnmarshalJSON(data []byte) (err error) {
	return apijson.UnmarshalRoot(data, r)
}

func (r evaluationVersionQueryResultListResponseJSON) RawJSON() string {
	return r.raw
}

type EvaluationVersionQueryResultListResponseGroupBy struct {
	Kind      EvaluationVersionQueryResultListResponseGroupByKind      `json:"kind"       api:"required"`
	ValueType EvaluationVersionQueryResultListResponseGroupByValueType `json:"value_type" api:"required"`
	Name      string                                                   `json:"name"`
	Source    EvaluationVersionQueryResultListResponseGroupBySource    `json:"source"`
	JSON      evaluationVersionQueryResultListResponseGroupByJSON      `json:"-"`
}

// evaluationVersionQueryResultListResponseGroupByJSON contains the JSON metadata
// for the struct [EvaluationVersionQueryResultListResponseGroupBy]
type evaluationVersionQueryResultListResponseGroupByJSON struct {
	Kind        apijson.Field
	ValueType   apijson.Field
	Name        apijson.Field
	Source      apijson.Field
	raw         string
	ExtraFields map[string]apijson.Field
}

func (r *EvaluationVersionQueryResultListResponseGroupBy) UnmarshalJSON(data []byte) (err error) {
	return apijson.UnmarshalRoot(data, r)
}

func (r evaluationVersionQueryResultListResponseGroupByJSON) RawJSON() string {
	return r.raw
}

type EvaluationVersionQueryResultListResponseGroupByKind string

const (
	EvaluationVersionQueryResultListResponseGroupByKindVariant            EvaluationVersionQueryResultListResponseGroupByKind = "variant"
	EvaluationVersionQueryResultListResponseGroupByKindDatasetField       EvaluationVersionQueryResultListResponseGroupByKind = "dataset_field"
	EvaluationVersionQueryResultListResponseGroupByKindScore              EvaluationVersionQueryResultListResponseGroupByKind = "score"
	EvaluationVersionQueryResultListResponseGroupByKindDepth              EvaluationVersionQueryResultListResponseGroupByKind = "depth"
	EvaluationVersionQueryResultListResponseGroupByKindParentTrajectoryID EvaluationVersionQueryResultListResponseGroupByKind = "parent_trajectory_id"
)

func (r EvaluationVersionQueryResultListResponseGroupByKind) IsKnown() bool {
	switch r {
	case EvaluationVersionQueryResultListResponseGroupByKindVariant,
		EvaluationVersionQueryResultListResponseGroupByKindDatasetField,
		EvaluationVersionQueryResultListResponseGroupByKindScore,
		EvaluationVersionQueryResultListResponseGroupByKindDepth,
		EvaluationVersionQueryResultListResponseGroupByKindParentTrajectoryID:
		return true
	}
	return false
}

type EvaluationVersionQueryResultListResponseGroupByValueType string

const (
	EvaluationVersionQueryResultListResponseGroupByValueTypeBoolean EvaluationVersionQueryResultListResponseGroupByValueType = "boolean"
	EvaluationVersionQueryResultListResponseGroupByValueTypeInteger EvaluationVersionQueryResultListResponseGroupByValueType = "integer"
	EvaluationVersionQueryResultListResponseGroupByValueTypeNumber  EvaluationVersionQueryResultListResponseGroupByValueType = "number"
	EvaluationVersionQueryResultListResponseGroupByValueTypeString  EvaluationVersionQueryResultListResponseGroupByValueType = "string"
)

func (r EvaluationVersionQueryResultListResponseGroupByValueType) IsKnown() bool {
	switch r {
	case EvaluationVersionQueryResultListResponseGroupByValueTypeBoolean,
		EvaluationVersionQueryResultListResponseGroupByValueTypeInteger,
		EvaluationVersionQueryResultListResponseGroupByValueTypeNumber,
		EvaluationVersionQueryResultListResponseGroupByValueTypeString:
		return true
	}
	return false
}

type EvaluationVersionQueryResultListResponseGroupBySource string

const (
	EvaluationVersionQueryResultListResponseGroupBySourceInput  EvaluationVersionQueryResultListResponseGroupBySource = "input"
	EvaluationVersionQueryResultListResponseGroupBySourceOutput EvaluationVersionQueryResultListResponseGroupBySource = "output"
)

func (r EvaluationVersionQueryResultListResponseGroupBySource) IsKnown() bool {
	switch r {
	case EvaluationVersionQueryResultListResponseGroupBySourceInput,
		EvaluationVersionQueryResultListResponseGroupBySourceOutput:
		return true
	}
	return false
}

type EvaluationVersionQueryResultListResponseMetric struct {
	Aggregation     EvaluationVersionQueryResultListResponseMetricsAggregation `json:"aggregation"       api:"required"`
	Name            string                                                     `json:"name"              api:"required"`
	ScorerID        string                                                     `json:"scorer_id"         api:"required" format:"uuid"`
	ScorerVersionID string                                                     `json:"scorer_version_id" api:"required" format:"uuid"`
	// Aggregation output type: number for mean and pass_at_k, integer for count and
	// boolean sum, and the scorer's type otherwise.
	ValueType EvaluationVersionQueryResultListResponseMetricsValueType `json:"value_type" api:"required"`
	K         int64                                                    `json:"k"`
	Missing   EvaluationVersionQueryResultListResponseMetricsMissing   `json:"missing"`
	// Trajectory queries only. Groups by depth, an integer that is 0 for a top-level
	// trajectory.
	Per  EvaluationVersionQueryResultListResponseMetricsPer `json:"per"`
	JSON evaluationVersionQueryResultListResponseMetricJSON `json:"-"`
}

// evaluationVersionQueryResultListResponseMetricJSON contains the JSON metadata
// for the struct [EvaluationVersionQueryResultListResponseMetric]
type evaluationVersionQueryResultListResponseMetricJSON struct {
	Aggregation     apijson.Field
	Name            apijson.Field
	ScorerID        apijson.Field
	ScorerVersionID apijson.Field
	ValueType       apijson.Field
	K               apijson.Field
	Missing         apijson.Field
	Per             apijson.Field
	raw             string
	ExtraFields     map[string]apijson.Field
}

func (r *EvaluationVersionQueryResultListResponseMetric) UnmarshalJSON(data []byte) (err error) {
	return apijson.UnmarshalRoot(data, r)
}

func (r evaluationVersionQueryResultListResponseMetricJSON) RawJSON() string {
	return r.raw
}

type EvaluationVersionQueryResultListResponseMetricsAggregation string

const (
	EvaluationVersionQueryResultListResponseMetricsAggregationMean    EvaluationVersionQueryResultListResponseMetricsAggregation = "mean"
	EvaluationVersionQueryResultListResponseMetricsAggregationSum     EvaluationVersionQueryResultListResponseMetricsAggregation = "sum"
	EvaluationVersionQueryResultListResponseMetricsAggregationMin     EvaluationVersionQueryResultListResponseMetricsAggregation = "min"
	EvaluationVersionQueryResultListResponseMetricsAggregationMax     EvaluationVersionQueryResultListResponseMetricsAggregation = "max"
	EvaluationVersionQueryResultListResponseMetricsAggregationCount   EvaluationVersionQueryResultListResponseMetricsAggregation = "count"
	EvaluationVersionQueryResultListResponseMetricsAggregationPassAtK EvaluationVersionQueryResultListResponseMetricsAggregation = "pass_at_k"
)

func (r EvaluationVersionQueryResultListResponseMetricsAggregation) IsKnown() bool {
	switch r {
	case EvaluationVersionQueryResultListResponseMetricsAggregationMean,
		EvaluationVersionQueryResultListResponseMetricsAggregationSum,
		EvaluationVersionQueryResultListResponseMetricsAggregationMin,
		EvaluationVersionQueryResultListResponseMetricsAggregationMax,
		EvaluationVersionQueryResultListResponseMetricsAggregationCount,
		EvaluationVersionQueryResultListResponseMetricsAggregationPassAtK:
		return true
	}
	return false
}

// Aggregation output type: number for mean and pass_at_k, integer for count and
// boolean sum, and the scorer's type otherwise.
type EvaluationVersionQueryResultListResponseMetricsValueType string

const (
	EvaluationVersionQueryResultListResponseMetricsValueTypeBoolean EvaluationVersionQueryResultListResponseMetricsValueType = "boolean"
	EvaluationVersionQueryResultListResponseMetricsValueTypeInteger EvaluationVersionQueryResultListResponseMetricsValueType = "integer"
	EvaluationVersionQueryResultListResponseMetricsValueTypeNumber  EvaluationVersionQueryResultListResponseMetricsValueType = "number"
	EvaluationVersionQueryResultListResponseMetricsValueTypeString  EvaluationVersionQueryResultListResponseMetricsValueType = "string"
)

func (r EvaluationVersionQueryResultListResponseMetricsValueType) IsKnown() bool {
	switch r {
	case EvaluationVersionQueryResultListResponseMetricsValueTypeBoolean,
		EvaluationVersionQueryResultListResponseMetricsValueTypeInteger,
		EvaluationVersionQueryResultListResponseMetricsValueTypeNumber,
		EvaluationVersionQueryResultListResponseMetricsValueTypeString:
		return true
	}
	return false
}

type EvaluationVersionQueryResultListResponseMetricsMissing string

const (
	EvaluationVersionQueryResultListResponseMetricsMissingSkip EvaluationVersionQueryResultListResponseMetricsMissing = "skip"
	EvaluationVersionQueryResultListResponseMetricsMissingZero EvaluationVersionQueryResultListResponseMetricsMissing = "zero"
)

func (r EvaluationVersionQueryResultListResponseMetricsMissing) IsKnown() bool {
	switch r {
	case EvaluationVersionQueryResultListResponseMetricsMissingSkip,
		EvaluationVersionQueryResultListResponseMetricsMissingZero:
		return true
	}
	return false
}

// Trajectory queries only. Groups by depth, an integer that is 0 for a top-level
// trajectory.
type EvaluationVersionQueryResultListResponseMetricsPer struct {
	Kind EvaluationVersionQueryResultListResponseMetricsPerKind `json:"kind" api:"required"`
	// Name of the input or output field to use as a column.
	Name string `json:"name"`
	// Whether the field belongs to the case's input or output.
	Source EvaluationVersionQueryResultListResponseMetricsPerSource `json:"source"`
	JSON   evaluationVersionQueryResultListResponseMetricsPerJSON   `json:"-"`
	union  EvaluationVersionQueryResultListResponseMetricsPerUnion
}

// evaluationVersionQueryResultListResponseMetricsPerJSON contains the JSON
// metadata for the struct [EvaluationVersionQueryResultListResponseMetricsPer]
type evaluationVersionQueryResultListResponseMetricsPerJSON struct {
	Kind        apijson.Field
	Name        apijson.Field
	Source      apijson.Field
	raw         string
	ExtraFields map[string]apijson.Field
}

func (r evaluationVersionQueryResultListResponseMetricsPerJSON) RawJSON() string {
	return r.raw
}

func (r *EvaluationVersionQueryResultListResponseMetricsPer) UnmarshalJSON(data []byte) (err error) {
	*r = EvaluationVersionQueryResultListResponseMetricsPer{}
	err = apijson.UnmarshalRoot(data, &r.union)
	if err != nil {
		return err
	}
	return apijson.Port(r.union, &r)
}

// AsUnion returns a [EvaluationVersionQueryResultListResponseMetricsPerUnion]
// interface which you can cast to the specific types for more type safety.
//
// Possible runtime types of the union are
// [EvaluationVersionQueryResultListResponseMetricsPerVariantEvaluationColumn],
// [EvaluationVersionQueryResultListResponseMetricsPerDatasetFieldEvaluationColumn],
// [EvaluationVersionQueryResultListResponseMetricsPerScoreEvaluationColumn],
// [EvaluationVersionQueryResultListResponseMetricsPerDepthEvaluationColumn],
// [EvaluationVersionQueryResultListResponseMetricsPerParentTrajectoryIDEvaluationColumn].
func (r EvaluationVersionQueryResultListResponseMetricsPer) AsUnion() EvaluationVersionQueryResultListResponseMetricsPerUnion {
	return r.union
}

// Trajectory queries only. Groups by depth, an integer that is 0 for a top-level
// trajectory.
//
// Union satisfied by
// [EvaluationVersionQueryResultListResponseMetricsPerVariantEvaluationColumn],
// [EvaluationVersionQueryResultListResponseMetricsPerDatasetFieldEvaluationColumn],
// [EvaluationVersionQueryResultListResponseMetricsPerScoreEvaluationColumn],
// [EvaluationVersionQueryResultListResponseMetricsPerDepthEvaluationColumn] or
// [EvaluationVersionQueryResultListResponseMetricsPerParentTrajectoryIDEvaluationColumn].
type EvaluationVersionQueryResultListResponseMetricsPerUnion interface {
	implementsEvaluationVersionQueryResultListResponseMetricsPer()
}

func init() {
	apijson.RegisterUnion(
		reflect.TypeOf((*EvaluationVersionQueryResultListResponseMetricsPerUnion)(nil)).Elem(),
		"kind",
		apijson.UnionVariant{
			TypeFilter: gjson.JSON,
			Type: reflect.TypeOf(
				EvaluationVersionQueryResultListResponseMetricsPerVariantEvaluationColumn{},
			),
			DiscriminatorValue: "variant",
		},
		apijson.UnionVariant{
			TypeFilter: gjson.JSON,
			Type: reflect.TypeOf(
				EvaluationVersionQueryResultListResponseMetricsPerDatasetFieldEvaluationColumn{},
			),
			DiscriminatorValue: "dataset_field",
		},
		apijson.UnionVariant{
			TypeFilter: gjson.JSON,
			Type: reflect.TypeOf(
				EvaluationVersionQueryResultListResponseMetricsPerScoreEvaluationColumn{},
			),
			DiscriminatorValue: "score",
		},
		apijson.UnionVariant{
			TypeFilter: gjson.JSON,
			Type: reflect.TypeOf(
				EvaluationVersionQueryResultListResponseMetricsPerDepthEvaluationColumn{},
			),
			DiscriminatorValue: "depth",
		},
		apijson.UnionVariant{
			TypeFilter: gjson.JSON,
			Type: reflect.TypeOf(
				EvaluationVersionQueryResultListResponseMetricsPerParentTrajectoryIDEvaluationColumn{},
			),
			DiscriminatorValue: "parent_trajectory_id",
		},
	)
}

type EvaluationVersionQueryResultListResponseMetricsPerVariantEvaluationColumn struct {
	Kind EvaluationVersionQueryResultListResponseMetricsPerVariantEvaluationColumnKind `json:"kind" api:"required"`
	JSON evaluationVersionQueryResultListResponseMetricsPerVariantEvaluationColumnJSON `json:"-"`
}

// evaluationVersionQueryResultListResponseMetricsPerVariantEvaluationColumnJSON
// contains the JSON metadata for the struct
// [EvaluationVersionQueryResultListResponseMetricsPerVariantEvaluationColumn]
type evaluationVersionQueryResultListResponseMetricsPerVariantEvaluationColumnJSON struct {
	Kind        apijson.Field
	raw         string
	ExtraFields map[string]apijson.Field
}

func (r *EvaluationVersionQueryResultListResponseMetricsPerVariantEvaluationColumn) UnmarshalJSON(
	data []byte,
) (err error) {
	return apijson.UnmarshalRoot(data, r)
}

func (r evaluationVersionQueryResultListResponseMetricsPerVariantEvaluationColumnJSON) RawJSON() string {
	return r.raw
}

func (r EvaluationVersionQueryResultListResponseMetricsPerVariantEvaluationColumn) implementsEvaluationVersionQueryResultListResponseMetricsPer() {
}

type EvaluationVersionQueryResultListResponseMetricsPerVariantEvaluationColumnKind string

const (
	EvaluationVersionQueryResultListResponseMetricsPerVariantEvaluationColumnKindVariant EvaluationVersionQueryResultListResponseMetricsPerVariantEvaluationColumnKind = "variant"
)

func (r EvaluationVersionQueryResultListResponseMetricsPerVariantEvaluationColumnKind) IsKnown() bool {
	switch r {
	case EvaluationVersionQueryResultListResponseMetricsPerVariantEvaluationColumnKindVariant:
		return true
	}
	return false
}

type EvaluationVersionQueryResultListResponseMetricsPerDatasetFieldEvaluationColumn struct {
	Kind EvaluationVersionQueryResultListResponseMetricsPerDatasetFieldEvaluationColumnKind `json:"kind" api:"required"`
	// Name of the input or output field to use as a column.
	Name string `json:"name" api:"required"`
	// Whether the field belongs to the case's input or output.
	Source EvaluationVersionQueryResultListResponseMetricsPerDatasetFieldEvaluationColumnSource `json:"source" api:"required"`
	JSON   evaluationVersionQueryResultListResponseMetricsPerDatasetFieldEvaluationColumnJSON   `json:"-"`
}

// evaluationVersionQueryResultListResponseMetricsPerDatasetFieldEvaluationColumnJSON
// contains the JSON metadata for the struct
// [EvaluationVersionQueryResultListResponseMetricsPerDatasetFieldEvaluationColumn]
type evaluationVersionQueryResultListResponseMetricsPerDatasetFieldEvaluationColumnJSON struct {
	Kind        apijson.Field
	Name        apijson.Field
	Source      apijson.Field
	raw         string
	ExtraFields map[string]apijson.Field
}

func (r *EvaluationVersionQueryResultListResponseMetricsPerDatasetFieldEvaluationColumn) UnmarshalJSON(
	data []byte,
) (err error) {
	return apijson.UnmarshalRoot(data, r)
}

func (r evaluationVersionQueryResultListResponseMetricsPerDatasetFieldEvaluationColumnJSON) RawJSON() string {
	return r.raw
}

func (r EvaluationVersionQueryResultListResponseMetricsPerDatasetFieldEvaluationColumn) implementsEvaluationVersionQueryResultListResponseMetricsPer() {
}

type EvaluationVersionQueryResultListResponseMetricsPerDatasetFieldEvaluationColumnKind string

const (
	EvaluationVersionQueryResultListResponseMetricsPerDatasetFieldEvaluationColumnKindDatasetField EvaluationVersionQueryResultListResponseMetricsPerDatasetFieldEvaluationColumnKind = "dataset_field"
)

func (r EvaluationVersionQueryResultListResponseMetricsPerDatasetFieldEvaluationColumnKind) IsKnown() bool {
	switch r {
	case EvaluationVersionQueryResultListResponseMetricsPerDatasetFieldEvaluationColumnKindDatasetField:
		return true
	}
	return false
}

// Whether the field belongs to the case's input or output.
type EvaluationVersionQueryResultListResponseMetricsPerDatasetFieldEvaluationColumnSource string

const (
	EvaluationVersionQueryResultListResponseMetricsPerDatasetFieldEvaluationColumnSourceInput  EvaluationVersionQueryResultListResponseMetricsPerDatasetFieldEvaluationColumnSource = "input"
	EvaluationVersionQueryResultListResponseMetricsPerDatasetFieldEvaluationColumnSourceOutput EvaluationVersionQueryResultListResponseMetricsPerDatasetFieldEvaluationColumnSource = "output"
)

func (r EvaluationVersionQueryResultListResponseMetricsPerDatasetFieldEvaluationColumnSource) IsKnown() bool {
	switch r {
	case EvaluationVersionQueryResultListResponseMetricsPerDatasetFieldEvaluationColumnSourceInput,
		EvaluationVersionQueryResultListResponseMetricsPerDatasetFieldEvaluationColumnSourceOutput:
		return true
	}
	return false
}

type EvaluationVersionQueryResultListResponseMetricsPerScoreEvaluationColumn struct {
	Kind EvaluationVersionQueryResultListResponseMetricsPerScoreEvaluationColumnKind `json:"kind" api:"required"`
	// Name of the scorer whose score supplies this column.
	Name string                                                                      `json:"name" api:"required"`
	JSON evaluationVersionQueryResultListResponseMetricsPerScoreEvaluationColumnJSON `json:"-"`
}

// evaluationVersionQueryResultListResponseMetricsPerScoreEvaluationColumnJSON
// contains the JSON metadata for the struct
// [EvaluationVersionQueryResultListResponseMetricsPerScoreEvaluationColumn]
type evaluationVersionQueryResultListResponseMetricsPerScoreEvaluationColumnJSON struct {
	Kind        apijson.Field
	Name        apijson.Field
	raw         string
	ExtraFields map[string]apijson.Field
}

func (r *EvaluationVersionQueryResultListResponseMetricsPerScoreEvaluationColumn) UnmarshalJSON(
	data []byte,
) (err error) {
	return apijson.UnmarshalRoot(data, r)
}

func (r evaluationVersionQueryResultListResponseMetricsPerScoreEvaluationColumnJSON) RawJSON() string {
	return r.raw
}

func (r EvaluationVersionQueryResultListResponseMetricsPerScoreEvaluationColumn) implementsEvaluationVersionQueryResultListResponseMetricsPer() {
}

type EvaluationVersionQueryResultListResponseMetricsPerScoreEvaluationColumnKind string

const (
	EvaluationVersionQueryResultListResponseMetricsPerScoreEvaluationColumnKindScore EvaluationVersionQueryResultListResponseMetricsPerScoreEvaluationColumnKind = "score"
)

func (r EvaluationVersionQueryResultListResponseMetricsPerScoreEvaluationColumnKind) IsKnown() bool {
	switch r {
	case EvaluationVersionQueryResultListResponseMetricsPerScoreEvaluationColumnKindScore:
		return true
	}
	return false
}

// Trajectory queries only. Groups by depth, an integer that is 0 for a top-level
// trajectory.
type EvaluationVersionQueryResultListResponseMetricsPerDepthEvaluationColumn struct {
	Kind EvaluationVersionQueryResultListResponseMetricsPerDepthEvaluationColumnKind `json:"kind" api:"required"`
	JSON evaluationVersionQueryResultListResponseMetricsPerDepthEvaluationColumnJSON `json:"-"`
}

// evaluationVersionQueryResultListResponseMetricsPerDepthEvaluationColumnJSON
// contains the JSON metadata for the struct
// [EvaluationVersionQueryResultListResponseMetricsPerDepthEvaluationColumn]
type evaluationVersionQueryResultListResponseMetricsPerDepthEvaluationColumnJSON struct {
	Kind        apijson.Field
	raw         string
	ExtraFields map[string]apijson.Field
}

func (r *EvaluationVersionQueryResultListResponseMetricsPerDepthEvaluationColumn) UnmarshalJSON(
	data []byte,
) (err error) {
	return apijson.UnmarshalRoot(data, r)
}

func (r evaluationVersionQueryResultListResponseMetricsPerDepthEvaluationColumnJSON) RawJSON() string {
	return r.raw
}

func (r EvaluationVersionQueryResultListResponseMetricsPerDepthEvaluationColumn) implementsEvaluationVersionQueryResultListResponseMetricsPer() {
}

type EvaluationVersionQueryResultListResponseMetricsPerDepthEvaluationColumnKind string

const (
	EvaluationVersionQueryResultListResponseMetricsPerDepthEvaluationColumnKindDepth EvaluationVersionQueryResultListResponseMetricsPerDepthEvaluationColumnKind = "depth"
)

func (r EvaluationVersionQueryResultListResponseMetricsPerDepthEvaluationColumnKind) IsKnown() bool {
	switch r {
	case EvaluationVersionQueryResultListResponseMetricsPerDepthEvaluationColumnKindDepth:
		return true
	}
	return false
}

// Trajectory queries only. Groups by the parent trajectory's ID. Top-level
// trajectories form the null group.
type EvaluationVersionQueryResultListResponseMetricsPerParentTrajectoryIDEvaluationColumn struct {
	Kind EvaluationVersionQueryResultListResponseMetricsPerParentTrajectoryIDEvaluationColumnKind `json:"kind" api:"required"`
	JSON evaluationVersionQueryResultListResponseMetricsPerParentTrajectoryIDEvaluationColumnJSON `json:"-"`
}

// evaluationVersionQueryResultListResponseMetricsPerParentTrajectoryIDEvaluationColumnJSON
// contains the JSON metadata for the struct
// [EvaluationVersionQueryResultListResponseMetricsPerParentTrajectoryIDEvaluationColumn]
type evaluationVersionQueryResultListResponseMetricsPerParentTrajectoryIDEvaluationColumnJSON struct {
	Kind        apijson.Field
	raw         string
	ExtraFields map[string]apijson.Field
}

func (r *EvaluationVersionQueryResultListResponseMetricsPerParentTrajectoryIDEvaluationColumn) UnmarshalJSON(
	data []byte,
) (err error) {
	return apijson.UnmarshalRoot(data, r)
}

func (r evaluationVersionQueryResultListResponseMetricsPerParentTrajectoryIDEvaluationColumnJSON) RawJSON() string {
	return r.raw
}

func (r EvaluationVersionQueryResultListResponseMetricsPerParentTrajectoryIDEvaluationColumn) implementsEvaluationVersionQueryResultListResponseMetricsPer() {
}

type EvaluationVersionQueryResultListResponseMetricsPerParentTrajectoryIDEvaluationColumnKind string

const (
	EvaluationVersionQueryResultListResponseMetricsPerParentTrajectoryIDEvaluationColumnKindParentTrajectoryID EvaluationVersionQueryResultListResponseMetricsPerParentTrajectoryIDEvaluationColumnKind = "parent_trajectory_id"
)

func (r EvaluationVersionQueryResultListResponseMetricsPerParentTrajectoryIDEvaluationColumnKind) IsKnown() bool {
	switch r {
	case EvaluationVersionQueryResultListResponseMetricsPerParentTrajectoryIDEvaluationColumnKindParentTrajectoryID:
		return true
	}
	return false
}

type EvaluationVersionQueryResultListResponseMetricsPerKind string

const (
	EvaluationVersionQueryResultListResponseMetricsPerKindVariant            EvaluationVersionQueryResultListResponseMetricsPerKind = "variant"
	EvaluationVersionQueryResultListResponseMetricsPerKindDatasetField       EvaluationVersionQueryResultListResponseMetricsPerKind = "dataset_field"
	EvaluationVersionQueryResultListResponseMetricsPerKindScore              EvaluationVersionQueryResultListResponseMetricsPerKind = "score"
	EvaluationVersionQueryResultListResponseMetricsPerKindDepth              EvaluationVersionQueryResultListResponseMetricsPerKind = "depth"
	EvaluationVersionQueryResultListResponseMetricsPerKindParentTrajectoryID EvaluationVersionQueryResultListResponseMetricsPerKind = "parent_trajectory_id"
)

func (r EvaluationVersionQueryResultListResponseMetricsPerKind) IsKnown() bool {
	switch r {
	case EvaluationVersionQueryResultListResponseMetricsPerKindVariant,
		EvaluationVersionQueryResultListResponseMetricsPerKindDatasetField,
		EvaluationVersionQueryResultListResponseMetricsPerKindScore,
		EvaluationVersionQueryResultListResponseMetricsPerKindDepth,
		EvaluationVersionQueryResultListResponseMetricsPerKindParentTrajectoryID:
		return true
	}
	return false
}

// Whether the field belongs to the case's input or output.
type EvaluationVersionQueryResultListResponseMetricsPerSource string

const (
	EvaluationVersionQueryResultListResponseMetricsPerSourceInput  EvaluationVersionQueryResultListResponseMetricsPerSource = "input"
	EvaluationVersionQueryResultListResponseMetricsPerSourceOutput EvaluationVersionQueryResultListResponseMetricsPerSource = "output"
)

func (r EvaluationVersionQueryResultListResponseMetricsPerSource) IsKnown() bool {
	switch r {
	case EvaluationVersionQueryResultListResponseMetricsPerSourceInput,
		EvaluationVersionQueryResultListResponseMetricsPerSourceOutput:
		return true
	}
	return false
}

// Namespace that assigned the scope reference.
type EvaluationVersionQueryResultListResponseNamespace string

const (
	EvaluationVersionQueryResultListResponseNamespaceWandb EvaluationVersionQueryResultListResponseNamespace = "wandb"
)

func (r EvaluationVersionQueryResultListResponseNamespace) IsKnown() bool {
	switch r {
	case EvaluationVersionQueryResultListResponseNamespaceWandb:
		return true
	}
	return false
}

type EvaluationVersionQueryResultListResponseRow struct {
	// Values in group_by order, with null for missing or null fields. Empty for an
	// ungrouped query.
	Group   []EvaluationVersionQueryResultListResponseRowsGroupUnion `json:"group"   api:"required"`
	Metrics []EvaluationVersionQueryResultListResponseRowsMetric     `json:"metrics" api:"required"`
	// Number of targets in this group: cases, or trajectories in a trajectory query.
	Targets int64                                           `json:"targets" api:"required"`
	JSON    evaluationVersionQueryResultListResponseRowJSON `json:"-"`
}

// evaluationVersionQueryResultListResponseRowJSON contains the JSON metadata for
// the struct [EvaluationVersionQueryResultListResponseRow]
type evaluationVersionQueryResultListResponseRowJSON struct {
	Group       apijson.Field
	Metrics     apijson.Field
	Targets     apijson.Field
	raw         string
	ExtraFields map[string]apijson.Field
}

func (r *EvaluationVersionQueryResultListResponseRow) UnmarshalJSON(data []byte) (err error) {
	return apijson.UnmarshalRoot(data, r)
}

func (r evaluationVersionQueryResultListResponseRowJSON) RawJSON() string {
	return r.raw
}

// A JSON scalar (boolean, integer, number, or string) or null.
//
// Union satisfied by [shared.UnionBool], [shared.UnionInt], [shared.UnionFloat] or
// [shared.UnionString].
type EvaluationVersionQueryResultListResponseRowsGroupUnion interface {
	ImplementsEvaluationVersionQueryResultListResponseRowsGroupUnion()
}

func init() {
	apijson.RegisterUnion(
		reflect.TypeOf((*EvaluationVersionQueryResultListResponseRowsGroupUnion)(nil)).Elem(),
		"",
		apijson.UnionVariant{
			TypeFilter: gjson.True,
			Type:       reflect.TypeOf(shared.UnionBool(false)),
		},
		apijson.UnionVariant{
			TypeFilter: gjson.False,
			Type:       reflect.TypeOf(shared.UnionBool(false)),
		},
		apijson.UnionVariant{
			TypeFilter: gjson.Number,
			Type:       reflect.TypeOf(shared.UnionInt(0)),
		},
		apijson.UnionVariant{
			TypeFilter: gjson.Number,
			Type:       reflect.TypeOf(shared.UnionFloat(0)),
		},
		apijson.UnionVariant{
			TypeFilter: gjson.String,
			Type:       reflect.TypeOf(shared.UnionString("")),
		},
	)
}

type EvaluationVersionQueryResultListResponseRowsMetric struct {
	Name string `json:"name" api:"required"`
	// Calculated metric value. If no target has a non-null latest visible score, count
	// returns 0 and other aggregations return null.
	Value EvaluationVersionQueryResultListResponseRowsMetricsValueUnion `json:"value" api:"required"`
	JSON  evaluationVersionQueryResultListResponseRowsMetricJSON        `json:"-"`
}

// evaluationVersionQueryResultListResponseRowsMetricJSON contains the JSON
// metadata for the struct [EvaluationVersionQueryResultListResponseRowsMetric]
type evaluationVersionQueryResultListResponseRowsMetricJSON struct {
	Name        apijson.Field
	Value       apijson.Field
	raw         string
	ExtraFields map[string]apijson.Field
}

func (r *EvaluationVersionQueryResultListResponseRowsMetric) UnmarshalJSON(data []byte) (err error) {
	return apijson.UnmarshalRoot(data, r)
}

func (r evaluationVersionQueryResultListResponseRowsMetricJSON) RawJSON() string {
	return r.raw
}

// Calculated metric value. If no target has a non-null latest visible score, count
// returns 0 and other aggregations return null.
//
// Union satisfied by [shared.UnionBool], [shared.UnionInt], [shared.UnionFloat] or
// [shared.UnionString].
type EvaluationVersionQueryResultListResponseRowsMetricsValueUnion interface {
	ImplementsEvaluationVersionQueryResultListResponseRowsMetricsValueUnion()
}

func init() {
	apijson.RegisterUnion(
		reflect.TypeOf((*EvaluationVersionQueryResultListResponseRowsMetricsValueUnion)(nil)).Elem(),
		"",
		apijson.UnionVariant{
			TypeFilter: gjson.True,
			Type:       reflect.TypeOf(shared.UnionBool(false)),
		},
		apijson.UnionVariant{
			TypeFilter: gjson.False,
			Type:       reflect.TypeOf(shared.UnionBool(false)),
		},
		apijson.UnionVariant{
			TypeFilter: gjson.Number,
			Type:       reflect.TypeOf(shared.UnionInt(0)),
		},
		apijson.UnionVariant{
			TypeFilter: gjson.Number,
			Type:       reflect.TypeOf(shared.UnionFloat(0)),
		},
		apijson.UnionVariant{
			TypeFilter: gjson.String,
			Type:       reflect.TypeOf(shared.UnionString("")),
		},
	)
}

// Kind of target that each row's targets field counts.
type EvaluationVersionQueryResultListResponseTargetKind string

const (
	EvaluationVersionQueryResultListResponseTargetKindCase       EvaluationVersionQueryResultListResponseTargetKind = "case"
	EvaluationVersionQueryResultListResponseTargetKindTrajectory EvaluationVersionQueryResultListResponseTargetKind = "trajectory"
)

func (r EvaluationVersionQueryResultListResponseTargetKind) IsKnown() bool {
	switch r {
	case EvaluationVersionQueryResultListResponseTargetKindCase,
		EvaluationVersionQueryResultListResponseTargetKindTrajectory:
		return true
	}
	return false
}

type EvaluationVersionQueryResultListParams struct {
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

// URLQuery serializes [EvaluationVersionQueryResultListParams]'s query parameters
// as `url.Values`.
func (r EvaluationVersionQueryResultListParams) URLQuery() (v url.Values) {
	return apiquery.MarshalWithSettings(r, apiquery.QuerySettings{
		ArrayFormat:  apiquery.ArrayQueryFormatComma,
		NestedFormat: apiquery.NestedQueryFormatBrackets,
	})
}
