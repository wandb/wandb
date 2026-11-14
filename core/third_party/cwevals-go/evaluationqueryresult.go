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

// EvaluationQueryResultService contains methods and other services that help with
// interacting with the CoreWeave Evaluations API.
//
// Note, unlike clients, this service does not read variables from the environment
// automatically. You should not instantiate this service directly, and instead use
// the [NewEvaluationQueryResultService] method instead.
type EvaluationQueryResultService struct {
	Options []option.RequestOption
}

// NewEvaluationQueryResultService generates a new service that applies the given
// options to each request. These options are applied after the parent client's
// options (if there is one), and before any request-specific options.
func NewEvaluationQueryResultService(opts ...option.RequestOption) (r *EvaluationQueryResultService) {
	r = &EvaluationQueryResultService{}
	r.Options = opts
	return
}

// Runs a saved aggregation query against the evaluation's latest published data.
//
// **Data included**
//
//   - A fixed evaluation reads the cases in its configured dataset version.
//   - A live evaluation reads the cases published to its dataset head.
//   - Scores come from all writes published so far for the evaluation's registered
//     scorers.
//   - Later pages keep the first page's cases and scores, even if new data arrives.
//
// **Grouping and ordering**
//
//   - Rows sort by the `group_by` columns in order, ascending, with nulls last.
//   - A missing grouping value and an explicit null belong to the same group.
//   - Without grouping, the response has one row with an empty `group` array, even
//     for an empty dataset.
//   - With grouping, an empty dataset returns no rows.
func (r *EvaluationQueryResultService) List(
	ctx context.Context,
	evaluationID string,
	evaluationQueryID string,
	params EvaluationQueryResultListParams,
	opts ...option.RequestOption,
) (res *EvaluationQueryResultListResponse, err error) {
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
	if evaluationQueryID == "" {
		err = errors.New("missing required evaluation_query_id parameter")
		return nil, err
	}
	path := fmt.Sprintf(
		"v1/namespaces/%s/scopes/%s/evaluations/%s/queries/%s/results",
		params.Namespace,
		params.ScopeID,
		evaluationID,
		evaluationQueryID,
	)
	err = requestconfig.ExecuteNewRequest(ctx, http.MethodGet, path, params, &res, opts...)
	return res, err
}

type EvaluationQueryResultListResponse struct {
	// Dataset version supplying the cases or trajectories. For a live evaluation
	// queried on latest data, this is the dataset head selected for the first page.
	DatasetVersionID  string                                     `json:"dataset_version_id"  api:"required" format:"uuid"`
	EvaluationID      string                                     `json:"evaluation_id"       api:"required" format:"uuid"`
	EvaluationQueryID string                                     `json:"evaluation_query_id" api:"required" format:"uuid"`
	GroupBy           []EvaluationQueryResultListResponseGroupBy `json:"group_by"            api:"required"`
	Metrics           []EvaluationQueryResultListResponseMetric  `json:"metrics"             api:"required"`
	// Namespace that assigned the scope reference.
	Namespace EvaluationQueryResultListResponseNamespace `json:"namespace" api:"required"`
	// Publication cutoff shared by every page of these results. Scores published later
	// are excluded. For a live evaluation's latest data, cases and trajectories
	// published later are also excluded.
	PublishedCommitID int64                                  `json:"published_commit_id" api:"required"`
	Rows              []EvaluationQueryResultListResponseRow `json:"rows"                api:"required"`
	ScopeRef          string                                 `json:"scope_ref"           api:"required"`
	// Kind of target that each row's targets field counts.
	TargetKind EvaluationQueryResultListResponseTargetKind `json:"target_kind" api:"required"`
	// Frozen evaluation version supplying the data. Omitted when querying the
	// evaluation's latest data.
	EvaluationVersionID string `json:"evaluation_version_id" format:"uuid"`
	// Cursor for the next page. Absent on the last page.
	NextCursor string                                `json:"next_cursor"`
	JSON       evaluationQueryResultListResponseJSON `json:"-"`
}

// evaluationQueryResultListResponseJSON contains the JSON metadata for the struct
// [EvaluationQueryResultListResponse]
type evaluationQueryResultListResponseJSON struct {
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

func (r *EvaluationQueryResultListResponse) UnmarshalJSON(data []byte) (err error) {
	return apijson.UnmarshalRoot(data, r)
}

func (r evaluationQueryResultListResponseJSON) RawJSON() string {
	return r.raw
}

type EvaluationQueryResultListResponseGroupBy struct {
	Kind      EvaluationQueryResultListResponseGroupByKind      `json:"kind"       api:"required"`
	ValueType EvaluationQueryResultListResponseGroupByValueType `json:"value_type" api:"required"`
	Name      string                                            `json:"name"`
	Source    EvaluationQueryResultListResponseGroupBySource    `json:"source"`
	JSON      evaluationQueryResultListResponseGroupByJSON      `json:"-"`
}

// evaluationQueryResultListResponseGroupByJSON contains the JSON metadata for the
// struct [EvaluationQueryResultListResponseGroupBy]
type evaluationQueryResultListResponseGroupByJSON struct {
	Kind        apijson.Field
	ValueType   apijson.Field
	Name        apijson.Field
	Source      apijson.Field
	raw         string
	ExtraFields map[string]apijson.Field
}

func (r *EvaluationQueryResultListResponseGroupBy) UnmarshalJSON(data []byte) (err error) {
	return apijson.UnmarshalRoot(data, r)
}

func (r evaluationQueryResultListResponseGroupByJSON) RawJSON() string {
	return r.raw
}

type EvaluationQueryResultListResponseGroupByKind string

const (
	EvaluationQueryResultListResponseGroupByKindVariant            EvaluationQueryResultListResponseGroupByKind = "variant"
	EvaluationQueryResultListResponseGroupByKindDatasetField       EvaluationQueryResultListResponseGroupByKind = "dataset_field"
	EvaluationQueryResultListResponseGroupByKindScore              EvaluationQueryResultListResponseGroupByKind = "score"
	EvaluationQueryResultListResponseGroupByKindDepth              EvaluationQueryResultListResponseGroupByKind = "depth"
	EvaluationQueryResultListResponseGroupByKindParentTrajectoryID EvaluationQueryResultListResponseGroupByKind = "parent_trajectory_id"
)

func (r EvaluationQueryResultListResponseGroupByKind) IsKnown() bool {
	switch r {
	case EvaluationQueryResultListResponseGroupByKindVariant,
		EvaluationQueryResultListResponseGroupByKindDatasetField,
		EvaluationQueryResultListResponseGroupByKindScore,
		EvaluationQueryResultListResponseGroupByKindDepth,
		EvaluationQueryResultListResponseGroupByKindParentTrajectoryID:
		return true
	}
	return false
}

type EvaluationQueryResultListResponseGroupByValueType string

const (
	EvaluationQueryResultListResponseGroupByValueTypeBoolean EvaluationQueryResultListResponseGroupByValueType = "boolean"
	EvaluationQueryResultListResponseGroupByValueTypeInteger EvaluationQueryResultListResponseGroupByValueType = "integer"
	EvaluationQueryResultListResponseGroupByValueTypeNumber  EvaluationQueryResultListResponseGroupByValueType = "number"
	EvaluationQueryResultListResponseGroupByValueTypeString  EvaluationQueryResultListResponseGroupByValueType = "string"
)

func (r EvaluationQueryResultListResponseGroupByValueType) IsKnown() bool {
	switch r {
	case EvaluationQueryResultListResponseGroupByValueTypeBoolean,
		EvaluationQueryResultListResponseGroupByValueTypeInteger,
		EvaluationQueryResultListResponseGroupByValueTypeNumber,
		EvaluationQueryResultListResponseGroupByValueTypeString:
		return true
	}
	return false
}

type EvaluationQueryResultListResponseGroupBySource string

const (
	EvaluationQueryResultListResponseGroupBySourceInput  EvaluationQueryResultListResponseGroupBySource = "input"
	EvaluationQueryResultListResponseGroupBySourceOutput EvaluationQueryResultListResponseGroupBySource = "output"
)

func (r EvaluationQueryResultListResponseGroupBySource) IsKnown() bool {
	switch r {
	case EvaluationQueryResultListResponseGroupBySourceInput, EvaluationQueryResultListResponseGroupBySourceOutput:
		return true
	}
	return false
}

type EvaluationQueryResultListResponseMetric struct {
	Aggregation     EvaluationQueryResultListResponseMetricsAggregation `json:"aggregation"       api:"required"`
	Name            string                                              `json:"name"              api:"required"`
	ScorerID        string                                              `json:"scorer_id"         api:"required" format:"uuid"`
	ScorerVersionID string                                              `json:"scorer_version_id" api:"required" format:"uuid"`
	// Aggregation output type: number for mean and pass_at_k, integer for count and
	// boolean sum, and the scorer's type otherwise.
	ValueType EvaluationQueryResultListResponseMetricsValueType `json:"value_type" api:"required"`
	K         int64                                             `json:"k"`
	Missing   EvaluationQueryResultListResponseMetricsMissing   `json:"missing"`
	// Trajectory queries only. Groups by depth, an integer that is 0 for a top-level
	// trajectory.
	Per  EvaluationQueryResultListResponseMetricsPer `json:"per"`
	JSON evaluationQueryResultListResponseMetricJSON `json:"-"`
}

// evaluationQueryResultListResponseMetricJSON contains the JSON metadata for the
// struct [EvaluationQueryResultListResponseMetric]
type evaluationQueryResultListResponseMetricJSON struct {
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

func (r *EvaluationQueryResultListResponseMetric) UnmarshalJSON(data []byte) (err error) {
	return apijson.UnmarshalRoot(data, r)
}

func (r evaluationQueryResultListResponseMetricJSON) RawJSON() string {
	return r.raw
}

type EvaluationQueryResultListResponseMetricsAggregation string

const (
	EvaluationQueryResultListResponseMetricsAggregationMean    EvaluationQueryResultListResponseMetricsAggregation = "mean"
	EvaluationQueryResultListResponseMetricsAggregationSum     EvaluationQueryResultListResponseMetricsAggregation = "sum"
	EvaluationQueryResultListResponseMetricsAggregationMin     EvaluationQueryResultListResponseMetricsAggregation = "min"
	EvaluationQueryResultListResponseMetricsAggregationMax     EvaluationQueryResultListResponseMetricsAggregation = "max"
	EvaluationQueryResultListResponseMetricsAggregationCount   EvaluationQueryResultListResponseMetricsAggregation = "count"
	EvaluationQueryResultListResponseMetricsAggregationPassAtK EvaluationQueryResultListResponseMetricsAggregation = "pass_at_k"
)

func (r EvaluationQueryResultListResponseMetricsAggregation) IsKnown() bool {
	switch r {
	case EvaluationQueryResultListResponseMetricsAggregationMean,
		EvaluationQueryResultListResponseMetricsAggregationSum,
		EvaluationQueryResultListResponseMetricsAggregationMin,
		EvaluationQueryResultListResponseMetricsAggregationMax,
		EvaluationQueryResultListResponseMetricsAggregationCount,
		EvaluationQueryResultListResponseMetricsAggregationPassAtK:
		return true
	}
	return false
}

// Aggregation output type: number for mean and pass_at_k, integer for count and
// boolean sum, and the scorer's type otherwise.
type EvaluationQueryResultListResponseMetricsValueType string

const (
	EvaluationQueryResultListResponseMetricsValueTypeBoolean EvaluationQueryResultListResponseMetricsValueType = "boolean"
	EvaluationQueryResultListResponseMetricsValueTypeInteger EvaluationQueryResultListResponseMetricsValueType = "integer"
	EvaluationQueryResultListResponseMetricsValueTypeNumber  EvaluationQueryResultListResponseMetricsValueType = "number"
	EvaluationQueryResultListResponseMetricsValueTypeString  EvaluationQueryResultListResponseMetricsValueType = "string"
)

func (r EvaluationQueryResultListResponseMetricsValueType) IsKnown() bool {
	switch r {
	case EvaluationQueryResultListResponseMetricsValueTypeBoolean,
		EvaluationQueryResultListResponseMetricsValueTypeInteger,
		EvaluationQueryResultListResponseMetricsValueTypeNumber,
		EvaluationQueryResultListResponseMetricsValueTypeString:
		return true
	}
	return false
}

type EvaluationQueryResultListResponseMetricsMissing string

const (
	EvaluationQueryResultListResponseMetricsMissingSkip EvaluationQueryResultListResponseMetricsMissing = "skip"
	EvaluationQueryResultListResponseMetricsMissingZero EvaluationQueryResultListResponseMetricsMissing = "zero"
)

func (r EvaluationQueryResultListResponseMetricsMissing) IsKnown() bool {
	switch r {
	case EvaluationQueryResultListResponseMetricsMissingSkip, EvaluationQueryResultListResponseMetricsMissingZero:
		return true
	}
	return false
}

// Trajectory queries only. Groups by depth, an integer that is 0 for a top-level
// trajectory.
type EvaluationQueryResultListResponseMetricsPer struct {
	Kind EvaluationQueryResultListResponseMetricsPerKind `json:"kind" api:"required"`
	// Name of the input or output field to use as a column.
	Name string `json:"name"`
	// Whether the field belongs to the case's input or output.
	Source EvaluationQueryResultListResponseMetricsPerSource `json:"source"`
	JSON   evaluationQueryResultListResponseMetricsPerJSON   `json:"-"`
	union  EvaluationQueryResultListResponseMetricsPerUnion
}

// evaluationQueryResultListResponseMetricsPerJSON contains the JSON metadata for
// the struct [EvaluationQueryResultListResponseMetricsPer]
type evaluationQueryResultListResponseMetricsPerJSON struct {
	Kind        apijson.Field
	Name        apijson.Field
	Source      apijson.Field
	raw         string
	ExtraFields map[string]apijson.Field
}

func (r evaluationQueryResultListResponseMetricsPerJSON) RawJSON() string {
	return r.raw
}

func (r *EvaluationQueryResultListResponseMetricsPer) UnmarshalJSON(data []byte) (err error) {
	*r = EvaluationQueryResultListResponseMetricsPer{}
	err = apijson.UnmarshalRoot(data, &r.union)
	if err != nil {
		return err
	}
	return apijson.Port(r.union, &r)
}

// AsUnion returns a [EvaluationQueryResultListResponseMetricsPerUnion] interface
// which you can cast to the specific types for more type safety.
//
// Possible runtime types of the union are
// [EvaluationQueryResultListResponseMetricsPerVariantEvaluationColumn],
// [EvaluationQueryResultListResponseMetricsPerDatasetFieldEvaluationColumn],
// [EvaluationQueryResultListResponseMetricsPerScoreEvaluationColumn],
// [EvaluationQueryResultListResponseMetricsPerDepthEvaluationColumn],
// [EvaluationQueryResultListResponseMetricsPerParentTrajectoryIDEvaluationColumn].
func (r EvaluationQueryResultListResponseMetricsPer) AsUnion() EvaluationQueryResultListResponseMetricsPerUnion {
	return r.union
}

// Trajectory queries only. Groups by depth, an integer that is 0 for a top-level
// trajectory.
//
// Union satisfied by
// [EvaluationQueryResultListResponseMetricsPerVariantEvaluationColumn],
// [EvaluationQueryResultListResponseMetricsPerDatasetFieldEvaluationColumn],
// [EvaluationQueryResultListResponseMetricsPerScoreEvaluationColumn],
// [EvaluationQueryResultListResponseMetricsPerDepthEvaluationColumn] or
// [EvaluationQueryResultListResponseMetricsPerParentTrajectoryIDEvaluationColumn].
type EvaluationQueryResultListResponseMetricsPerUnion interface {
	implementsEvaluationQueryResultListResponseMetricsPer()
}

func init() {
	apijson.RegisterUnion(
		reflect.TypeOf((*EvaluationQueryResultListResponseMetricsPerUnion)(nil)).Elem(),
		"kind",
		apijson.UnionVariant{
			TypeFilter:         gjson.JSON,
			Type:               reflect.TypeOf(EvaluationQueryResultListResponseMetricsPerVariantEvaluationColumn{}),
			DiscriminatorValue: "variant",
		},
		apijson.UnionVariant{
			TypeFilter: gjson.JSON,
			Type: reflect.TypeOf(
				EvaluationQueryResultListResponseMetricsPerDatasetFieldEvaluationColumn{},
			),
			DiscriminatorValue: "dataset_field",
		},
		apijson.UnionVariant{
			TypeFilter:         gjson.JSON,
			Type:               reflect.TypeOf(EvaluationQueryResultListResponseMetricsPerScoreEvaluationColumn{}),
			DiscriminatorValue: "score",
		},
		apijson.UnionVariant{
			TypeFilter:         gjson.JSON,
			Type:               reflect.TypeOf(EvaluationQueryResultListResponseMetricsPerDepthEvaluationColumn{}),
			DiscriminatorValue: "depth",
		},
		apijson.UnionVariant{
			TypeFilter: gjson.JSON,
			Type: reflect.TypeOf(
				EvaluationQueryResultListResponseMetricsPerParentTrajectoryIDEvaluationColumn{},
			),
			DiscriminatorValue: "parent_trajectory_id",
		},
	)
}

type EvaluationQueryResultListResponseMetricsPerVariantEvaluationColumn struct {
	Kind EvaluationQueryResultListResponseMetricsPerVariantEvaluationColumnKind `json:"kind" api:"required"`
	JSON evaluationQueryResultListResponseMetricsPerVariantEvaluationColumnJSON `json:"-"`
}

// evaluationQueryResultListResponseMetricsPerVariantEvaluationColumnJSON contains
// the JSON metadata for the struct
// [EvaluationQueryResultListResponseMetricsPerVariantEvaluationColumn]
type evaluationQueryResultListResponseMetricsPerVariantEvaluationColumnJSON struct {
	Kind        apijson.Field
	raw         string
	ExtraFields map[string]apijson.Field
}

func (r *EvaluationQueryResultListResponseMetricsPerVariantEvaluationColumn) UnmarshalJSON(data []byte) (err error) {
	return apijson.UnmarshalRoot(data, r)
}

func (r evaluationQueryResultListResponseMetricsPerVariantEvaluationColumnJSON) RawJSON() string {
	return r.raw
}

func (r EvaluationQueryResultListResponseMetricsPerVariantEvaluationColumn) implementsEvaluationQueryResultListResponseMetricsPer() {
}

type EvaluationQueryResultListResponseMetricsPerVariantEvaluationColumnKind string

const (
	EvaluationQueryResultListResponseMetricsPerVariantEvaluationColumnKindVariant EvaluationQueryResultListResponseMetricsPerVariantEvaluationColumnKind = "variant"
)

func (r EvaluationQueryResultListResponseMetricsPerVariantEvaluationColumnKind) IsKnown() bool {
	switch r {
	case EvaluationQueryResultListResponseMetricsPerVariantEvaluationColumnKindVariant:
		return true
	}
	return false
}

type EvaluationQueryResultListResponseMetricsPerDatasetFieldEvaluationColumn struct {
	Kind EvaluationQueryResultListResponseMetricsPerDatasetFieldEvaluationColumnKind `json:"kind" api:"required"`
	// Name of the input or output field to use as a column.
	Name string `json:"name" api:"required"`
	// Whether the field belongs to the case's input or output.
	Source EvaluationQueryResultListResponseMetricsPerDatasetFieldEvaluationColumnSource `json:"source" api:"required"`
	JSON   evaluationQueryResultListResponseMetricsPerDatasetFieldEvaluationColumnJSON   `json:"-"`
}

// evaluationQueryResultListResponseMetricsPerDatasetFieldEvaluationColumnJSON
// contains the JSON metadata for the struct
// [EvaluationQueryResultListResponseMetricsPerDatasetFieldEvaluationColumn]
type evaluationQueryResultListResponseMetricsPerDatasetFieldEvaluationColumnJSON struct {
	Kind        apijson.Field
	Name        apijson.Field
	Source      apijson.Field
	raw         string
	ExtraFields map[string]apijson.Field
}

func (r *EvaluationQueryResultListResponseMetricsPerDatasetFieldEvaluationColumn) UnmarshalJSON(
	data []byte,
) (err error) {
	return apijson.UnmarshalRoot(data, r)
}

func (r evaluationQueryResultListResponseMetricsPerDatasetFieldEvaluationColumnJSON) RawJSON() string {
	return r.raw
}

func (r EvaluationQueryResultListResponseMetricsPerDatasetFieldEvaluationColumn) implementsEvaluationQueryResultListResponseMetricsPer() {
}

type EvaluationQueryResultListResponseMetricsPerDatasetFieldEvaluationColumnKind string

const (
	EvaluationQueryResultListResponseMetricsPerDatasetFieldEvaluationColumnKindDatasetField EvaluationQueryResultListResponseMetricsPerDatasetFieldEvaluationColumnKind = "dataset_field"
)

func (r EvaluationQueryResultListResponseMetricsPerDatasetFieldEvaluationColumnKind) IsKnown() bool {
	switch r {
	case EvaluationQueryResultListResponseMetricsPerDatasetFieldEvaluationColumnKindDatasetField:
		return true
	}
	return false
}

// Whether the field belongs to the case's input or output.
type EvaluationQueryResultListResponseMetricsPerDatasetFieldEvaluationColumnSource string

const (
	EvaluationQueryResultListResponseMetricsPerDatasetFieldEvaluationColumnSourceInput  EvaluationQueryResultListResponseMetricsPerDatasetFieldEvaluationColumnSource = "input"
	EvaluationQueryResultListResponseMetricsPerDatasetFieldEvaluationColumnSourceOutput EvaluationQueryResultListResponseMetricsPerDatasetFieldEvaluationColumnSource = "output"
)

func (r EvaluationQueryResultListResponseMetricsPerDatasetFieldEvaluationColumnSource) IsKnown() bool {
	switch r {
	case EvaluationQueryResultListResponseMetricsPerDatasetFieldEvaluationColumnSourceInput,
		EvaluationQueryResultListResponseMetricsPerDatasetFieldEvaluationColumnSourceOutput:
		return true
	}
	return false
}

type EvaluationQueryResultListResponseMetricsPerScoreEvaluationColumn struct {
	Kind EvaluationQueryResultListResponseMetricsPerScoreEvaluationColumnKind `json:"kind" api:"required"`
	// Name of the scorer whose score supplies this column.
	Name string                                                               `json:"name" api:"required"`
	JSON evaluationQueryResultListResponseMetricsPerScoreEvaluationColumnJSON `json:"-"`
}

// evaluationQueryResultListResponseMetricsPerScoreEvaluationColumnJSON contains
// the JSON metadata for the struct
// [EvaluationQueryResultListResponseMetricsPerScoreEvaluationColumn]
type evaluationQueryResultListResponseMetricsPerScoreEvaluationColumnJSON struct {
	Kind        apijson.Field
	Name        apijson.Field
	raw         string
	ExtraFields map[string]apijson.Field
}

func (r *EvaluationQueryResultListResponseMetricsPerScoreEvaluationColumn) UnmarshalJSON(data []byte) (err error) {
	return apijson.UnmarshalRoot(data, r)
}

func (r evaluationQueryResultListResponseMetricsPerScoreEvaluationColumnJSON) RawJSON() string {
	return r.raw
}

func (r EvaluationQueryResultListResponseMetricsPerScoreEvaluationColumn) implementsEvaluationQueryResultListResponseMetricsPer() {
}

type EvaluationQueryResultListResponseMetricsPerScoreEvaluationColumnKind string

const (
	EvaluationQueryResultListResponseMetricsPerScoreEvaluationColumnKindScore EvaluationQueryResultListResponseMetricsPerScoreEvaluationColumnKind = "score"
)

func (r EvaluationQueryResultListResponseMetricsPerScoreEvaluationColumnKind) IsKnown() bool {
	switch r {
	case EvaluationQueryResultListResponseMetricsPerScoreEvaluationColumnKindScore:
		return true
	}
	return false
}

// Trajectory queries only. Groups by depth, an integer that is 0 for a top-level
// trajectory.
type EvaluationQueryResultListResponseMetricsPerDepthEvaluationColumn struct {
	Kind EvaluationQueryResultListResponseMetricsPerDepthEvaluationColumnKind `json:"kind" api:"required"`
	JSON evaluationQueryResultListResponseMetricsPerDepthEvaluationColumnJSON `json:"-"`
}

// evaluationQueryResultListResponseMetricsPerDepthEvaluationColumnJSON contains
// the JSON metadata for the struct
// [EvaluationQueryResultListResponseMetricsPerDepthEvaluationColumn]
type evaluationQueryResultListResponseMetricsPerDepthEvaluationColumnJSON struct {
	Kind        apijson.Field
	raw         string
	ExtraFields map[string]apijson.Field
}

func (r *EvaluationQueryResultListResponseMetricsPerDepthEvaluationColumn) UnmarshalJSON(data []byte) (err error) {
	return apijson.UnmarshalRoot(data, r)
}

func (r evaluationQueryResultListResponseMetricsPerDepthEvaluationColumnJSON) RawJSON() string {
	return r.raw
}

func (r EvaluationQueryResultListResponseMetricsPerDepthEvaluationColumn) implementsEvaluationQueryResultListResponseMetricsPer() {
}

type EvaluationQueryResultListResponseMetricsPerDepthEvaluationColumnKind string

const (
	EvaluationQueryResultListResponseMetricsPerDepthEvaluationColumnKindDepth EvaluationQueryResultListResponseMetricsPerDepthEvaluationColumnKind = "depth"
)

func (r EvaluationQueryResultListResponseMetricsPerDepthEvaluationColumnKind) IsKnown() bool {
	switch r {
	case EvaluationQueryResultListResponseMetricsPerDepthEvaluationColumnKindDepth:
		return true
	}
	return false
}

// Trajectory queries only. Groups by the parent trajectory's ID. Top-level
// trajectories form the null group.
type EvaluationQueryResultListResponseMetricsPerParentTrajectoryIDEvaluationColumn struct {
	Kind EvaluationQueryResultListResponseMetricsPerParentTrajectoryIDEvaluationColumnKind `json:"kind" api:"required"`
	JSON evaluationQueryResultListResponseMetricsPerParentTrajectoryIDEvaluationColumnJSON `json:"-"`
}

// evaluationQueryResultListResponseMetricsPerParentTrajectoryIDEvaluationColumnJSON
// contains the JSON metadata for the struct
// [EvaluationQueryResultListResponseMetricsPerParentTrajectoryIDEvaluationColumn]
type evaluationQueryResultListResponseMetricsPerParentTrajectoryIDEvaluationColumnJSON struct {
	Kind        apijson.Field
	raw         string
	ExtraFields map[string]apijson.Field
}

func (r *EvaluationQueryResultListResponseMetricsPerParentTrajectoryIDEvaluationColumn) UnmarshalJSON(
	data []byte,
) (err error) {
	return apijson.UnmarshalRoot(data, r)
}

func (r evaluationQueryResultListResponseMetricsPerParentTrajectoryIDEvaluationColumnJSON) RawJSON() string {
	return r.raw
}

func (r EvaluationQueryResultListResponseMetricsPerParentTrajectoryIDEvaluationColumn) implementsEvaluationQueryResultListResponseMetricsPer() {
}

type EvaluationQueryResultListResponseMetricsPerParentTrajectoryIDEvaluationColumnKind string

const (
	EvaluationQueryResultListResponseMetricsPerParentTrajectoryIDEvaluationColumnKindParentTrajectoryID EvaluationQueryResultListResponseMetricsPerParentTrajectoryIDEvaluationColumnKind = "parent_trajectory_id"
)

func (r EvaluationQueryResultListResponseMetricsPerParentTrajectoryIDEvaluationColumnKind) IsKnown() bool {
	switch r {
	case EvaluationQueryResultListResponseMetricsPerParentTrajectoryIDEvaluationColumnKindParentTrajectoryID:
		return true
	}
	return false
}

type EvaluationQueryResultListResponseMetricsPerKind string

const (
	EvaluationQueryResultListResponseMetricsPerKindVariant            EvaluationQueryResultListResponseMetricsPerKind = "variant"
	EvaluationQueryResultListResponseMetricsPerKindDatasetField       EvaluationQueryResultListResponseMetricsPerKind = "dataset_field"
	EvaluationQueryResultListResponseMetricsPerKindScore              EvaluationQueryResultListResponseMetricsPerKind = "score"
	EvaluationQueryResultListResponseMetricsPerKindDepth              EvaluationQueryResultListResponseMetricsPerKind = "depth"
	EvaluationQueryResultListResponseMetricsPerKindParentTrajectoryID EvaluationQueryResultListResponseMetricsPerKind = "parent_trajectory_id"
)

func (r EvaluationQueryResultListResponseMetricsPerKind) IsKnown() bool {
	switch r {
	case EvaluationQueryResultListResponseMetricsPerKindVariant,
		EvaluationQueryResultListResponseMetricsPerKindDatasetField,
		EvaluationQueryResultListResponseMetricsPerKindScore,
		EvaluationQueryResultListResponseMetricsPerKindDepth,
		EvaluationQueryResultListResponseMetricsPerKindParentTrajectoryID:
		return true
	}
	return false
}

// Whether the field belongs to the case's input or output.
type EvaluationQueryResultListResponseMetricsPerSource string

const (
	EvaluationQueryResultListResponseMetricsPerSourceInput  EvaluationQueryResultListResponseMetricsPerSource = "input"
	EvaluationQueryResultListResponseMetricsPerSourceOutput EvaluationQueryResultListResponseMetricsPerSource = "output"
)

func (r EvaluationQueryResultListResponseMetricsPerSource) IsKnown() bool {
	switch r {
	case EvaluationQueryResultListResponseMetricsPerSourceInput,
		EvaluationQueryResultListResponseMetricsPerSourceOutput:
		return true
	}
	return false
}

// Namespace that assigned the scope reference.
type EvaluationQueryResultListResponseNamespace string

const (
	EvaluationQueryResultListResponseNamespaceWandb EvaluationQueryResultListResponseNamespace = "wandb"
)

func (r EvaluationQueryResultListResponseNamespace) IsKnown() bool {
	switch r {
	case EvaluationQueryResultListResponseNamespaceWandb:
		return true
	}
	return false
}

type EvaluationQueryResultListResponseRow struct {
	// Values in group_by order, with null for missing or null fields. Empty for an
	// ungrouped query.
	Group   []EvaluationQueryResultListResponseRowsGroupUnion `json:"group"   api:"required"`
	Metrics []EvaluationQueryResultListResponseRowsMetric     `json:"metrics" api:"required"`
	// Number of targets in this group: cases, or trajectories in a trajectory query.
	Targets int64                                    `json:"targets" api:"required"`
	JSON    evaluationQueryResultListResponseRowJSON `json:"-"`
}

// evaluationQueryResultListResponseRowJSON contains the JSON metadata for the
// struct [EvaluationQueryResultListResponseRow]
type evaluationQueryResultListResponseRowJSON struct {
	Group       apijson.Field
	Metrics     apijson.Field
	Targets     apijson.Field
	raw         string
	ExtraFields map[string]apijson.Field
}

func (r *EvaluationQueryResultListResponseRow) UnmarshalJSON(data []byte) (err error) {
	return apijson.UnmarshalRoot(data, r)
}

func (r evaluationQueryResultListResponseRowJSON) RawJSON() string {
	return r.raw
}

// A JSON scalar (boolean, integer, number, or string) or null.
//
// Union satisfied by [shared.UnionBool], [shared.UnionInt], [shared.UnionFloat] or
// [shared.UnionString].
type EvaluationQueryResultListResponseRowsGroupUnion interface {
	ImplementsEvaluationQueryResultListResponseRowsGroupUnion()
}

func init() {
	apijson.RegisterUnion(
		reflect.TypeOf((*EvaluationQueryResultListResponseRowsGroupUnion)(nil)).Elem(),
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

type EvaluationQueryResultListResponseRowsMetric struct {
	Name string `json:"name" api:"required"`
	// Calculated metric value. If no target has a non-null latest visible score, count
	// returns 0 and other aggregations return null.
	Value EvaluationQueryResultListResponseRowsMetricsValueUnion `json:"value" api:"required"`
	JSON  evaluationQueryResultListResponseRowsMetricJSON        `json:"-"`
}

// evaluationQueryResultListResponseRowsMetricJSON contains the JSON metadata for
// the struct [EvaluationQueryResultListResponseRowsMetric]
type evaluationQueryResultListResponseRowsMetricJSON struct {
	Name        apijson.Field
	Value       apijson.Field
	raw         string
	ExtraFields map[string]apijson.Field
}

func (r *EvaluationQueryResultListResponseRowsMetric) UnmarshalJSON(data []byte) (err error) {
	return apijson.UnmarshalRoot(data, r)
}

func (r evaluationQueryResultListResponseRowsMetricJSON) RawJSON() string {
	return r.raw
}

// Calculated metric value. If no target has a non-null latest visible score, count
// returns 0 and other aggregations return null.
//
// Union satisfied by [shared.UnionBool], [shared.UnionInt], [shared.UnionFloat] or
// [shared.UnionString].
type EvaluationQueryResultListResponseRowsMetricsValueUnion interface {
	ImplementsEvaluationQueryResultListResponseRowsMetricsValueUnion()
}

func init() {
	apijson.RegisterUnion(
		reflect.TypeOf((*EvaluationQueryResultListResponseRowsMetricsValueUnion)(nil)).Elem(),
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
type EvaluationQueryResultListResponseTargetKind string

const (
	EvaluationQueryResultListResponseTargetKindCase       EvaluationQueryResultListResponseTargetKind = "case"
	EvaluationQueryResultListResponseTargetKindTrajectory EvaluationQueryResultListResponseTargetKind = "trajectory"
)

func (r EvaluationQueryResultListResponseTargetKind) IsKnown() bool {
	switch r {
	case EvaluationQueryResultListResponseTargetKindCase, EvaluationQueryResultListResponseTargetKindTrajectory:
		return true
	}
	return false
}

type EvaluationQueryResultListParams struct {
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

// URLQuery serializes [EvaluationQueryResultListParams]'s query parameters as
// `url.Values`.
func (r EvaluationQueryResultListParams) URLQuery() (v url.Values) {
	return apiquery.MarshalWithSettings(r, apiquery.QuerySettings{
		ArrayFormat:  apiquery.ArrayQueryFormatComma,
		NestedFormat: apiquery.NestedQueryFormatBrackets,
	})
}
