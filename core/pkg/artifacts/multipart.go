package artifacts

import (
	"context"
	"fmt"
	"io"
	"math"
	"os"
	"runtime"
	"time"

	"github.com/wandb/wandb/core/internal/gql"
	"github.com/wandb/wandb/core/internal/hashencode"
	"github.com/wandb/wandb/core/internal/observability"
	"golang.org/x/sync/errgroup"
)

const (
	S3MinMultiUploadSize = 2 << 30   // 2 GiB, the threshold we've chosen to switch to multipart
	S3MaxMultiUploadSize = 5 << 40   // 5 TiB, maximum possible object size
	S3DefaultChunkSize   = 100 << 20 // 100 MiB
	S3MaxParts           = 10000
)

// createMultiPartRequest checks if the file size is large enough to use multipart upload.
// If so, it computes the hash of each parts required for getting multipart upload url from server.
// Otherwise, it returns nil, which is a valid input for the graphql CreateArtifactFileSpecInput.
func createMultiPartRequest(
	logger *observability.CoreLogger,
	path string,
) ([]gql.UploadPartsInput, error) {
	fileInfo, err := os.Stat(path)
	if err != nil {
		return nil, fmt.Errorf("failed to get file size for path %s: %v", path, err)
	}
	fileSize := fileInfo.Size()

	// Small or empty file. Empty file is supported by artifact and should NOT trigger multipart.
	if fileSize < S3MinMultiUploadSize {
		// We don't need to use multipart for small files.
		return nil, nil
	}
	if fileSize > S3MaxMultiUploadSize {
		return nil, fmt.Errorf("file size exceeds maximum S3 object size: %v", fileSize)
	}

	return computeMultipartHashes(logger, path, fileSize, getChunkSize(fileSize), runtime.NumCPU())
}

func getChunkSize(fileSize int64) int64 {
	if fileSize < S3DefaultChunkSize*S3MaxParts {
		return S3DefaultChunkSize
	}
	// Use a larger chunk size if we would need more than 10,000 chunks.
	chunkSize := int64(math.Ceil(float64(fileSize) / float64(S3MaxParts)))
	// Round up to the nearest multiple of 4096.
	chunkSize = int64(math.Ceil(float64(chunkSize)/4096) * 4096)
	return chunkSize
}

// computeMultipartHashes split tasks for workers and wait until all workers finish or one of them fails.
func computeMultipartHashes(
	logger *observability.CoreLogger,
	path string,
	fileSize int64,
	chunkSize int64,
	numWorkers int,
) ([]gql.UploadPartsInput, error) {
	if numWorkers < 1 {
		return nil, fmt.Errorf("number of workers is less than 1: %d", numWorkers)
	}
	if chunkSize < 1 {
		return nil, fmt.Errorf("chunk size is less than 1: %d", chunkSize)
	}
	if fileSize < chunkSize {
		return nil, fmt.Errorf("file size is less than chunk size: %d < %d", fileSize, chunkSize)
	}

	numParts := int(fileSize / chunkSize)
	if fileSize%chunkSize != 0 {
		numParts++
	}
	numWorkers = min(numWorkers, numParts)
	workerTasks := splitHashTasks(numParts, numWorkers)
	partsInfo := make([]gql.UploadPartsInput, numParts)

	startTime := time.Now()
	ctx := context.Background() // TODO: Refactor ArtifactSaver to pass in a context for all the long running operations
	g, ctx := errgroup.WithContext(ctx)
	for i, task := range workerTasks {
		g.Go(func() error {
			worker := multipartHashWorker{
				id:        i,
				path:      path,
				fileSize:  fileSize,
				chunkSize: chunkSize,
			}
			return worker.hashFileParts(ctx, task, partsInfo)
		})
	}

	if err := g.Wait(); err != nil {
		return nil, err
	}

	hashTime := time.Since(startTime)
	hashSpeedMBps := float64(fileSize) / (1024 * 1024) / hashTime.Seconds()
	logger.Debug("Computed multipart hashes",
		"hashTimeMs", hashTime.Milliseconds(),
		"hashSpeedMBps", hashSpeedMBps,
		"numWorkers", numWorkers,
		"numParts", len(partsInfo),
		"fileSize", fileSize,
		"chunkSize", chunkSize,
	)
	return partsInfo, nil
}

type hashWorkerTask struct {
	startPart int // inclusive
	endPart   int // exclusive
}

// splitHashTasks distributes parts evenly among workers for parallel processing.
// If parts cannot be divided evenly, extra parts are distributed to earlier workers.
func splitHashTasks(numParts int, numWorkers int) []hashWorkerTask {
	partsPerWorker := numParts / numWorkers
	workersWithOneMorePart := numParts % numWorkers

	var workerTasks []hashWorkerTask
	// NOTE: We start from 0, and only switch to 1-indexed when assiging the partNumber for server request
	for i := range numWorkers {
		var start, end int
		if i < workersWithOneMorePart {
			start = (partsPerWorker + 1) * i // All the previous workers get one more part
			end = start + partsPerWorker + 1
		} else {
			start = workersWithOneMorePart + partsPerWorker*i
			end = start + partsPerWorker
		}
		workerTasks = append(workerTasks, hashWorkerTask{
			startPart: start,
			endPart:   end,
		})
	}
	return workerTasks
}

type multipartHashWorker struct {
	id        int
	path      string
	fileSize  int64
	chunkSize int64
}

// hashFileParts hash the md5 of consecutive parts of the file in serial.
func (worker *multipartHashWorker) hashFileParts(
	ctx context.Context,
	task hashWorkerTask,
	partsInfo []gql.UploadPartsInput,
) error {
	// One open file per worker so they seek in sequential order within its own file handler
	// instead of jumping around by different workers. Might make file system's life easier (not benchmarked).
	file, err := os.Open(worker.path)
	if err != nil {
		return fmt.Errorf("worker %d failed to open file: %w", worker.id, err)
	}
	defer file.Close()

	for part := task.startPart; part < task.endPart; part++ {
		// Return early if other worker had error
		select {
		case <-ctx.Done():
			return ctx.Err()
		default:
		}

		offset := int64(part) * worker.chunkSize
		partSize := min(worker.chunkSize, worker.fileSize-offset)
		hexMD5, err := hashencode.ComputeReaderHexMD5(io.NewSectionReader(file, offset, partSize))
		if err != nil {
			return fmt.Errorf("worker %d failed to compute hash for part %d: %w", worker.id, part, err)
		}

		// Each worker is updating different index of the partsInfo slice so there is no race condition.
		partsInfo[part] = gql.UploadPartsInput{
			// Server request uses 1-indexed part numbers.
			// https://cloud.google.com/storage/docs/xml-api/put-object-multipart#query_string_parameters
			// https://docs.aws.amazon.com/AmazonS3/latest/userguide/mpuoverview.html#:~:text=You%20can%20choose%20any%20part%20number%20between%201%20and%2010%2C000
			PartNumber: int64(part + 1),
			HexMD5:     hexMD5,
		}
	}

	return nil
}
