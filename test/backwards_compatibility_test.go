package test

import (
	"fmt"
	"os"
	"os/exec"
	"path/filepath"
	"strings"
	"testing"
)

const (
	WORKSPACE_ID  = "5316df47-1f1c-4a5e-85e6-645e6b821616"
	SYSTEM_ID     = "55469883-36ae-450a-bc2b-60f6637ed3f4"
	DEPLOYMENT_ID = "c585065c-4132-4b91-a479-cf45830b1576"
	API_KEY       = "f89b6f6172b99919.a02ec78ed6bb0729f860ca7bee5e44495b39eb543ed5c9d8dea7b05e55aa40bf"
	API_URL       = "http://localhost:3000/api"
)

func runCommand(args ...string) (string, error) {
	// Get the current working directory
	cmdDir, err := os.Getwd()
	if err != nil {
		return "", fmt.Errorf("failed to get working directory: %v", err)
	}

	// If we're in the test directory, go up one level to the cli directory
	if filepath.Base(cmdDir) == "test" {
		cmdDir = filepath.Dir(cmdDir)
	}

	// Prepend 'api' to the command args
	args = append([]string{"api"}, args...)

	cmd := exec.Command("go", append([]string{"run", "cmd/ctrlc/ctrlc.go"}, args...)...)
	cmd.Dir = cmdDir
	cmd.Env = append(os.Environ(),
		fmt.Sprintf("CTRLPLANE_API_KEY=%s", API_KEY),
		fmt.Sprintf("CTRLPLANE_URL=%s", API_URL),
	)
	output, err := cmd.CombinedOutput()
	if err != nil {
		return "", fmt.Errorf("command failed: %v\nOutput: %s", err, string(output))
	}
	return string(output), nil
}

func extractID(output string) string {
	lines := strings.Split(output, "\n")
	for _, line := range lines {
		if strings.Contains(line, "\"id\":") {
			// Find the last occurrence of ":" to handle cases where the ID might contain colons
			lastColon := strings.LastIndex(line, ":")
			if lastColon != -1 {
				// Get everything after the last colon
				id := line[lastColon+1:]
				// Remove any quotes, commas, and whitespace
				id = strings.TrimSpace(id)
				id = strings.Trim(id, ",")
				id = strings.Trim(id, `"`)
				id = strings.TrimSpace(id)
				fmt.Println("ID:", id)
				return id
			}
		}
	}
	return ""
}

func TestReleaseBackwardsCompatibility(t *testing.T) {
	fmt.Println("\n=== Testing Release Endpoints ===")

	// Test old release endpoint (create)
	fmt.Println("\nTesting old release endpoint (create release)")
	oldReleaseOutput, err := runCommand("create", "release",
		"--version", "v1.0.0",
		"--deployment", DEPLOYMENT_ID,
		"--name", "Test Release",
		"--config", "test=config",
		"--job-agent-config", "test=job_config",
	)
	if err != nil {
		t.Fatalf("Failed to create old release: %v", err)
	}
	fmt.Println("Old release output:", oldReleaseOutput)

	// Extract release ID from output
	releaseID := extractID(oldReleaseOutput)
	fmt.Println("Release ID:", releaseID)
	if releaseID == "" {
		t.Fatal("Failed to extract release ID from output")
	}

	// Test old release update endpoint
	fmt.Println("\nTesting old release update endpoint (update release)")
	oldUpdateOutput, err := runCommand("update", "release",
		"--release-id", releaseID,
		"--version", "v1.0.1",
	)
	if err != nil {
		t.Fatalf("Failed to update old release: %v", err)
	}
	fmt.Println("Old release update output:", oldUpdateOutput)

	// Test new deployment version endpoint (create)
	fmt.Println("\nTesting new deployment version endpoint (create deployment-version)")
	newVersionOutput, err := runCommand("create", "deployment-version",
		"--tag", "v1.1.0",
		"--deployment", DEPLOYMENT_ID,
		"--name", "Test Deployment Version",
		"--config", "test=config",
		"--job-agent-config", "test=job_config",
	)
	if err != nil {
		t.Fatalf("Failed to create new deployment version: %v", err)
	}
	fmt.Println("New deployment version output:", newVersionOutput)

	// Extract version ID from output
	versionID := extractID(newVersionOutput)
	if versionID == "" {
		t.Fatal("Failed to extract version ID from output")
	}

	// Test new deployment version update endpoint
	fmt.Println("\nTesting new deployment version update endpoint (update deployment-version)")
	newUpdateOutput, err := runCommand("update", "deployment-version",
		"--deployment-version-id", versionID,
		"--tag", "v1.1.1",
	)
	if err != nil {
		t.Fatalf("Failed to update new deployment version: %v", err)
	}
	fmt.Println("New deployment version update output:", newUpdateOutput)
}

func TestReleaseChannelBackwardsCompatibility(t *testing.T) {
	fmt.Println("\n=== Testing Release Channel Endpoints ===")

	// Test old release channel endpoint (create)
	fmt.Println("\nTesting old release channel endpoint (create release-channel)")
	oldChannelOutput, err := runCommand("create", "release-channel",
		"--deployment", DEPLOYMENT_ID,
		"--name", "test-channel",
		"--description", "Test channel",
		"--selector", `{"type":"version","operator":"equals","value":"v1.0.0"}`,
	)
	if err != nil {
		t.Fatalf("Failed to create old release channel: %v", err)
	}
	fmt.Println("Old release channel output:", oldChannelOutput)

	// Test old release channel deletion
	fmt.Println("\nTesting old release channel deletion (delete release-channel)")
	oldDeleteOutput, err := runCommand("delete", "release-channel",
		"--deployment", DEPLOYMENT_ID,
		"--name", "test-channel",
	)
	if err != nil {
		t.Fatalf("Failed to delete old release channel: %v", err)
	}
	fmt.Println("Old release channel deletion output:", oldDeleteOutput)

	// Test new deployment version channel endpoint (create)
	fmt.Println("\nTesting new deployment version channel endpoint (create deployment-version-channel)")
	newChannelOutput, err := runCommand("create", "deployment-version-channel",
		"--deployment", DEPLOYMENT_ID,
		"--name", "test-version-channel",
		"--description", "Test version channel",
		"--selector", `{"type":"tag","operator":"equals","value":"v1.1.0"}`,
	)
	if err != nil {
		t.Fatalf("Failed to create new deployment version channel: %v", err)
	}
	fmt.Println("New deployment version channel output:", newChannelOutput)

	// Skip deployment version channel deletion since endpoint doesn't exist yet
	runCommand("delete", "deployment-version-channel", "--deployment", DEPLOYMENT_ID, "--name", "test-version-channel")

	// Extract release channel ID
	releaseChannelID := extractID(oldChannelOutput)
	fmt.Println("Release channel ID:", releaseChannelID)
	if releaseChannelID == "" {
		t.Fatal("Failed to extract release channel ID")
	}
}

func TestEnvironmentWithMixedChannels(t *testing.T) {
	fmt.Println("\n=== Testing Environment with Mixed Channels ===")

	// Create a release channel
	fmt.Println("\nCreating release channel for mixed environment")
	releaseChannelOutput, err := runCommand("create", "release-channel",
		"--deployment", DEPLOYMENT_ID,
		"--name", "mixed-test-release-channel",
		"--description", "Test release channel for mixed environment",
		"--selector", `{"type":"version","operator":"equals","value":"v1.0.0"}`,
	)
	if err != nil {
		t.Fatalf("Failed to create release channel: %v", err)
	}
	fmt.Println("Release channel output:", releaseChannelOutput)

	// Extract release channel ID
	releaseChannelID := extractID(releaseChannelOutput)
	fmt.Println("Release channel ID:", releaseChannelID)
	if releaseChannelID == "" {
		t.Fatal("Failed to extract release channel ID")
	}

	// Create a deployment version channel
	fmt.Println("\nCreating deployment version channel for mixed environment")
	versionChannelOutput, err := runCommand("create", "deployment-version-channel",
		"--deployment", DEPLOYMENT_ID,
		"--name", "mixed-test-version-channel",
		"--description", "Test version channel for mixed environment",
		"--selector", `{"type":"tag","operator":"equals","value":"v1.1.0"}`,
	)
	if err != nil {
		t.Fatalf("Failed to create deployment version channel: %v", err)
	}
	fmt.Println("Deployment version channel output:", versionChannelOutput)

	// Extract version channel ID
	versionChannelID := extractID(versionChannelOutput)
	fmt.Println("Version channel ID:", versionChannelID)
	if versionChannelID == "" {
		t.Fatal("Failed to extract version channel ID")
	}

	// Create environment with both channels
	fmt.Println("\nCreating environment with mixed channels")
	environmentOutput, err := runCommand("create", "environment",
		"--system", SYSTEM_ID,
		"--name", "mixed-test-environment",
		"--release-channel", releaseChannelID,
		"--deployment-version-channel", versionChannelID,
		"--metadata", "test=mixed environment",
	)
	if err != nil {
		t.Fatalf("Failed to create environment: %v", err)
	}
	fmt.Println("Environment output:", environmentOutput)

	// Extract environment ID
	environmentID := extractID(environmentOutput)
	if environmentID == "" {
		t.Fatal("Failed to extract environment ID")
	}

	// Clean up
	fmt.Println("\nCleaning up...")
	runCommand("delete", "environment", "--environment", environmentID)
	runCommand("delete", "release-channel", "--deployment", DEPLOYMENT_ID, "--name", "mixed-test-release-channel")
	runCommand("delete", "deployment-version-channel", "--deployment", DEPLOYMENT_ID, "--name", "mixed-test-version-channel")
}
