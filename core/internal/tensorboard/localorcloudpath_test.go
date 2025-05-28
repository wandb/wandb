package tensorboard_test

import (
	"testing"

	"github.com/stretchr/testify/assert"
	"github.com/stretchr/testify/require"
	"github.com/wandb/wandb/core/internal/paths"
	"github.com/wandb/wandb/core/internal/tensorboard"
)

func toAbsolutePathPtr(t *testing.T, s string) *paths.AbsolutePath {
	t.Helper()
	path, err := paths.Absolute(s)
	require.NoError(t, err)
	return path
}

func TestParseS3Path(t *testing.T) {
	path, err := tensorboard.ParseTBPath("s3://my-bucket/path/to/dir/")

	require.NoError(t, err)
	assert.Equal(t, &tensorboard.LocalOrCloudPath{
		CloudPath: &tensorboard.CloudPath{
			Scheme:     "s3",
			BucketName: "my-bucket",
			Path:       "path/to/dir",
		},
	}, path)
}

func TestParseGSPath(t *testing.T) {
	path, err := tensorboard.ParseTBPath("gs://my-bucket/path/to/dir/")

	require.NoError(t, err)
	assert.Equal(t, &tensorboard.LocalOrCloudPath{
		CloudPath: &tensorboard.CloudPath{
			Scheme:     "gs",
			BucketName: "my-bucket",
			Path:       "path/to/dir",
		},
	}, path)
}

func TestParseAZPath(t *testing.T) {
	path, err := tensorboard.ParseTBPath("az://account/bucket/path/to/dir/")

	require.NoError(t, err)
	assert.Equal(t, &tensorboard.LocalOrCloudPath{
		CloudPath: &tensorboard.CloudPath{
			Scheme:     "azblob",
			BucketName: "bucket",
			Path:       "path/to/dir",
		},
	}, path)
}

func TestParseCloudPath_InvalidURL_Error(t *testing.T) {
	path, err := tensorboard.ParseTBPath("s3://my-bucket\n<-invalid character")

	assert.Nil(t, path)
	assert.ErrorContains(t, err, "failed to parse cloud URL")
}

func TestParseLocalPath(t *testing.T) {
	path, err := tensorboard.ParseTBPath("/my/unix/path")

	require.NoError(t, err)
	assert.Equal(t, &tensorboard.LocalOrCloudPath{
		LocalPath: toAbsolutePathPtr(t, "/my/unix/path"),
	}, path)
}

func TestToSlashPath(t *testing.T) {
	testCases := []struct {
		url      string
		expected string
	}{
		{url: "gs://my-bucket/log/dir", expected: "my-bucket/log/dir"},
		{url: "/local/path", expected: "/local/path"},
	}

	for _, testCase := range testCases {
		t.Run(testCase.url, func(t *testing.T) {
			path, err := tensorboard.ParseTBPath(testCase.url)
			require.NoError(t, err)

			assert.Equal(t, testCase.expected, path.ToSlashPath())
		})
	}
}

func TestChild(t *testing.T) {
	testCases := []struct {
		url      string
		child    string
		expected string
	}{
		{url: "gs://my-bucket", child: "abc", expected: "gs://my-bucket/abc"},
		{url: "s3://bucket/xyz", child: "abc", expected: "s3://bucket/xyz/abc"},
		{url: "/my/unix/path", child: "tfevents", expected: "/my/unix/path/tfevents"},
	}

	for _, testCase := range testCases {
		t.Run(testCase.url, func(t *testing.T) {
			path, err := tensorboard.ParseTBPath(testCase.url)
			require.NoError(t, err)
			expectedPath, err := tensorboard.ParseTBPath(testCase.expected)
			require.NoError(t, err)

			result, err := path.Child(testCase.child)

			require.NoError(t, err)
			assert.Equal(t, expectedPath, result)
		})
	}
}

func TestChild_LocalPathError(t *testing.T) {
	testCases := []struct {
		name  string
		url   string
		child string
	}{
		{name: "Absolute", url: "some/path", child: "/xyz"},
		{name: "Nonlocal", url: "some/path", child: "../xyz"},
	}

	for _, testCase := range testCases {
		t.Run(testCase.name, func(t *testing.T) {
			path, err := tensorboard.ParseTBPath(testCase.url)
			require.NoError(t, err)

			result, err := path.Child(testCase.child)

			assert.Nil(t, result)
			assert.Error(t, err)
		})
	}
}
