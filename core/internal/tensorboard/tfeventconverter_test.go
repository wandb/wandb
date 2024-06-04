package tensorboard_test

import (
	"bytes"
	"encoding/binary"
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

func tensorValueBytes(
	tag string,
	plugin string,
	dtype tbproto.DataType,
	data []byte,
) *tbproto.Summary_Value {
	return &tbproto.Summary_Value{
		Tag: tag,
		Value: &tbproto.Summary_Value_Tensor{
			Tensor: &tbproto.TensorProto{
				Dtype:         dtype,
				TensorContent: data,
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

func TestConvertStepAndTimestamp(t *testing.T) {
	converter := tensorboard.TFEventConverter{
		Namespace: "train",
	}

	result := converter.Convert(
		summaryEvent(
			123, 0.345,
			scalarValue("epoch_loss", "scalars", 0.5)),
		observability.NewNoOpLogger(),
	)

	require.NotNil(t, result)
	require.Len(t, result.Item, 3)
	assert.Equal(t,
		`nested_key:"train" nested_key:"global_step" value_json:"123"`,
		result.Item[0].String())
	assert.Equal(t,
		`key:"_timestamp" value_json:"0.345"`,
		result.Item[1].String())
	assert.Equal(t,
		`nested_key:"train" nested_key:"epoch_loss" value_json:"0.5"`,
		result.Item[2].String())
}

func TestConvertScalar(t *testing.T) {
	converter := tensorboard.TFEventConverter{Namespace: "train"}

	result := converter.Convert(
		summaryEvent(123, 0.345, scalarValue("epoch_loss", "scalars", 0.5)),
		observability.NewNoOpLogger(),
	)

	require.NotNil(t, result)
	require.Len(t, result.Item, 3)
	assert.Equal(t,
		`nested_key:"train" nested_key:"epoch_loss" value_json:"0.5"`,
		result.Item[2].String())
}

func TestConvertTensor(t *testing.T) {
	converter := tensorboard.TFEventConverter{Namespace: "train"}
	doubleOneTwoBytes := bytes.NewBuffer([]byte{})
	binary.Write(doubleOneTwoBytes, binary.NativeEndian, float64(1))
	binary.Write(doubleOneTwoBytes, binary.NativeEndian, float64(2))

	result := converter.Convert(
		summaryEvent(123, 0.345,
			tensorValue("point-five", "scalars", 0.5),
			tensorValueBytes("one-two", "scalars",
				tbproto.DataType_DT_DOUBLE, doubleOneTwoBytes.Bytes()),
			tensorValue("three-four", "scalars", 3, 4)),
		observability.NewNoOpLogger(),
	)

	require.NotNil(t, result)
	require.Len(t, result.Item, 5)
	assert.Equal(t,
		`nested_key:"train" nested_key:"point-five" value_json:"0.5"`,
		result.Item[2].String())
	assert.Equal(t,
		`nested_key:"train" nested_key:"one-two" value_json:"[1,2]"`,
		result.Item[3].String())
	assert.Equal(t,
		`nested_key:"train" nested_key:"three-four" value_json:"[3,4]"`,
		result.Item[4].String())
}
