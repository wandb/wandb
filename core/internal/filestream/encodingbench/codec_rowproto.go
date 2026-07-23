package encodingbench

import (
	"encoding/base64"
	"fmt"

	spb "github.com/wandb/wandb/core/pkg/service_go_proto"

	"google.golang.org/protobuf/proto"
)

type JSONRowProtoEnvelopeCodec struct{}

func (JSONRowProtoEnvelopeCodec) Name() string { return "row_proto/json" }

func (JSONRowProtoEnvelopeCodec) Encode(records []*spb.HistoryRecord) (EncodedEnvelope, error) {
	content := make([]string, len(records))
	bodyBytes := 0
	for rowIndex, record := range records {
		encoded, err := proto.Marshal(record)
		if err != nil {
			return EncodedEnvelope{}, fmt.Errorf("marshal row %d: %w", rowIndex, err)
		}
		bodyBytes += len(encoded)
		content[rowIndex] = base64.StdEncoding.EncodeToString(encoded)
	}
	data, err := marshalJSONEnvelope(content)
	if err != nil {
		return EncodedEnvelope{}, fmt.Errorf("marshal row-proto JSON envelope: %w", err)
	}
	return EncodedEnvelope{Data: data, BodyBytes: bodyBytes}, nil
}

func (JSONRowProtoEnvelopeCodec) Decode(data []byte, _ ValueMode) ([]*spb.HistoryRecord, error) {
	content, err := unmarshalJSONEnvelope(data)
	if err != nil {
		return nil, err
	}
	records := make([]*spb.HistoryRecord, len(content))
	for rowIndex, encoded := range content {
		recordBytes, err := base64.StdEncoding.DecodeString(encoded)
		if err != nil {
			return nil, fmt.Errorf("decode row %d base64: %w", rowIndex, err)
		}
		record := &spb.HistoryRecord{}
		if err := proto.Unmarshal(recordBytes, record); err != nil {
			return nil, fmt.Errorf("unmarshal row %d: %w", rowIndex, err)
		}
		records[rowIndex] = record
	}
	return records, nil
}

type ProtoRowEnvelopeCodec struct{}

func (ProtoRowEnvelopeCodec) Name() string { return "row_proto/native" }

func (ProtoRowEnvelopeCodec) Encode(records []*spb.HistoryRecord) (EncodedEnvelope, error) {
	bodyBytes := 0
	for _, record := range records {
		bodyBytes += proto.Size(record)
	}
	request := &BenchmarkFileStreamRequest{
		FileName: historyFileName,
		Content: &BenchmarkFileStreamRequest_RowHistory{
			RowHistory: &RowHistoryBatch{Records: records},
		},
	}
	data, err := proto.Marshal(request)
	if err != nil {
		return EncodedEnvelope{}, fmt.Errorf("marshal row-proto envelope: %w", err)
	}
	return EncodedEnvelope{Data: data, BodyBytes: bodyBytes}, nil
}

func (ProtoRowEnvelopeCodec) Decode(data []byte, _ ValueMode) ([]*spb.HistoryRecord, error) {
	request := &BenchmarkFileStreamRequest{}
	if err := proto.Unmarshal(data, request); err != nil {
		return nil, fmt.Errorf("unmarshal row-proto envelope: %w", err)
	}
	if err := validateProtoEnvelope(request); err != nil {
		return nil, err
	}
	batch := request.GetRowHistory()
	if batch == nil {
		return nil, fmt.Errorf("protobuf envelope does not contain row history")
	}
	return batch.Records, nil
}

func validateProtoEnvelope(request *BenchmarkFileStreamRequest) error {
	if request.FileName != historyFileName {
		return fmt.Errorf("unexpected file name %q", request.FileName)
	}
	if request.Offset != 0 {
		return fmt.Errorf("unexpected history offset %d", request.Offset)
	}
	if request.Content == nil {
		return fmt.Errorf("protobuf envelope is missing history content")
	}
	return nil
}
