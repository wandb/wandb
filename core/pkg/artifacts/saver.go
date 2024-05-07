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

type fileUploadResult struct {
	localPath       *string
	birthArtifactID *string
	lagTime         time.Duration // Time between getting the URL and finishing the upload.
	err             error
}

func (as *ArtifactSaver) batchUploadWorker(batchChan <-chan map[string]gql.CreateArtifactFileSpecInput,
	uploadResultChan chan<- fileUploadResult, numInProgress *int32) {
	for batch := range batchChan {
		paths := []string{}
		fileSpecs := []gql.CreateArtifactFileSpecInput{}
		for localPath, fileSpec := range batch {
			paths = append(paths, localPath)
			fileSpecs = append(fileSpecs, fileSpec)
		}
		response, err := gql.CreateArtifactFiles(
			as.Ctx,
			as.GraphqlClient,
			fileSpecs,
			gql.ArtifactStorageLayoutV2,
		)
		urlReceivedAt := time.Now()
		if err == nil && len(batch) != len(response.CreateArtifactFiles.Files.Edges) {
			err = fmt.Errorf(
				"expected %v upload URLs, got %v",
				len(batch),
				len(response.CreateArtifactFiles.Files.Edges),
			)
		}
		if err != nil {
			uploadResultChan <- fileUploadResult{err: err}
			return
		}

		// Enqueue individual uploads to the upload manager and wait for them to finish.
		uploadWg := sync.WaitGroup{}
		for i, edge := range response.CreateArtifactFiles.Files.Edges {
			uploadResult := fileUploadResult{
				localPath:       &paths[i],
				birthArtifactID: &edge.Node.Artifact.Id,
			}
			if edge.Node.UploadUrl == nil {
				uploadResultChan <- uploadResult
				continue
			}
			task := &filetransfer.Task{
				FileKind: filetransfer.RunFileKindArtifact,
				Type:     filetransfer.UploadTask,
				Path:     paths[i],
				Url:      *edge.Node.UploadUrl,
				Headers:  edge.Node.UploadHeaders,
			}
			task.SetCompletionCallback(
				func(t *filetransfer.Task) {
					uploadResult.lagTime = time.Since(urlReceivedAt)
					uploadResult.err = t.Err
					uploadResultChan <- uploadResult
					uploadWg.Done()
				},
			)
			uploadWg.Add(1)
			atomic.AddInt32(numInProgress, 1)
			as.FileTransferManager.AddTask(task)
		}
		uploadWg.Wait()
	}
}

func (as *ArtifactSaver) uploadFiles(
	uploadInfo map[string]gql.CreateArtifactFileSpecInput, manifest *Manifest) error {
	const batchSize = 1000
	const batchWorkers = 5

	batchUploadChan := make(chan map[string]gql.CreateArtifactFileSpecInput)
	uploadResultChan := make(chan fileUploadResult, batchSize*batchWorkers)

	numInProgress := int32(0)
	batchWg := sync.WaitGroup{}
	for i := 0; i < batchWorkers; i++ {
		batchWg.Add(1)
		go func() {
			as.batchUploadWorker(batchUploadChan, uploadResultChan, &numInProgress)
			batchWg.Done()
		}()
	}

	// Assemble and send batches.
	// Run in the background in order to start processing results as they come in.
	go func() {
		batchInfo := make(map[string]gql.CreateArtifactFileSpecInput)
		for localPath, fileSpec := range uploadInfo {
			batchInfo[localPath] = fileSpec
			if len(batchInfo) >= batchSize {
				batchUploadChan <- batchInfo
				batchInfo = make(map[string]gql.CreateArtifactFileSpecInput)
			}
		}
		if len(batchInfo) > 0 {
			batchUploadChan <- batchInfo
		}

		// Close the result channel once all batches are done.
		close(batchUploadChan)
		batchWg.Wait()
		close(uploadResultChan)
	}()

	numDone := 0
	retryFiles := make(map[string]gql.CreateArtifactFileSpecInput)
	for result := range uploadResultChan {
		if result.localPath == nil {
			return result.err
		}
		atomic.AddInt32(&numInProgress, -1)
		name := uploadInfo[*result.localPath].Name
		entry := manifest.Contents[name]

		if result.err != nil {
			if result.lagTime > 1*time.Hour {
				// We can't tell the difference between an expired signed URL and an upload
				// that fails due to a real authentication problem. So if the upload happens
				// more than an hour after the signed URL was fetched, we retry.
				retryFiles[*result.localPath] = uploadInfo[*result.localPath]
				continue
			} else {
				return result.err
			}
		}
		// Update the manifest entry to reflect the actual birth artifact ID.
		entry.BirthArtifactID = result.birthArtifactID
		manifest.Contents[name] = entry
    // Cache entry if necessary
    if !entry.SkipCache {
      digest := entry.Digest
      go func() {
        err := as.FileCache.AddFileAndCheckDigest(result.LocalPath, digest)
        if err != nil {
          slog.Error("error adding file to cache", "err", err)
        }
      }()
    }
		numDone++
	}

	// If there are failed uploads that should be retried, do so.
	if len(retryFiles) > 0 {
		return as.uploadFiles(retryFiles, manifest)
	}
	return nil
}

func (as *ArtifactSaver) uploadAllFiles(artifactID string, manifest *Manifest, manifestID string) error {
	uploadInfo := make(map[string]gql.CreateArtifactFileSpecInput)
	for name, entry := range manifest.Contents {
		if entry.LocalPath == nil {
			continue
		}
		uploadInfo[*entry.LocalPath] = gql.CreateArtifactFileSpecInput{
			ArtifactID:         artifactID,
			Name:               name,
			Md5:                entry.Digest,
			ArtifactManifestID: &manifestID,
		}
	}
	return as.uploadFiles(uploadInfo, manifest)
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

func (as *ArtifactSaver) uploadManifest(manifestFile string, uploadUrl *string, uploadHeaders []string, outChan chan<- *service.Record) error {
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

	err = as.uploadAllFiles(artifactID, &manifest, manifestAttrs.Id)
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
