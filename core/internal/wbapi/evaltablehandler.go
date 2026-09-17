package wbapi

import (
	"bytes"
	"context"
	"crypto/tls"
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"net/http"

	coreweaveevaluations "github.com/wandb/core/services/evaluations/generated/go"
	"github.com/wandb/core/services/evaluations/generated/go/option"

	"github.com/wandb/wandb/core/internal/api"
	"github.com/wandb/wandb/core/internal/httplayers"
	"github.com/wandb/wandb/core/internal/settings"
	spb "github.com/wandb/wandb/core/pkg/service_go_proto"
)

// MERGE BLOCKER: The generated CES Go SDK is currently available only from a
// local sibling checkout through the replacement in core/go.mod. Do not merge
// this handler until that module is published and the replacement is removed.

type EvalTableHandler struct {
	httpClient *http.Client
}

func NewEvalTableHandler(
	credentialProvider api.CredentialProvider,
	s *settings.Settings,
) *EvalTableHandler {
	transport := http.DefaultTransport.(*http.Transport).Clone()
	transport.Proxy = s.GetProxyFn()
	transport.ProxyConnectHeader = s.GetProxyConnectHeader()
	if s.IsInsecureDisableSSL() {
		tlsConfig := transport.TLSClientConfig
		if tlsConfig == nil {
			tlsConfig = &tls.Config{}
		} else {
			tlsConfig = tlsConfig.Clone()
		}
		tlsConfig.InsecureSkipVerify = true
		transport.TLSClientConfig = tlsConfig
	}

	return &EvalTableHandler{
		httpClient: &http.Client{
			Transport: httplayers.WrapRoundTripper(
				transport,
				credentialProvider,
			),
		},
	}
}

func (h *EvalTableHandler) HandleRequest(
	ctx context.Context,
	request *spb.EvalTableRequest,
) *spb.ApiResponse {
	if request.GetBaseUrl() == "" {
		return apiErrorResponse("CES base URL is required", 0)
	}
	if request.GetScopeRef() == "" {
		return apiErrorResponse("CES scope reference is required", 0)
	}
	if request.GetIdempotencyKey() == "" {
		return apiErrorResponse("CES idempotency key is required", 0)
	}

	service := coreweaveevaluations.NewEvalTableService(
		option.WithBaseURL(request.GetBaseUrl()),
		option.WithHTTPClient(h.httpClient),
	)
	requestOptions := []option.RequestOption{
		option.WithHeader("Idempotency-Key", request.GetIdempotencyKey()),
	}

	switch operation := request.Operation.(type) {
	case *spb.EvalTableRequest_Create:
		return h.create(ctx, service, request.GetScopeRef(), operation.Create, requestOptions)
	case *spb.EvalTableRequest_CreateColumns:
		return h.createColumns(
			ctx,
			service,
			request.GetScopeRef(),
			operation.CreateColumns,
			requestOptions,
		)
	case *spb.EvalTableRequest_AddRows:
		return h.addRows(ctx, service, request.GetScopeRef(), operation.AddRows, requestOptions)
	case *spb.EvalTableRequest_CreateVersion:
		return h.createVersion(
			ctx,
			service,
			request.GetScopeRef(),
			operation.CreateVersion,
			requestOptions,
		)
	default:
		return apiErrorResponse(
			fmt.Sprintf("unsupported CES EvalTable operation: %T", request.Operation),
			0,
		)
	}
}

func (h *EvalTableHandler) create(
	ctx context.Context,
	service *coreweaveevaluations.EvalTableService,
	scopeRef string,
	request *spb.EvalTableCreateRequest,
	requestOptions []option.RequestOption,
) *spb.ApiResponse {
	result, err := service.New(
		ctx,
		coreweaveevaluations.EvalTableNewParamsNamespaceWandb,
		scopeRef,
		coreweaveevaluations.EvalTableNewParams{
			Name: coreweaveevaluations.F(request.GetName()),
		},
		requestOptions...,
	)
	if err != nil {
		return evalTableErrorResponse("create EvalTable", err)
	}

	return evalTableResponse(&spb.EvalTableResponse{
		EvaluationId: result.EvaluationID,
		DatasetId:    result.DatasetID,
	})
}

type evalTableColumnsBody struct {
	DatasetFields []evalTableDatasetField `json:"dataset_fields"`
	Scorers       []evalTableScorer       `json:"scorers"`
}

type evalTableDatasetField struct {
	Name      string `json:"name"`
	Source    string `json:"source"`
	ValueType string `json:"value_type"`
}

type evalTableScorer struct {
	Name      string `json:"name"`
	ValueType string `json:"value_type"`
}

func (h *EvalTableHandler) createColumns(
	ctx context.Context,
	service *coreweaveevaluations.EvalTableService,
	scopeRef string,
	request *spb.EvalTableCreateColumnsRequest,
	requestOptions []option.RequestOption,
) *spb.ApiResponse {
	var body evalTableColumnsBody
	if err := decodeEvalTableBody(request.GetBodyJson(), &body); err != nil {
		return apiErrorResponse(fmt.Sprintf("decode EvalTable columns: %v", err), 0)
	}

	datasetFields := make(
		[]coreweaveevaluations.EvalTableNewColumnsParamsDatasetField,
		0,
		len(body.DatasetFields),
	)
	for _, field := range body.DatasetFields {
		source := coreweaveevaluations.EvalTableNewColumnsParamsDatasetFieldsSource(field.Source)
		valueType := coreweaveevaluations.EvalTableNewColumnsParamsDatasetFieldsValueType(field.ValueType)
		if !source.IsKnown() || !valueType.IsKnown() {
			return apiErrorResponse(
				fmt.Sprintf("invalid CES Dataset field %q type or source", field.Name),
				0,
			)
		}
		datasetFields = append(
			datasetFields,
			coreweaveevaluations.EvalTableNewColumnsParamsDatasetField{
				Name:      coreweaveevaluations.F(field.Name),
				Source:    coreweaveevaluations.F(source),
				ValueType: coreweaveevaluations.F(valueType),
			},
		)
	}

	scorers := make(
		[]coreweaveevaluations.EvalTableNewColumnsParamsScorer,
		0,
		len(body.Scorers),
	)
	for _, scorer := range body.Scorers {
		valueType := coreweaveevaluations.EvalTableNewColumnsParamsScorersValueType(scorer.ValueType)
		if !valueType.IsKnown() {
			return apiErrorResponse(
				fmt.Sprintf("invalid CES scorer %q type", scorer.Name),
				0,
			)
		}
		scorers = append(
			scorers,
			coreweaveevaluations.EvalTableNewColumnsParamsScorer{
				Name:      coreweaveevaluations.F(scorer.Name),
				ValueType: coreweaveevaluations.F(valueType),
			},
		)
	}

	_, err := service.NewColumns(
		ctx,
		coreweaveevaluations.EvalTableNewColumnsParamsNamespaceWandb,
		scopeRef,
		request.GetEvaluationId(),
		coreweaveevaluations.EvalTableNewColumnsParams{
			DatasetFields: coreweaveevaluations.F(datasetFields),
			Scorers:       coreweaveevaluations.F(scorers),
		},
		requestOptions...,
	)
	if err != nil {
		return evalTableErrorResponse("create EvalTable columns", err)
	}

	return evalTableResponse(&spb.EvalTableResponse{
		EvaluationId: request.GetEvaluationId(),
	})
}

type evalTableRowsBody struct {
	Rows []evalTableRow `json:"rows"`
}

type evalTableRow struct {
	Input  any            `json:"input"`
	Output any            `json:"output"`
	Scores map[string]any `json:"scores"`
}

func (h *EvalTableHandler) addRows(
	ctx context.Context,
	service *coreweaveevaluations.EvalTableService,
	scopeRef string,
	request *spb.EvalTableAddRowsRequest,
	requestOptions []option.RequestOption,
) *spb.ApiResponse {
	var body evalTableRowsBody
	if err := decodeEvalTableBody(request.GetBodyJson(), &body); err != nil {
		return apiErrorResponse(fmt.Sprintf("decode EvalTable rows: %v", err), 0)
	}

	rows := make(
		[]coreweaveevaluations.EvalTableAddRowsParamsRow,
		0,
		len(body.Rows),
	)
	for _, row := range body.Rows {
		rows = append(rows, coreweaveevaluations.EvalTableAddRowsParamsRow{
			Input:  coreweaveevaluations.F(row.Input),
			Output: coreweaveevaluations.F(row.Output),
			Scores: coreweaveevaluations.F(row.Scores),
		})
	}

	_, err := service.AddRows(
		ctx,
		coreweaveevaluations.EvalTableAddRowsParamsNamespaceWandb,
		scopeRef,
		request.GetEvaluationId(),
		coreweaveevaluations.EvalTableAddRowsParams{
			Rows: coreweaveevaluations.F(rows),
		},
		requestOptions...,
	)
	if err != nil {
		return evalTableErrorResponse("add EvalTable rows", err)
	}

	return evalTableResponse(&spb.EvalTableResponse{
		EvaluationId: request.GetEvaluationId(),
	})
}

func (h *EvalTableHandler) createVersion(
	ctx context.Context,
	service *coreweaveevaluations.EvalTableService,
	scopeRef string,
	request *spb.EvalTableCreateVersionRequest,
	requestOptions []option.RequestOption,
) *spb.ApiResponse {
	result, err := service.NewVersion(
		ctx,
		coreweaveevaluations.EvalTableNewVersionParamsNamespaceWandb,
		scopeRef,
		request.GetEvaluationId(),
		requestOptions...,
	)
	if err != nil {
		return evalTableErrorResponse("create EvalTable version", err)
	}

	return evalTableResponse(&spb.EvalTableResponse{
		EvaluationId:        request.GetEvaluationId(),
		EvaluationVersionId: result.EvaluationVersionID,
		DatasetVersionId:    result.DatasetVersionID,
	})
}

func decodeEvalTableBody(data []byte, value any) error {
	decoder := json.NewDecoder(bytes.NewReader(data))
	decoder.UseNumber()
	if err := decoder.Decode(value); err != nil {
		return err
	}
	if err := decoder.Decode(&struct{}{}); err != io.EOF {
		if err == nil {
			return errors.New("multiple JSON values")
		}
		return err
	}
	return nil
}

func evalTableResponse(response *spb.EvalTableResponse) *spb.ApiResponse {
	return &spb.ApiResponse{
		Response: &spb.ApiResponse_EvalTableResponse{
			EvalTableResponse: response,
		},
	}
}

func evalTableErrorResponse(operation string, err error) *spb.ApiResponse {
	status := int32(0)
	var apiError *coreweaveevaluations.Error
	if errors.As(err, &apiError) {
		status = int32(apiError.StatusCode)
	}
	return apiErrorResponse(fmt.Sprintf("%s: %v", operation, err), status)
}
