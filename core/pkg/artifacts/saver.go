package artifacts

import (
	"context"
	"fmt"
	"log/slog"
	"net/url"
	"os"
	"strings"
	"sync"
	"sync/atomic"
	"time"

	"github.com/Khan/genqlient/graphql"

	"github.com/wandb/wandb/core/internal/filetransfer"
	"github.com/wandb/wandb/core/internal/gql"
	"github.com/wandb/wandb/core/pkg/service"
	"github.com/wandb/wandb/core/pkg/utils"
)

type ArtifactSaver struct {
	// Resources.
	Ctx                 context.Context
	GraphqlClient       graphql.Client
	FileTransferManager filetransfer.FileTransferManager
	FileCache           Cache
	// Input.
	Artifact    *service.ArtifactRecord
	HistoryStep int64
	StagingDir  string
	batchSize   int
}

type serverFileResponse struct {
	Name            string
	BirthArtifactID string
	UploadUrl       *string
	UploadHeaders   []string
}

func NewArtifactSaver(
	ctx context.Context,
	graphQLClient graphql.Client,
	uploadManager filetransfer.FileTransferManager,
	artifact *service.ArtifactRecord,
	historyStep int64,
	stagingDir string,
) ArtifactSaver {
	return ArtifactSaver{
		Ctx:                 ctx,
		GraphqlClient:       graphQLClient,
		FileTransferManager: uploadManager,
		FileCache:           NewFileCache(UserCacheDir()),
		Artifact:            artifact,
		HistoryStep:         historyStep,
		StagingDir:          stagingDir,
		batchSize:           1000,
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

func (as *ArtifactSaver) uploadFiles(artifactID string, manifest *Manifest, manifestID string) error {

	// Prepare GQL input for files that (might) need to be uploaded.
	fileSpecs := map[string]gql.CreateArtifactFileSpecInput{}
	for name, entry := range manifest.Contents {
		if entry.LocalPath == nil {
			continue
		}
		fileSpec := gql.CreateArtifactFileSpecInput{
			ArtifactID:         artifactID,
			Name:               name,
			Md5:                entry.Digest,
			ArtifactManifestID: &manifestID,
		}
		fileSpecs[name] = fileSpec
	}

	var err error
	for len(fileSpecs) > 0 {
		numNeedUploading := len(fileSpecs)
		if fileSpecs, err = as.processFiles(manifest, fileSpecs); err != nil {
			return err
		}
		// If more than half of the remaining files uploaded we'll keep retrying.
		// We shouldn't ordinarily need to retry at all; our internal client handles
		// retry-able errors, and the only "normal" failure that is handled by retrying
		// at this level is signed urls that expired before the upload was started, and
		// this is exceedingly rare.
		// Still, as long as more than half of them succeed in each iteration this will
		// eventually terminate.
		if len(fileSpecs) >= numNeedUploading/2 {
			return fmt.Errorf(
				"most remaining uploads (%d/%d) have failed, giving up",
				len(fileSpecs), numNeedUploading,
			)
		}
		if len(fileSpecs) > 0 {
			slog.Warn("some files failed to upload, retrying", "count", len(fileSpecs))
		}
	}
	return nil
}

func (as *ArtifactSaver) processFiles(
	manifest *Manifest,
	fileSpecs map[string]gql.CreateArtifactFileSpecInput,
) (map[string]gql.CreateArtifactFileSpecInput, error) {

	// The sender side of these channels are workers in their own gorountines, so they
	// don't need to be buffered.
	readyChan := make(chan serverFileResponse)
	errorChan := make(chan error)

	// Add upload and ancestry info to the file specs in the background.
	go func() {
		as.getFileDataFromServer(fileSpecs, readyChan, errorChan)
		close(readyChan)
	}()

	// We don't need to buffer doneChan: each callback is executed in its own goroutine.
	doneChan := make(chan *filetransfer.Task)
	mustRetry := map[string]gql.CreateArtifactFileSpecInput{}
	wg := sync.WaitGroup{}

	numDone := int32(0)
	numInProgress := int32(0)
	check := make(chan struct{})
	go func() {
		for {
			time.Sleep(1 * time.Second)
			check <- struct{}{}
		}
	}()

	// Concurrently schedule uploads and process results until an error is signaled or
	// we finish scheduling all files.
	notDone := true
	for notDone {
		select {
		case err := <-errorChan:
			return nil, err
		case <-check:
			fmt.Printf("In progress: %v; Done: %v/%v\n", numInProgress, numDone, len(fileSpecs))
		case result := <-doneChan:
			if result.Err != nil {
				mustRetry[result.Name] = fileSpecs[result.Name]
			}
		case fileInfo, ok := <-readyChan:
			if !ok {
				// The channel has been closed, we're done starting new upload tasks.
				notDone = false
				break
			}
			entry := manifest.Contents[fileInfo.Name]
			entry.BirthArtifactID = &fileInfo.BirthArtifactID
			manifest.Contents[fileInfo.Name] = entry
			if fileInfo.UploadUrl == nil {
				// The server already has this file.
				continue
			}
			task := &filetransfer.Task{
				FileKind: filetransfer.RunFileKindArtifact,
				Type:     filetransfer.UploadTask,
				Path:     *entry.LocalPath,
				Name:     fileInfo.Name,
				Url:      *fileInfo.UploadUrl,
				Headers:  fileInfo.UploadHeaders,
			}
			task.SetCompletionCallback(
				func(t *filetransfer.Task) {
					doneChan <- t
					atomic.AddInt32(&numInProgress, -1)
					atomic.AddInt32(&numDone, 1)
					wg.Done()
				},
			)
			// Schedule the file for upload. The transfer manager will run up to 128
			// concurrent uploads, accepts any number of tasks and launches a goroutine
			// for each. In order to avoid ballooning
			wg.Add(1)
			atomic.AddInt32(&numInProgress, 1)
			as.FileTransferManager.AddTask(task)
		}
	}

	// Close the results channel once all the uploads have finished.
	go func() {
		wg.Wait()
		close(doneChan)
	}()

	// Process all remaining results.
	for result := range doneChan {
		if result.Err != nil {
			mustRetry[result.Name] = fileSpecs[result.Name]
		}
	}
	return mustRetry, nil
}

// getFileDataFromServer takes a map of file specs and uses a worker pool that processes
// batches to add upload URLs and BirthArtifactIDs to ready them for individual upload.
func (as *ArtifactSaver) getFileDataFromServer(
	fileSpecs map[string]gql.CreateArtifactFileSpecInput,
	resultChan chan<- serverFileResponse,
	errorChan chan<- error,
) {
	batchChan := make(chan []gql.CreateArtifactFileSpecInput)

	// Start three batch url retrievers.
	wg := sync.WaitGroup{}
	for i := 0; i < 3; i++ {
		wg.Add(1)
		go func() {
			as.batchFileDataRetriever(batchChan, resultChan, errorChan)
			wg.Done()
		}()
	}

	// Group file specs into batches and send to the workers.
	batch := []gql.CreateArtifactFileSpecInput{}
	for _, fileSpec := range fileSpecs {
		batch = append(batch, fileSpec)
		if len(batch) >= as.batchSize {
			batchChan <- batch
			batch = nil
		}
	}
	if len(batch) > 0 {
		batchChan <- batch
	}
	close(batchChan) // Signal the workers to stop.
	wg.Wait()
}

// batchFileDataRetriever takes batches of file specs, requests upload URLs for each file,
// assembles the info needed for the next step, and feeds them into an output channel.
func (as *ArtifactSaver) batchFileDataRetriever(
	batchChan <-chan []gql.CreateArtifactFileSpecInput,
	resultChan chan<- serverFileResponse,
	errorChan chan<- error,
) {
	for batch := range batchChan {
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
			// We block on this channel, so we won't request data on more batches until
			// the next step has handled these responses.
			resultChan <- serverFileResponse{
				Name:            batch[i].Name,
				BirthArtifactID: edge.Node.Artifact.Id,
				UploadUrl:       edge.Node.UploadUrl,
				UploadHeaders:   edge.Node.UploadHeaders,
			}
		}
	}
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

func (as *ArtifactSaver) uploadManifest(manifestFile string, uploadUrl *string, uploadHeaders []string) error {
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
	manifestAttrs, err = as.createManifest(artifactID, baseArtifactId, manifestDigest, true /* includeUpload */)
	if err != nil {
		return "", fmt.Errorf("ArtifactSaver.createManifest: %w", err)
	}
	err = as.uploadManifest(manifestFile, manifestAttrs.File.UploadUrl, manifestAttrs.File.UploadHeaders)
	if err != nil {
		return "", fmt.Errorf("ArtifactSaver.uploadManifest: %w", err)
	}

	if as.Artifact.Finalize {
		err = as.commitArtifact(artifactID)
		if err != nil {
			return "", fmt.Errorf("ArtifactSacer.commitArtifact: %w", err)
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
