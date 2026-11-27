package metricsbatch

import (
	"google.golang.org/protobuf/encoding/protowire"

	filestreamv1 "github.com/wandb/wandb/core/internal/filestream/proto"
)

const (
	keysField      = 1
	rowEndsField   = 2
	cellKeysField  = 3
	cellKindsField = 4
	floatsField    = 5
	intsField      = 6
	boolsField     = 7
	stringsField   = 8
	jsonsField     = 9
	seqsField      = 10
	hasSeqField    = 11
)

type batchWireSize struct {
	unpacked int
	packed   [hasSeqField + 1]int
}

func (s batchWireSize) total() int {
	total := s.unpacked
	for field, payloadBytes := range s.packed {
		if payloadBytes != 0 {
			total += sizedField(protowire.Number(field), payloadBytes)
		}
	}
	return total
}

func (s *batchWireSize) addCell(c *cell, id uint32, newKey bool) {
	if newKey {
		s.unpacked += sizedField(keysField, len(c.key))
	}
	s.packed[cellKeysField] += protowire.SizeVarint(uint64(id))
	s.packed[cellKindsField] += protowire.SizeVarint(uint64(c.kind))
	switch c.kind {
	case filestreamv1.MetricsBatch_KIND_FLOAT:
		s.packed[floatsField] += 8
	case filestreamv1.MetricsBatch_KIND_INT:
		s.packed[intsField] += protowire.SizeVarint(protowire.EncodeZigZag(c.int))
	case filestreamv1.MetricsBatch_KIND_BOOL:
		s.packed[boolsField]++
	case filestreamv1.MetricsBatch_KIND_STRING:
		s.unpacked += sizedField(stringsField, len(c.text))
	case filestreamv1.MetricsBatch_KIND_JSON:
		s.unpacked += sizedField(jsonsField, len(c.text))
	}
}

func (s *batchWireSize) addRow(row *Row, rowEnd uint32) {
	s.packed[rowEndsField] += protowire.SizeVarint(uint64(rowEnd))
	s.packed[seqsField] += protowire.SizeVarint(protowire.EncodeZigZag(row.step))
	s.packed[hasSeqField]++
}

func sizedField(field protowire.Number, payloadBytes int) int {
	return protowire.SizeTag(field) + protowire.SizeBytes(payloadBytes)
}
