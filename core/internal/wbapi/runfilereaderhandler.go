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

// RunFileReaderHandler handles requests to read local .wandb files.
type RunFileReaderHandler struct {
	mu     sync.RWMutex
	logger *observability.CoreLogger

	// currentRequestId is the id for the next reader init request.
	//
	// It is used to provide a unique id for each reader init request
	// and track the associated reader across read requests.
	currentRequestId atomic.Int32

	// readers is a map of request ids to transactionlog readers.
	readers map[int32]*transactionlog.Reader
}

func NewRunFileReaderHandler() *RunFileReaderHandler {
	return &RunFileReaderHandler{
		readers: make(map[int32]*transactionlog.Reader),
		logger: observability.NewCoreLogger(
			slog.Default(),
			nil,
		),
	}
}

// HandleRequest dispatches a RunFileReaderRequest to the appropriate handler.
func (h *RunFileReaderHandler) HandleRequest(
	request *spb.RunFileReaderRequest,
) *spb.ApiResponse {
	switch request.Request.(type) {
	case *spb.RunFileReaderRequest_RunFileReaderInit:
		return h.handleInit(request.GetRunFileReaderInit())
	case *spb.RunFileReaderRequest_RunFileReaderRead:
		return h.handleRead(request.GetRunFileReaderRead())
	case *spb.RunFileReaderRequest_RunFileReaderCleanup:
		h.handleCleanup(request.GetRunFileReaderCleanup())
		return nil
	}
	return nil
}

// handleInit initializes a transactionlog reader for a .wandb file,
// And saves it for iterating over the file's records.
func (h *RunFileReaderHandler) handleInit(
	request *spb.RunFileReaderInit,
) *spb.ApiResponse {
	reader, err := transactionlog.OpenReader(request.Path, h.logger)
	if err != nil {
		return runFileReaderError(err.Error())
	}

	requestId := h.currentRequestId.Add(1)

	h.mu.Lock()
	h.readers[requestId] = reader
	h.mu.Unlock()

	return &spb.ApiResponse{
		Response: &spb.ApiResponse_RunFileReaderResponse{
			RunFileReaderResponse: &spb.RunFileReaderResponse{
				Response: &spb.RunFileReaderResponse_RunFileReaderInit{
					RunFileReaderInit: &spb.RunFileReaderInitResponse{
						RequestId: requestId,
					},
				},
			},
		},
	}
}

// handleRead reads a batch of records from a transactionlog reader for a given request id.
func (h *RunFileReaderHandler) handleRead(
	request *spb.RunFileReaderRead,
) *spb.ApiResponse {
	h.mu.RLock()
	reader, ok := h.readers[request.RequestId]
	h.mu.RUnlock()
	if !ok || reader == nil {
		return runFileReaderError("Transaction log reader has not been initialized.")
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
	hasMore := true

	for len(records) < pageSize {
		record, err := reader.Read()

		if errors.Is(err, io.EOF) {
			hasMore = false
			break
		}
		if err != nil {
			return runFileReaderError(err.Error())
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
			return runFileReaderError(err.Error())
		}

		records = append(records, &spb.ParsedRecord{
			RecordType:  recordType,
			RecordNum:   record.Num,
			JsonContent: string(jsonBytes),
		})
	}

	return &spb.ApiResponse{
		Response: &spb.ApiResponse_RunFileReaderResponse{
			RunFileReaderResponse: &spb.RunFileReaderResponse{
				Response: &spb.RunFileReaderResponse_RunFileReaderRead{
					RunFileReaderRead: &spb.RunFileReaderReadResponse{
						Records: records,
						HasMore: hasMore,
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
func (h *RunFileReaderHandler) handleCleanup(
	request *spb.RunFileReaderCleanup,
) {
	h.mu.Lock()
	reader, ok := h.readers[request.RequestId]
	if ok && reader != nil {
		delete(h.readers, request.RequestId)
	}
	h.mu.Unlock()

	if ok && reader != nil {
		reader.Close()
	}
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

func runFileReaderError(message string) *spb.ApiResponse {
	return &spb.ApiResponse{
		Response: &spb.ApiResponse_ApiErrorResponse{
			ApiErrorResponse: &spb.ApiErrorResponse{
				Message: message,
			},
		},
	}
}
