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

// EvalTableColumnService contains methods and other services that help with
// interacting with the CoreWeave Evaluations API.
//
// Note, unlike clients, this service does not read variables from the environment
// automatically. You should not instantiate this service directly, and instead use
// the [NewEvalTableColumnService] method instead.
type EvalTableColumnService struct {
	Options []option.RequestOption
}

// NewEvalTableColumnService generates a new service that applies the given options
// to each request. These options are applied after the parent client's options (if
// there is one), and before any request-specific options.
func NewEvalTableColumnService(opts ...option.RequestOption) (r *EvalTableColumnService) {
	r = &EvalTableColumnService{}
	r.Options = opts
	return
}

// Declares typed input and output fields and named score columns for an evaluation
// table. Use this operation when you want to choose column types explicitly.
//
// `Idempotency-Key` is required, but this operation does not replay an earlier
// response or check whether the key was used with different content.
//
// Request bodies must be at most 16 MiB. Bodies larger than the limit are rejected
// with 413 Request Entity Too Large.
func (r *EvalTableColumnService) New(
	ctx context.Context,
	evaluationID string,
	params EvalTableColumnNewParams,
	opts ...option.RequestOption,
) (res *EvalTableColumnNewResponse, err error) {
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
		"v1/namespaces/%s/scopes/%s/eval-tables/%s/columns",
		params.Namespace,
		params.ScopeID,
		evaluationID,
	)
	err = requestconfig.ExecuteNewRequest(ctx, http.MethodPost, path, params, &res, opts...)
	return res, err
}

type EvalTableColumnNewResponse struct {
	DatasetFields []EvalTableColumnNewResponseDatasetField `json:"dataset_fields" api:"required"`
	Scorers       []EvalTableColumnNewResponseScorer       `json:"scorers"        api:"required"`
	JSON          evalTableColumnNewResponseJSON           `json:"-"`
}

// evalTableColumnNewResponseJSON contains the JSON metadata for the struct
// [EvalTableColumnNewResponse]
type evalTableColumnNewResponseJSON struct {
	DatasetFields apijson.Field
	Scorers       apijson.Field
	raw           string
	ExtraFields   map[string]apijson.Field
}

func (r *EvalTableColumnNewResponse) UnmarshalJSON(data []byte) (err error) {
	return apijson.UnmarshalRoot(data, r)
}

func (r evalTableColumnNewResponseJSON) RawJSON() string {
	return r.raw
}

type EvalTableColumnNewResponseDatasetField struct {
	Name   string                                        `json:"name"   api:"required"`
	Source EvalTableColumnNewResponseDatasetFieldsSource `json:"source" api:"required"`
	// json may represent an extension-backed field or an ordinary JSON field.
	ValueType EvalTableColumnNewResponseDatasetFieldsValueType `json:"value_type" api:"required"`
	// Extension schema version. Omitted for ordinary fields.
	ExtensionSchemaVersion int64 `json:"extension_schema_version"`
	// Extension schema type. Omitted for ordinary fields.
	ExtensionType EvalTableColumnNewResponseDatasetFieldsExtensionType `json:"extension_type"`
	JSON          evalTableColumnNewResponseDatasetFieldJSON           `json:"-"`
}

// evalTableColumnNewResponseDatasetFieldJSON contains the JSON metadata for the
// struct [EvalTableColumnNewResponseDatasetField]
type evalTableColumnNewResponseDatasetFieldJSON struct {
	Name                   apijson.Field
	Source                 apijson.Field
	ValueType              apijson.Field
	ExtensionSchemaVersion apijson.Field
	ExtensionType          apijson.Field
	raw                    string
	ExtraFields            map[string]apijson.Field
}

func (r *EvalTableColumnNewResponseDatasetField) UnmarshalJSON(data []byte) (err error) {
	return apijson.UnmarshalRoot(data, r)
}

func (r evalTableColumnNewResponseDatasetFieldJSON) RawJSON() string {
	return r.raw
}

type EvalTableColumnNewResponseDatasetFieldsSource string

const (
	EvalTableColumnNewResponseDatasetFieldsSourceInput  EvalTableColumnNewResponseDatasetFieldsSource = "input"
	EvalTableColumnNewResponseDatasetFieldsSourceOutput EvalTableColumnNewResponseDatasetFieldsSource = "output"
)

func (r EvalTableColumnNewResponseDatasetFieldsSource) IsKnown() bool {
	switch r {
	case EvalTableColumnNewResponseDatasetFieldsSourceInput, EvalTableColumnNewResponseDatasetFieldsSourceOutput:
		return true
	}
	return false
}

// json may represent an extension-backed field or an ordinary JSON field.
type EvalTableColumnNewResponseDatasetFieldsValueType string

const (
	EvalTableColumnNewResponseDatasetFieldsValueTypeNull    EvalTableColumnNewResponseDatasetFieldsValueType = "null"
	EvalTableColumnNewResponseDatasetFieldsValueTypeBoolean EvalTableColumnNewResponseDatasetFieldsValueType = "boolean"
	EvalTableColumnNewResponseDatasetFieldsValueTypeInteger EvalTableColumnNewResponseDatasetFieldsValueType = "integer"
	EvalTableColumnNewResponseDatasetFieldsValueTypeNumber  EvalTableColumnNewResponseDatasetFieldsValueType = "number"
	EvalTableColumnNewResponseDatasetFieldsValueTypeString  EvalTableColumnNewResponseDatasetFieldsValueType = "string"
	EvalTableColumnNewResponseDatasetFieldsValueTypeJson    EvalTableColumnNewResponseDatasetFieldsValueType = "json"
)

func (r EvalTableColumnNewResponseDatasetFieldsValueType) IsKnown() bool {
	switch r {
	case EvalTableColumnNewResponseDatasetFieldsValueTypeNull,
		EvalTableColumnNewResponseDatasetFieldsValueTypeBoolean,
		EvalTableColumnNewResponseDatasetFieldsValueTypeInteger,
		EvalTableColumnNewResponseDatasetFieldsValueTypeNumber,
		EvalTableColumnNewResponseDatasetFieldsValueTypeString,
		EvalTableColumnNewResponseDatasetFieldsValueTypeJson:
		return true
	}
	return false
}

// Extension schema type. Omitted for ordinary fields.
type EvalTableColumnNewResponseDatasetFieldsExtensionType string

const (
	EvalTableColumnNewResponseDatasetFieldsExtensionTypeWandbImage    EvalTableColumnNewResponseDatasetFieldsExtensionType = "wandb-image"
	EvalTableColumnNewResponseDatasetFieldsExtensionTypeWandbAudio    EvalTableColumnNewResponseDatasetFieldsExtensionType = "wandb-audio"
	EvalTableColumnNewResponseDatasetFieldsExtensionTypeWandbVideo    EvalTableColumnNewResponseDatasetFieldsExtensionType = "wandb-video"
	EvalTableColumnNewResponseDatasetFieldsExtensionTypeWandbHTML     EvalTableColumnNewResponseDatasetFieldsExtensionType = "wandb-html"
	EvalTableColumnNewResponseDatasetFieldsExtensionTypeWandbBokeh    EvalTableColumnNewResponseDatasetFieldsExtensionType = "wandb-bokeh"
	EvalTableColumnNewResponseDatasetFieldsExtensionTypeWandbObject3d EvalTableColumnNewResponseDatasetFieldsExtensionType = "wandb-object3d"
	EvalTableColumnNewResponseDatasetFieldsExtensionTypeWandbMolecule EvalTableColumnNewResponseDatasetFieldsExtensionType = "wandb-molecule"
)

func (r EvalTableColumnNewResponseDatasetFieldsExtensionType) IsKnown() bool {
	switch r {
	case EvalTableColumnNewResponseDatasetFieldsExtensionTypeWandbImage,
		EvalTableColumnNewResponseDatasetFieldsExtensionTypeWandbAudio,
		EvalTableColumnNewResponseDatasetFieldsExtensionTypeWandbVideo,
		EvalTableColumnNewResponseDatasetFieldsExtensionTypeWandbHTML,
		EvalTableColumnNewResponseDatasetFieldsExtensionTypeWandbBokeh,
		EvalTableColumnNewResponseDatasetFieldsExtensionTypeWandbObject3d,
		EvalTableColumnNewResponseDatasetFieldsExtensionTypeWandbMolecule:
		return true
	}
	return false
}

type EvalTableColumnNewResponseScorer struct {
	Name            string                                     `json:"name"              api:"required"`
	ScorerID        string                                     `json:"scorer_id"         api:"required" format:"uuid"`
	ScorerVersionID string                                     `json:"scorer_version_id" api:"required" format:"uuid"`
	ValueType       EvalTableColumnNewResponseScorersValueType `json:"value_type"        api:"required"`
	JSON            evalTableColumnNewResponseScorerJSON       `json:"-"`
}

// evalTableColumnNewResponseScorerJSON contains the JSON metadata for the struct
// [EvalTableColumnNewResponseScorer]
type evalTableColumnNewResponseScorerJSON struct {
	Name            apijson.Field
	ScorerID        apijson.Field
	ScorerVersionID apijson.Field
	ValueType       apijson.Field
	raw             string
	ExtraFields     map[string]apijson.Field
}

func (r *EvalTableColumnNewResponseScorer) UnmarshalJSON(data []byte) (err error) {
	return apijson.UnmarshalRoot(data, r)
}

func (r evalTableColumnNewResponseScorerJSON) RawJSON() string {
	return r.raw
}

type EvalTableColumnNewResponseScorersValueType string

const (
	EvalTableColumnNewResponseScorersValueTypeBoolean EvalTableColumnNewResponseScorersValueType = "boolean"
	EvalTableColumnNewResponseScorersValueTypeInteger EvalTableColumnNewResponseScorersValueType = "integer"
	EvalTableColumnNewResponseScorersValueTypeNumber  EvalTableColumnNewResponseScorersValueType = "number"
	EvalTableColumnNewResponseScorersValueTypeString  EvalTableColumnNewResponseScorersValueType = "string"
)

func (r EvalTableColumnNewResponseScorersValueType) IsKnown() bool {
	switch r {
	case EvalTableColumnNewResponseScorersValueTypeBoolean,
		EvalTableColumnNewResponseScorersValueTypeInteger,
		EvalTableColumnNewResponseScorersValueTypeNumber,
		EvalTableColumnNewResponseScorersValueTypeString:
		return true
	}
	return false
}

type EvalTableColumnNewParams struct {
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
	// Input and output columns to declare, with a name and value type for each.
	DatasetFields param.Field[[]EvalTableColumnNewParamsDatasetField] `json:"dataset_fields"`
	// Named score columns to declare, with the value type each score must use.
	Scorers param.Field[[]EvalTableColumnNewParamsScorer] `json:"scorers"`
}

func (r EvalTableColumnNewParams) MarshalJSON() (data []byte, err error) {
	return apijson.MarshalRoot(r)
}

type EvalTableColumnNewParamsDatasetField struct {
	Name   param.Field[string]                                      `json:"name"   api:"required"`
	Source param.Field[EvalTableColumnNewParamsDatasetFieldsSource] `json:"source" api:"required"`
	// JSON type accepted by this column. Use json for ordinary JSON fields and for
	// media extension values.
	ValueType param.Field[EvalTableColumnNewParamsDatasetFieldsValueType] `json:"value_type" api:"required"`
	// Version of the media format. Set together with extension_type. Omit both for an
	// ordinary field.
	ExtensionSchemaVersion param.Field[int64] `json:"extension_schema_version"`
	// Media format stored in this field. Set together with extension_schema_version.
	// Omit both for an ordinary field.
	ExtensionType param.Field[EvalTableColumnNewParamsDatasetFieldsExtensionType] `json:"extension_type"`
}

func (r EvalTableColumnNewParamsDatasetField) MarshalJSON() (data []byte, err error) {
	return apijson.MarshalRoot(r)
}

type EvalTableColumnNewParamsDatasetFieldsSource string

const (
	EvalTableColumnNewParamsDatasetFieldsSourceInput  EvalTableColumnNewParamsDatasetFieldsSource = "input"
	EvalTableColumnNewParamsDatasetFieldsSourceOutput EvalTableColumnNewParamsDatasetFieldsSource = "output"
)

func (r EvalTableColumnNewParamsDatasetFieldsSource) IsKnown() bool {
	switch r {
	case EvalTableColumnNewParamsDatasetFieldsSourceInput, EvalTableColumnNewParamsDatasetFieldsSourceOutput:
		return true
	}
	return false
}

// JSON type accepted by this column. Use json for ordinary JSON fields and for
// media extension values.
type EvalTableColumnNewParamsDatasetFieldsValueType string

const (
	EvalTableColumnNewParamsDatasetFieldsValueTypeBoolean EvalTableColumnNewParamsDatasetFieldsValueType = "boolean"
	EvalTableColumnNewParamsDatasetFieldsValueTypeInteger EvalTableColumnNewParamsDatasetFieldsValueType = "integer"
	EvalTableColumnNewParamsDatasetFieldsValueTypeNumber  EvalTableColumnNewParamsDatasetFieldsValueType = "number"
	EvalTableColumnNewParamsDatasetFieldsValueTypeString  EvalTableColumnNewParamsDatasetFieldsValueType = "string"
	EvalTableColumnNewParamsDatasetFieldsValueTypeJson    EvalTableColumnNewParamsDatasetFieldsValueType = "json"
)

func (r EvalTableColumnNewParamsDatasetFieldsValueType) IsKnown() bool {
	switch r {
	case EvalTableColumnNewParamsDatasetFieldsValueTypeBoolean,
		EvalTableColumnNewParamsDatasetFieldsValueTypeInteger,
		EvalTableColumnNewParamsDatasetFieldsValueTypeNumber,
		EvalTableColumnNewParamsDatasetFieldsValueTypeString,
		EvalTableColumnNewParamsDatasetFieldsValueTypeJson:
		return true
	}
	return false
}

// Media format stored in this field. Set together with extension_schema_version.
// Omit both for an ordinary field.
type EvalTableColumnNewParamsDatasetFieldsExtensionType string

const (
	EvalTableColumnNewParamsDatasetFieldsExtensionTypeWandbImage    EvalTableColumnNewParamsDatasetFieldsExtensionType = "wandb-image"
	EvalTableColumnNewParamsDatasetFieldsExtensionTypeWandbAudio    EvalTableColumnNewParamsDatasetFieldsExtensionType = "wandb-audio"
	EvalTableColumnNewParamsDatasetFieldsExtensionTypeWandbVideo    EvalTableColumnNewParamsDatasetFieldsExtensionType = "wandb-video"
	EvalTableColumnNewParamsDatasetFieldsExtensionTypeWandbHTML     EvalTableColumnNewParamsDatasetFieldsExtensionType = "wandb-html"
	EvalTableColumnNewParamsDatasetFieldsExtensionTypeWandbBokeh    EvalTableColumnNewParamsDatasetFieldsExtensionType = "wandb-bokeh"
	EvalTableColumnNewParamsDatasetFieldsExtensionTypeWandbObject3d EvalTableColumnNewParamsDatasetFieldsExtensionType = "wandb-object3d"
	EvalTableColumnNewParamsDatasetFieldsExtensionTypeWandbMolecule EvalTableColumnNewParamsDatasetFieldsExtensionType = "wandb-molecule"
)

func (r EvalTableColumnNewParamsDatasetFieldsExtensionType) IsKnown() bool {
	switch r {
	case EvalTableColumnNewParamsDatasetFieldsExtensionTypeWandbImage,
		EvalTableColumnNewParamsDatasetFieldsExtensionTypeWandbAudio,
		EvalTableColumnNewParamsDatasetFieldsExtensionTypeWandbVideo,
		EvalTableColumnNewParamsDatasetFieldsExtensionTypeWandbHTML,
		EvalTableColumnNewParamsDatasetFieldsExtensionTypeWandbBokeh,
		EvalTableColumnNewParamsDatasetFieldsExtensionTypeWandbObject3d,
		EvalTableColumnNewParamsDatasetFieldsExtensionTypeWandbMolecule:
		return true
	}
	return false
}

type EvalTableColumnNewParamsScorer struct {
	// Name used as a key in each row's scores object. Leading and trailing whitespace
	// are not allowed.
	Name      param.Field[string]                                   `json:"name"       api:"required"`
	ValueType param.Field[EvalTableColumnNewParamsScorersValueType] `json:"value_type" api:"required"`
}

func (r EvalTableColumnNewParamsScorer) MarshalJSON() (data []byte, err error) {
	return apijson.MarshalRoot(r)
}

type EvalTableColumnNewParamsScorersValueType string

const (
	EvalTableColumnNewParamsScorersValueTypeBoolean EvalTableColumnNewParamsScorersValueType = "boolean"
	EvalTableColumnNewParamsScorersValueTypeInteger EvalTableColumnNewParamsScorersValueType = "integer"
	EvalTableColumnNewParamsScorersValueTypeNumber  EvalTableColumnNewParamsScorersValueType = "number"
	EvalTableColumnNewParamsScorersValueTypeString  EvalTableColumnNewParamsScorersValueType = "string"
)

func (r EvalTableColumnNewParamsScorersValueType) IsKnown() bool {
	switch r {
	case EvalTableColumnNewParamsScorersValueTypeBoolean,
		EvalTableColumnNewParamsScorersValueTypeInteger,
		EvalTableColumnNewParamsScorersValueTypeNumber,
		EvalTableColumnNewParamsScorersValueTypeString:
		return true
	}
	return false
}
