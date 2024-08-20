package artifacts

import (
	"context"
	"fmt"
	"log/slog"
	"path/filepath"
	"time"

	"github.com/Khan/genqlient/graphql"
	"github.com/wandb/wandb/core/internal/filetransfer"
	"github.com/wandb/wandb/core/internal/gql"
)

const BATCH_SIZE int = 10000
const MAX_BACKLOG int = 10000

type ArtifactDownloader struct {
	// Resources
	Ctx             context.Context
	GraphqlClient   graphql.Client
	DownloadManager filetransfer.FileTransferManager
	FileCache       Cache
	// Input
	ArtifactID             string
	DownloadRoot           string
	AllowMissingReferences bool   // Currently unused
	SkipCache              bool   // Currently unused
	PathPrefix             string // Currently unused
}

func NewArtifactDownloader(
	ctx context.Context,
	graphQLClient graphql.Client,
	downloadManager filetransfer.FileTransferManager,
	artifactID string,
	downloadRoot string,
	allowMissingReferences bool,
	skipCache bool,
	pathPrefix string,
) *ArtifactDownloader {
	fileCache := NewHashOnlyCache()
	if !skipCache {
		fileCache = NewFileCache(UserCacheDir())
	}
	return &ArtifactDownloader{
		Ctx:                    ctx,
		GraphqlClient:          graphQLClient,
		DownloadManager:        downloadManager,
		ArtifactID:             artifactID,
		DownloadRoot:           downloadRoot,
		AllowMissingReferences: allowMissingReferences,
		SkipCache:              skipCache,
		PathPrefix:             pathPrefix,
		FileCache:              fileCache,
	}
}

func (ad *ArtifactDownloader) getArtifactManifest(artifactID string) (manifest Manifest, rerr error) {
	response, err := gql.ArtifactManifest(
		ad.Ctx,
		ad.GraphqlClient,
		artifactID,
	)
	if err != nil {
		return Manifest{}, err
	} else if response == nil {
		return Manifest{}, fmt.Errorf("could not get manifest for artifact")
	}
	artifact := response.Artifact
	if artifact == nil {
		return Manifest{}, fmt.Errorf("could not access artifact")
	}
	artifactManifest := artifact.CurrentManifest
	if artifactManifest == nil {
		return Manifest{}, fmt.Errorf("could not access manifest for artifact")
	}
	directURL := artifactManifest.GetFile().DirectUrl
	manifest, err = loadManifestFromURL(directURL)
	if err != nil {
		return Manifest{}, err
	}
	return manifest, nil
}

func (ad *ArtifactDownloader) downloadFiles(artifactID string, manifest Manifest) error {
	// retrieve from "WANDB_ARTIFACT_FETCH_FILE_URL_BATCH_SIZE"?
	batchSize := BATCH_SIZE

	type TaskResult struct {
		Path string
		Err  error
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
				if _, ok := nameToScheduledTime[filePath]; ok {
					continue
				}
				// Reference artifacts will temporarily be handled by the python user process
				if entry.Ref != nil {
					numDone++
					continue
				}
				node := edge.GetNode()
				if node == nil {
					return fmt.Errorf("error reading entry from fetched file urls")
				}
				entry.DownloadURL = &node.DirectUrl
				entry.LocalPath = &filePath
				nameToScheduledTime[*entry.LocalPath] = now
				manifestEntriesBatch = append(manifestEntriesBatch, entry)
			}

			// Schedule downloads
			if len(manifestEntriesBatch) > 0 {
				for _, entry := range manifestEntriesBatch {
					// Add function that returns download path?
					downloadLocalPath := filepath.Join(ad.DownloadRoot, *entry.LocalPath)
					// If we're skipping the cache, the HashOnlyCache still checks the destination
					// and returns true if the file is there and has the correct hash.
					if success := ad.FileCache.RestoreTo(entry, downloadLocalPath); success {
						numDone++
						continue
					}
					if entry.Ref != nil {
						task := &filetransfer.ReferenceArtifactDownloadTask{
							FileKind:  filetransfer.RunFileKindArtifact,
							Path:      downloadLocalPath,
							Reference: *entry.Ref,
							Digest:    entry.Digest,
							Size:      entry.Size,
						}
						versionId, ok := entry.Extra["versionID"]
						if ok {
							task.VersionId = versionId
						}

						task.OnComplete = func() {
							taskResultsChan <- TaskResult{downloadLocalPath, task.Err, *entry.LocalPath}
						}
						ad.DownloadManager.AddTask(task)
					} else {
						task := &filetransfer.DefaultDownloadTask{
							FileKind: filetransfer.RunFileKindArtifact,
							Path:     downloadLocalPath,
							Url:      *entry.DownloadURL,
							Size:     entry.Size,
						}

						task.OnComplete = func() {
							taskResultsChan <- TaskResult{downloadLocalPath, task.Err, *entry.LocalPath}
						}
						ad.DownloadManager.AddTask(task)
					}
					numInProgress++
				}
			}
			// Wait for downloader to catch up. If there's nothing more to schedule, wait for all in progress tasks.
			for numInProgress > MAX_BACKLOG || (len(manifestEntriesBatch) == 0 && numInProgress > 0) {
				numInProgress--
				result := <-taskResultsChan
				if result.Err != nil {
					// We want to retry when the signed URL expires. However, distinguishing that error from others is not
					// trivial. As a heuristic, we retry if the request failed more than an hour after we fetched the URL.
					if time.Since(nameToScheduledTime[result.Name]) < 1*time.Hour {
						return result.Err
					}
					delete(nameToScheduledTime, result.Name) // retry
					continue
				}
				numDone++
				digest := manifest.Contents[result.Name].Digest
				go func() {
					err := ad.FileCache.AddFileAndCheckDigest(result.Path, digest)
					if err != nil {
						slog.Error("Error adding file to cache", "err", err)
					}
				}()
			}
		}
	}
	return nil
}

func (ad *ArtifactDownloader) Download() (rerr error) {
	artifactManifest, err := ad.getArtifactManifest(ad.ArtifactID)
	if err != nil {
		return err
	}

	if err := ad.downloadFiles(ad.ArtifactID, artifactManifest); err != nil {
		return err
	}
	return nil
}
