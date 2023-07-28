package server

import (
	"context"
	"crypto/md5"
	b64 "encoding/base64"
	"encoding/json"
	"fmt"
	"os"
	"sync"

	"github.com/Khan/genqlient/graphql"
	"github.com/wandb/wandb/nexus/pkg/observability"
	"github.com/wandb/wandb/nexus/pkg/service"
)

type ArtifactSaver struct {
	ctx           context.Context
	logger        *observability.NexusLogger
	artifact      *service.ArtifactRecord
	graphqlClient graphql.Client
	uploader      *Uploader
	wgOutstanding sync.WaitGroup
}

type ArtifactSaverResult struct {
	ArtifactId string
}

type ManifestStoragePolicyConfig struct {
	StorageLayout string `json:"storageLayout"`
}

type ManifestEntry struct {
	Digest          string `json:"digest"`
	BirthArtifactID string `json:"birthArifactID"`
	Size            int64  `json:"size"`
}

type ManifestV1 struct {
	Version             int32                       `json:"version"`
	StoragePolicy       string                      `json:"storagePolicy"`
	StoragePolicyConfig ManifestStoragePolicyConfig `json:"storagePolicyConfig"`
	Contents            map[string]ManifestEntry    `json:"contents"`
}

func computeB64MD5(manifestFile string) (string, error) {
	file, err := os.ReadFile(manifestFile)
	if err != nil {
		return "", err
	}
	hasher := md5.New()
	hasher.Write(file)
	encodedString := b64.StdEncoding.EncodeToString(hasher.Sum(nil))
	return encodedString, nil
}

func (as *ArtifactSaver) createArtifact() (string, *string) {
	enableDedup := false
	aliases := []ArtifactAliasInput{}
	for _, alias := range as.artifact.Aliases {
		aliases = append(aliases,
			ArtifactAliasInput{
				ArtifactCollectionName: as.artifact.Name,
				Alias:                  alias,
			},
		)
	}

	response, err := CreateArtifact(
		as.ctx,
		as.graphqlClient,
		as.artifact.Type,
		[]string{as.artifact.Name},
		as.artifact.Entity,
		as.artifact.Project,
		&as.artifact.RunId,
		&as.artifact.Description,
		as.artifact.Digest,
		nil, // Labels
		aliases,
		nil, // metadata
		// 0,   // historyStep
		// &as.artifact.DistributedId,
		as.artifact.ClientId,
		as.artifact.SequenceClientId,
		&enableDedup, // enableDigestDeduplication
	)
	if err != nil {
		err = fmt.Errorf("CreateArtifact: %s, error: %+v response: %+v", as.artifact.Name, err, response)
		as.logger.CaptureFatalAndPanic("createArtifact", err)
	}
	artifact := response.GetCreateArtifact().GetArtifact()
	latest := artifact.ArtifactSequence.GetLatestArtifact()

	var baseId *string
	if latest != nil {
		baseId = &latest.Id
	}
	return artifact.Id, baseId
}

func (as *ArtifactSaver) createManifest(artifactId string, baseArtifactId *string, manifestDigest string, includeUpload bool) (string, *string, []string) {
	const manifestFilename = "wandb_manifest.json"
	manifestType := ArtifactManifestTypeFull

	response, err := CreateArtifactManifest(
		as.ctx,
		as.graphqlClient,
		manifestFilename,
		manifestDigest,
		artifactId,
		baseArtifactId,
		as.artifact.Entity,
		as.artifact.Project,
		as.artifact.RunId,
		includeUpload,
		&manifestType,
	)
	if err != nil {
		err = fmt.Errorf("CreateArtifactManifest: %s, error: %+v response: %+v", as.artifact.Name, err, response)
		as.logger.CaptureFatalAndPanic("createManifest", err)
	}
	createManifest := response.GetCreateArtifactManifest()
	manifest := createManifest.ArtifactManifest

	var upload *string
	var headers []string
	if includeUpload {
		upload = manifest.File.GetUploadUrl()
		headers = manifest.File.GetUploadHeaders()
	}

	return manifest.Id, upload, headers
}

func (as *ArtifactSaver) sendManifestFiles(artifactID string, manifestID string) {
	artifactFiles := []CreateArtifactFileSpecInput{}
	man := as.artifact.Manifest
	for _, entry := range man.Contents {
		as.logger.Info("sendfiles", "entry", entry)
		md5Checksum := ""
		artifactFiles = append(artifactFiles,
			CreateArtifactFileSpecInput{
				ArtifactID:         artifactID,
				Name:               entry.Path,
				Md5:                md5Checksum,
				ArtifactManifestID: &manifestID,
			})
	}
	response, err := CreateArtifactFiles(
		as.ctx,
		as.graphqlClient,
		ArtifactStorageLayoutV2,
		artifactFiles,
	)
	if err != nil {
		err = fmt.Errorf("CreateArtifactFiles: %s, error: %+v response: %+v", as.artifact.Name, err, response)
		as.logger.CaptureFatalAndPanic("sendManifestFiles", err)
	}
	for n, edge := range response.GetCreateArtifactFiles().GetFiles().Edges {
		upload := UploadTask{
			url:           *edge.Node.GetUploadUrl(),
			path:          man.Contents[n].LocalPath,
			wgOutstanding: &as.wgOutstanding,
		}
		as.uploader.AddTask(&upload)
	}
}

func (as *ArtifactSaver) writeManifest() (string, error) {
	man := as.artifact.Manifest

	m := &ManifestV1{
		Version:       man.Version,
		StoragePolicy: man.StoragePolicy,
		StoragePolicyConfig: ManifestStoragePolicyConfig{
			StorageLayout: "V2",
		},
		Contents: make(map[string]ManifestEntry),
	}

	for _, entry := range man.Contents {
		m.Contents[entry.Path] = ManifestEntry{
			Digest: entry.Digest,
			Size:   entry.Size,
		}
	}

	jsonBytes, _ := json.MarshalIndent(m, "", "    ")

	f, err := os.CreateTemp("", "tmpfile-")
	if err != nil {
		return "", err
	}

	defer f.Close()

	if _, err := f.Write(jsonBytes); err != nil {
		return "", err
	}

	return f.Name(), nil
}

func (as *ArtifactSaver) sendManifest(manifestFile string, uploadUrl *string, uploadHeaders []string) {
	upload := UploadTask{
		url:           *uploadUrl,
		path:          manifestFile,
		headers:       uploadHeaders,
		wgOutstanding: &as.wgOutstanding,
	}
	as.uploader.AddTask(&upload)
}

func (as *ArtifactSaver) commitArtifact(artifactId string) {
	response, err := CommitArtifact(
		as.ctx,
		as.graphqlClient,
		artifactId,
	)
	if err != nil {
		err = fmt.Errorf("CommitArtifact: %s, error: %+v response: %+v", as.artifact.Name, err, response)
		as.logger.CaptureFatalAndPanic("commitArtifact", err)
	}
}

func (as *ArtifactSaver) save() (ArtifactSaverResult, error) {
	artifactId, baseArtifactId := as.createArtifact()
	manifestId, _, _ := as.createManifest(artifactId, baseArtifactId, "", false)
	as.sendManifestFiles(artifactId, manifestId)
	manifestFile, err := as.writeManifest()
	if err != nil {
		return ArtifactSaverResult{}, err
	}
	manifestDigest, err := computeB64MD5(manifestFile)
	if err != nil {
		return ArtifactSaverResult{}, err
	}
	defer os.Remove(manifestFile)
	_, uploadUrl, uploadHeaders := as.createManifest(artifactId, baseArtifactId, manifestDigest, true)
	as.sendManifest(manifestFile, uploadUrl, uploadHeaders)
	// wait on all outstanding requests before commit
	as.wgOutstanding.Wait()
	as.commitArtifact(artifactId)

	return ArtifactSaverResult{ArtifactId: artifactId}, nil
}
