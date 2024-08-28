package tensorboard

import (
	"errors"
	"fmt"
	"slices"
	"strconv"

	"github.com/wandb/wandb/core/internal/pathtree"
	"github.com/wandb/wandb/core/internal/tensorboard/tbproto"
	"github.com/wandb/wandb/core/internal/wbvalue"
	"github.com/wandb/wandb/core/pkg/observability"
)

// processImages process data logged with `tf.summary.image()`.
func processImages(
	emitter Emitter,
	tag string,
	value *tbproto.Summary_Value,
	logger *observability.CoreLogger,
) {
	tensorValue, ok := value.GetValue().(*tbproto.Summary_Value_Tensor)
	if !ok {
		logger.CaptureError(
			fmt.Errorf(
				"tensorboard: expected images value to be a Tensor"+
					" but its type is %T",
				value.GetValue()))
		return
	}

	if len(tensorValue.Tensor.StringVal) != 3 {
		logger.CaptureError(
			fmt.Errorf(
				"tensorboard: expected images tensor string_val"+
					" to have 3 values, but it has %d",
				len(tensorValue.Tensor.StringVal)))
		return
	}

	// Format: https://github.com/tensorflow/tensorboard/blob/b56c65521cbccf3097414cbd7e30e55902e08cab/tensorboard/plugins/image/summary.py#L17-L18
	width, err1 := strconv.Atoi(string(tensorValue.Tensor.StringVal[0]))
	height, err2 := strconv.Atoi(string(tensorValue.Tensor.StringVal[1]))
	png := tensorValue.Tensor.StringVal[2]
	if err1 != nil || err2 != nil {
		logger.CaptureError(
			fmt.Errorf(
				"tensorboard: couldn't parse image dimensions: %v",
				errors.Join(err1, err2)))
		return
	}

	// Verify that the first 8 bytes are the PNG signature.
	if len(png) < 8 || !slices.Equal(
		png[:8],
		[]byte{0x89, 0x50, 0x4E, 0x47, 0x0D, 0x0A, 0x1A, 0x0A},
	) {
		logger.CaptureError(errors.New("tensorboard: image is not PNG-encoded"))
		return
	}

	err := emitter.EmitImage(
		pathtree.PathOf(tag),
		wbvalue.Image{
			PNG:    png,
			Width:  width,
			Height: height,
		},
	)
	if err != nil {
		logger.CaptureError(
			fmt.Errorf(
				"tensorboard: couldn't emit image: %v", err))
	}
}
