// File generated from our OpenAPI spec by Stainless.

package cwevals

import (
	"context"
	"errors"
	"fmt"
	"net/http"
	"slices"

	"github.com/wandb/cwevals-go/internal/apijson"
	"github.com/wandb/cwevals-go/internal/param"
	"github.com/wandb/cwevals-go/internal/requestconfig"
	"github.com/wandb/cwevals-go/option"
)

// EvalTableVersionColumnService contains methods and other services that help with
// interacting with the CoreWeave Evaluations API.
//
// Note, unlike clients, this service does not read variables from the environment
// automatically. You should not instantiate this service directly, and instead use
// the [NewEvalTableVersionColumnService] method instead.
type EvalTableVersionColumnService struct {
	Options []option.RequestOption
}

// NewEvalTableVersionColumnService generates a new service that applies the given
// options to each request. These options are applied after the parent client's
// options (if there is one), and before any request-specific options.
func NewEvalTableVersionColumnService(opts ...option.RequestOption) (r *EvalTableVersionColumnService) {
	r = &EvalTableVersionColumnService{}
	r.Options = opts
	return
}

// Returns the input, output, and score columns selected by the frozen evaluation
// table version.
func (r *EvalTableVersionColumnService) Get(
	ctx context.Context,
	evaluationVersionID string,
	query EvalTableVersionColumnGetParams,
	opts ...option.RequestOption,
) (res *EvalTableVersionColumnGetResponse, err error) {
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
	if evaluationVersionID == "" {
		err = errors.New("missing required evaluation_version_id parameter")
		return nil, err
	}
	path := fmt.Sprintf(
		"v1/namespaces/%s/scopes/%s/eval-table-versions/%s/columns",
		query.Namespace,
		query.ScopeID,
		evaluationVersionID,
	)
	err = requestconfig.ExecuteNewRequest(ctx, http.MethodGet, path, nil, &res, opts...)
	return res, err
}

type EvalTableVersionColumnGetResponse struct {
	DatasetFields       []EvalTableVersionColumnGetResponseDatasetField `json:"dataset_fields"        api:"required"`
	EvaluationID        string                                          `json:"evaluation_id"         api:"required" format:"uuid"`
	EvaluationVersionID string                                          `json:"evaluation_version_id" api:"required" format:"uuid"`
	Scorers             []EvalTableVersionColumnGetResponseScorer       `json:"scorers"               api:"required"`
	JSON                evalTableVersionColumnGetResponseJSON           `json:"-"`
}

// evalTableVersionColumnGetResponseJSON contains the JSON metadata for the struct
// [EvalTableVersionColumnGetResponse]
type evalTableVersionColumnGetResponseJSON struct {
	DatasetFields       apijson.Field
	EvaluationID        apijson.Field
	EvaluationVersionID apijson.Field
	Scorers             apijson.Field
	raw                 string
	ExtraFields         map[string]apijson.Field
}

func (r *EvalTableVersionColumnGetResponse) UnmarshalJSON(data []byte) (err error) {
	return apijson.UnmarshalRoot(data, r)
}

func (r evalTableVersionColumnGetResponseJSON) RawJSON() string {
	return r.raw
}

type EvalTableVersionColumnGetResponseDatasetField struct {
	Name   string                                               `json:"name"   api:"required"`
	Source EvalTableVersionColumnGetResponseDatasetFieldsSource `json:"source" api:"required"`
	// json may represent an extension-backed field or an ordinary JSON field.
	ValueType EvalTableVersionColumnGetResponseDatasetFieldsValueType `json:"value_type" api:"required"`
	// Extension schema version. Omitted for ordinary fields.
	ExtensionSchemaVersion int64 `json:"extension_schema_version"`
	// Extension schema type. Omitted for ordinary fields.
	ExtensionType EvalTableVersionColumnGetResponseDatasetFieldsExtensionType `json:"extension_type"`
	JSON          evalTableVersionColumnGetResponseDatasetFieldJSON           `json:"-"`
}

// evalTableVersionColumnGetResponseDatasetFieldJSON contains the JSON metadata for
// the struct [EvalTableVersionColumnGetResponseDatasetField]
type evalTableVersionColumnGetResponseDatasetFieldJSON struct {
	Name                   apijson.Field
	Source                 apijson.Field
	ValueType              apijson.Field
	ExtensionSchemaVersion apijson.Field
	ExtensionType          apijson.Field
	raw                    string
	ExtraFields            map[string]apijson.Field
}

func (r *EvalTableVersionColumnGetResponseDatasetField) UnmarshalJSON(data []byte) (err error) {
	return apijson.UnmarshalRoot(data, r)
}

func (r evalTableVersionColumnGetResponseDatasetFieldJSON) RawJSON() string {
	return r.raw
}

type EvalTableVersionColumnGetResponseDatasetFieldsSource string

const (
	EvalTableVersionColumnGetResponseDatasetFieldsSourceInput  EvalTableVersionColumnGetResponseDatasetFieldsSource = "input"
	EvalTableVersionColumnGetResponseDatasetFieldsSourceOutput EvalTableVersionColumnGetResponseDatasetFieldsSource = "output"
)

func (r EvalTableVersionColumnGetResponseDatasetFieldsSource) IsKnown() bool {
	switch r {
	case EvalTableVersionColumnGetResponseDatasetFieldsSourceInput,
		EvalTableVersionColumnGetResponseDatasetFieldsSourceOutput:
		return true
	}
	return false
}

// json may represent an extension-backed field or an ordinary JSON field.
type EvalTableVersionColumnGetResponseDatasetFieldsValueType string

const (
	EvalTableVersionColumnGetResponseDatasetFieldsValueTypeNull    EvalTableVersionColumnGetResponseDatasetFieldsValueType = "null"
	EvalTableVersionColumnGetResponseDatasetFieldsValueTypeBoolean EvalTableVersionColumnGetResponseDatasetFieldsValueType = "boolean"
	EvalTableVersionColumnGetResponseDatasetFieldsValueTypeInteger EvalTableVersionColumnGetResponseDatasetFieldsValueType = "integer"
	EvalTableVersionColumnGetResponseDatasetFieldsValueTypeNumber  EvalTableVersionColumnGetResponseDatasetFieldsValueType = "number"
	EvalTableVersionColumnGetResponseDatasetFieldsValueTypeString  EvalTableVersionColumnGetResponseDatasetFieldsValueType = "string"
	EvalTableVersionColumnGetResponseDatasetFieldsValueTypeJson    EvalTableVersionColumnGetResponseDatasetFieldsValueType = "json"
)

func (r EvalTableVersionColumnGetResponseDatasetFieldsValueType) IsKnown() bool {
	switch r {
	case EvalTableVersionColumnGetResponseDatasetFieldsValueTypeNull,
		EvalTableVersionColumnGetResponseDatasetFieldsValueTypeBoolean,
		EvalTableVersionColumnGetResponseDatasetFieldsValueTypeInteger,
		EvalTableVersionColumnGetResponseDatasetFieldsValueTypeNumber,
		EvalTableVersionColumnGetResponseDatasetFieldsValueTypeString,
		EvalTableVersionColumnGetResponseDatasetFieldsValueTypeJson:
		return true
	}
	return false
}

// Extension schema type. Omitted for ordinary fields.
type EvalTableVersionColumnGetResponseDatasetFieldsExtensionType string

const (
	EvalTableVersionColumnGetResponseDatasetFieldsExtensionTypeWandbImage    EvalTableVersionColumnGetResponseDatasetFieldsExtensionType = "wandb-image"
	EvalTableVersionColumnGetResponseDatasetFieldsExtensionTypeWandbAudio    EvalTableVersionColumnGetResponseDatasetFieldsExtensionType = "wandb-audio"
	EvalTableVersionColumnGetResponseDatasetFieldsExtensionTypeWandbVideo    EvalTableVersionColumnGetResponseDatasetFieldsExtensionType = "wandb-video"
	EvalTableVersionColumnGetResponseDatasetFieldsExtensionTypeWandbHTML     EvalTableVersionColumnGetResponseDatasetFieldsExtensionType = "wandb-html"
	EvalTableVersionColumnGetResponseDatasetFieldsExtensionTypeWandbBokeh    EvalTableVersionColumnGetResponseDatasetFieldsExtensionType = "wandb-bokeh"
	EvalTableVersionColumnGetResponseDatasetFieldsExtensionTypeWandbObject3d EvalTableVersionColumnGetResponseDatasetFieldsExtensionType = "wandb-object3d"
	EvalTableVersionColumnGetResponseDatasetFieldsExtensionTypeWandbMolecule EvalTableVersionColumnGetResponseDatasetFieldsExtensionType = "wandb-molecule"
)

func (r EvalTableVersionColumnGetResponseDatasetFieldsExtensionType) IsKnown() bool {
	switch r {
	case EvalTableVersionColumnGetResponseDatasetFieldsExtensionTypeWandbImage,
		EvalTableVersionColumnGetResponseDatasetFieldsExtensionTypeWandbAudio,
		EvalTableVersionColumnGetResponseDatasetFieldsExtensionTypeWandbVideo,
		EvalTableVersionColumnGetResponseDatasetFieldsExtensionTypeWandbHTML,
		EvalTableVersionColumnGetResponseDatasetFieldsExtensionTypeWandbBokeh,
		EvalTableVersionColumnGetResponseDatasetFieldsExtensionTypeWandbObject3d,
		EvalTableVersionColumnGetResponseDatasetFieldsExtensionTypeWandbMolecule:
		return true
	}
	return false
}

type EvalTableVersionColumnGetResponseScorer struct {
	Name            string                                            `json:"name"              api:"required"`
	ScorerID        string                                            `json:"scorer_id"         api:"required" format:"uuid"`
	ScorerVersionID string                                            `json:"scorer_version_id" api:"required" format:"uuid"`
	ValueType       EvalTableVersionColumnGetResponseScorersValueType `json:"value_type"        api:"required"`
	JSON            evalTableVersionColumnGetResponseScorerJSON       `json:"-"`
}

// evalTableVersionColumnGetResponseScorerJSON contains the JSON metadata for the
// struct [EvalTableVersionColumnGetResponseScorer]
type evalTableVersionColumnGetResponseScorerJSON struct {
	Name            apijson.Field
	ScorerID        apijson.Field
	ScorerVersionID apijson.Field
	ValueType       apijson.Field
	raw             string
	ExtraFields     map[string]apijson.Field
}

func (r *EvalTableVersionColumnGetResponseScorer) UnmarshalJSON(data []byte) (err error) {
	return apijson.UnmarshalRoot(data, r)
}

func (r evalTableVersionColumnGetResponseScorerJSON) RawJSON() string {
	return r.raw
}

type EvalTableVersionColumnGetResponseScorersValueType string

const (
	EvalTableVersionColumnGetResponseScorersValueTypeBoolean EvalTableVersionColumnGetResponseScorersValueType = "boolean"
	EvalTableVersionColumnGetResponseScorersValueTypeInteger EvalTableVersionColumnGetResponseScorersValueType = "integer"
	EvalTableVersionColumnGetResponseScorersValueTypeNumber  EvalTableVersionColumnGetResponseScorersValueType = "number"
	EvalTableVersionColumnGetResponseScorersValueTypeString  EvalTableVersionColumnGetResponseScorersValueType = "string"
)

func (r EvalTableVersionColumnGetResponseScorersValueType) IsKnown() bool {
	switch r {
	case EvalTableVersionColumnGetResponseScorersValueTypeBoolean,
		EvalTableVersionColumnGetResponseScorersValueTypeInteger,
		EvalTableVersionColumnGetResponseScorersValueTypeNumber,
		EvalTableVersionColumnGetResponseScorersValueTypeString:
		return true
	}
	return false
}

type EvalTableVersionColumnGetParams struct {
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
