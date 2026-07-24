package encodingbench

import (
	"fmt"
	"slices"

	"github.com/wandb/simplejsonext"

	"github.com/wandb/wandb/core/internal/pathtree"
	spb "github.com/wandb/wandb/core/pkg/service_go_proto"
)

type LegacyJSONEnvelopeCodec struct{}

func (LegacyJSONEnvelopeCodec) Name() string { return "jsonl/json" }

func (LegacyJSONEnvelopeCodec) Encode(records []*spb.HistoryRecord) (EncodedEnvelope, error) {
	lines := make([]string, len(records))
	bodyBytes := 0
	for rowIndex, record := range records {
		line, err := recordToExtendedJSON(record)
		if err != nil {
			return EncodedEnvelope{}, fmt.Errorf("row %d: %w", rowIndex, err)
		}
		lines[rowIndex] = string(line)
		bodyBytes += len(line)
	}
	data, err := marshalJSONEnvelope(lines)
	if err != nil {
		return EncodedEnvelope{}, fmt.Errorf("marshal legacy envelope: %w", err)
	}
	return EncodedEnvelope{Data: data, BodyBytes: bodyBytes}, nil
}

func (LegacyJSONEnvelopeCodec) Decode(data []byte, mode ValueMode) ([]*spb.HistoryRecord, error) {
	lines, err := unmarshalJSONEnvelope(data)
	if err != nil {
		return nil, err
	}
	records := make([]*spb.HistoryRecord, len(lines))
	for rowIndex, line := range lines {
		record, err := recordFromExtendedJSON(line, mode)
		if err != nil {
			return nil, fmt.Errorf("row %d: %w", rowIndex, err)
		}
		records[rowIndex] = record
	}
	return records, nil
}

func recordToExtendedJSON(record *spb.HistoryRecord) ([]byte, error) {
	if record == nil {
		return nil, fmt.Errorf("nil history record")
	}
	tree := pathtree.New[any]()
	for _, item := range record.Item {
		if item == nil {
			return nil, fmt.Errorf("nil history item")
		}
		path, err := itemPath(item)
		if err != nil {
			return nil, err
		}
		value, err := valueFromItem(item)
		if err != nil {
			return nil, fmt.Errorf("decode %v: %w", path.Labels(), err)
		}
		decoded, err := valueAny(value)
		if err != nil {
			return nil, fmt.Errorf("decode %v: %w", path.Labels(), err)
		}
		setUnmarshaledJSON(tree, path, decoded)
	}
	return marshalSortedJSON(tree.CloneTree())
}

func itemPath(item *spb.HistoryItem) (pathtree.TreePath, error) {
	switch {
	case len(item.NestedKey) > 0:
		return pathtree.PathOf(item.NestedKey[0], item.NestedKey[1:]...), nil
	case item.Key != "":
		return pathtree.PathOf(item.Key), nil
	default:
		return pathtree.TreePath{}, fmt.Errorf("empty history item key")
	}
}

func setUnmarshaledJSON(tree *pathtree.PathTree[any], path pathtree.TreePath, value any) {
	if object, ok := value.(map[string]any); ok {
		for key, child := range object {
			setUnmarshaledJSON(tree, path.With(key), child)
		}
		return
	}
	tree.Set(path, value)
}

func recordFromExtendedJSON(line string, mode ValueMode) (*spb.HistoryRecord, error) {
	decoded, err := simplejsonext.UnmarshalString(line)
	if err != nil {
		return nil, fmt.Errorf("unmarshal history line: %w", err)
	}
	object, ok := decoded.(map[string]any)
	if !ok {
		return nil, fmt.Errorf("history line is %T, not an object", decoded)
	}
	keys := make([]string, 0, len(object))
	for key := range object {
		keys = append(keys, key)
	}
	slices.Sort(keys)
	record := &spb.HistoryRecord{Item: make([]*spb.HistoryItem, 0, len(keys))}
	for _, key := range keys {
		value, err := valueFromAny(object[key])
		if err != nil {
			return nil, fmt.Errorf("decode %q: %w", key, err)
		}
		item, err := itemFromValue(key, nil, value, mode)
		if err != nil {
			return nil, fmt.Errorf("decode %q: %w", key, err)
		}
		record.Item = append(record.Item, item)
	}
	return record, nil
}
