package filetransfer

import (
	"context"
	"fmt"
	"os"
)

// httpRange is http range header. Both start and end are inclusive
// https://developer.mozilla.org/en-US/docs/Web/HTTP/Reference/Headers/Range
type httpRange struct {
	start int64 // inclusive
	end   int64 // exclusive
}

// SplitHttpRanges splits the file into multiple http ranges for making parallel requests.
func SplitHttpRanges(fileSize int64, partSize int64) []httpRange {
	numRanges := int(fileSize / partSize)
	if fileSize%partSize != 0 {
		numRanges++
	}
	ranges := make([]httpRange, numRanges)
	for i := range ranges {
		start := int64(i) * partSize
		end := min(start+partSize-1, fileSize-1)
		ranges[i] = httpRange{
			start: start,
			end:   end,
		}
	}
	return ranges
}

// WorkerTaskRange allocates tasks to a worker using [SplitWorkerTasks]
type WorkerTaskRange struct {
	Start int // inclusive
	End   int // exclusive
}

// SplitWorkerTasks distributes tasks evenly among workers for parallel processing.
// If tasks cannot be divided evenly, extra tasks are distributed to earlier workers.
// If there are fewer tasks than workers, number of workers would be same as number of tasks
// instead of the max number of workers.
func SplitWorkerTasks(numTasks int, maxNumWorkers int) ([]WorkerTaskRange, error) {
	// No work is error to force caller to short circuit.
	if numTasks <= 0 {
		return nil, fmt.Errorf("numTasks must be greater than 0")
	}
	// 0 worker is likely configuration error from caller.
	if maxNumWorkers <= 0 {
		return nil, fmt.Errorf("maxNumWorkers must be greater than 0")
	}
	numWorkers := min(numTasks, maxNumWorkers)

	tasksPerWorker := numTasks / numWorkers
	workersWithOneMoreTask := numTasks % numWorkers

	var workerTasks []WorkerTaskRange
	for i := range numWorkers {
		var start, end int
		if i < workersWithOneMoreTask {
			start = (tasksPerWorker + 1) * i // All the previous workers get one more task
			end = start + tasksPerWorker + 1
		} else {
			start = workersWithOneMoreTask + tasksPerWorker*i
			end = start + tasksPerWorker
		}

		workerTasks = append(workerTasks, WorkerTaskRange{
			Start: start,
			End:   end,
		})
	}
	return workerTasks, nil
}

var _ WriterAt = (*os.File)(nil)

// WriterAt allow passing mock file to simulate file write error.
type WriterAt interface {
	// WriteAt is more efficient than doing a seek and write.
	// https://stackoverflow.com/questions/41781840/go-seekwrite-vs-writeat-performance
	WriteAt(p []byte, off int64) (n int, err error)
}

// FileChunk is streamed out from http response body to avoid buffering entire response
// body in memory before start writing to file. Offset indicate where to write at in file.
type FileChunk struct {
	Offset int64
	Data   []byte
}

func WriteChunksToFile(ctx context.Context, file WriterAt, chunkChan <-chan *FileChunk) error {
	for {
		select {
		case buf, ok := <-chunkChan:
			if !ok {
				// Channel closed, all buffers from all download workers are written
				// Closing file is handled by caller, we just write.
				return nil
			}
			_, err := file.WriteAt(buf.Data, buf.Offset)
			if err != nil {
				return err
			}
		case <-ctx.Done():
			return ctx.Err()
		}
	}
}
