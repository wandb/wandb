// File generated from our OpenAPI spec by Stainless.

package cwevals

import (
	"context"
	"errors"
	"fmt"
	"net/http"
	"net/url"
	"slices"
	"time"

	"github.com/wandb/cwevals-go/internal/apijson"
	"github.com/wandb/cwevals-go/internal/apiquery"
	"github.com/wandb/cwevals-go/internal/param"
	"github.com/wandb/cwevals-go/internal/requestconfig"
	"github.com/wandb/cwevals-go/option"
)

// DatasetService contains methods and other services that help with interacting
// with the CoreWeave Evaluations API.
//
// Note, unlike clients, this service does not read variables from the environment
// automatically. You should not instantiate this service directly, and instead use
// the [NewDatasetService] method instead.
type DatasetService struct {
	Options      []option.RequestOption
	Cases        *DatasetCaseService
	Fields       *DatasetFieldService
	Versions     *DatasetVersionService
	Trajectories *DatasetTrajectoryService
}

// NewDatasetService generates a new service that applies the given options to each
// request. These options are applied after the parent client's options (if there
// is one), and before any request-specific options.
func NewDatasetService(opts ...option.RequestOption) (r *DatasetService) {
	r = &DatasetService{}
	r.Options = opts
	r.Cases = NewDatasetCaseService(opts...)
	r.Fields = NewDatasetFieldService(opts...)
	r.Versions = NewDatasetVersionService(opts...)
	r.Trajectories = NewDatasetTrajectoryService(opts...)
	return
}

// Creates a named collection for cases and an empty, pending first version. Add
// cases to the dataset, then create a dataset version when you need a reproducible
// snapshot.
//
// Request bodies must be at most 1 MiB. Bodies larger than the limit are rejected
// with 413 Request Entity Too Large.
func (r *DatasetService) New(
	ctx context.Context,
	params DatasetNewParams,
	opts ...option.RequestOption,
) (res *DatasetNewResponse, err error) {
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
	path := fmt.Sprintf("v1/namespaces/%s/scopes/%s/datasets", params.Namespace, params.ScopeID)
	err = requestconfig.ExecuteNewRequest(ctx, http.MethodPost, path, params, &res, opts...)
	return res, err
}

// Replaces the Dataset's name, attributes, or both. Omitted fields keep their
// values, and attributes are replaced as a whole object. A body without either
// field is rejected. Versions, Cases, and the head version are unchanged, so the
// ETag stays the same. Concurrent updates are last-writer-wins. A retry with the
// same Idempotency-Key replays the first response.
//
// Request bodies must be at most 1 MiB. Bodies larger than the limit are rejected
// with 413 Request Entity Too Large.
func (r *DatasetService) Update(
	ctx context.Context,
	datasetID string,
	params DatasetUpdateParams,
	opts ...option.RequestOption,
) (res *DatasetUpdateResponse, err error) {
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
	if datasetID == "" {
		err = errors.New("missing required dataset_id parameter")
		return nil, err
	}
	path := fmt.Sprintf("v1/namespaces/%s/scopes/%s/datasets/%s", params.Namespace, params.ScopeID, datasetID)
	err = requestconfig.ExecuteNewRequest(ctx, http.MethodPatch, path, params, &res, opts...)
	return res, err
}

// Pages the scope's Datasets, including those EvalTables created, in ID order. IDs
// are time-ordered, so the order approximates creation order. A scope without
// Datasets returns an empty page.
func (r *DatasetService) List(
	ctx context.Context,
	params DatasetListParams,
	opts ...option.RequestOption,
) (res *DatasetListResponse, err error) {
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
	path := fmt.Sprintf("v1/namespaces/%s/scopes/%s/datasets", params.Namespace, params.ScopeID)
	err = requestconfig.ExecuteNewRequest(ctx, http.MethodGet, path, params, &res, opts...)
	return res, err
}

// Soft-deletes the Dataset. It, its DatasetVersions, their Cases pages, and their
// fields then return 404, and writes to them are rejected with 404. A Dataset that
// an Evaluation or EvalTable still sources returns 409 resource_in_use. Delete
// those Evaluations first. Cases stay readable by ID, and Comparisons and Scores
// are unchanged. An absent or already deleted Dataset returns 404. A retry with
// the same Idempotency-Key replays the first response.
func (r *DatasetService) Delete(
	ctx context.Context,
	datasetID string,
	body DatasetDeleteParams,
	opts ...option.RequestOption,
) (err error) {
	opts = slices.Concat(r.Options, opts)
	opts = append([]option.RequestOption{option.WithHeader("Accept", "*/*")}, opts...)
	precfg, err := requestconfig.PreRequestOptions(opts...)
	if err != nil {
		return err
	}
	requestconfig.UseDefaultParam(&body.Namespace, precfg.Namespace)
	requestconfig.UseDefaultParam(&body.ScopeID, precfg.ScopeID)
	if body.Namespace.Value == "" {
		err = errors.New("missing required namespace parameter")
		return err
	}
	if body.ScopeID.Value == "" {
		err = errors.New("missing required scope_id parameter")
		return err
	}
	if datasetID == "" {
		err = errors.New("missing required dataset_id parameter")
		return err
	}
	path := fmt.Sprintf("v1/namespaces/%s/scopes/%s/datasets/%s", body.Namespace, body.ScopeID, datasetID)
	err = requestconfig.ExecuteNewRequest(ctx, http.MethodDelete, path, nil, nil, opts...)
	return err
}

// Returns the dataset metadata and the ID of its current pending version in
// `head_version_id`. The response `ETag` contains the same version ID.
func (r *DatasetService) Get(
	ctx context.Context,
	datasetID string,
	query DatasetGetParams,
	opts ...option.RequestOption,
) (res *DatasetGetResponse, err error) {
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
	if datasetID == "" {
		err = errors.New("missing required dataset_id parameter")
		return nil, err
	}
	path := fmt.Sprintf("v1/namespaces/%s/scopes/%s/datasets/%s", query.Namespace, query.ScopeID, datasetID)
	err = requestconfig.ExecuteNewRequest(ctx, http.MethodGet, path, nil, &res, opts...)
	return res, err
}

// A value in a top-level Case input or output field.
type CaseFieldValueParam struct {
	ExtensionType param.Field[CaseFieldValueExtensionType] `json:"extension_type" api:"required"`
	SchemaVersion param.Field[CaseFieldValueSchemaVersion] `json:"schema_version" api:"required"`
	Sha256        param.Field[string]                      `json:"sha256"         api:"required"`
	Size          param.Field[int64]                       `json:"size"           api:"required"`
	// Row comparison across EvaluationVersions ignores this property.
	Uri         param.Field[string]                    `json:"uri"           api:"required"`
	WbMediaType param.Field[CaseFieldValueWbMediaType] `json:"wb_media_type" api:"required"`
	Boxes       param.Field[interface{}]               `json:"boxes"`
	Caption     param.Field[string]                    `json:"caption"`
	Format      param.Field[string]                    `json:"format"`
	Height      param.Field[int64]                     `json:"height"`
	Masks       param.Field[interface{}]               `json:"masks"`
	Width       param.Field[int64]                     `json:"width"`
}

func (r CaseFieldValueParam) MarshalJSON() (data []byte, err error) {
	return apijson.MarshalRoot(r)
}

func (r CaseFieldValueParam) ImplementsCaseFieldValueUnionParam() {}

// A value in a top-level Case input or output field.
//
// Satisfied by [WandbImageV1Param], [WandbAudioV1Param], [WandbVideoV1Param],
// [WandbHTMLV1Param], [WandbBokehV1Param], [WandbObject3dV1Param],
// [WandbMoleculeV1Param], [shared.UnionBool], [shared.UnionFloat],
// [shared.UnionString], [CaseFieldValueArrayParam], [CaseFieldValueMapParam],
// [CaseFieldValueParam].
//
// Use [Raw()] to specify an arbitrary value for this param
type CaseFieldValueUnionParam interface {
	ImplementsCaseFieldValueUnionParam()
}

type CaseFieldValueArrayParam []interface{}

func (r CaseFieldValueArrayParam) ImplementsCaseFieldValueUnionParam() {}

type CaseFieldValueMapParam map[string]interface{}

func (r CaseFieldValueMapParam) ImplementsCaseFieldValueUnionParam() {}

type CaseFieldValueExtensionType string

const (
	CaseFieldValueExtensionTypeWandbImage    CaseFieldValueExtensionType = "wandb-image"
	CaseFieldValueExtensionTypeWandbAudio    CaseFieldValueExtensionType = "wandb-audio"
	CaseFieldValueExtensionTypeWandbVideo    CaseFieldValueExtensionType = "wandb-video"
	CaseFieldValueExtensionTypeWandbHTML     CaseFieldValueExtensionType = "wandb-html"
	CaseFieldValueExtensionTypeWandbBokeh    CaseFieldValueExtensionType = "wandb-bokeh"
	CaseFieldValueExtensionTypeWandbObject3d CaseFieldValueExtensionType = "wandb-object3d"
	CaseFieldValueExtensionTypeWandbMolecule CaseFieldValueExtensionType = "wandb-molecule"
)

func (r CaseFieldValueExtensionType) IsKnown() bool {
	switch r {
	case CaseFieldValueExtensionTypeWandbImage,
		CaseFieldValueExtensionTypeWandbAudio,
		CaseFieldValueExtensionTypeWandbVideo,
		CaseFieldValueExtensionTypeWandbHTML,
		CaseFieldValueExtensionTypeWandbBokeh,
		CaseFieldValueExtensionTypeWandbObject3d,
		CaseFieldValueExtensionTypeWandbMolecule:
		return true
	}
	return false
}

type CaseFieldValueSchemaVersion int64

const (
	CaseFieldValueSchemaVersion1 CaseFieldValueSchemaVersion = 1
)

func (r CaseFieldValueSchemaVersion) IsKnown() bool {
	switch r {
	case CaseFieldValueSchemaVersion1:
		return true
	}
	return false
}

type CaseFieldValueWbMediaType string

const (
	CaseFieldValueWbMediaTypeImageFile    CaseFieldValueWbMediaType = "image-file"
	CaseFieldValueWbMediaTypeAudioFile    CaseFieldValueWbMediaType = "audio-file"
	CaseFieldValueWbMediaTypeVideoFile    CaseFieldValueWbMediaType = "video-file"
	CaseFieldValueWbMediaTypeHTMLFile     CaseFieldValueWbMediaType = "html-file"
	CaseFieldValueWbMediaTypeBokehFile    CaseFieldValueWbMediaType = "bokeh-file"
	CaseFieldValueWbMediaTypeObject3DFile CaseFieldValueWbMediaType = "object3D-file"
	CaseFieldValueWbMediaTypeMoleculeFile CaseFieldValueWbMediaType = "molecule-file"
)

func (r CaseFieldValueWbMediaType) IsKnown() bool {
	switch r {
	case CaseFieldValueWbMediaTypeImageFile,
		CaseFieldValueWbMediaTypeAudioFile,
		CaseFieldValueWbMediaTypeVideoFile,
		CaseFieldValueWbMediaTypeHTMLFile,
		CaseFieldValueWbMediaTypeBokehFile,
		CaseFieldValueWbMediaTypeObject3DFile,
		CaseFieldValueWbMediaTypeMoleculeFile:
		return true
	}
	return false
}

// A Case input or output value.
//
// Satisfied by [CaseValueMapParam], [shared.UnionBool], [shared.UnionFloat],
// [shared.UnionString], [CaseValueArrayParam].
type CaseValueUnionParam interface {
	ImplementsCaseValueUnionParam()
}

type CaseValueMapParam map[string]CaseFieldValueUnionParam

func (r CaseValueMapParam) ImplementsCaseValueUnionParam() {}

type CaseValueArrayParam []interface{}

func (r CaseValueArrayParam) ImplementsCaseValueUnionParam() {}

// A V1 W&B audio value in an evaluation input or output field. Row comparison
// across EvaluationVersions matches this value by every property except `uri`. An
// empty optional property matches a missing one.
type WandbAudioV1Param struct {
	ExtensionType param.Field[WandbAudioV1ExtensionType] `json:"extension_type" api:"required"`
	SchemaVersion param.Field[WandbAudioV1SchemaVersion] `json:"schema_version" api:"required"`
	Sha256        param.Field[string]                    `json:"sha256"         api:"required"`
	Size          param.Field[int64]                     `json:"size"           api:"required"`
	// Row comparison across EvaluationVersions ignores this property.
	Uri         param.Field[string]                  `json:"uri"           api:"required"`
	WbMediaType param.Field[WandbAudioV1WbMediaType] `json:"wb_media_type" api:"required"`
	Caption     param.Field[string]                  `json:"caption"`
	ExtraFields map[string]interface{}               `json:"-,extras"`
}

func (r WandbAudioV1Param) MarshalJSON() (data []byte, err error) {
	return apijson.MarshalRoot(r)
}

func (r WandbAudioV1Param) ImplementsCaseFieldValueUnionParam() {}

type WandbAudioV1ExtensionType string

const (
	WandbAudioV1ExtensionTypeWandbAudio WandbAudioV1ExtensionType = "wandb-audio"
)

func (r WandbAudioV1ExtensionType) IsKnown() bool {
	switch r {
	case WandbAudioV1ExtensionTypeWandbAudio:
		return true
	}
	return false
}

type WandbAudioV1SchemaVersion int64

const (
	WandbAudioV1SchemaVersion1 WandbAudioV1SchemaVersion = 1
)

func (r WandbAudioV1SchemaVersion) IsKnown() bool {
	switch r {
	case WandbAudioV1SchemaVersion1:
		return true
	}
	return false
}

type WandbAudioV1WbMediaType string

const (
	WandbAudioV1WbMediaTypeAudioFile WandbAudioV1WbMediaType = "audio-file"
)

func (r WandbAudioV1WbMediaType) IsKnown() bool {
	switch r {
	case WandbAudioV1WbMediaTypeAudioFile:
		return true
	}
	return false
}

// A V1 W&B Bokeh value in an evaluation input or output field. Row comparison
// across EvaluationVersions matches this value by every property except `uri`. An
// empty optional property matches a missing one.
type WandbBokehV1Param struct {
	ExtensionType param.Field[WandbBokehV1ExtensionType] `json:"extension_type" api:"required"`
	SchemaVersion param.Field[WandbBokehV1SchemaVersion] `json:"schema_version" api:"required"`
	Sha256        param.Field[string]                    `json:"sha256"         api:"required"`
	Size          param.Field[int64]                     `json:"size"           api:"required"`
	// W&B run-file or artifact reference only. Row comparison across
	// EvaluationVersions ignores this property.
	Uri         param.Field[string]                  `json:"uri"           api:"required" format:"uri"`
	WbMediaType param.Field[WandbBokehV1WbMediaType] `json:"wb_media_type" api:"required"`
	Caption     param.Field[string]                  `json:"caption"`
	ExtraFields map[string]interface{}               `json:"-,extras"`
}

func (r WandbBokehV1Param) MarshalJSON() (data []byte, err error) {
	return apijson.MarshalRoot(r)
}

func (r WandbBokehV1Param) ImplementsCaseFieldValueUnionParam() {}

type WandbBokehV1ExtensionType string

const (
	WandbBokehV1ExtensionTypeWandbBokeh WandbBokehV1ExtensionType = "wandb-bokeh"
)

func (r WandbBokehV1ExtensionType) IsKnown() bool {
	switch r {
	case WandbBokehV1ExtensionTypeWandbBokeh:
		return true
	}
	return false
}

type WandbBokehV1SchemaVersion int64

const (
	WandbBokehV1SchemaVersion1 WandbBokehV1SchemaVersion = 1
)

func (r WandbBokehV1SchemaVersion) IsKnown() bool {
	switch r {
	case WandbBokehV1SchemaVersion1:
		return true
	}
	return false
}

type WandbBokehV1WbMediaType string

const (
	WandbBokehV1WbMediaTypeBokehFile WandbBokehV1WbMediaType = "bokeh-file"
)

func (r WandbBokehV1WbMediaType) IsKnown() bool {
	switch r {
	case WandbBokehV1WbMediaTypeBokehFile:
		return true
	}
	return false
}

// A V1 W&B HTML value in an evaluation input or output field. Row comparison
// across EvaluationVersions matches this value by every property except `uri`. An
// empty optional property matches a missing one.
type WandbHTMLV1Param struct {
	ExtensionType param.Field[WandbHTMLV1ExtensionType] `json:"extension_type" api:"required"`
	SchemaVersion param.Field[WandbHTMLV1SchemaVersion] `json:"schema_version" api:"required"`
	Sha256        param.Field[string]                   `json:"sha256"         api:"required"`
	Size          param.Field[int64]                    `json:"size"           api:"required"`
	// W&B run-file or artifact reference only. Row comparison across
	// EvaluationVersions ignores this property.
	Uri         param.Field[string]                 `json:"uri"           api:"required" format:"uri"`
	WbMediaType param.Field[WandbHTMLV1WbMediaType] `json:"wb_media_type" api:"required"`
	Caption     param.Field[string]                 `json:"caption"`
	ExtraFields map[string]interface{}              `json:"-,extras"`
}

func (r WandbHTMLV1Param) MarshalJSON() (data []byte, err error) {
	return apijson.MarshalRoot(r)
}

func (r WandbHTMLV1Param) ImplementsCaseFieldValueUnionParam() {}

type WandbHTMLV1ExtensionType string

const (
	WandbHTMLV1ExtensionTypeWandbHTML WandbHTMLV1ExtensionType = "wandb-html"
)

func (r WandbHTMLV1ExtensionType) IsKnown() bool {
	switch r {
	case WandbHTMLV1ExtensionTypeWandbHTML:
		return true
	}
	return false
}

type WandbHTMLV1SchemaVersion int64

const (
	WandbHTMLV1SchemaVersion1 WandbHTMLV1SchemaVersion = 1
)

func (r WandbHTMLV1SchemaVersion) IsKnown() bool {
	switch r {
	case WandbHTMLV1SchemaVersion1:
		return true
	}
	return false
}

type WandbHTMLV1WbMediaType string

const (
	WandbHTMLV1WbMediaTypeHTMLFile WandbHTMLV1WbMediaType = "html-file"
)

func (r WandbHTMLV1WbMediaType) IsKnown() bool {
	switch r {
	case WandbHTMLV1WbMediaTypeHTMLFile:
		return true
	}
	return false
}

// A file of 2D bounding boxes drawn over a W&B image. Row comparison across
// EvaluationVersions matches this value by every property except `uri`. An empty
// optional property matches a missing one.
type WandbImageBoxesV1Param struct {
	Sha256 param.Field[string] `json:"sha256" api:"required"`
	Size   param.Field[int64]  `json:"size"   api:"required"`
	// Row comparison across EvaluationVersions ignores this property.
	Uri         param.Field[string]                 `json:"uri"      api:"required"`
	Type        param.Field[WandbImageBoxesV1_Type] `json:"_type"`
	ExtraFields map[string]interface{}              `json:"-,extras"`
}

func (r WandbImageBoxesV1Param) MarshalJSON() (data []byte, err error) {
	return apijson.MarshalRoot(r)
}

type WandbImageBoxesV1_Type string

const (
	WandbImageBoxesV1_TypeBoxes2D WandbImageBoxesV1_Type = "boxes2D"
)

func (r WandbImageBoxesV1_Type) IsKnown() bool {
	switch r {
	case WandbImageBoxesV1_TypeBoxes2D:
		return true
	}
	return false
}

// A segmentation mask file drawn over a W&B image. Row comparison across
// EvaluationVersions matches this value by every property except `uri`. An empty
// optional property matches a missing one.
type WandbImageMaskV1Param struct {
	Sha256 param.Field[string] `json:"sha256" api:"required"`
	Size   param.Field[int64]  `json:"size"   api:"required"`
	// Row comparison across EvaluationVersions ignores this property.
	Uri         param.Field[string]                `json:"uri"      api:"required"`
	Type        param.Field[WandbImageMaskV1_Type] `json:"_type"`
	ExtraFields map[string]interface{}             `json:"-,extras"`
}

func (r WandbImageMaskV1Param) MarshalJSON() (data []byte, err error) {
	return apijson.MarshalRoot(r)
}

type WandbImageMaskV1_Type string

const (
	WandbImageMaskV1_TypeMask WandbImageMaskV1_Type = "mask"
)

func (r WandbImageMaskV1_Type) IsKnown() bool {
	switch r {
	case WandbImageMaskV1_TypeMask:
		return true
	}
	return false
}

// A V1 W&B image value in an evaluation input or output field. Row comparison
// across EvaluationVersions matches this value by every property except `uri`. An
// empty optional property matches a missing one.
type WandbImageV1Param struct {
	ExtensionType param.Field[WandbImageV1ExtensionType] `json:"extension_type" api:"required"`
	Format        param.Field[string]                    `json:"format"         api:"required"`
	SchemaVersion param.Field[WandbImageV1SchemaVersion] `json:"schema_version" api:"required"`
	Sha256        param.Field[string]                    `json:"sha256"         api:"required"`
	Size          param.Field[int64]                     `json:"size"           api:"required"`
	// Row comparison across EvaluationVersions ignores this property.
	Uri         param.Field[string]                            `json:"uri"           api:"required"`
	WbMediaType param.Field[WandbImageV1WbMediaType]           `json:"wb_media_type" api:"required"`
	Boxes       param.Field[map[string]WandbImageBoxesV1Param] `json:"boxes"`
	Caption     param.Field[string]                            `json:"caption"`
	Height      param.Field[int64]                             `json:"height"`
	Masks       param.Field[map[string]WandbImageMaskV1Param]  `json:"masks"`
	Width       param.Field[int64]                             `json:"width"`
	ExtraFields map[string]interface{}                         `json:"-,extras"`
}

func (r WandbImageV1Param) MarshalJSON() (data []byte, err error) {
	return apijson.MarshalRoot(r)
}

func (r WandbImageV1Param) ImplementsCaseFieldValueUnionParam() {}

type WandbImageV1ExtensionType string

const (
	WandbImageV1ExtensionTypeWandbImage WandbImageV1ExtensionType = "wandb-image"
)

func (r WandbImageV1ExtensionType) IsKnown() bool {
	switch r {
	case WandbImageV1ExtensionTypeWandbImage:
		return true
	}
	return false
}

type WandbImageV1SchemaVersion int64

const (
	WandbImageV1SchemaVersion1 WandbImageV1SchemaVersion = 1
)

func (r WandbImageV1SchemaVersion) IsKnown() bool {
	switch r {
	case WandbImageV1SchemaVersion1:
		return true
	}
	return false
}

type WandbImageV1WbMediaType string

const (
	WandbImageV1WbMediaTypeImageFile WandbImageV1WbMediaType = "image-file"
)

func (r WandbImageV1WbMediaType) IsKnown() bool {
	switch r {
	case WandbImageV1WbMediaTypeImageFile:
		return true
	}
	return false
}

// A V1 W&B Molecule value in an evaluation input or output field. Row comparison
// across EvaluationVersions matches this value by every property except `uri`. An
// empty optional property matches a missing one.
type WandbMoleculeV1Param struct {
	ExtensionType param.Field[WandbMoleculeV1ExtensionType] `json:"extension_type" api:"required"`
	SchemaVersion param.Field[WandbMoleculeV1SchemaVersion] `json:"schema_version" api:"required"`
	Sha256        param.Field[string]                       `json:"sha256"         api:"required"`
	Size          param.Field[int64]                        `json:"size"           api:"required"`
	// W&B run-file or artifact reference only. Row comparison across
	// EvaluationVersions ignores this property.
	Uri         param.Field[string]                     `json:"uri"           api:"required" format:"uri"`
	WbMediaType param.Field[WandbMoleculeV1WbMediaType] `json:"wb_media_type" api:"required"`
	Caption     param.Field[string]                     `json:"caption"`
	ExtraFields map[string]interface{}                  `json:"-,extras"`
}

func (r WandbMoleculeV1Param) MarshalJSON() (data []byte, err error) {
	return apijson.MarshalRoot(r)
}

func (r WandbMoleculeV1Param) ImplementsCaseFieldValueUnionParam() {}

type WandbMoleculeV1ExtensionType string

const (
	WandbMoleculeV1ExtensionTypeWandbMolecule WandbMoleculeV1ExtensionType = "wandb-molecule"
)

func (r WandbMoleculeV1ExtensionType) IsKnown() bool {
	switch r {
	case WandbMoleculeV1ExtensionTypeWandbMolecule:
		return true
	}
	return false
}

type WandbMoleculeV1SchemaVersion int64

const (
	WandbMoleculeV1SchemaVersion1 WandbMoleculeV1SchemaVersion = 1
)

func (r WandbMoleculeV1SchemaVersion) IsKnown() bool {
	switch r {
	case WandbMoleculeV1SchemaVersion1:
		return true
	}
	return false
}

type WandbMoleculeV1WbMediaType string

const (
	WandbMoleculeV1WbMediaTypeMoleculeFile WandbMoleculeV1WbMediaType = "molecule-file"
)

func (r WandbMoleculeV1WbMediaType) IsKnown() bool {
	switch r {
	case WandbMoleculeV1WbMediaTypeMoleculeFile:
		return true
	}
	return false
}

// A V1 W&B Object3D value in an evaluation input or output field. Row comparison
// across EvaluationVersions matches this value by every property except `uri`. An
// empty optional property matches a missing one.
type WandbObject3dV1Param struct {
	ExtensionType param.Field[WandbObject3dV1ExtensionType] `json:"extension_type" api:"required"`
	SchemaVersion param.Field[WandbObject3dV1SchemaVersion] `json:"schema_version" api:"required"`
	Sha256        param.Field[string]                       `json:"sha256"         api:"required"`
	Size          param.Field[int64]                        `json:"size"           api:"required"`
	// W&B run-file or artifact reference only. Row comparison across
	// EvaluationVersions ignores this property.
	Uri         param.Field[string]                     `json:"uri"           api:"required" format:"uri"`
	WbMediaType param.Field[WandbObject3dV1WbMediaType] `json:"wb_media_type" api:"required"`
	Caption     param.Field[string]                     `json:"caption"`
	ExtraFields map[string]interface{}                  `json:"-,extras"`
}

func (r WandbObject3dV1Param) MarshalJSON() (data []byte, err error) {
	return apijson.MarshalRoot(r)
}

func (r WandbObject3dV1Param) ImplementsCaseFieldValueUnionParam() {}

type WandbObject3dV1ExtensionType string

const (
	WandbObject3dV1ExtensionTypeWandbObject3d WandbObject3dV1ExtensionType = "wandb-object3d"
)

func (r WandbObject3dV1ExtensionType) IsKnown() bool {
	switch r {
	case WandbObject3dV1ExtensionTypeWandbObject3d:
		return true
	}
	return false
}

type WandbObject3dV1SchemaVersion int64

const (
	WandbObject3dV1SchemaVersion1 WandbObject3dV1SchemaVersion = 1
)

func (r WandbObject3dV1SchemaVersion) IsKnown() bool {
	switch r {
	case WandbObject3dV1SchemaVersion1:
		return true
	}
	return false
}

type WandbObject3dV1WbMediaType string

const (
	WandbObject3dV1WbMediaTypeObject3DFile WandbObject3dV1WbMediaType = "object3D-file"
)

func (r WandbObject3dV1WbMediaType) IsKnown() bool {
	switch r {
	case WandbObject3dV1WbMediaTypeObject3DFile:
		return true
	}
	return false
}

// A V1 W&B video value in an evaluation input or output field. Row comparison
// across EvaluationVersions matches this value by every property except `uri`. An
// empty optional property matches a missing one.
type WandbVideoV1Param struct {
	ExtensionType param.Field[WandbVideoV1ExtensionType] `json:"extension_type" api:"required"`
	SchemaVersion param.Field[WandbVideoV1SchemaVersion] `json:"schema_version" api:"required"`
	Sha256        param.Field[string]                    `json:"sha256"         api:"required"`
	Size          param.Field[int64]                     `json:"size"           api:"required"`
	// Row comparison across EvaluationVersions ignores this property.
	Uri         param.Field[string]                  `json:"uri"           api:"required"`
	WbMediaType param.Field[WandbVideoV1WbMediaType] `json:"wb_media_type" api:"required"`
	Caption     param.Field[string]                  `json:"caption"`
	Height      param.Field[int64]                   `json:"height"`
	Width       param.Field[int64]                   `json:"width"`
	ExtraFields map[string]interface{}               `json:"-,extras"`
}

func (r WandbVideoV1Param) MarshalJSON() (data []byte, err error) {
	return apijson.MarshalRoot(r)
}

func (r WandbVideoV1Param) ImplementsCaseFieldValueUnionParam() {}

type WandbVideoV1ExtensionType string

const (
	WandbVideoV1ExtensionTypeWandbVideo WandbVideoV1ExtensionType = "wandb-video"
)

func (r WandbVideoV1ExtensionType) IsKnown() bool {
	switch r {
	case WandbVideoV1ExtensionTypeWandbVideo:
		return true
	}
	return false
}

type WandbVideoV1SchemaVersion int64

const (
	WandbVideoV1SchemaVersion1 WandbVideoV1SchemaVersion = 1
)

func (r WandbVideoV1SchemaVersion) IsKnown() bool {
	switch r {
	case WandbVideoV1SchemaVersion1:
		return true
	}
	return false
}

type WandbVideoV1WbMediaType string

const (
	WandbVideoV1WbMediaTypeVideoFile WandbVideoV1WbMediaType = "video-file"
)

func (r WandbVideoV1WbMediaType) IsKnown() bool {
	switch r {
	case WandbVideoV1WbMediaTypeVideoFile:
		return true
	}
	return false
}

type DatasetNewResponse struct {
	Attributes map[string]interface{} `json:"attributes" api:"required"`
	CreatedAt  time.Time              `json:"created_at" api:"required" format:"date-time"`
	DatasetID  string                 `json:"dataset_id" api:"required" format:"uuid"`
	// ID of the current pending dataset version. Publishing this version freezes its
	// contents and opens a new pending version.
	HeadVersionID string `json:"head_version_id" api:"required" format:"uuid"`
	Name          string `json:"name"            api:"required"`
	// Namespace that assigned the scope reference.
	Namespace DatasetNewResponseNamespace `json:"namespace" api:"required"`
	ScopeRef  string                      `json:"scope_ref" api:"required"`
	JSON      datasetNewResponseJSON      `json:"-"`
}

// datasetNewResponseJSON contains the JSON metadata for the struct
// [DatasetNewResponse]
type datasetNewResponseJSON struct {
	Attributes    apijson.Field
	CreatedAt     apijson.Field
	DatasetID     apijson.Field
	HeadVersionID apijson.Field
	Name          apijson.Field
	Namespace     apijson.Field
	ScopeRef      apijson.Field
	raw           string
	ExtraFields   map[string]apijson.Field
}

func (r *DatasetNewResponse) UnmarshalJSON(data []byte) (err error) {
	return apijson.UnmarshalRoot(data, r)
}

func (r datasetNewResponseJSON) RawJSON() string {
	return r.raw
}

// Namespace that assigned the scope reference.
type DatasetNewResponseNamespace string

const (
	DatasetNewResponseNamespaceWandb DatasetNewResponseNamespace = "wandb"
)

func (r DatasetNewResponseNamespace) IsKnown() bool {
	switch r {
	case DatasetNewResponseNamespaceWandb:
		return true
	}
	return false
}

type DatasetUpdateResponse struct {
	Attributes map[string]interface{} `json:"attributes" api:"required"`
	CreatedAt  time.Time              `json:"created_at" api:"required" format:"date-time"`
	DatasetID  string                 `json:"dataset_id" api:"required" format:"uuid"`
	// ID of the current pending dataset version. Publishing this version freezes its
	// contents and opens a new pending version.
	HeadVersionID string `json:"head_version_id" api:"required" format:"uuid"`
	Name          string `json:"name"            api:"required"`
	// Namespace that assigned the scope reference.
	Namespace DatasetUpdateResponseNamespace `json:"namespace" api:"required"`
	ScopeRef  string                         `json:"scope_ref" api:"required"`
	JSON      datasetUpdateResponseJSON      `json:"-"`
}

// datasetUpdateResponseJSON contains the JSON metadata for the struct
// [DatasetUpdateResponse]
type datasetUpdateResponseJSON struct {
	Attributes    apijson.Field
	CreatedAt     apijson.Field
	DatasetID     apijson.Field
	HeadVersionID apijson.Field
	Name          apijson.Field
	Namespace     apijson.Field
	ScopeRef      apijson.Field
	raw           string
	ExtraFields   map[string]apijson.Field
}

func (r *DatasetUpdateResponse) UnmarshalJSON(data []byte) (err error) {
	return apijson.UnmarshalRoot(data, r)
}

func (r datasetUpdateResponseJSON) RawJSON() string {
	return r.raw
}

// Namespace that assigned the scope reference.
type DatasetUpdateResponseNamespace string

const (
	DatasetUpdateResponseNamespaceWandb DatasetUpdateResponseNamespace = "wandb"
)

func (r DatasetUpdateResponseNamespace) IsKnown() bool {
	switch r {
	case DatasetUpdateResponseNamespaceWandb:
		return true
	}
	return false
}

type DatasetListResponse struct {
	Datasets   []DatasetListResponseDataset `json:"datasets"    api:"required"`
	NextCursor string                       `json:"next_cursor"`
	JSON       datasetListResponseJSON      `json:"-"`
}

// datasetListResponseJSON contains the JSON metadata for the struct
// [DatasetListResponse]
type datasetListResponseJSON struct {
	Datasets    apijson.Field
	NextCursor  apijson.Field
	raw         string
	ExtraFields map[string]apijson.Field
}

func (r *DatasetListResponse) UnmarshalJSON(data []byte) (err error) {
	return apijson.UnmarshalRoot(data, r)
}

func (r datasetListResponseJSON) RawJSON() string {
	return r.raw
}

type DatasetListResponseDataset struct {
	Attributes map[string]interface{} `json:"attributes" api:"required"`
	CreatedAt  time.Time              `json:"created_at" api:"required" format:"date-time"`
	DatasetID  string                 `json:"dataset_id" api:"required" format:"uuid"`
	// ID of the current pending dataset version. Publishing this version freezes its
	// contents and opens a new pending version.
	HeadVersionID string `json:"head_version_id" api:"required" format:"uuid"`
	Name          string `json:"name"            api:"required"`
	// Namespace that assigned the scope reference.
	Namespace DatasetListResponseDatasetsNamespace `json:"namespace" api:"required"`
	ScopeRef  string                               `json:"scope_ref" api:"required"`
	JSON      datasetListResponseDatasetJSON       `json:"-"`
}

// datasetListResponseDatasetJSON contains the JSON metadata for the struct
// [DatasetListResponseDataset]
type datasetListResponseDatasetJSON struct {
	Attributes    apijson.Field
	CreatedAt     apijson.Field
	DatasetID     apijson.Field
	HeadVersionID apijson.Field
	Name          apijson.Field
	Namespace     apijson.Field
	ScopeRef      apijson.Field
	raw           string
	ExtraFields   map[string]apijson.Field
}

func (r *DatasetListResponseDataset) UnmarshalJSON(data []byte) (err error) {
	return apijson.UnmarshalRoot(data, r)
}

func (r datasetListResponseDatasetJSON) RawJSON() string {
	return r.raw
}

// Namespace that assigned the scope reference.
type DatasetListResponseDatasetsNamespace string

const (
	DatasetListResponseDatasetsNamespaceWandb DatasetListResponseDatasetsNamespace = "wandb"
)

func (r DatasetListResponseDatasetsNamespace) IsKnown() bool {
	switch r {
	case DatasetListResponseDatasetsNamespaceWandb:
		return true
	}
	return false
}

type DatasetGetResponse struct {
	Attributes map[string]interface{} `json:"attributes" api:"required"`
	CreatedAt  time.Time              `json:"created_at" api:"required" format:"date-time"`
	DatasetID  string                 `json:"dataset_id" api:"required" format:"uuid"`
	// ID of the current pending dataset version. Publishing this version freezes its
	// contents and opens a new pending version.
	HeadVersionID string `json:"head_version_id" api:"required" format:"uuid"`
	Name          string `json:"name"            api:"required"`
	// Namespace that assigned the scope reference.
	Namespace DatasetGetResponseNamespace `json:"namespace" api:"required"`
	ScopeRef  string                      `json:"scope_ref" api:"required"`
	JSON      datasetGetResponseJSON      `json:"-"`
}

// datasetGetResponseJSON contains the JSON metadata for the struct
// [DatasetGetResponse]
type datasetGetResponseJSON struct {
	Attributes    apijson.Field
	CreatedAt     apijson.Field
	DatasetID     apijson.Field
	HeadVersionID apijson.Field
	Name          apijson.Field
	Namespace     apijson.Field
	ScopeRef      apijson.Field
	raw           string
	ExtraFields   map[string]apijson.Field
}

func (r *DatasetGetResponse) UnmarshalJSON(data []byte) (err error) {
	return apijson.UnmarshalRoot(data, r)
}

func (r datasetGetResponseJSON) RawJSON() string {
	return r.raw
}

// Namespace that assigned the scope reference.
type DatasetGetResponseNamespace string

const (
	DatasetGetResponseNamespaceWandb DatasetGetResponseNamespace = "wandb"
)

func (r DatasetGetResponseNamespace) IsKnown() bool {
	switch r {
	case DatasetGetResponseNamespaceWandb:
		return true
	}
	return false
}

type DatasetNewParams struct {
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
	ScopeID    param.Field[string]                 `path:"scope_id" api:"required"`
	Name       param.Field[string]                 `                api:"required" json:"name"`
	Attributes param.Field[map[string]interface{}] `                               json:"attributes"`
	// Location of externally stored data, such as s3://bucket/prefix/ or
	// hf://datasets/org/name. The service stores this URI as metadata and does not
	// read from it. Dataset versions inherit it until you supply a replacement when
	// publishing a version.
	Uri param.Field[string] `json:"uri" format:"uri"`
}

func (r DatasetNewParams) MarshalJSON() (data []byte, err error) {
	return apijson.MarshalRoot(r)
}

type DatasetUpdateParams struct {
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
	// Replaces the attributes as a whole object. Omit to keep them.
	Attributes param.Field[map[string]interface{}] `json:"attributes"`
	// Replaces the name. Omit to keep it.
	Name param.Field[string] `json:"name"`
}

func (r DatasetUpdateParams) MarshalJSON() (data []byte, err error) {
	return apijson.MarshalRoot(r)
}

type DatasetListParams struct {
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
	// Cursor from the previous page's next_cursor. Omit for the first page.
	Cursor param.Field[string] `query:"cursor"`
	Limit  param.Field[int64]  `query:"limit"`
	// Lists only Datasets with exactly this name. Omit to list every Dataset in the
	// scope.
	Name param.Field[string] `query:"name"`
}

// URLQuery serializes [DatasetListParams]'s query parameters as `url.Values`.
func (r DatasetListParams) URLQuery() (v url.Values) {
	return apiquery.MarshalWithSettings(r, apiquery.QuerySettings{
		ArrayFormat:  apiquery.ArrayQueryFormatComma,
		NestedFormat: apiquery.NestedQueryFormatBrackets,
	})
}

type DatasetDeleteParams struct {
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

type DatasetGetParams struct {
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
