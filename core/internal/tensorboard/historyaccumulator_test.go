package tensorboard_test

import (
	"testing"

	"github.com/stretchr/testify/assert"
	"github.com/wandb/wandb/core/internal/tensorboard"
	"github.com/wandb/wandb/core/internal/tensorboard/tbproto"
	"github.com/wandb/wandb/core/pkg/service"
)

func simpleValueEvent(step int64, values ...any) *tbproto.TFEvent {
	summaryValues := make([]*tbproto.Summary_Value, 0)
	for i := range len(values) / 2 {
		summaryValues = append(summaryValues, &tbproto.Summary_Value{
			Tag: values[i*2+0].(string),
			Value: &tbproto.Summary_Value_SimpleValue{
				SimpleValue: values[i*2+1].(float32),
			},
		})
	}

	return &tbproto.TFEvent{
		Step: step,
		What: &tbproto.TFEvent_Summary{
			Summary: &tbproto.Summary{Value: summaryValues},
		},
	}
}

func TestAdd(t *testing.T) {
	accum := tensorboard.HistoryAccumulator{}

	assert.Nil(t, accum.Add(
		simpleValueEvent(1,
			"a/b/c", float32(1.2),
			"d/e/f", float32(3.4))))
	assert.Nil(t, accum.Add(
		simpleValueEvent(1,
			"g/h/i", float32(5.6))))
	rec1 := accum.Add(simpleValueEvent(2, "x", float32(7.8)))
	rec2 := accum.Add(simpleValueEvent(3, "x", float32(0)))

	assert.Equal(t,
		&service.HistoryRecord{
			Item: []*service.HistoryItem{
				{NestedKey: []string{"a", "b", "c"}, ValueJson: "1.2"},
				{NestedKey: []string{"d", "e", "f"}, ValueJson: "3.4"},
				{NestedKey: []string{"g", "h", "i"}, ValueJson: "5.6"},
			},
		},
		rec1)
	assert.Equal(t,
		&service.HistoryRecord{
			Item: []*service.HistoryItem{
				{NestedKey: []string{"x"}, ValueJson: "7.8"},
			},
		},
		rec2)
}
