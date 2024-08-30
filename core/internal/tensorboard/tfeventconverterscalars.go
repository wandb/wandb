package tensorboard

import (
	"fmt"
	"strconv"

	"github.com/wandb/wandb/core/internal/pathtree"
	"github.com/wandb/wandb/core/internal/tensorboard/tbproto"
	"github.com/wandb/wandb/core/pkg/observability"
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
		processScalarsSimpleValue(emitter, tag, value.SimpleValue)

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

		emitter.EmitHistory(
			pathtree.PathOf(tag),
			strconv.FormatFloat(scalar, 'f', -1, 64),
		)

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
) {
	emitter.EmitHistory(
		pathtree.PathOf(tag),
		strconv.FormatFloat(float64(value), 'f', -1, 64),
	)
}
