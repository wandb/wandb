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
	spb "github.com/wandb/wandb/core/pkg/service_go_proto"
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
	Artifact         *spb.ArtifactRecord
	HistoryStep      int64
	StagingDir       string
	maxActiveBatches int
	numTotal         int
	numDone          int
	startTime        time.Time
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

func NewArtifactSaver(
	ctx context.Context,
	logger *observability.CoreLogger,
	graphQLClient graphql.Client,
	uploadManager filetransfer.FileTransferManager,
	artifact *spb.ArtifactRecord,
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

func (as *ArtifactSaver) updateManifest(
	artifactManifestId string, manifestDigest string,
) (attrs updateArtifactManifestAttrs, rerr error) {
	response, err := gql.UpdateArtifactManifest(
		as.Ctx,
		as.GraphqlClient,
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
	if as.Artifact.IncrementalBeta1 || as.Artifact.DistributedId != "" {
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
				task := newUploadTask(fileInfo, *entry.LocalPath)
				task.OnComplete = func() {
					doneChan <- uploadResult{name: fileInfo.name, err: task.Err}
				}
				as.FileTransferManager.AddTask(task)
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

func newUploadTask(fileInfo serverFileResponse, localPath string) *filetransfer.DefaultUploadTask {
	return &filetransfer.DefaultUploadTask{
		FileKind: filetransfer.RunFileKindArtifact,
		Path:     localPath,
		Name:     fileInfo.name,
		Url:      *fileInfo.uploadUrl,
		Headers:  fileInfo.uploadHeaders,
	}
}

const (
	S3MinMultiUploadSize = 2 << 30   // 2 GiB, the threshold we've chosen to switch to multipart
	S3MaxMultiUploadSize = 5 << 40   // 5 TiB, maximum possible object size
	S3DefaultChunkSize   = 100 << 20 // 1 MiB
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
	partNumber := int64(1)
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

	contentType, err := getContentType(fileInfo.uploadHeaders)
	if err != nil {
		return uploadResult{name: fileInfo.name, err: err}
	}

	partInfo := fileInfo.multipartUploadInfo
	for i, part := range partInfo {
		task := newUploadTask(fileInfo, path)
		task.Url = part.UploadUrl
		task.Offset = int64(i) * chunkSize
		remainingSize := statInfo.Size() - task.Offset
		task.Size = min(remainingSize, chunkSize)
		b64md5, err := utils.HexToB64(partData[i].HexMD5)
		if err != nil {
			return uploadResult{name: fileInfo.name, err: err}
		}
		task.Headers = []string{
			"Content-Md5:" + b64md5,
			"Content-Length:" + strconv.FormatInt(task.Size, 10),
			"Content-Type:" + contentType,
		}
		task.OnComplete = func() {
			partResponses <- partResponse{partNumber: partData[i].PartNumber, task: task}
			wg.Done()
		}
		wg.Add(1)
		as.FileTransferManager.AddTask(task)
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
		as.Ctx, as.GraphqlClient, gql.CompleteMultipartActionComplete, partEtags,
		fileInfo.birthArtifactID, *fileInfo.storagePath, fileInfo.uploadID,
	)
	return uploadResult{name: fileInfo.name, err: err}
}

func getContentType(headers []string) (string, error) {
	for _, h := range headers {
		if strings.HasPrefix(h, "Content-Type:") {
			return strings.TrimPrefix(h, "Content-Type:"), nil
		}
	}
	return "", fmt.Errorf("content-type header is required for multipart uploads")
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

func (as *ArtifactSaver) uploadManifest(
	manifestFile string,
	uploadUrl *string,
	uploadHeaders []string,
) error {
	resultChan := make(chan *filetransfer.DefaultUploadTask)
	task := &filetransfer.DefaultUploadTask{
		FileKind: filetransfer.RunFileKindArtifact,
		Path:     manifestFile,
		Url:      *uploadUrl,
		Headers:  uploadHeaders,
	}
	task.OnComplete = func() { resultChan <- task }

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

func (as *ArtifactSaver) Save() (artifactID string, rerr error) {
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
	defer os.Remove(manifestFile)

	uploadUrl, uploadHeaders, err := as.upsertManifest(artifactID, baseArtifactId, manifestAttrs.Id, manifestDigest)
	if err != nil {
		return "", fmt.Errorf("ArtifactSaver.upsertManifest: %w", err)
	}

	err = as.uploadManifest(manifestFile, uploadUrl, uploadHeaders)
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
