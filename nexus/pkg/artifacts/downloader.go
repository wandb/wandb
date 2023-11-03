package artifacts

import (
	"context"
	"encoding/json"
	"fmt"
	"io"
	"net/http"
	"os"
	"path/filepath"
	"time"

	"github.com/Khan/genqlient/graphql"
	"github.com/wandb/wandb/nexus/internal/filetransfer"
	"github.com/wandb/wandb/nexus/internal/gql"
	"github.com/wandb/wandb/nexus/pkg/env"
)

const BATCH_SIZE int = 10000
const MAX_BACKLOG int = 10000

type ArtifactDownloader struct {
	// Resources
	Ctx             context.Context
	GraphqlClient   graphql.Client
	DownloadManager *filetransfer.FileTransferManager
	// Input
	QualifiedName          string
	DownloadRoot           *string
	Recursive              *bool
	AllowMissingReferences *bool
	// Properties
	UpstreamArtifacts   []gql.ArtifactByIDArtifact
	DefaultDownloadRoot *string
}

func NewArtifactDownloader(
	ctx context.Context,
	graphQLClient graphql.Client,
	downloadManager *filetransfer.FileTransferManager,
	qualifiedName string,
	downloadRoot *string,
	recursive *bool,
	allowMissingReferences *bool,
) *ArtifactDownloader {
	return &ArtifactDownloader{
		Ctx:                    ctx,
		GraphqlClient:          graphQLClient,
		DownloadManager:        downloadManager,
		QualifiedName:          qualifiedName,
		DownloadRoot:           downloadRoot,
		Recursive:              recursive,
		AllowMissingReferences: allowMissingReferences,
		UpstreamArtifacts:      []gql.ArtifactByIDArtifact{},
		DefaultDownloadRoot:    nil,
	}
}

func (ad *ArtifactDownloader) getArtifact() (attrs gql.ArtifactByNameProjectArtifact, rerr error) {
	entityName, projectName, artifactName, err := parseArtifactQualifiedName(ad.QualifiedName)
	if err != nil {
		return gql.ArtifactByNameProjectArtifact{}, err
	}
	response, err := gql.ArtifactByName(
		ad.Ctx,
		ad.GraphqlClient,
		entityName,
		projectName,
		artifactName,
	)
	if err != nil {
		return gql.ArtifactByNameProjectArtifact{}, err
	}
	return *response.GetProject().GetArtifact(), nil
}

func loadManifestFromURL(url string) (Manifest, error) {
	resp, err := http.Get(url)
	if err != nil {
		return Manifest{}, err
	}
	defer resp.Body.Close()
	manifest := Manifest{}
	if resp.StatusCode == http.StatusOK {
		body, err := io.ReadAll(resp.Body)
		if err != nil {
			return Manifest{}, fmt.Errorf("error reading response body: %v", err)
		}
		err = json.Unmarshal(body, &manifest)
		if err != nil {
			return Manifest{}, nil
		}
	} else {
		return Manifest{}, fmt.Errorf("request to get manifest from url failed with status code: %d", resp.StatusCode)
	}
	return manifest, nil
}

func (ad *ArtifactDownloader) getArtifactManifest() (artifactManifest Manifest, rerr error) {
	entityName, projectName, artifactName, err := parseArtifactQualifiedName(ad.QualifiedName)
	if err != nil {
		return Manifest{}, err
	}
	response, err := gql.ArtifactManifest(
		ad.Ctx,
		ad.GraphqlClient,
		entityName,
		projectName,
		artifactName,
	)
	if err != nil {
		return Manifest{}, err
	} else if response == nil {
		return Manifest{}, fmt.Errorf("could not get manifest for artifact %s", ad.QualifiedName)
	}
	directURL := response.GetProject().GetArtifact().GetCurrentManifest().GetFile().DirectUrl
	manifest, err := loadManifestFromURL(directURL)
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

func (ad *ArtifactDownloader) setDefaultDownloadRoot(artifactAttrs gql.ArtifactByNameProjectArtifact) (rerr error) {
	// This sets the absolute path of source_artifact_name:v{versionIndex} as default download root
	sourceArtifactName := artifactAttrs.GetArtifactSequence().Name
	versionIndex := artifactAttrs.GetVersionIndex()
	if versionIndex == nil {
		return fmt.Errorf("invalid artifact download, missing version index")
	}
	artifactDir, err := env.GetArtifactDir()
	if err != nil {
		return err
	}
	downloadRoot := filepath.Join(artifactDir, fmt.Sprintf("%s:v%d", sourceArtifactName, *versionIndex))

	path := CheckExists(downloadRoot)
	if path == nil {
		downloadRoot = SystemPreferredPath(downloadRoot, false)
	}
	ad.DefaultDownloadRoot = &downloadRoot
	return nil
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
			} else if response == nil {
				return fmt.Errorf("could not get artifact by id for reference %s", *entry.Ref)
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
	var downloadRoot string
	if ad.DownloadRoot != nil {
		downloadRoot = *ad.DownloadRoot
	} else if ad.DefaultDownloadRoot != nil {
		downloadRoot = *ad.DefaultDownloadRoot
	}
	if downloadRoot == "" {
		return fmt.Errorf("download root was not set")
	}
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
		cursor := ""
		hasNextPage := true
		for hasNextPage {
			// Prepare a batch
			now := time.Now()
			manifestEntriesBatch = manifestEntriesBatch[:0]
			response, err := gql.ArtifactFileURLs(
				ad.Ctx,
				ad.GraphqlClient,
				artifactID,
				&cursor,
				&batchSize,
			)
			if err != nil {
				return err
			} else if response == nil {
				return fmt.Errorf("could not fetch artifact file urls for %s", ad.QualifiedName)
			}
			hasNextPage = response.GetArtifact().GetFiles().PageInfo.HasNextPage
			cursor = *response.GetArtifact().GetFiles().PageInfo.EndCursor
			for _, edge := range response.GetArtifact().GetFiles().Edges {
				filePath := edge.GetNode().Name
				entry, err := manifest.GetManifestEntryFromArtifactFilePath(filePath)
				if err != nil {
					return err
				}
				if entry.Ref != nil {
					numDone++
					continue
				}
				entry.DownloadURL = &edge.GetNode().DirectUrl
				entry.LocalPath = &filePath
				if _, ok := nameToScheduledTime[*entry.LocalPath]; ok {
					continue
				}
				nameToScheduledTime[*entry.LocalPath] = now
				manifestEntriesBatch = append(manifestEntriesBatch, entry)
			}

			// Schedule downloads
			if len(manifestEntriesBatch) > 0 {
				for _, entry := range manifestEntriesBatch {
					// Add function that returns download path?
					downloadLocalPath := filepath.Join(downloadRoot, *entry.LocalPath)
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
					// Skip downloading the file if it already exists
					if _, err := os.Stat(task.Path); err == nil {
						numDone++
						continue
					}
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

func (ad *ArtifactDownloader) Download() (downloadRoot string, rerr error) {
	artifactAttrs, err := ad.getArtifact()
	if err != nil {
		return "", err
	}
	if ad.DownloadRoot == nil {
		err = ad.setDefaultDownloadRoot(artifactAttrs)
		if err != nil {
			return "", err
		}
		downloadRoot = *ad.DefaultDownloadRoot
	} else {
		downloadRoot = *ad.DownloadRoot
	}

	artifactManifest, err := ad.getArtifactManifest()
	if err != nil {
		return "", err
	}

	if err := ad.downloadFiles(artifactAttrs.Id, artifactManifest); err != nil {
		return "", err
	}
	return downloadRoot, nil
}
