package metricsbatch

import (
	"fmt"
	"testing"

	"github.com/wandb/wandb/core/internal/runhistory"
	spb "github.com/wandb/wandb/core/pkg/service_go_proto"
)

const imageJSON = `{"_type":"image-file","path":"media/image.png",` +
	`"width":32,"height":32}`

func benchmarkRows() map[string]func(i int) []*spb.HistoryItem {
	scalars := func(n int, typed bool) func(int) []*spb.HistoryItem {
		return func(row int) []*spb.HistoryItem {
			items := []*spb.HistoryItem{{
				Key: "_step", Value: &spb.HistoryItem_Integer{Integer: int64(row)},
			}}
			for k := range n {
				item := &spb.HistoryItem{Key: fmt.Sprintf("metric-%04d", k)}
				if typed {
					item.Value = &spb.HistoryItem_Number{Number: float64(row) + 0.5}
				} else {
					item.ValueJson = fmt.Sprint(float64(row) + 0.5)
				}
				items = append(items, item)
			}
			return items
		}
	}
	return map[string]func(int) []*spb.HistoryItem{
		"typed-scalars-50":  scalars(50, true),
		"legacy-scalars-50": scalars(50, false),
		"wide-10000":        scalars(10000, true),
		"sparse": func(row int) []*spb.HistoryItem {
			all := scalars(1000, true)(row)
			return []*spb.HistoryItem{all[0], all[1+row%1000], all[1+(row*7)%1000]}
		},
		"nested": func(row int) []*spb.HistoryItem {
			return []*spb.HistoryItem{
				{Key: "_step", Value: &spb.HistoryItem_Integer{Integer: int64(row)}},
				{Key: "image", Value: &spb.HistoryItem_Json{Json: imageJSON}},
				{NestedKey: []string{"train", "loss"}, Value: &spb.HistoryItem_Number{Number: 0.5}},
				{NestedKey: []string{"train", "acc"}, Value: &spb.HistoryItem_Number{Number: 0.9}},
				{Key: "hist", ValueJson: `{"bins":[0,1,2,3],"values":[4,5,6]}`},
			}
		},
	}
}

func benchmarkHistories(b *testing.B, items func(int) []*spb.HistoryItem) []*runhistory.RunHistory {
	b.Helper()
	const rows = 64
	histories := make([]*runhistory.RunHistory, rows)
	for i := range histories {
		rh := runhistory.New()
		for _, item := range items(i) {
			if err := rh.SetFromRecord(item); err != nil {
				b.Fatal(err)
			}
		}
		histories[i] = rh
	}
	return histories
}

func BenchmarkPrepare(b *testing.B) {
	for name, items := range benchmarkRows() {
		b.Run(name, func(b *testing.B) {
			histories := benchmarkHistories(b, items)
			b.ReportAllocs()
			b.ResetTimer()
			for i := range b.N {
				if _, err := Prepare(histories[i%len(histories)]); err != nil {
					b.Fatal(err)
				}
			}
		})
	}
}

func BenchmarkAppend(b *testing.B) {
	for name, items := range benchmarkRows() {
		b.Run(name, func(b *testing.B) {
			histories := benchmarkHistories(b, items)
			rows := make([]*Row, len(histories))
			for i, rh := range histories {
				row, err := Prepare(rh)
				if err != nil {
					b.Fatal(err)
				}
				rows[i] = row
			}
			builder := NewBuilder()
			b.ReportAllocs()
			b.ResetTimer()
			for i := range b.N {
				builder.Append(rows[i%len(rows)])
				if builder.Rows() == len(rows) {
					builder.Finish()
				}
			}
		})
	}
}
