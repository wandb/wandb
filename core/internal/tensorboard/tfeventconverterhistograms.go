package tensorboard

import (
	"errors"
	"fmt"

	"github.com/wandb/wandb/core/internal/pathtree"
	"github.com/wandb/wandb/core/internal/tensorboard/tbproto"
	"github.com/wandb/wandb/core/internal/wbvalue"
	"github.com/wandb/wandb/core/pkg/observability"
)

// processHistograms processes data logged with `tf.summary.histogram()`.
func processHistograms(
	emitter Emitter,
	tag string,
	value *tbproto.Summary_Value,
	logger *observability.CoreLogger,
) {
	tensorValue, ok := value.GetValue().(*tbproto.Summary_Value_Tensor)
	if !ok {
		logger.CaptureError(
			fmt.Errorf(
				"tensorboard: expected histograms value to be a Tensor"+
					" but its type is %T",
				value.GetValue()))
		return
	}

	tensor, err := tensorFromProto(tensorValue.Tensor)
	if err != nil {
		logger.CaptureError(
			fmt.Errorf("tensorboard: failed to parse tensor: %v", err))
		return
	}

	leftEdges, err1 := tensor.Col(0)
	rightEdges, err2 := tensor.Col(1)
	weights, err3 := tensor.Col(2)
	if err1 != nil || err2 != nil || err3 != nil {
		logger.CaptureError(
			fmt.Errorf("tensorboard: couldn't read histograms row: %v",
				errors.Join(err1, err2, err3)))
		return
	}

	if len(weights) == 0 || len(leftEdges) == 0 || len(rightEdges) == 0 {
		// This is a histogram of no data.
		return
	}

	leftEdge := leftEdges[0]
	rightEdge := rightEdges[len(rightEdges)-1]

	binEdges := make([]float64, 0, 1+len(leftEdges))
	binEdges = append(binEdges, leftEdges...)
	binEdges = append(binEdges, rightEdge)

	if len(weights) > 32 {
		binEdges, weights, err = reduceHistogram(
			32,
			leftEdge,
			rightEdge,
			weights,
		)

		if err != nil {
			logger.CaptureError(
				fmt.Errorf("tensorboard: error rebinning histogram: %v", err))
			return
		}
	}

	str, err := wbvalue.Histogram{
		BinEdges:   binEdges,
		BinWeights: weights,
	}.HistoryValueJSON()
	if err != nil {
		logger.CaptureError(
			fmt.Errorf("tensorboard: error serializing histogram: %v", err))
		return
	}

	emitter.EmitHistory(pathtree.PathOf(tag), str)
}

// reduceHistogram returns a histogram with fewer bins preserving their total.
//
// The input histogram is assumed to consist of adjacent, equal-width bins.
// This is consistent with the current TensorBoard histogram summary
// implementation:
//
// https://github.com/tensorflow/tensorboard/blob/b56c65521cbccf3097414cbd7e30e55902e08cab/tensorboard/plugins/histogram/summary.py#L94
func reduceHistogram(
	desiredBins int,
	leftEdge float64,
	rightEdge float64,
	oldWeights []float64,
) (newEdges []float64, newWeights []float64, err error) {
	if desiredBins >= len(oldWeights) {
		return nil, nil, fmt.Errorf(
			"%d is not smaller than %d",
			desiredBins, len(oldWeights))
	}
	if rightEdge <= leftEdge {
		return nil, nil, fmt.Errorf(
			"histogram right edge is %f, which is <= %f",
			rightEdge, leftEdge)
	}

	oldBinWidth := (rightEdge - leftEdge) / float64(len(oldWeights))
	newBinWidth := (rightEdge - leftEdge) / float64(desiredBins)

	newEdges = make([]float64, desiredBins+1)
	newEdges[0] = leftEdge
	for i := 1; i <= desiredBins; i++ {
		newEdges[i] = leftEdge + newBinWidth*float64(i)
	}

	newWeights = make([]float64, desiredBins)
	for i, x := range oldWeights {
		oldLeftEdge := leftEdge + oldBinWidth*float64(i)
		oldRightEdge := oldLeftEdge + oldBinWidth

		firstBinIdx := int((oldLeftEdge - leftEdge) / newBinWidth)
		lastBinIdx := int((oldRightEdge - leftEdge) / newBinWidth)

		// On the last value, lastBinIdx is 1+len(newWeights).
		// Clamp defensively to avoid panics.
		firstBinIdx = max(0, min(len(newWeights)-1, firstBinIdx))
		lastBinIdx = max(0, min(len(newWeights)-1, lastBinIdx))

		// NOTE: len(newEdges) == len(newWeights)+1 so this is safe.
		firstBinRightEdge := newEdges[firstBinIdx+1]
		lastBinLeftEdge := newEdges[lastBinIdx]

		// The first bin may contain all or part of the original weight.
		newWeights[firstBinIdx] += x *
			((min(firstBinRightEdge, oldRightEdge) - oldLeftEdge) / oldBinWidth)

		// The last bin, if different from the first, gets the remainder
		// of the original weight. Here, it must be true that:
		//   * leftBinEdge < lastBinLeftEdge <= oldRightEdge
		//   * lastBinIdx == firstBinIdx+1
		if lastBinIdx > firstBinIdx {
			newWeights[lastBinIdx] +=
				x * ((oldRightEdge - lastBinLeftEdge) / oldBinWidth)
		}
	}

	return
}
