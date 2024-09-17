#!/bin/bash
set -e

# Ensure Go is installed
if ! command -v go &> /dev/null
then
    echo "Go is not installed. Please install Go and try again."
    exit 1
fi

# Build the project (this will trigger the Go binary build as well)
dotnet build src/Wandb/Wandb.csproj --configuration Release

# Run tests
dotnet test src/Wandb.Tests/Wandb.Tests.csproj

# Create NuGet package
dotnet pack src/Wandb/Wandb.csproj --configuration Release

echo "Build completed successfully!"
