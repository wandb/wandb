package wbapi

import (
	"errors"
	"io"
	"log/slog"
	"sync"
	"sync/atomic"

	"google.golang.org/protobuf/encoding/protojson"

	"github.com/wandb/wandb/core/internal/observability"
	"github.com/wandb/wandb/core/internal/transactionlog"
	spb "github.com/wandb/wandb/core/pkg/service_go_proto"
)

// ParseRunFileHandler handles requests to parse local .wandb files.
type ParseRunFileHandler struct {
	mu               sync.RWMutex
	currentRequestId atomic.Int32
	readers          map[int32]*transactionlog.Reader
	logger           *observability.CoreLogger
}

func NewParseRunFileHandler() *ParseRunFileHandler {
	return &ParseRunFileHandler{
		readers: make(map[int32]*transactionlog.Reader),
		logger: observability.NewCoreLogger(
			slog.Default(),
			nil,
		),
	}
}

// HandleRequest dispatches a ParseRunFileRequest to the appropriate handler.
func (h *ParseRunFileHandler) HandleRequest(
	request *spb.ParseRunFileRequest,
) *spb.ApiResponse {
	switch request.Request.(type) {
	case *spb.ParseRunFileRequest_ParseRunFileInit:
		return h.handleInit(request.GetParseRunFileInit())
	case *spb.ParseRunFileRequest_ParseRunFileRead:
		return h.handleRead(request.GetParseRunFileRead())
	case *spb.ParseRunFileRequest_ParseRunFileCleanup:
		return h.handleCleanup(request.GetParseRunFileCleanup())
	}
	return nil
}

func (h *ParseRunFileHandler) handleInit(
	request *spb.ParseRunFileInit,
) *spb.ApiResponse {
	reader, err := transactionlog.OpenReader(request.Path, h.logger)
	if err != nil {
		return parseRunFileError(err.Error())
	}

	requestId := h.currentRequestId.Add(1)

	h.mu.Lock()
	h.readers[requestId] = reader
	h.mu.Unlock()

	return &spb.ApiResponse{
		Response: &spb.ApiResponse_ParseRunFileResponse{
			ParseRunFileResponse: &spb.ParseRunFileResponse{
				Response: &spb.ParseRunFileResponse_ParseRunFileInit{
					ParseRunFileInit: &spb.ParseRunFileInitResponse{
						RequestId: requestId,
					},
				},
			},
		},
	}
}

func (h *ParseRunFileHandler) handleRead(
	request *spb.ParseRunFileRead,
) *spb.ApiResponse {
	h.mu.RLock()
	reader, ok := h.readers[request.RequestId]
	h.mu.RUnlock()
	if !ok || reader == nil {
		return parseRunFileError("Parse operation not initialized.")
	}

	pageSize := int(request.PageSize)
	if pageSize <= 0 {
		pageSize = 100
	}

	filterSet := make(map[string]bool, len(request.RecordTypes))
	for _, rt := range request.RecordTypes {
		filterSet[rt] = true
	}

	marshaler := protojson.MarshalOptions{
		UseProtoNames: true,
	}

	var records []*spb.ParsedRecord
	eof := false

	for len(records) < pageSize {
		record, err := reader.Read()

		if errors.Is(err, io.EOF) {
			eof = true
			break
		}
		if err != nil {
			return parseRunFileError(err.Error())
		}

		recordType := recordTypeName(record)
		if recordType == "" {
			continue
		}

		if len(filterSet) > 0 && !filterSet[recordType] {
			continue
		}

		jsonBytes, err := marshaler.Marshal(record)
		if err != nil {
			return parseRunFileError(err.Error())
		}

		records = append(records, &spb.ParsedRecord{
			RecordType:  recordType,
			RecordNum:   record.Num,
			JsonContent: string(jsonBytes),
		})
	}

	return &spb.ApiResponse{
		Response: &spb.ApiResponse_ParseRunFileResponse{
			ParseRunFileResponse: &spb.ParseRunFileResponse{
				Response: &spb.ParseRunFileResponse_ParseRunFileRead{
					ParseRunFileRead: &spb.ParseRunFileReadResponse{
						Records: records,
						Eof:     eof,
					},
				},
			},
		},
	}
}

// handleCleanup closes the reader and frees resources.
//
// Returns nil so that no response is sent back to the client —
// cleanup is fire-and-forget from the caller's perspective.
func (h *ParseRunFileHandler) handleCleanup(
	request *spb.ParseRunFileCleanup,
) *spb.ApiResponse {
	h.mu.Lock()
	reader, ok := h.readers[request.RequestId]
	if ok && reader != nil {
		delete(h.readers, request.RequestId)
	}
	h.mu.Unlock()

	if ok && reader != nil {
		reader.Close()
	}

	return nil
}

// recordTypeName returns the proto field name of the record's oneof variant.
func recordTypeName(record *spb.Record) string {
	if record == nil {
		return ""
	}

	ref := record.ProtoReflect()
	oneofDesc := ref.Descriptor().Oneofs().ByName("record_type")
	if oneofDesc == nil {
		return ""
	}

	field := ref.WhichOneof(oneofDesc)
	if field == nil {
		return ""
	}

	return string(field.Name())
}

func parseRunFileError(message string) *spb.ApiResponse {
	return &spb.ApiResponse{
		Response: &spb.ApiResponse_ApiErrorResponse{
			ApiErrorResponse: &spb.ApiErrorResponse{
				Message: message,
			},
		},
	}
}
