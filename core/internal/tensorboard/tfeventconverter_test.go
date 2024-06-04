package tensorboard_test

import (
	"testing"

	"github.com/stretchr/testify/assert"
	"github.com/stretchr/testify/require"
	"github.com/wandb/wandb/core/internal/tensorboard"
	"github.com/wandb/wandb/core/internal/tensorboard/tbproto"
	"github.com/wandb/wandb/core/pkg/observability"
)

func scalarValue(tag string, plugin string, value float32) *tbproto.Summary_Value {
	return &tbproto.Summary_Value{
		Tag: tag,
		Value: &tbproto.Summary_Value_SimpleValue{
			SimpleValue: value,
		},
		Metadata: &tbproto.SummaryMetadata{
			PluginData: &tbproto.SummaryMetadata_PluginData{
				PluginName: plugin,
			},
		},
	}
}

func tensorValue(tag string, plugin string, values ...float32) *tbproto.Summary_Value {
	return &tbproto.Summary_Value{
		Tag: tag,
		Value: &tbproto.Summary_Value_Tensor{
			Tensor: &tbproto.TensorProto{
				Dtype:    tbproto.DataType_DT_FLOAT,
				FloatVal: values,
			},
		},
		Metadata: &tbproto.SummaryMetadata{
			PluginData: &tbproto.SummaryMetadata_PluginData{
				PluginName: plugin,
			},
		},
	}
}

func summaryEvent(
	step int64,
	wallTime float64,
	values ...*tbproto.Summary_Value,
) *tbproto.TFEvent {
	return &tbproto.TFEvent{
		Step:     step,
		WallTime: wallTime,
		What: &tbproto.TFEvent_Summary{
			Summary: &tbproto.Summary{
				Value: values,
			},
		},
	}
}

func TestConvertValues(t *testing.T) {
	converter := tensorboard.TFEventConverter{}

	result := converter.Convert(
		summaryEvent(
			123, 0.345,
			scalarValue("train/epoch_loss", "scalars", 0.5),
			tensorValue("train/epoch_histogram", "scalars", 0.1, 0.2, 0.3),
		),
		observability.NewNoOpLogger(),
	)

	require.NotNil(t, result)
	require.Len(t, result.Item, 4)
	assert.Equal(t,
		`nested_key:"global_step"  value_json:"123"`,
		result.Item[0].String())
	assert.Equal(t,
		`key:"_timestamp"  value_json:"0.345"`,
		result.Item[1].String())
	assert.Equal(t,
		`nested_key:"train"  nested_key:"epoch_loss"  value_json:"0.5"`,
		result.Item[2].String())
	assert.Equal(t,
		`nested_key:"train"  nested_key:"epoch_histogram"  value_json:"[0.1,0.2,0.3]"`,
		result.Item[3].String())
}
