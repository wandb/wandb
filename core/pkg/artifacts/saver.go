package artifacts

import (
	"context"
	"errors"
	"fmt"
	"net/url"
	"os"
	"slices"
	"strconv"
	"strings"
	"sync"
	"time"

	"github.com/Khan/genqlient/graphql"
	"golang.org/x/sync/errgroup"

	"github.com/wandb/wandb/core/internal/filetransfer"
	"github.com/wandb/wandb/core/internal/gql"
	"github.com/wandb/wandb/core/internal/hashencode"
	"github.com/wandb/wandb/core/internal/namedgoroutines"
	"github.com/wandb/wandb/core/internal/nullify"
	"github.com/wandb/wandb/core/internal/observability"
	"github.com/wandb/wandb/core/internal/wboperation"
	spb "github.com/wandb/wandb/core/pkg/service_go_proto"
)

const (
	// uploadBufferPerArtifactName is the number of Save operations
	// that can be queued per artifact name before Save begins to block.
	//
	// The value is high enough so that Save almost never blocks,
	// without consuming too much memory just for bookkeeping.
	uploadBufferPerArtifactName = 32

	// maxSimultaneousUploads is the maximum number of concurrent
	// artifact save operations.
	maxSimultaneousUploads = 128
)

// ArtifactSaveManager manages artifact uploads.
type ArtifactSaveManager struct {
	logger                       *observability.CoreLogger
	graphqlClient                graphql.Client
	fileTransferManager          filetransfer.FileTransferManager
	fileCache                    Cache
	useArtifactProjectEntityInfo bool

	// uploadsByName ensures that uploads for the same artifact name happen
	// serially, so that version numbers are assigned deterministically.
	uploadsByName *namedgoroutines.Operation[*ArtifactSaver]
}

func NewArtifactSaveManager(
	logger *observability.CoreLogger,
	graphqlClient graphql.Client,
	fileTransferManager filetransfer.FileTransferManager,
	useArtifactProjectEntityInfo bool,
) *ArtifactSaveManager {
	workerPool := &errgroup.Group{}
	workerPool.SetLimit(maxSimultaneousUploads)

	return &ArtifactSaveManager{
		logger:                       logger,
		graphqlClient:                graphqlClient,
		fileTransferManager:          fileTransferManager,
		fileCache:                    NewFileCache(UserCacheDir()),
		useArtifactProjectEntityInfo: useArtifactProjectEntityInfo,
		uploadsByName: namedgoroutines.New(
			uploadBufferPerArtifactName,
			workerPool,
			func(saver *ArtifactSaver) {
				artifactID, err := saver.Save()
				saver.resultChan <- ArtifactSaveResult{
					ArtifactID: artifactID,
					Err:        err,
				}
				close(saver.resultChan)
			},
		),
	}
}

type ArtifactSaveResult struct {
	ArtifactID string
	Err        error
}

// Save asynchronously uploads an artifact.
//
// This returns a channel to which the operation result is eventually
// pushed. The channel is guaranteed to receive exactly one value and
// then close.
func (as *ArtifactSaveManager) Save(
	ctx context.Context,
	artifact *spb.ArtifactRecord,
	historyStep int64,
	stagingDir string,
) <-chan ArtifactSaveResult {
	resultChan := make(chan ArtifactSaveResult, 1)

	as.uploadsByName.Go(
		artifact.Name,
		&ArtifactSaver{
			ctx:                          ctx,
			logger:                       as.logger,
			graphqlClient:                as.graphqlClient,
			fileTransferManager:          as.fileTransferManager,
			fileCache:                    as.fileCache,
			artifact:                     artifact,
			historyStep:                  historyStep,
			stagingDir:                   stagingDir,
			maxActiveBatches:             5,
			resultChan:                   resultChan,
			useArtifactProjectEntityInfo: as.useArtifactProjectEntityInfo,
		},
	)

	return resultChan
}

// ArtifactSaver is a save operation for one artifact.
type ArtifactSaver struct {
	// Resources.
	ctx                 context.Context
	logger              *observability.CoreLogger
	graphqlClient       graphql.Client
	fileTransferManager filetransfer.FileTransferManager
	fileCache           Cache
	resultChan          chan<- ArtifactSaveResult

	// Input.
	artifact                     *spb.ArtifactRecord
	historyStep                  int64
	stagingDir                   string
	maxActiveBatches             int
	numTotal                     int
	numDone                      int
	startTime                    time.Time
	useArtifactProjectEntityInfo bool
}

type multipartUploadInfo = []gql.CreateArtifactFilesCreateArtifactFilesCreateArtifactFilesPayloadFilesFileConnectionEdgesFileEdgeNodeFileUploadMultipartUrlsUploadUrlPartsUploadUrlPart
type updateArtifactManifestAttrs = gql.UpdateArtifactManifestUpdateArtifactManifestUpdateArtifactManifestPayloadArtifactManifest

type serverFileResponse struct {
	name            string
	birthArtifactID string
	uploadUrl       *string
	uploadHeaders   []string

	// Used only for multipart uploads.
	uploadID            string
	storagePath         *string
	multipartUploadInfo multipartUploadInfo
}

type uploadResult struct {
	name string
	err  error
}

func (as *ArtifactSaver) createArtifact() (
	attrs gql.CreatedArtifactArtifact,
	rerr error,
) {
	var aliases []gql.ArtifactAliasInput
	for _, alias := range as.artifact.Aliases {
		aliases = append(aliases,
			gql.ArtifactAliasInput{
				ArtifactCollectionName: as.artifact.Name,
				Alias:                  alias,
			},
		)
	}

	var runId *string
	if !as.artifact.UserCreated {
		runId = &as.artifact.RunId
	}

	// Check which fields are actually supported on the input
	inputFieldNames, err := GetGraphQLInputFields(as.ctx, as.graphqlClient, "CreateArtifactInput")
	if err != nil {
		return gql.CreatedArtifactArtifact{}, err
	}

	// Note: if tags are empty, `omitempty` ensures they're nulled out
	// (effectively omitted) in the prepare GraphQL request
	var tags []gql.TagInput
	if slices.Contains(inputFieldNames, "tags") {
		for _, tag := range as.artifact.Tags {
			tags = append(tags, gql.TagInput{TagName: tag})
		}
	}

	input := gql.CreateArtifactInput{
		EntityName:                as.artifact.Entity,
		ProjectName:               as.artifact.Project,
		ArtifactTypeName:          as.artifact.Type,
		ArtifactCollectionName:    as.artifact.Name,
		RunName:                   runId,
		Digest:                    as.artifact.Digest,
		DigestAlgorithm:           gql.ArtifactDigestAlgorithmManifestMd5,
		Description:               nullify.NilIfZero(as.artifact.Description),
		Aliases:                   aliases,
		Tags:                      tags,
		Metadata:                  nullify.NilIfZero(as.artifact.Metadata),
		TtlDurationSeconds:        nullify.NilIfZero(as.artifact.TtlDurationSeconds),
		HistoryStep:               nullify.NilIfZero(as.historyStep),
		EnableDigestDeduplication: true,
		DistributedID:             nullify.NilIfZero(as.artifact.DistributedId),
		ClientID:                  as.artifact.ClientId,
		SequenceClientID:          as.artifact.SequenceClientId,
	}

	response, err := gql.CreateArtifact(as.ctx, as.graphqlClient, input)
	if err != nil {
		return gql.CreatedArtifactArtifact{}, err
	}
	return response.GetCreateArtifact().GetArtifact(), nil
}

type createArtifactManifest = gql.CreateArtifactManifestCreateArtifactManifestCreateArtifactManifestPayloadArtifactManifest

func (as *ArtifactSaver) createManifest(
	artifactId string, baseArtifactId *string, manifestDigest string, includeUpload bool,
) (attrs createArtifactManifest, rerr error) {
	manifestType := gql.ArtifactManifestTypeFull
	manifestFilename := "wandb_manifest.json"
	if as.artifact.IncrementalBeta1 {
		manifestType = gql.ArtifactManifestTypeIncremental
		manifestFilename = "wandb_manifest.incremental.json"
	} else if as.artifact.DistributedId != "" {
		manifestType = gql.ArtifactManifestTypePatch
		manifestFilename = "wandb_manifest.patch.json"
	}

	response, err := gql.CreateArtifactManifest(
		as.ctx,
		as.graphqlClient,
		artifactId,
		baseArtifactId,
		manifestFilename,
		manifestDigest,
		as.artifact.Entity,
		as.artifact.Project,
		as.artifact.RunId,
		manifestType,
		includeUpload,
	)
	if err != nil {
		return createArtifactManifest{}, err
	}
	if response.GetCreateArtifactManifest() == nil {
		return createArtifactManifest{}, errors.New("nil createArtifactManifest")
	}

	return response.GetCreateArtifactManifest().ArtifactManifest, nil
}

func (as *ArtifactSaver) updateManifest(
	artifactManifestId string, manifestDigest string,
) (attrs updateArtifactManifestAttrs, rerr error) {
	response, err := gql.UpdateArtifactManifest(
		as.ctx,
		as.graphqlClient,
		artifactManifestId,
		&manifestDigest,
		nil,
		true,
	)
	if err != nil {
		return updateArtifactManifestAttrs{}, err
	}
	if response == nil || response.GetUpdateArtifactManifest() == nil {
		return updateArtifactManifestAttrs{}, fmt.Errorf("received invalid response from UpdateArtifactManifest")
	}
	return response.GetUpdateArtifactManifest().ArtifactManifest, nil
}

func (as *ArtifactSaver) upsertManifest(
	artifactId string, baseArtifactId *string, artifactManifestId string, manifestDigest string,
) (uploadUrl *string, uploadHeaders []string, rerr error) {
	if as.artifact.IncrementalBeta1 || as.artifact.DistributedId != "" {
		updateManifestAttrs, err := as.updateManifest(artifactManifestId, manifestDigest)
		if err != nil {
			return nil, nil, fmt.Errorf("ArtifactSaver.updateManifest: %w", err)
		}
		return updateManifestAttrs.File.UploadUrl, updateManifestAttrs.File.UploadHeaders, nil
	} else {
		manifestAttrs, err := as.createManifest(artifactId, baseArtifactId, manifestDigest, true /* includeUpload */)
		if err != nil {
			return nil, nil, fmt.Errorf("ArtifactSaver.createManifest: %w", err)
		}
		return manifestAttrs.File.UploadUrl, manifestAttrs.File.UploadHeaders, nil
	}
}

func (as *ArtifactSaver) uploadFiles(
	artifactID string,
	manifest *Manifest,
	manifestID string,
) error {
	// Prepare GQL input for files that (might) need to be uploaded.
	namedFileSpecs := map[string]gql.CreateArtifactFileSpecInput{}
	for name, entry := range manifest.Contents {
		if entry.LocalPath == nil {
			continue
		}
		parts, err := createMultiPartRequest(as.logger, *entry.LocalPath)
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
			as.logger.Warn("some files failed to upload, retrying", "count", len(namedFileSpecs))
		}
	}
	return nil
}

func (as *ArtifactSaver) processFiles(
	manifest *Manifest,
	namedFileSpecs map[string]gql.CreateArtifactFileSpecInput,
) (map[string]gql.CreateArtifactFileSpecInput, error) {
	// Channels to get responses from the batch url retrievers.
	readyChan := make(chan serverFileResponse)
	errorChan := make(chan error)

	doneChan := make(chan uploadResult, len(namedFileSpecs))
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
			entry := manifest.Contents[fileInfo.name]
			entry.BirthArtifactID = &fileInfo.birthArtifactID
			manifest.Contents[fileInfo.name] = entry
			as.cacheEntry(entry)
			if fileInfo.uploadUrl == nil {
				// The server already has this file.
				numActive--
				as.numDone++
				continue
			}
			if fileInfo.multipartUploadInfo != nil {
				partData := namedFileSpecs[fileInfo.name].UploadPartsInput
				go func() {
					doneChan <- as.uploadMultipart(*entry.LocalPath, fileInfo, partData)
				}()
			} else {
				suboperation := wboperation.Get(as.ctx).Subtask(fileInfo.name)
				task := newUploadTask(fileInfo, *entry.LocalPath)
				task.Context = suboperation.Context(as.ctx)
				task.OnComplete = func() {
					suboperation.Finish()
					doneChan <- uploadResult{name: fileInfo.name, err: task.Err}
				}
				as.fileTransferManager.AddTask(task)
			}
		// Listen for completed uploads, adding to the retry list if they failed.
		case result := <-doneChan:
			numActive--
			if result.err != nil {
				mustRetry[result.name] = namedFileSpecs[result.name]
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
		as.ctx, as.graphqlClient, batch, gql.ArtifactStorageLayoutV2,
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
			name:            batch[i].Name,
			birthArtifactID: edge.Node.Artifact.Id,
			uploadUrl:       edge.Node.UploadUrl,
			uploadHeaders:   edge.Node.UploadHeaders,
			storagePath:     edge.Node.StoragePath,
		}
		if edge.Node.UploadMultipartUrls != nil {
			resp.uploadID = edge.Node.UploadMultipartUrls.UploadID
			resp.multipartUploadInfo = edge.Node.UploadMultipartUrls.UploadUrlParts
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

func newUploadTask(
	fileInfo serverFileResponse,
	localPath string,
) *filetransfer.DefaultUploadTask {
	return &filetransfer.DefaultUploadTask{
		FileKind: filetransfer.RunFileKindArtifact,
		Path:     localPath,
		Name:     fileInfo.name,
		Url:      *fileInfo.uploadUrl,
		Headers:  fileInfo.uploadHeaders,
	}
}

func (as *ArtifactSaver) uploadMultipart(
	path string,
	fileInfo serverFileResponse,
	partData []gql.UploadPartsInput,
) uploadResult {
	statInfo, err := os.Stat(path)
	if err != nil {
		return uploadResult{name: fileInfo.name, err: err}
	}
	chunkSize := getChunkSize(statInfo.Size())

	type partResponse struct {
		partNumber int64
		task       *filetransfer.DefaultUploadTask
	}

	wg := sync.WaitGroup{}
	partResponses := make(chan partResponse, len(partData))
	// TODO: add mid-upload cancel.

	contentType := getContentType(fileInfo.uploadHeaders)

	// Record start time for network upload phase
	uploadStartTime := time.Now()

	partInfo := fileInfo.multipartUploadInfo
	for i, part := range partInfo {
		suboperation := wboperation.Get(as.ctx).Subtask(
			fmt.Sprintf(
				"%s (%d/%d)",
				fileInfo.name, i+1, len(partInfo),
			))
		task := newUploadTask(fileInfo, path)
		task.Context = suboperation.Context(as.ctx)
		task.Url = part.UploadUrl
		task.Offset = int64(i) * chunkSize
		remainingSize := statInfo.Size() - task.Offset
		task.Size = min(remainingSize, chunkSize)
		b64md5, err := hashencode.HexToB64(partData[i].HexMD5)
		if err != nil {
			return uploadResult{name: fileInfo.name, err: err}
		}
		task.Headers = []string{
			"Content-Md5:" + b64md5,
			"Content-Length:" + strconv.FormatInt(task.Size, 10),
			"Content-Type:" + contentType,
		}
		task.OnComplete = func() {
			suboperation.Finish()
			partResponses <- partResponse{partNumber: partData[i].PartNumber, task: task}
			wg.Done()
		}
		wg.Add(1)
		as.fileTransferManager.AddTask(task)
	}

	go func() {
		wg.Wait()
		close(partResponses)
	}()

	partEtags := make([]gql.UploadPartsInput, len(partData))

	for t := range partResponses {
		err := t.task.Err
		if err != nil {
			return uploadResult{name: fileInfo.name, err: err}
		}
		if t.task.Response == nil {
			err = fmt.Errorf("no response in task %v", t.task.Name)
			return uploadResult{name: fileInfo.name, err: err}
		}
		etag := ""
		if t.task.Response != nil {
			etag = t.task.Response.Header.Get("ETag")
			if etag == "" {
				err = fmt.Errorf("no ETag in response %v", t.task.Response.Header)
				return uploadResult{name: fileInfo.name, err: err}
			}
		}
		// Part numbers should be unique values from 1 to len(partData).
		if t.partNumber < 1 || t.partNumber > int64(len(partData)) {
			err = fmt.Errorf("invalid part number: %d", t.partNumber)
			return uploadResult{name: fileInfo.name, err: err}
		}
		if partEtags[t.partNumber-1].PartNumber != 0 {
			err = fmt.Errorf("duplicate part number: %d", t.partNumber)
			return uploadResult{name: fileInfo.name, err: err}
		}
		partEtags[t.partNumber-1] = gql.UploadPartsInput{
			PartNumber: t.partNumber,
			HexMD5:     etag,
		}
	}

	_, err = gql.CompleteMultipartUploadArtifact(
		as.ctx, as.graphqlClient, gql.CompleteMultipartActionComplete, partEtags,
		fileInfo.birthArtifactID, *fileInfo.storagePath, fileInfo.uploadID,
	)

	// Log network upload time
	uploadTime := time.Since(uploadStartTime)
	uploadSpeedMBps := float64(statInfo.Size()) / (1024 * 1024) / uploadTime.Seconds()
	as.logger.Debug("Completed multipart upload",
		"fileName", fileInfo.name,
		"uploadTimeMs", uploadTime.Milliseconds(),
		"uploadSpeedMBps", uploadSpeedMBps,
		"numParts", len(partData),
		"fileSize", statInfo.Size(),
		"chunkSize", chunkSize,
	)

	return uploadResult{name: fileInfo.name, err: err}
}

func getContentType(headers []string) string {
	for _, h := range headers {
		if strings.HasPrefix(h, "Content-Type:") {
			return strings.TrimPrefix(h, "Content-Type:")
		}
	}
	return ""
}

func (as *ArtifactSaver) cacheEntry(entry ManifestEntry) {
	if entry.SkipCache {
		return
	}
	path := *entry.LocalPath
	digest := entry.Digest
	go func() {
		if err := as.fileCache.AddFileAndCheckDigest(path, digest); err != nil {
			as.logger.Error("error adding file to cache", "err", err)
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
				response, err := gql.ClientIDMapping(as.ctx, as.graphqlClient, clientId)
				if err != nil {
					return err
				}
				if response.ClientIDMapping == nil {
					return fmt.Errorf("could not resolve client id %v", clientId)
				}
				serverId = response.ClientIDMapping.ServerID
				cache[clientId] = serverId
			}
			serverIdHex, err := hashencode.B64ToHex(serverId)
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

func (as *ArtifactSaver) uploadManifest(
	manifestFile string,
	uploadURL *string,
	uploadHeaders []string,
) error {
	if uploadURL == nil {
		return errors.New("nil uploadURL")
	}

	resultChan := make(chan *filetransfer.DefaultUploadTask, 1)
	task := &filetransfer.DefaultUploadTask{
		FileKind: filetransfer.RunFileKindArtifact,
		Path:     manifestFile,
		Url:      *uploadURL,
		Headers:  uploadHeaders,
	}
	task.OnComplete = func() { resultChan <- task }

	as.fileTransferManager.AddTask(task)
	<-resultChan
	return task.Err
}

func (as *ArtifactSaver) commitArtifact(artifactID string) error {
	_, err := gql.CommitArtifact(
		as.ctx,
		as.graphqlClient,
		artifactID,
	)
	return err
}

func (as *ArtifactSaver) deleteStagingFiles(manifest *Manifest) {
	for _, entry := range manifest.Contents {
		if entry.LocalPath != nil && strings.HasPrefix(*entry.LocalPath, as.stagingDir) {
			// We intentionally ignore errors below.
			_ = os.Chmod(*entry.LocalPath, 0600)
			_ = os.Remove(*entry.LocalPath)
		}
	}
}

// Save performs the upload operation, blocking until it completes.
func (as *ArtifactSaver) Save() (artifactID string, rerr error) {
	manifest, err := NewManifestFromProto(as.artifact.Manifest)
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
	if as.artifact.BaseId != "" {
		baseArtifactId = &as.artifact.BaseId
	} else if artifactAttrs.ArtifactSequence.LatestArtifact != nil {
		baseArtifactId = &artifactAttrs.ArtifactSequence.LatestArtifact.Id
	}

	useArtifactInput := gql.UseArtifactInput{
		ArtifactID:  artifactID,
		EntityName:  as.artifact.Entity,
		ProjectName: as.artifact.Project,
		RunName:     as.artifact.RunId,
	}

	if as.useArtifactProjectEntityInfo {
		useArtifactInput.ArtifactEntityName = &as.artifact.Entity
		useArtifactInput.ArtifactProjectName = &as.artifact.Project
	}

	if artifactAttrs.State == gql.ArtifactStateCommitted {
		if as.artifact.UseAfterCommit {
			var err error
			_, err = gql.UseArtifact(
				as.ctx,
				as.graphqlClient,
				useArtifactInput,
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

	err = as.uploadFiles(artifactID, &manifest, manifestAttrs.Id)
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
	defer func() {
		_ = os.Remove(manifestFile)
	}()

	uploadUrl, uploadHeaders, err := as.upsertManifest(artifactID, baseArtifactId, manifestAttrs.Id, manifestDigest)
	if err != nil {
		return "", fmt.Errorf("ArtifactSaver.upsertManifest: %w", err)
	}

	err = as.uploadManifest(manifestFile, uploadUrl, uploadHeaders)
	if err != nil {
		return "", fmt.Errorf("ArtifactSaver.uploadManifest: %w", err)
	}

	if as.artifact.Finalize {
		err = as.commitArtifact(artifactID)
		if err != nil {
			return "", fmt.Errorf("ArtifactSaver.commitArtifact: %w", err)
		}

		if as.artifact.UseAfterCommit {
			_, err = gql.UseArtifact(
				as.ctx,
				as.graphqlClient,
				useArtifactInput,
			)

			if err != nil {
				return "", fmt.Errorf("gql.UseArtifact: %w", err)
			}
		}
	}

	return artifactID, nil
}
