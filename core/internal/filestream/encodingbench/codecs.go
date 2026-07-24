package encodingbench

import spb "github.com/wandb/wandb/core/pkg/service_go_proto"

func benchmarkCodecs() []EnvelopeCodec {
	return []EnvelopeCodec{
		LegacyJSONEnvelopeCodec{},
		JSONRowProtoEnvelopeCodec{},
		ProtoRowEnvelopeCodec{},
		JSONColumnProtoEnvelopeCodec{},
		ProtoColumnEnvelopeCodec{},
	}
}

func recordCounts(records []*spb.HistoryRecord) (rows, cells int) {
	rows = len(records)
	for _, record := range records {
		cells += len(record.Item)
	}
	return rows, cells
}
