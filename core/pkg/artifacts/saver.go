package artifacts

import (
	"context"
	"fmt"
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
	// Input.
	Artifact    *service.ArtifactRecord
	HistoryStep int64
	StagingDir  string
	Manifest    *Manifest
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
		Artifact:            artifact,
		HistoryStep:         historyStep,
		StagingDir:          stagingDir,
		Manifest:            nil, // The manifest will be loaded from the proto by Save.
	}
}

func (as *ArtifactSaver) createArtifact() (
	attrs gql.CreateArtifactCreateArtifactCreateArtifactPayloadArtifact,
	rerr error,
) {
	aliases := []gql.ArtifactAliasInput{}
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

func (as *ArtifactSaver) uploadBatch(fileSpecs []gql.CreateArtifactFileSpecInput,
	numInProgress *int32, numDone *int32, errorChan chan error,
	retryChan chan gql.CreateArtifactFileSpecInput) {


	// Get upload URLs for the whole batch.
	response, err := gql.CreateArtifactFiles(
		as.Ctx,
		as.GraphqlClient,
		fileSpecs,
		gql.ArtifactStorageLayoutV2,
	)
	if err != nil {
		errorChan <- err
		return
	}
	if len(fileSpecs) != len(response.CreateArtifactFiles.Files.Edges) {
		errorChan <- fmt.Errorf(
			"expected %v upload URLs, got %v",
			len(fileSpecs),
			len(response.CreateArtifactFiles.Files.Edges),
		)
		return
	}

	receivedAt := time.Now()
	wg := sync.WaitGroup{}

	// Set birth artifact ids and schedule uploads.
	for i, edge := range response.CreateArtifactFiles.Files.Edges {
		fileSpec := fileSpecs[i]
		name := fileSpec.Name
		entry := as.Manifest.Contents[name]
		entry.BirthArtifactID = &edge.Node.Artifact.Id
		as.Manifest.Contents[name] = entry
		if edge.Node.UploadUrl == nil {
			atomic.AddInt32(numDone, 1)
			continue
		}
		task := &filetransfer.Task{
			FileKind: filetransfer.RunFileKindArtifact,
			Type:     filetransfer.UploadTask,
			Path:     *entry.LocalPath,
			Url:      *edge.Node.UploadUrl,
			Headers:  edge.Node.UploadHeaders,
		}
		task.SetCompletionCallback(
			func(t *filetransfer.Task) {
				defer wg.Done()
				atomic.AddInt32(numInProgress, -1)
				if t.Err != nil {
					// Retry if it's been more than an hour (URL may have expired).
					if time.Since(receivedAt) > 1*time.Hour {
						retryChan <- fileSpec
					} else {
						errorChan <- t.Err
					}
				} else {
					atomic.AddInt32(numDone, 1)
				}
			},
		)
		wg.Add(1)
		atomic.AddInt32(numInProgress, 1)
		as.FileTransferManager.AddTask(task)
	}
	wg.Wait()
}

func (as *ArtifactSaver) uploadFiles(fileSpecs []gql.CreateArtifactFileSpecInput,
	numInProgress *int32, numDone *int32) error {
	const batchSize int = 10000
	const maxActiveBatches int = 3
	batchSemaphore := make(chan struct{}, maxActiveBatches)
	var wg sync.WaitGroup

	errorChan := make(chan error)
	retryChan := make(chan gql.CreateArtifactFileSpecInput)

	// Batch fileSpecs and upload.
	for len(fileSpecs) > 0 {
		currentBatchSize := batchSize
		if len(fileSpecs) < batchSize {
			currentBatchSize = len(fileSpecs)
		}
		currentBatch := fileSpecs[:currentBatchSize]
		fileSpecs = fileSpecs[currentBatchSize:]

		wg.Add(1)
		go func(batch []gql.CreateArtifactFileSpecInput) {
			batchSemaphore <- struct{}{}
			defer func() {
				<-batchSemaphore
				wg.Done()
			}()
			as.uploadBatch(batch, numInProgress, numDone, errorChan, retryChan)
		}(currentBatch)
	}

	// Wait until at least one upload has started or finished.
	for {
		if atomic.LoadInt32(numInProgress) > 0 || atomic.LoadInt32(numDone) > 0 {
			break
		}
	}

	// Do a non-blocking check for errors until no more uploads are in progress.
	for atomic.LoadInt32(numInProgress) > 0 {
		select {
		case err := <-errorChan:
			return err
		default:
		}
	}

	// Wait for all batches to finish, then check for errors and files to retry.
	wg.Wait()
	close(errorChan)
	for err := range errorChan {
		if err != nil {
			return err
		}
	}
	close(retryChan)
	// Drain the retryChan into a batch to retry.
	retryBatch := []gql.CreateArtifactFileSpecInput{}
	for fileSpec := range retryChan {
		retryBatch = append(retryBatch, fileSpec)
	}
	if len(retryBatch) > 0 {

		return as.uploadFiles(retryBatch, numInProgress, numDone)
	}
	return nil
}

func (as *ArtifactSaver) uploadAllFiles(artifactID string, manifestID string) error {
	if len(as.Manifest.Contents) == 0 {
		return nil
	}
	fileSpecs := []gql.CreateArtifactFileSpecInput{}
	for name, entry := range as.Manifest.Contents {
		if entry.LocalPath == nil {
			continue
		}
		fileSpec := gql.CreateArtifactFileSpecInput{
			ArtifactID:         artifactID,
			Name:               name,
			Md5:                entry.Digest,
			ArtifactManifestID: &manifestID,
		}
		fileSpecs = append(fileSpecs, fileSpec)
	}
	numInProgress := int32(0)
	numDone := int32(0)
	return as.uploadFiles(fileSpecs, &numInProgress, &numDone)
}

func (as *ArtifactSaver) resolveClientIDReferences() error {
	cache := map[string]string{}
	for name, entry := range as.Manifest.Contents {
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
			as.Manifest.Contents[name] = entry
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

func (as *ArtifactSaver) deleteStagingFiles() {
	for _, entry := range as.Manifest.Contents {
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
	as.Manifest = &manifest
	defer as.deleteStagingFiles()

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

	err = as.uploadAllFiles(artifactID, manifestAttrs.Id)
	if err != nil {
		return "", fmt.Errorf("ArtifactSaver.uploadFiles: %w", err)
	}

	err = as.resolveClientIDReferences()
	if err != nil {
		return "", fmt.Errorf("ArtifactSaver.resolveClientIDReferences: %w", err)
	}
	// TODO: check if size is needed
	manifestFile, manifestDigest, _, err := as.Manifest.WriteToFile()
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
