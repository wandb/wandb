package encodingbench

import (
	"encoding/base64"
	"fmt"
	"slices"

	spb "github.com/wandb/wandb/core/pkg/service_go_proto"

	"google.golang.org/protobuf/proto"
)

type JSONColumnProtoEnvelopeCodec struct{}

func (JSONColumnProtoEnvelopeCodec) Name() string { return "column_proto/json" }

func (JSONColumnProtoEnvelopeCodec) Encode(records []*spb.HistoryRecord) (EncodedEnvelope, error) {
	batch, err := columnarBatchFromRecords(records)
	if err != nil {
		return EncodedEnvelope{}, err
	}
	body, err := proto.Marshal(batch)
	if err != nil {
		return EncodedEnvelope{}, fmt.Errorf("marshal columnar batch: %w", err)
	}
	data, err := marshalJSONEnvelope([]string{base64.StdEncoding.EncodeToString(body)})
	if err != nil {
		return EncodedEnvelope{}, fmt.Errorf("marshal columnar JSON envelope: %w", err)
	}
	return EncodedEnvelope{Data: data, BodyBytes: len(body)}, nil
}

func (JSONColumnProtoEnvelopeCodec) Decode(data []byte, mode ValueMode) ([]*spb.HistoryRecord, error) {
	content, err := unmarshalJSONEnvelope(data)
	if err != nil {
		return nil, err
	}
	if len(content) != 1 {
		return nil, fmt.Errorf("columnar JSON envelope has %d content entries, want 1", len(content))
	}
	body, err := base64.StdEncoding.DecodeString(content[0])
	if err != nil {
		return nil, fmt.Errorf("decode columnar base64: %w", err)
	}
	batch := &ColumnarHistoryBatch{}
	if err := proto.Unmarshal(body, batch); err != nil {
		return nil, fmt.Errorf("unmarshal columnar batch: %w", err)
	}
	return recordsFromColumnarBatch(batch, mode)
}

type ProtoColumnEnvelopeCodec struct{}

func (ProtoColumnEnvelopeCodec) Name() string { return "column_proto/native" }

func (ProtoColumnEnvelopeCodec) Encode(records []*spb.HistoryRecord) (EncodedEnvelope, error) {
	batch, err := columnarBatchFromRecords(records)
	if err != nil {
		return EncodedEnvelope{}, err
	}
	request := &BenchmarkFileStreamRequest{
		FileName: historyFileName,
		Content: &BenchmarkFileStreamRequest_ColumnarHistory{
			ColumnarHistory: batch,
		},
	}
	data, err := proto.Marshal(request)
	if err != nil {
		return EncodedEnvelope{}, fmt.Errorf("marshal columnar envelope: %w", err)
	}
	return EncodedEnvelope{Data: data, BodyBytes: proto.Size(batch)}, nil
}

func (ProtoColumnEnvelopeCodec) Decode(data []byte, mode ValueMode) ([]*spb.HistoryRecord, error) {
	request := &BenchmarkFileStreamRequest{}
	if err := proto.Unmarshal(data, request); err != nil {
		return nil, fmt.Errorf("unmarshal columnar envelope: %w", err)
	}
	if err := validateProtoEnvelope(request); err != nil {
		return nil, err
	}
	batch := request.GetColumnarHistory()
	if batch == nil {
		return nil, fmt.Errorf("protobuf envelope does not contain columnar history")
	}
	return recordsFromColumnarBatch(batch, mode)
}

func columnarBatchFromRecords(records []*spb.HistoryRecord) (*ColumnarHistoryBatch, error) {
	batch := &ColumnarHistoryBatch{RowCount: uint32(len(records))}
	keyIndexes := make(map[string]uint32)

	for rowIndex, record := range records {
		if record == nil {
			return nil, fmt.Errorf("row %d: nil history record", rowIndex)
		}
		for cellIndex, item := range record.Item {
			if item == nil {
				return nil, fmt.Errorf("row %d cell %d: nil history item", rowIndex, cellIndex)
			}
			key := &HistoryKey{Key: item.Key, NestedKey: slices.Clone(item.NestedKey)}
			fingerprintBytes, err := proto.MarshalOptions{Deterministic: true}.Marshal(key)
			if err != nil {
				return nil, fmt.Errorf("encode key: %w", err)
			}
			fingerprint := string(fingerprintBytes)
			keyIndex, ok := keyIndexes[fingerprint]
			if !ok {
				keyIndex = uint32(len(batch.Keys))
				keyIndexes[fingerprint] = keyIndex
				batch.Keys = append(batch.Keys, key)
			}

			value, err := valueFromItem(item)
			if err != nil {
				return nil, fmt.Errorf("row %d cell %d: %w", rowIndex, cellIndex, err)
			}
			batch.RowIndex = append(batch.RowIndex, uint32(rowIndex))
			batch.KeyIndex = append(batch.KeyIndex, keyIndex)
			if err := appendColumnValue(batch, value); err != nil {
				return nil, fmt.Errorf("row %d cell %d: %w", rowIndex, cellIndex, err)
			}
		}
	}
	return batch, nil
}

func appendColumnValue(batch *ColumnarHistoryBatch, value Value) error {
	switch value.Kind {
	case KindNull:
		batch.Kind = append(batch.Kind, ColumnarHistoryBatch_KIND_NULL)
		batch.ValueIndex = append(batch.ValueIndex, 0)
	case KindBool:
		batch.Kind = append(batch.Kind, ColumnarHistoryBatch_KIND_BOOL)
		batch.ValueIndex = append(batch.ValueIndex, uint32(len(batch.BoolValue)))
		batch.BoolValue = append(batch.BoolValue, value.Bool)
	case KindNumber:
		batch.Kind = append(batch.Kind, ColumnarHistoryBatch_KIND_NUMBER)
		batch.ValueIndex = append(batch.ValueIndex, uint32(len(batch.NumberValue)))
		batch.NumberValue = append(batch.NumberValue, value.Number)
	case KindString:
		batch.Kind = append(batch.Kind, ColumnarHistoryBatch_KIND_STRING)
		batch.ValueIndex = append(batch.ValueIndex, uint32(len(batch.StringValue)))
		batch.StringValue = append(batch.StringValue, value.String)
	case KindJSON:
		batch.Kind = append(batch.Kind, ColumnarHistoryBatch_KIND_JSON)
		batch.ValueIndex = append(batch.ValueIndex, uint32(len(batch.JsonValue)))
		batch.JsonValue = append(batch.JsonValue, slices.Clone(value.JSON))
	default:
		return fmt.Errorf("unknown value kind %d", value.Kind)
	}
	return nil
}

func recordsFromColumnarBatch(batch *ColumnarHistoryBatch, mode ValueMode) ([]*spb.HistoryRecord, error) {
	cellCount := len(batch.RowIndex)
	if len(batch.KeyIndex) != cellCount || len(batch.Kind) != cellCount || len(batch.ValueIndex) != cellCount {
		return nil, fmt.Errorf(
			"mismatched cell columns: row=%d key=%d kind=%d value=%d",
			cellCount,
			len(batch.KeyIndex),
			len(batch.Kind),
			len(batch.ValueIndex),
		)
	}

	rowSizes := make([]int, batch.RowCount)
	for _, rowIndex := range batch.RowIndex {
		if rowIndex >= batch.RowCount {
			return nil, fmt.Errorf("row index %d exceeds row count %d", rowIndex, batch.RowCount)
		}
		rowSizes[rowIndex]++
	}
	records := make([]*spb.HistoryRecord, batch.RowCount)
	for rowIndex, size := range rowSizes {
		records[rowIndex] = &spb.HistoryRecord{Item: make([]*spb.HistoryItem, 0, size)}
	}

	for cellIndex := range cellCount {
		keyIndex := batch.KeyIndex[cellIndex]
		if keyIndex >= uint32(len(batch.Keys)) {
			return nil, fmt.Errorf("key index %d exceeds key count %d", keyIndex, len(batch.Keys))
		}
		key := batch.Keys[keyIndex]
		if key == nil {
			return nil, fmt.Errorf("key index %d is nil", keyIndex)
		}
		value, err := columnValue(batch, batch.Kind[cellIndex], batch.ValueIndex[cellIndex])
		if err != nil {
			return nil, fmt.Errorf("cell %d: %w", cellIndex, err)
		}
		item, err := itemFromValue(key.Key, key.NestedKey, value, mode)
		if err != nil {
			return nil, fmt.Errorf("cell %d: %w", cellIndex, err)
		}
		rowIndex := batch.RowIndex[cellIndex]
		records[rowIndex].Item = append(records[rowIndex].Item, item)
	}
	return records, nil
}

func columnValue(batch *ColumnarHistoryBatch, kind ColumnarHistoryBatch_Kind, index uint32) (Value, error) {
	switch kind {
	case ColumnarHistoryBatch_KIND_NULL:
		return Value{Kind: KindNull}, nil
	case ColumnarHistoryBatch_KIND_BOOL:
		if index >= uint32(len(batch.BoolValue)) {
			return Value{}, fmt.Errorf("bool index %d exceeds value count %d", index, len(batch.BoolValue))
		}
		return Value{Kind: KindBool, Bool: batch.BoolValue[index]}, nil
	case ColumnarHistoryBatch_KIND_NUMBER:
		if index >= uint32(len(batch.NumberValue)) {
			return Value{}, fmt.Errorf("number index %d exceeds value count %d", index, len(batch.NumberValue))
		}
		return Value{Kind: KindNumber, Number: batch.NumberValue[index]}, nil
	case ColumnarHistoryBatch_KIND_STRING:
		if index >= uint32(len(batch.StringValue)) {
			return Value{}, fmt.Errorf("string index %d exceeds value count %d", index, len(batch.StringValue))
		}
		return Value{Kind: KindString, String: batch.StringValue[index]}, nil
	case ColumnarHistoryBatch_KIND_JSON:
		if index >= uint32(len(batch.JsonValue)) {
			return Value{}, fmt.Errorf("JSON index %d exceeds value count %d", index, len(batch.JsonValue))
		}
		value := Value{Kind: KindJSON, JSON: slices.Clone(batch.JsonValue[index])}
		if _, err := valueJSON(value); err != nil {
			return Value{}, err
		}
		return value, nil
	default:
		return Value{}, fmt.Errorf("unknown value kind %d", kind)
	}
}
