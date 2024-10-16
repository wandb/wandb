#!/bin/bash

# Exit immediately if a command exits with a non-zero status.
set -e

# Move to the script's directory
cd "$(dirname "$0")"

# Build the Wandb library
echo "Building Wandb library..."
dotnet build ../../src/Wandb/Wandb.csproj

# Build the example project
echo "Building Basic example..."
dotnet build Basic.csproj

# Run the example
echo "Running Basic example..."
dotnet run --project Basic.csproj

echo "Example completed."
