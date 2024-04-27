package artifacts

import (
	"context"
	"fmt"
	"log/slog"
	"net/url"
	"os"
	"strings"
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

func (as *ArtifactSaver) uploadFiles(artifactID string, manifest *Manifest, manifestID string, _ chan<- *service.Record) error {
	const batchSize int = 10000
	const maxBacklog int = 10000

	type TaskResult struct {
		Task *filetransfer.Task
		Name string
	}

	// Prepare all file specs.
	var fileSpecs []gql.CreateArtifactFileSpecInput
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
		fileSpecs = append(fileSpecs, fileSpec)
	}

	// Upload in batches.
	numInProgress, numDone := 0, 0
	nameToScheduledTime := map[string]time.Time{}
	taskResultsChan := make(chan TaskResult)
	fileSpecsBatch := make([]gql.CreateArtifactFileSpecInput, 0, batchSize)
	for numDone < len(fileSpecs) {
		// Prepare a batch.
		now := time.Now()
		fileSpecsBatch = fileSpecsBatch[:0]
		for _, fileSpec := range fileSpecs {
			if _, ok := nameToScheduledTime[fileSpec.Name]; ok {
				continue
			}
			nameToScheduledTime[fileSpec.Name] = now
			fileSpecsBatch = append(fileSpecsBatch, fileSpec)
			if len(fileSpecsBatch) >= batchSize {
				break
			}
		}
		if len(fileSpecsBatch) > 0 {
			// Fetch upload URLs.
			response, err := gql.CreateArtifactFiles(
				as.Ctx,
				as.GraphqlClient,
				fileSpecsBatch,
				gql.ArtifactStorageLayoutV2,
			)
			if err != nil {
				return err
			}
			if len(fileSpecsBatch) != len(response.CreateArtifactFiles.Files.Edges) {
				return fmt.Errorf(
					"expected %v upload URLs, got %v",
					len(fileSpecsBatch),
					len(response.CreateArtifactFiles.Files.Edges),
				)
			}
			// Save birth artifact ids, schedule uploads.
			for i, edge := range response.CreateArtifactFiles.Files.Edges {
				name := fileSpecsBatch[i].Name
				entry := manifest.Contents[name]
				entry.BirthArtifactID = &edge.Node.Artifact.Id
				manifest.Contents[name] = entry
				if edge.Node.UploadUrl == nil {
					numDone++
					continue
				}
				numInProgress++
				task := &filetransfer.Task{
					FileKind: filetransfer.RunFileKindArtifact,
					Type:     filetransfer.UploadTask,
					Path:     *entry.LocalPath,
					Url:      *edge.Node.UploadUrl,
					Headers:  edge.Node.UploadHeaders,
				}
				task.SetCompletionCallback(
					func(t *filetransfer.Task) {
						taskResultsChan <- TaskResult{t, name}
					},
				)
				as.FileTransferManager.AddTask(task)
			}
		}
		// Wait for filetransfer to catch up. If there's nothing more to schedule, wait for all in progress tasks.
		for numInProgress > maxBacklog || (len(fileSpecsBatch) == 0 && numInProgress > 0) {
			numInProgress--
			result := <-taskResultsChan
			if result.Task.Err != nil {
				// We want to retry when the signed URL expires. However, distinguishing that error from others is not
				// trivial. As a heuristic, we retry if the request failed more than an hour after we fetched the URL.
				if time.Since(nameToScheduledTime[result.Name]) < 1*time.Hour {
					return result.Task.Err
				}
				delete(nameToScheduledTime, result.Name) // retry
				continue
			}
			numDone++
			entry := manifest.Contents[result.Name]
			if !entry.SkipCache {
				digest := entry.Digest
				go func() {
					err := as.FileCache.AddFileAndCheckDigest(result.Task.Path, digest)
					if err != nil {
						slog.Error("error adding file to cache", "err", err)
					}
				}()
			}
		}
	}
	return nil
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
