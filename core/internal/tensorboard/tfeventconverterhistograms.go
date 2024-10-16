package tensorboard

import (
	"errors"
	"fmt"
	"runtime/debug"

	"github.com/wandb/wandb/core/internal/observability"
	"github.com/wandb/wandb/core/internal/pathtree"
	"github.com/wandb/wandb/core/internal/tensorboard/tbproto"
	"github.com/wandb/wandb/core/internal/wbvalue"
)

// processHistograms processes data logged with `tf.summary.histogram()`.
func processHistograms(
	emitter Emitter,
	tag string,
	value *tbproto.Summary_Value,
	logger *observability.CoreLogger,
) {
	switch value := value.GetValue().(type) {
	case *tbproto.Summary_Value_Tensor:
		processHistogramsTensor(emitter, tag, value.Tensor, logger)

	case *tbproto.Summary_Value_Histo:
		processHistogramsProto(emitter, tag, value.Histo, logger)

	default:
		logger.CaptureError(
			fmt.Errorf(
				"tensorboard: expected histograms value to be a Tensor"+
					" or HistogramProto but its type is %T",
				value))
	}
}

// processHistogramsTensor handles a tensor summary value as a histogram.
func processHistogramsTensor(
	emitter Emitter,
	tag string,
	tensorValue *tbproto.TensorProto,
	logger *observability.CoreLogger,
) {
	tensor, err := tensorFromProto(tensorValue)
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

	rightEdge := rightEdges[len(rightEdges)-1]

	binEdges := make([]float64, 0, 1+len(leftEdges))
	binEdges = append(binEdges, leftEdges...)
	binEdges = append(binEdges, rightEdge)

	emitHistogram(binEdges, weights, emitter, tag, logger)
}

// processHistogramsProto handles a histo summary value.
func processHistogramsProto(
	emitter Emitter,
	tag string,
	histo *tbproto.HistogramProto,
	logger *observability.CoreLogger,
) {
	rightEdges := histo.BucketLimit
	binWeights := histo.Bucket

	if len(rightEdges) == 0 {
		logger.CaptureError(
			errors.New("tensorboard: invalid histogram: empty BucketLimit"))
		return
	}
	if len(rightEdges) != len(binWeights) {
		logger.CaptureError(
			errors.New("tensorboard: invalid histogram: len(BucketLimit) != len(Bucket)"))
		return
	}

	var binEdges []float64
	switch {
	// TB defines the left-most bin's edges as (-inf, rightEdges[0]),
	// but this bin's value is often set to 0. If that's the case,
	// just drop the bin so that we only have finite width bins.
	case binWeights[0] == 0:
		binEdges = rightEdges
		binWeights = binWeights[1:]

	// If the left bin has a count, try using histo.Min as its
	// leftmost edge.
	case histo.Min < rightEdges[0]:
		binEdges = make([]float64, 0, 1+len(rightEdges))
		binEdges = append(binEdges, histo.Min)
		binEdges = append(binEdges, rightEdges...)

	default:
		logger.CaptureError(
			errors.New("tensorboard: invalid histogram: histo.Min >= rightEdges[0]"))
		return
	}

	emitHistogram(binEdges, binWeights, emitter, tag, logger)
}

func emitHistogram(
	binEdges []float64,
	binWeights []float64,
	emitter Emitter,
	tag string,
	logger *observability.CoreLogger,
) {
	if len(binEdges) != 1+len(binWeights) {
		logger.CaptureError(
			errors.New("tensorboard: invalid histogram"),
			"len(binEdges)", len(binEdges),
			"len(binWeights)", len(binWeights))
		return
	}

	if len(binWeights) > 512 {
		var err error
		binEdges, binWeights, err = reduceHistogram(
			512,
			binEdges,
			binWeights,
		)

		if err != nil {
			logger.CaptureError(
				fmt.Errorf("tensorboard: error rebinning histogram: %v", err))
			return
		}
	}

	str, err := wbvalue.Histogram{
		BinEdges:   binEdges,
		BinWeights: binWeights,
	}.HistoryValueJSON()
	if err != nil {
		logger.CaptureError(
			fmt.Errorf("tensorboard: error serializing histogram: %v", err))
		return
	}

	emitter.EmitHistory(pathtree.PathOf(tag), str)
}

// reduceHistogram returns a histogram with fewer bins preserving their total
// and the bin edge distribution.
func reduceHistogram(
	desiredBins int,
	oldEdges []float64,
	oldWeights []float64,
) (newEdges []float64, newWeights []float64, err error) {
	// There are many array accesses that are safe but only
	// due to non-obvious arithmetic reasons, so catch all
	// panics just in case.
	defer func() {
		if recoveredErr := recover(); recoveredErr != nil {
			newEdges = nil
			newWeights = nil
			err = fmt.Errorf(
				"panic: %v\n%s",
				recoveredErr,
				string(debug.Stack()),
			)
		}
	}()

	newEdges, err = reduceEdges(desiredBins, oldEdges)
	if err != nil {
		return nil, nil, err
	}

	newWeights = make([]float64, desiredBins)
	oldBinIdx := 0

	for newBinIdx := 0; newBinIdx < desiredBins; newBinIdx++ {
		// Add whole old bins to the new bin.
		//
		// oldBinIdx cannot go out of bounds because the final
		// edges in oldEdges and newEdges are equal.
		for oldEdges[oldBinIdx+1] < newEdges[newBinIdx+1] {
			newWeights[newBinIdx] += oldWeights[oldBinIdx]
			oldBinIdx++
		}

		// If the new bin's right edge is between two old edges,
		// add a fraction of the old bin to the current new bin,
		// and the rest to the next new bin.
		oldLeftEdge := oldEdges[oldBinIdx]
		oldRightEdge := oldEdges[oldBinIdx+1]
		newRightEdge := newEdges[newBinIdx+1]

		if newRightEdge <= oldRightEdge {
			frac := (newRightEdge - oldLeftEdge) / (oldRightEdge - oldLeftEdge)

			newWeights[newBinIdx] += frac * oldWeights[oldBinIdx]
			newWeights[min(
				newBinIdx+1,
				len(newWeights)-1,
			)] += (1 - frac) * oldWeights[oldBinIdx]

			oldBinIdx++
		}
	}

	return
}

func reduceEdges(
	desiredBins int,
	oldEdges []float64,
) ([]float64, error) {
	if len(oldEdges) < 1 {
		return nil, errors.New("invalid histogram")
	}

	oldBinCount := len(oldEdges) - 1

	if desiredBins >= oldBinCount {
		return nil, fmt.Errorf(
			"%d is not smaller than %d",
			desiredBins, oldBinCount)
	}

	oldEdgeIdxStep := oldBinCount / desiredBins
	oldEdgeIdxFracStep := oldBinCount % desiredBins

	newEdges := make([]float64, desiredBins+1)
	newEdges[0] = oldEdges[0]
	newEdges[desiredBins] = oldEdges[oldBinCount]

	// Use a fractional index to avoid floating-point arithmetic.
	//
	// Using '/' to denote float division, our position in
	// the oldEdges array is given by
	//     oldEdgeIdx + oldEdgeIdxFrac / desiredBins
	// and it increases by
	//     oldBinCount / desiredBins
	// after each iteration.
	//
	// Using integers avoids precision errors and ensures
	//     oldEdgeIdx = floor(newEdgeIdx * oldBinCount / desiredBins)
	//                < floor(desiredBins * oldBinCount / desiredBins)
	//                = oldBinCount
	//                = len(oldEdges) - 1
	oldEdgeIdx := oldEdgeIdxStep
	oldEdgeIdxFrac := oldEdgeIdxFracStep

	for newEdgeIdx := 1; newEdgeIdx < desiredBins; newEdgeIdx++ {
		oldEdge1 := oldEdges[oldEdgeIdx]
		oldEdge2 := oldEdges[oldEdgeIdx+1] // guaranteed safe, see above

		newEdges[newEdgeIdx] = oldEdge1 +
			(oldEdge2-oldEdge1)*
				(float64(oldEdgeIdxFrac)/float64(desiredBins))

		oldEdgeIdx += oldEdgeIdxStep
		oldEdgeIdxFrac += oldEdgeIdxFracStep
		if oldEdgeIdxFrac >= desiredBins {
			oldEdgeIdx++
			oldEdgeIdxFrac -= desiredBins
		}
	}

	return newEdges, nil
}
