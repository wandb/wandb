package artifacts

import (
	"context"
	"fmt"
	"io"
	"math"
	"net/url"
	"os"
	"strconv"
	"strings"
	"sync"
	"time"

	"github.com/Khan/genqlient/graphql"

	"github.com/wandb/wandb/core/internal/filetransfer"
	"github.com/wandb/wandb/core/internal/gql"
	"github.com/wandb/wandb/core/pkg/observability"
	"github.com/wandb/wandb/core/pkg/service"
	"github.com/wandb/wandb/core/pkg/utils"
)

type ArtifactSaver struct {
	// Resources.
	Ctx                 context.Context
	Logger              *observability.CoreLogger
	GraphqlClient       graphql.Client
	FileTransferManager filetransfer.FileTransferManager
	FileCache           Cache
	// Input.
	Artifact         *service.ArtifactRecord
	HistoryStep      int64
	StagingDir       string
	maxActiveBatches int
	numTotal         int
	numDone          int
	startTime        time.Time
}

type MultipartUploadInfo = []gql.CreateArtifactFilesCreateArtifactFilesCreateArtifactFilesPayloadFilesFileConnectionEdgesFileEdgeNodeFileUploadMultipartUrlsUploadUrlPartsUploadUrlPart

type serverFileResponse struct {
	Name            string
	BirthArtifactID string
	UploadUrl       *string
	UploadHeaders   []string

	// Used only for multipart uploads.
	UploadID            string
	StoragePath         *string
	MultipartUploadInfo MultipartUploadInfo
}

func NewArtifactSaver(
	ctx context.Context,
	logger *observability.CoreLogger,
	graphQLClient graphql.Client,
	uploadManager filetransfer.FileTransferManager,
	artifact *service.ArtifactRecord,
	historyStep int64,
	stagingDir string,
) ArtifactSaver {
	return ArtifactSaver{
		Ctx:                 ctx,
		Logger:              logger,
		GraphqlClient:       graphQLClient,
		FileTransferManager: uploadManager,
		FileCache:           NewFileCache(UserCacheDir()),
		Artifact:            artifact,
		HistoryStep:         historyStep,
		StagingDir:          stagingDir,
		maxActiveBatches:    5,
	}
}

func (as *ArtifactSaver) createArtifact() (
	attrs gql.CreateArtifactCreateArtifactCreateArtifactPayloadArtifact,
	rerr error,
) {
	var aliases []gql.ArtifactAliasInput
	for _, alias := range as.Artifact.Aliases {
		aliases = append(aliases,
			gql.ArtifactAliasInput{
				ArtifactCollectionName: as.Artifact.Name,
				Alias:                  alias,
			},
		)
	}

	var runId *string
	if !as.Artifact.UserCreated {
		runId = &as.Artifact.RunId
	}

	response, err := gql.CreateArtifact(
		as.Ctx,
		as.GraphqlClient,
		as.Artifact.Entity,
		as.Artifact.Project,
		as.Artifact.Type,
		as.Artifact.Name,
		runId,
		as.Artifact.Digest,
		utils.NilIfZero(as.Artifact.Description),
		aliases,
		utils.NilIfZero(as.Artifact.Metadata),
		utils.NilIfZero(as.Artifact.TtlDurationSeconds),
		utils.NilIfZero(as.HistoryStep),
		utils.NilIfZero(as.Artifact.DistributedId),
		as.Artifact.ClientId,
		as.Artifact.SequenceClientId,
	)
	if err != nil {
		return gql.CreateArtifactCreateArtifactCreateArtifactPayloadArtifact{}, err
	}
	return response.GetCreateArtifact().GetArtifact(), nil
}

func (as *ArtifactSaver) createManifest(
	artifactId string, baseArtifactId *string, manifestDigest string, includeUpload bool,
) (attrs gql.CreateArtifactManifestCreateArtifactManifestCreateArtifactManifestPayloadArtifactManifest, rerr error) {
	manifestType := gql.ArtifactManifestTypeFull
	manifestFilename := "wandb_manifest.json"
	if as.Artifact.IncrementalBeta1 {
		manifestType = gql.ArtifactManifestTypeIncremental
		manifestFilename = "wandb_manifest.incremental.json"
	} else if as.Artifact.DistributedId != "" {
		manifestType = gql.ArtifactManifestTypePatch
		manifestFilename = "wandb_manifest.patch.json"
	}

	response, err := gql.CreateArtifactManifest(
		as.Ctx,
		as.GraphqlClient,
		artifactId,
		baseArtifactId,
		manifestFilename,
		manifestDigest,
		as.Artifact.Entity,
		as.Artifact.Project,
		as.Artifact.RunId,
		manifestType,
		includeUpload,
	)
	if err != nil {
		return gql.CreateArtifactManifestCreateArtifactManifestCreateArtifactManifestPayloadArtifactManifest{}, err
	}
	return response.GetCreateArtifactManifest().ArtifactManifest, nil
}

func (as *ArtifactSaver) uploadFiles(
	artifactID string, manifest *Manifest, manifestID string, _ chan<- *service.Record,
) error {
	// Prepare GQL input for files that (might) need to be uploaded.
	namedFileSpecs := map[string]gql.CreateArtifactFileSpecInput{}
	for name, entry := range manifest.Contents {
		if entry.LocalPath == nil {
			continue
		}
		parts, err := multiPartRequest(*entry.LocalPath)
		if err != nil {
			return err
		}
		fileSpec := gql.CreateArtifactFileSpecInput{
			ArtifactID:         artifactID,
			Name:               name,
			Md5:                entry.Digest,
			ArtifactManifestID: &manifestID,
			UploadPartsInput:   parts,
		}
		namedFileSpecs[name] = fileSpec
	}
	as.numTotal = len(namedFileSpecs)

	as.startTime = time.Now()
	var err error
	for len(namedFileSpecs) > 0 {
		numNeedUploading := len(namedFileSpecs)
		if namedFileSpecs, err = as.processFiles(manifest, namedFileSpecs); err != nil {
			return err
		}
		// If more than half of the remaining files uploaded we'll keep retrying.
		// We shouldn't ordinarily need to retry at all: our internal client handles
		// retryable errors, and the only failure this retry loop is for is when signed
		// urls expire before an upload was started (exceedingly rare).
		// Still, as long as more than half of them succeed in each iteration this will
		// eventually terminate, so we're generous with our retry policy.
		if len(namedFileSpecs) > numNeedUploading/2 {
			return fmt.Errorf(
				"most remaining uploads (%d/%d) have failed, giving up",
				len(namedFileSpecs), numNeedUploading,
			)
		}
		if len(namedFileSpecs) > 0 {
			as.Logger.Warn("some files failed to upload, retrying", "count", len(namedFileSpecs))
		}
	}
	return nil
}

func (as *ArtifactSaver) processFiles(
	manifest *Manifest, namedFileSpecs map[string]gql.CreateArtifactFileSpecInput,
) (map[string]gql.CreateArtifactFileSpecInput, error) {
	// Channels to get responses from the batch url retrievers.
	readyChan := make(chan serverFileResponse)
	errorChan := make(chan error)

	doneChan := make(chan *filetransfer.Task)
	mustRetry := map[string]gql.CreateArtifactFileSpecInput{}

	numActive := 0

	var batch []gql.CreateArtifactFileSpecInput
	fileSpecs := []gql.CreateArtifactFileSpecInput{}
	for _, spec := range namedFileSpecs {
		fileSpecs = append(fileSpecs, spec)
	}

	for as.numDone+len(mustRetry) < as.numTotal {
		// Start new batches until we get to the desired number of active uploads.
		for len(fileSpecs) > 0 && numActive <= (as.maxActiveBatches-1)*as.batchSize() {
			batch, fileSpecs = as.nextBatch(fileSpecs)
			numActive += len(batch)
			go as.batchFileDataRetriever(batch, readyChan, errorChan)
		}
		select {
		// Start any uploads that are ready.
		case fileInfo := <-readyChan:
			entry := manifest.Contents[fileInfo.Name]
			entry.BirthArtifactID = &fileInfo.BirthArtifactID
			manifest.Contents[fileInfo.Name] = entry
			as.cacheEntry(entry)
			if fileInfo.UploadUrl == nil {
				// The server already has this file.
				numActive--
				as.numDone++
				continue
			}
			if fileInfo.MultipartUploadInfo != nil {
				partData := namedFileSpecs[fileInfo.Name].UploadPartsInput
				go as.uploadMultipart(*entry.LocalPath, fileInfo, partData, doneChan)
			} else {
				task := newUploadTask(fileInfo, *entry.LocalPath)
				task.SetCompletionCallback(func(t *filetransfer.Task) { doneChan <- t })
				as.FileTransferManager.AddTask(task)
			}
		// Listen for completed uploads, adding to the retry list if they failed.
		case result := <-doneChan:
			numActive--
			if result.Err != nil {
				mustRetry[result.Name] = namedFileSpecs[result.Name]
			} else {
				as.numDone++
			}
		// Check for errors.
		case err := <-errorChan:
			return nil, err
		}
	}
	return mustRetry, nil
}

// batchFileDataRetriever takes a batch of file specs, requests upload URLs for each file,
// assembles the info needed for the next step, and feeds them into an output channel.
func (as *ArtifactSaver) batchFileDataRetriever(
	batch []gql.CreateArtifactFileSpecInput,
	resultChan chan<- serverFileResponse,
	errorChan chan<- error,
) {
	response, err := gql.CreateArtifactFiles(
		as.Ctx, as.GraphqlClient, batch, gql.ArtifactStorageLayoutV2,
	)
	if err != nil {
		errorChan <- fmt.Errorf("requesting upload URLs failed: %v", err)
		return
	}
	batchDetails := response.CreateArtifactFiles.Files.Edges
	if len(batch) != len(batchDetails) {
		errorChan <- fmt.Errorf("expected %v upload URLs, got %v", len(batch), len(batchDetails))
		return
	}
	for i, edge := range batchDetails {
		resp := serverFileResponse{
			Name:            batch[i].Name,
			BirthArtifactID: edge.Node.Artifact.Id,
			UploadUrl:       edge.Node.UploadUrl,
			UploadHeaders:   edge.Node.UploadHeaders,
			StoragePath:     edge.Node.StoragePath,
		}
		if edge.Node.UploadMultipartUrls != nil {
			resp.UploadID = edge.Node.UploadMultipartUrls.UploadID
			resp.MultipartUploadInfo = edge.Node.UploadMultipartUrls.UploadUrlParts
		}
		resultChan <- resp
	}
}

func (as *ArtifactSaver) nextBatch(
	fileSpecs []gql.CreateArtifactFileSpecInput,
) ([]gql.CreateArtifactFileSpecInput, []gql.CreateArtifactFileSpecInput) {
	batchSize := min(as.batchSize(), len(fileSpecs))
	return fileSpecs[:batchSize], fileSpecs[batchSize:]
}

func (as *ArtifactSaver) batchSize() int {
	// We want to keep the number of pending uploads under the concurrency limit until
	// we know how fast they upload.
	minBatchSize := filetransfer.DefaultConcurrencyLimit / as.maxActiveBatches
	maxBatchSize := 10000 / as.maxActiveBatches
	sinceStart := time.Since(as.startTime)
	if as.numDone < filetransfer.DefaultConcurrencyLimit || sinceStart < 1*time.Second {
		return minBatchSize
	}
	// Given the average time per item, estimate a batch size that will take 1 minute.
	filesPerMin := int(float64(as.numDone) / sinceStart.Minutes())
	return max(min(maxBatchSize, filesPerMin), minBatchSize)
}

func newUploadTask(fileInfo serverFileResponse, localPath string) *filetransfer.Task {
	return &filetransfer.Task{
		FileKind: filetransfer.RunFileKindArtifact,
		Type:     filetransfer.UploadTask,
		Path:     localPath,
		Name:     fileInfo.Name,
		Url:      *fileInfo.UploadUrl,
		Headers:  fileInfo.UploadHeaders,
	}
}

const (
	S3MinMultiUploadSize = 2 << 30 // 2 GiB, the threshold we've chosen to switch to multipart
	S3MaxMultiUploadSize = 5 << 40 // 5 TiB, maximum possible object size
	S3MaxParts           = 10000
)

func multiPartRequest(path string) ([]gql.UploadPartsInput, error) {
	fileInfo, err := os.Stat(path)
	if err != nil {
		return nil, fmt.Errorf("failed to get file size for path %s: %w", path, err)
	}
	fileSize := fileInfo.Size()

	if fileSize < S3MinMultiUploadSize {
		// We don't need to use multipart for small files.
		return nil, nil
	}
	if fileSize > S3MaxMultiUploadSize {
		return nil, fmt.Errorf("file size exceeds maximum S3 object size: %v", fileSize)
	}

	file, err := os.Open(path)
	if err != nil {
		return nil, err
	}
	defer file.Close()

	partsInfo := []gql.UploadPartsInput{}
	partNumber := int64(0)
	buffer := make([]byte, getChunkSize(fileSize))
	for {
		bytesRead, err := file.Read(buffer)
		if err != nil && err != io.EOF {
			return nil, err
		}
		if bytesRead == 0 {
			break
		}
		partsInfo = append(partsInfo, gql.UploadPartsInput{
			PartNumber: partNumber,
			HexMD5:     utils.ComputeHexMD5(buffer[:bytesRead]),
		})
		partNumber++
	}
	return partsInfo, nil
}

func (as *ArtifactSaver) uploadMultipart(
	path string,
	fileInfo serverFileResponse,
	partData []gql.UploadPartsInput,
	doneChan chan<- *filetransfer.Task,
) {
	statInfo, err := os.Stat(path)
	if err != nil {
		doneChan <- &filetransfer.Task{Err: err}
		return
	}
	chunkSize := getChunkSize(statInfo.Size())

	wg := sync.WaitGroup{}
	subChan := make(chan *filetransfer.Task)
	// TODO: add mid-upload cancel.

	partInfo := fileInfo.MultipartUploadInfo
	for i, part := range partInfo {
		task := newUploadTask(fileInfo, path)
		task.Offset = part.PartNumber * chunkSize
		remainingSize := statInfo.Size() - task.Offset
		if remainingSize < chunkSize {
			task.Size = remainingSize
		} else {
			task.Size = chunkSize
		}
		task.Headers = append(task.Headers, "content-md5:"+partData[i].HexMD5)
		task.Headers = append(task.Headers, "content-length:"+strconv.FormatInt(task.Size, 10))
		task.SetCompletionCallback(func(t *filetransfer.Task) {
			subChan <- t
			wg.Done()
		})
		wg.Add(1)
		as.FileTransferManager.AddTask(task)
	}

	go func() {
		wg.Wait()
		close(subChan)
	}()

	for t := range subChan {
		if t.Err != nil {
			doneChan <- t
			return
		}
	}
	_, err = gql.CompleteMultipartUploadArtifact(
		as.Ctx, as.GraphqlClient, gql.CompleteMultipartActionComplete, partData,
		fileInfo.BirthArtifactID, *fileInfo.StoragePath, fileInfo.UploadID,
	)
	task := newUploadTask(fileInfo, path)
	task.Err = err
	doneChan <- task
}

func getChunkSize(fileSize int64) int64 {
	// Default to 100MiB chunks
	const defaultChunkSize = int64(100 * 1024 * 1024)
	if fileSize < defaultChunkSize*S3MaxParts {
		return defaultChunkSize
	}
	// Use a larger chunk size if we would need more than 10,000 chunks.
	chunkSize := int64(math.Ceil(float64(fileSize) / float64(S3MaxParts)))
	chunkSize = int64(math.Ceil(float64(chunkSize)/4096) * 4096) // Round up to the nearest multiple of 4096.
	return chunkSize
}

func (as *ArtifactSaver) cacheEntry(entry ManifestEntry) {
	if entry.SkipCache {
		return
	}
	path := *entry.LocalPath
	digest := entry.Digest
	go func() {
		if err := as.FileCache.AddFileAndCheckDigest(path, digest); err != nil {
			as.Logger.Error("error adding file to cache", "err", err)
		}
	}()
}

func (as *ArtifactSaver) resolveClientIDReferences(manifest *Manifest) error {
	cache := map[string]string{}
	for name, entry := range manifest.Contents {
		if entry.Ref != nil && strings.HasPrefix(*entry.Ref, "wandb-client-artifact:") {
			refParsed, err := url.Parse(*entry.Ref)
			if err != nil {
				return err
			}
			clientId, path := refParsed.Host, strings.TrimPrefix(refParsed.Path, "/")
			serverId, ok := cache[clientId]
			if !ok {
				response, err := gql.ClientIDMapping(as.Ctx, as.GraphqlClient, clientId)
				if err != nil {
					return err
				}
				if response.ClientIDMapping == nil {
					return fmt.Errorf("could not resolve client id %v", clientId)
				}
				serverId = response.ClientIDMapping.ServerID
				cache[clientId] = serverId
			}
			serverIdHex, err := utils.B64ToHex(serverId)
			if err != nil {
				return err
			}
			resolvedRef := "wandb-artifact://" + serverIdHex + "/" + path
			entry.Ref = &resolvedRef
			manifest.Contents[name] = entry
		}
	}
	return nil
}

func (as *ArtifactSaver) uploadManifest(manifestFile string, uploadUrl *string, uploadHeaders []string, _ chan<- *service.Record) error {
	resultChan := make(chan *filetransfer.Task)
	task := &filetransfer.Task{
		FileKind: filetransfer.RunFileKindArtifact,
		Type:     filetransfer.UploadTask,
		Path:     manifestFile,
		Url:      *uploadUrl,
		Headers:  uploadHeaders,
	}
	task.SetCompletionCallback(
		func(t *filetransfer.Task) {
			resultChan <- t
		},
	)

	as.FileTransferManager.AddTask(task)
	<-resultChan
	return task.Err
}

func (as *ArtifactSaver) commitArtifact(artifactID string) error {
	_, err := gql.CommitArtifact(
		as.Ctx,
		as.GraphqlClient,
		artifactID,
	)
	return err
}

func (as *ArtifactSaver) deleteStagingFiles(manifest *Manifest) {
	for _, entry := range manifest.Contents {
		if entry.LocalPath != nil && strings.HasPrefix(*entry.LocalPath, as.StagingDir) {
			// We intentionally ignore errors below.
			_ = os.Chmod(*entry.LocalPath, 0600)
			_ = os.Remove(*entry.LocalPath)
		}
	}
}

func (as *ArtifactSaver) Save(ch chan<- *service.Record) (artifactID string, rerr error) {
	manifest, err := NewManifestFromProto(as.Artifact.Manifest)
	if err != nil {
		return "", err
	}

	defer as.deleteStagingFiles(&manifest)

	artifactAttrs, err := as.createArtifact()
	if err != nil {
		return "", fmt.Errorf("ArtifactSaver.createArtifact: %w", err)
	}
	artifactID = artifactAttrs.Id
	var baseArtifactId *string
	if as.Artifact.BaseId != "" {
		baseArtifactId = &as.Artifact.BaseId
	} else if artifactAttrs.ArtifactSequence.LatestArtifact != nil {
		baseArtifactId = &artifactAttrs.ArtifactSequence.LatestArtifact.Id
	}
	if artifactAttrs.State == gql.ArtifactStateCommitted {
		if as.Artifact.UseAfterCommit {
			_, err := gql.UseArtifact(
				as.Ctx,
				as.GraphqlClient,
				as.Artifact.Entity,
				as.Artifact.Project,
				as.Artifact.RunId,
				artifactID,
			)
			if err != nil {
				return "", fmt.Errorf("gql.UseArtifact: %w", err)
			}
		}
		return artifactID, nil
	}
	// DELETED is for old servers, see https://github.com/wandb/wandb/pull/6190
	if artifactAttrs.State != gql.ArtifactStatePending && artifactAttrs.State != gql.ArtifactStateDeleted {
		return "", fmt.Errorf("unexpected artifact state %v", artifactAttrs.State)
	}

	manifestAttrs, err := as.createManifest(
		artifactID, baseArtifactId, "" /* manifestDigest */, false, /* includeUpload */
	)
	if err != nil {
		return "", fmt.Errorf("ArtifactSaver.createManifest: %w", err)
	}

	err = as.uploadFiles(artifactID, &manifest, manifestAttrs.Id, ch)
	if err != nil {
		return "", fmt.Errorf("ArtifactSaver.uploadFiles: %w", err)
	}

	err = as.resolveClientIDReferences(&manifest)
	if err != nil {
		return "", fmt.Errorf("ArtifactSaver.resolveClientIDReferences: %w", err)
	}
	// TODO: check if size is needed
	manifestFile, manifestDigest, _, err := manifest.WriteToFile()
	if err != nil {
		return "", fmt.Errorf("ArtifactSaver.writeManifest: %w", err)
	}
	defer os.Remove(manifestFile)
	manifestAttrs, err = as.createManifest(artifactID, baseArtifactId, manifestDigest, true /* includeUpload */)
	if err != nil {
		return "", fmt.Errorf("ArtifactSaver.createManifest: %w", err)
	}
	err = as.uploadManifest(manifestFile, manifestAttrs.File.UploadUrl, manifestAttrs.File.UploadHeaders, ch)
	if err != nil {
		return "", fmt.Errorf("ArtifactSaver.uploadManifest: %w", err)
	}

	if as.Artifact.Finalize {
		err = as.commitArtifact(artifactID)
		if err != nil {
			return "", fmt.Errorf("ArtifactSaver.commitArtifact: %w", err)
		}

		if as.Artifact.UseAfterCommit {
			_, err = gql.UseArtifact(
				as.Ctx,
				as.GraphqlClient,
				as.Artifact.Entity,
				as.Artifact.Project,
				as.Artifact.RunId,
				artifactID,
			)
			if err != nil {
				return "", fmt.Errorf("gql.UseArtifact: %w", err)
			}
		}
	}

	return artifactID, nil
}
