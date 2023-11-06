package artifacts

import (
	"context"
	"fmt"
	"os"
	"path/filepath"
	"time"

	"github.com/Khan/genqlient/graphql"
	"github.com/wandb/wandb/nexus/internal/filetransfer"
	"github.com/wandb/wandb/nexus/internal/gql"
)

const BATCH_SIZE int = 10000
const MAX_BACKLOG int = 10000

type ArtifactDownloader struct {
	// Resources
	Ctx             context.Context
	GraphqlClient   graphql.Client
	DownloadManager *filetransfer.FileTransferManager
	// Input
	ArtifactID             string
	DownloadRoot           string
	Recursive              *bool
	AllowMissingReferences *bool
	// Properties
	UpstreamArtifacts []gql.ArtifactByIDArtifact
}

func NewArtifactDownloader(
	ctx context.Context,
	graphQLClient graphql.Client,
	downloadManager *filetransfer.FileTransferManager,
	artifactID string,
	downloadRoot string,
	recursive *bool,
	allowMissingReferences *bool,
) *ArtifactDownloader {
	return &ArtifactDownloader{
		Ctx:                    ctx,
		GraphqlClient:          graphQLClient,
		DownloadManager:        downloadManager,
		ArtifactID:             artifactID,
		DownloadRoot:           downloadRoot,
		Recursive:              recursive,
		AllowMissingReferences: allowMissingReferences,
		UpstreamArtifacts:      []gql.ArtifactByIDArtifact{},
	}
}

func (ad *ArtifactDownloader) getArtifact() (attrs gql.ArtifactByIDArtifact, rerr error) {
	response, err := gql.ArtifactByID(
		ad.Ctx,
		ad.GraphqlClient,
		ad.ArtifactID,
	)
	if err != nil {
		return gql.ArtifactByIDArtifact{}, err
	}
	artifact := response.GetArtifact()
	if artifact == nil {
		return gql.ArtifactByIDArtifact{}, fmt.Errorf("could not access artifact")
	}
	return *artifact, nil
}

func (ad *ArtifactDownloader) getArtifactManifest(artifact gql.ArtifactByIDArtifact) (manifest Manifest, rerr error) {
	response, err := gql.ArtifactManifest(
		ad.Ctx,
		ad.GraphqlClient,
		artifact.ArtifactSequence.Project.EntityName,
		artifact.ArtifactSequence.Project.Name,
		artifact.ArtifactSequence.Name,
	)
	if err != nil {
		return Manifest{}, err
	} else if response == nil {
		return Manifest{}, fmt.Errorf("could not get manifest for artifact %s", artifact.ArtifactSequence.Name)
	}
	artifactManifest := response.GetProject().GetArtifact().GetCurrentManifest()
	if artifactManifest == nil {
		return Manifest{}, fmt.Errorf("could not access manifest for artifact %s", artifact.ArtifactSequence.Name)
	}
	directURL := artifactManifest.GetFile().DirectUrl
	manifest, err = loadManifestFromURL(directURL)
	if err != nil {
		return Manifest{}, err
	}

	// Set upstream artifacts, if any
	err = ad.setUpstreamArtifacts(manifest)
	if err != nil {
		return Manifest{}, err
	}
	return manifest, nil
}

func (ad *ArtifactDownloader) setUpstreamArtifacts(manifest Manifest) error {
	for _, entry := range manifest.Contents {
		referencedID, err := getReferencedID(entry.Ref)
		if err != nil {
			return err
		}
		if referencedID != nil {
			response, err := gql.ArtifactByID(
				ad.Ctx,
				ad.GraphqlClient,
				*referencedID,
			)
			if err != nil {
				return err
			}
			depArtifact := response.GetArtifact()
			if depArtifact != nil {
				ad.UpstreamArtifacts = append(ad.UpstreamArtifacts, *depArtifact)
			}
		}
	}
	return nil
}

func (ad *ArtifactDownloader) downloadFiles(artifactID string, manifest Manifest) error {
	// retrieve from "WANDB_ARTIFACT_FETCH_FILE_URL_BATCH_SIZE"?
	batchSize := BATCH_SIZE

	type TaskResult struct {
		Task *filetransfer.Task
		Name string
	}

	// Fetch URLs and download files in batches
	manifestEntries := manifest.Contents
	numInProgress, numDone := 0, 0
	nameToScheduledTime := map[string]time.Time{}
	taskResultsChan := make(chan TaskResult)
	manifestEntriesBatch := make([]ManifestEntry, 0, batchSize)

	for numDone < len(manifestEntries) {
		var cursor *string
		hasNextPage := true
		for hasNextPage {
			// Prepare a batch
			now := time.Now()
			manifestEntriesBatch = manifestEntriesBatch[:0]
			response, err := gql.ArtifactFileURLs(
				ad.Ctx,
				ad.GraphqlClient,
				artifactID,
				cursor,
				&batchSize,
			)
			if err != nil {
				return err
			}
			hasNextPage = response.Artifact.Files.PageInfo.HasNextPage
			cursor = response.Artifact.Files.PageInfo.EndCursor
			for _, edge := range response.GetArtifact().GetFiles().Edges {
				filePath := edge.GetNode().Name
				entry, err := manifest.GetManifestEntryFromArtifactFilePath(filePath)
				if err != nil {
					return err
				}
				if _, ok := nameToScheduledTime[*entry.LocalPath]; ok {
					continue
				}
				// Reference artifacts will temporarily be handled by the python user process
				if entry.Ref != nil {
					numDone++
					continue
				}
				entry.DownloadURL = &edge.GetNode().DirectUrl
				entry.LocalPath = &filePath
				nameToScheduledTime[*entry.LocalPath] = now
				manifestEntriesBatch = append(manifestEntriesBatch, entry)
			}

			// Schedule downloads
			if len(manifestEntriesBatch) > 0 {
				for _, entry := range manifestEntriesBatch {
					// Add function that returns download path?
					downloadLocalPath := filepath.Join(ad.DownloadRoot, *entry.LocalPath)
					// Skip downloading the file if it already exists
					if _, err := os.Stat(downloadLocalPath); err == nil {
						numDone++
						continue
					}
					task := &filetransfer.Task{
						Type:     filetransfer.DownloadTask,
						Path:     downloadLocalPath,
						Url:      *entry.DownloadURL,
						FileType: filetransfer.ArtifactFile,
					}
					task.AddCompletionCallback(
						func(task *filetransfer.Task) {
							taskResultsChan <- TaskResult{task, *entry.LocalPath}
						},
					)
					numInProgress++
					ad.DownloadManager.AddTask(task)
				}
			}
			// Wait for downloader to catch up. If there's nothing more to schedule, wait for all in progress tasks.
			for numInProgress > MAX_BACKLOG || (len(manifestEntriesBatch) == 0 && numInProgress > 0) {
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
			}
		}
	}
	return nil
}

func (ad *ArtifactDownloader) Download() (rerr error) {
	artifactAttrs, err := ad.getArtifact()
	if err != nil {
		return err
	}
	artifactManifest, err := ad.getArtifactManifest(artifactAttrs)
	if err != nil {
		return err
	}

	if err := ad.downloadFiles(artifactAttrs.Id, artifactManifest); err != nil {
		return err
	}
	return nil
}
