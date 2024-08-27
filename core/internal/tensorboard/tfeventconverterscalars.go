package tensorboard

import (
	"fmt"

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
		emitter.EmitHistory(
			pathtree.PathOf(tag),
			fmt.Sprintf("%v", value.SimpleValue))

	case *tbproto.Summary_Value_Tensor:
		tensor, err := tensorFromProto(value.Tensor)
		if err != nil {
			logger.CaptureError(
				fmt.Errorf("tensorboard: error parsing tensor: %v", err))
			return
		}

		str, err := tensor.ToHistogramJSON(32)
		if err != nil {
			logger.CaptureError(
				fmt.Errorf("tensorboard: error serializing tensor: %v", err))
			return
		}

		emitter.EmitHistory(pathtree.PathOf(tag), str)

	default:
		logger.CaptureError(
			fmt.Errorf(
				"tensorboard: unexpected scalars value type: %T",
				value))
	}
}
