package tensorboard

import (
	"fmt"

	"github.com/wandb/simplejsonext"
	"github.com/wandb/wandb/core/internal/observability"
	"github.com/wandb/wandb/core/internal/pathtree"
	"github.com/wandb/wandb/core/internal/tensorboard/tbproto"
)

// processScalars processes data logged with `tf.summary.scalar()`.
func processScalars(
	emitter Emitter,
	tag string,
	value *tbproto.Summary_Value,
	logger *observability.CoreLogger,
) {
	switch value := value.GetValue().(type) {
	case *tbproto.Summary_Value_SimpleValue:
		processScalarsSimpleValue(emitter, tag, value.SimpleValue, logger)

	case *tbproto.Summary_Value_Tensor:
		tensor, err := tensorFromProto(value.Tensor)
		if err != nil {
			logger.CaptureError(
				fmt.Errorf("tensorboard: error parsing tensor: %v", err))
			return
		}

		scalar, err := tensor.Scalar()
		if err != nil {
			logger.CaptureError(
				fmt.Errorf("tensorboard: error getting scalar: %v", err))
			return
		}

		floatJSON, err := simplejsonext.MarshalToString(scalar)
		if err != nil {
			logger.CaptureError(
				fmt.Errorf("tensorboard: error encoding scalar: %v", err))
			return
		}

		emitter.EmitHistory(pathtree.PathOf(tag), floatJSON)

	default:
		logger.CaptureError(
			fmt.Errorf(
				"tensorboard: unexpected scalars value type: %T",
				value))
	}
}

// processScalarsSimpleValue handles a simple_value summary as a scalar.
func processScalarsSimpleValue(
	emitter Emitter,
	tag string,
	value float32,
	logger *observability.CoreLogger,
) {
	floatJSON, err := simplejsonext.MarshalToString(value)
	if err != nil {
		logger.CaptureError(
			fmt.Errorf("tensorboard: error encoding scalar: %v", err))
		return
	}

	emitter.EmitHistory(pathtree.PathOf(tag), floatJSON)
}
