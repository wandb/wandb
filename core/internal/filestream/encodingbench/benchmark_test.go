package encodingbench

import (
	"bytes"
	"compress/gzip"
	"fmt"
	"testing"

	spb "github.com/wandb/wandb/core/pkg/service_go_proto"
)

var benchmarkSink any

func BenchmarkEncode(b *testing.B) {
	for _, workload := range SyntheticWorkloads() {
		fixtures, err := recordFixtures(workload.Rows)
		if err != nil {
			b.Fatal(err)
		}
		for _, fixture := range fixtures {
			for _, codec := range benchmarkCodecs() {
				b.Run(workload.Name+"/"+string(fixture.Mode)+"/"+codec.Name(), func(b *testing.B) {
					encoded, err := codec.Encode(fixture.Records)
					if err != nil {
						b.Fatal(err)
					}
					gzip1Bytes := compressedSize(b, encoded.Data, gzip.BestSpeed)
					gzip6Bytes := compressedSize(b, encoded.Data, 6)
					rows, cells := recordCounts(fixture.Records)
					b.SetBytes(int64(len(encoded.Data)))
					b.ReportAllocs()
					b.ResetTimer()
					for b.Loop() {
						encoded, err = codec.Encode(fixture.Records)
						if err != nil {
							b.Fatal(err)
						}
					}
					reportOpsPerSecond(b)
					reportEnvelopeMetrics(b, encoded, gzip1Bytes, gzip6Bytes, rows, cells)
					benchmarkSink = encoded.Data
				})
			}
		}
	}
}

func BenchmarkDecode(b *testing.B) {
	for _, workload := range SyntheticWorkloads() {
		fixtures, err := recordFixtures(workload.Rows)
		if err != nil {
			b.Fatal(err)
		}
		for _, fixture := range fixtures {
			for _, codec := range benchmarkCodecs() {
				encoded, err := codec.Encode(fixture.Records)
				if err != nil {
					b.Fatal(err)
				}
				b.Run(workload.Name+"/"+string(fixture.Mode)+"/"+codec.Name(), func(b *testing.B) {
					rows, cells := recordCounts(fixture.Records)
					b.SetBytes(int64(len(encoded.Data)))
					b.ReportAllocs()
					for b.Loop() {
						decoded, err := codec.Decode(encoded.Data, fixture.Mode)
						if err != nil {
							b.Fatal(err)
						}
						benchmarkSink = decoded
					}
					reportOpsPerSecond(b)
					b.ReportMetric(float64(rows), "rows/op")
					b.ReportMetric(float64(cells), "cells/op")
				})
			}
		}
	}
}

func BenchmarkCompress(b *testing.B) {
	for _, workload := range SyntheticWorkloads() {
		fixtures, err := recordFixtures(workload.Rows)
		if err != nil {
			b.Fatal(err)
		}
		for _, fixture := range fixtures {
			for _, codec := range benchmarkCodecs() {
				encoded, err := codec.Encode(fixture.Records)
				if err != nil {
					b.Fatal(err)
				}
				for _, level := range []int{gzip.BestSpeed, 6} {
					name := fmt.Sprintf(
						"%s/%s/%s/gzip%d",
						workload.Name,
						fixture.Mode,
						codec.Name(),
						level,
					)
					b.Run(name, func(b *testing.B) {
						var destination bytes.Buffer
						b.SetBytes(int64(len(encoded.Data)))
						b.ReportAllocs()
						for b.Loop() {
							destination.Reset()
							writer, err := gzip.NewWriterLevel(&destination, level)
							if err != nil {
								b.Fatal(err)
							}
							if _, err := writer.Write(encoded.Data); err != nil {
								b.Fatal(err)
							}
							if err := writer.Close(); err != nil {
								b.Fatal(err)
							}
						}
						reportOpsPerSecond(b)
						b.ReportMetric(float64(destination.Len()), "compressed_bytes")
						benchmarkSink = destination.Len()
					})
				}
			}
		}
	}
}

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

func reportOpsPerSecond(b *testing.B) {
	b.Helper()
	if elapsed := b.Elapsed(); elapsed > 0 {
		b.ReportMetric(float64(b.N)/elapsed.Seconds(), "ops/s")
	}
}

func reportEnvelopeMetrics(
	b *testing.B,
	encoded EncodedEnvelope,
	gzip1Bytes, gzip6Bytes, rows, cells int,
) {
	b.Helper()
	b.ReportMetric(float64(len(encoded.Data)), "envelope_bytes")
	b.ReportMetric(float64(encoded.BodyBytes), "body_bytes")
	if encoded.BodyBytes > 0 {
		b.ReportMetric(float64(len(encoded.Data))/float64(encoded.BodyBytes), "envelope_ratio")
	}
	b.ReportMetric(float64(gzip1Bytes), "gzip1_bytes")
	b.ReportMetric(float64(gzip6Bytes), "gzip6_bytes")
	if len(encoded.Data) > 0 {
		b.ReportMetric(float64(gzip1Bytes)/float64(len(encoded.Data)), "gzip1_ratio")
		b.ReportMetric(float64(gzip6Bytes)/float64(len(encoded.Data)), "gzip6_ratio")
	}
	b.ReportMetric(float64(rows), "rows/op")
	b.ReportMetric(float64(cells), "cells/op")
}

func compressedSize(b *testing.B, data []byte, level int) int {
	b.Helper()
	var destination bytes.Buffer
	writer, err := gzip.NewWriterLevel(&destination, level)
	if err != nil {
		b.Fatal(err)
	}
	if _, err := writer.Write(data); err != nil {
		b.Fatal(err)
	}
	if err := writer.Close(); err != nil {
		b.Fatal(err)
	}
	return destination.Len()
}
