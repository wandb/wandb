# Tag Modification in `wandb sync`

## Overview

This feature allows users to modify run tags during the sync process for offline runs, providing a flexible solution for handling invalid tags that might cause sync failures due to database constraints.

## Why This Approach?

Instead of validating tags during `wandb.init()`, this approach:

1. **Allows maximum flexibility**: Users can set any tags they want during offline runs
2. **Avoids hardcoded limits**: No need to update client code when backend constraints change
3. **Provides user control**: Users can decide how to handle invalid tags during sync
4. **Better UX**: Users aren't blocked from creating runs with problematic tags

## Usage

### Automatic Tag Fixing

```bash
# Automatically fix invalid tags (truncate to 64 chars, remove empty tags)
wandb sync --fix-tags /path/to/offline/run
wandb sync --fix-tags --sync-all
```

### Replace All Tags

```bash
# Replace all tags with a new set
wandb sync --replace-tags "production,model-v2,final" /path/to/offline/run
```

### Examples

```bash
# Fix tags for all offline runs
wandb sync --fix-tags --sync-all

# Replace tags for a specific run
wandb sync --replace-tags "experiment-1,baseline" wandb/offline-run-20231201_143022-abc123

# Multiple options can be combined
wandb sync --fix-tags --project my-project --entity my-team /path/to/run
```

## How It Works

1. **During sync**: The sync process reads the `.wandb` file containing run data
2. **Tag processing**: When a run record is encountered, tags are processed based on the options:
   - `--fix-tags`: Truncates tags >64 chars and removes empty tags
   - `--replace-tags`: Replaces all tags with the provided comma-separated list
3. **User feedback**: The sync process logs what modifications were made
4. **Upload**: The modified run data is uploaded to W&B

## Implementation Details

### Command Line Options

- `--fix-tags`: Boolean flag to automatically fix invalid tags
- `--replace-tags`: String parameter with comma-separated tag list

### Tag Processing Logic

```python
def _process_tags(self, original_tags):
    if self._replace_tags is not None:
        # Replace all tags with provided list
        new_tags = [tag.strip() for tag in self._replace_tags.split(",") if tag.strip()]
        return new_tags
    
    if self._fix_tags:
        # Fix invalid tags
        new_tags = []
        for tag in original_tags:
            if len(tag) == 0:
                continue  # Skip empty tags
            elif len(tag) > 64:
                new_tags.append(tag[:64])  # Truncate to 64 chars
            else:
                new_tags.append(tag)
        return new_tags
    
    return original_tags  # No modifications
```

### Integration Points

1. **CLI**: `wandb/cli/cli.py` - Added command line options
2. **SyncManager**: `wandb/sync/sync.py` - Pass options to sync thread
3. **SyncThread**: `wandb/sync/sync.py` - Process tags in `_parse_pb()` method

## Benefits

1. **No client-side validation**: No hardcoded limits that need updating
2. **User empowerment**: Users can fix their own tag issues
3. **Flexible handling**: Multiple strategies for dealing with invalid tags
4. **Backward compatible**: Existing sync behavior unchanged when options not used
5. **Clear feedback**: Users see exactly what modifications were made

## Future Enhancements

Potential additions:
- Interactive mode: Prompt user for each invalid tag
- Tag validation rules: Allow custom validation patterns
- Batch processing: Apply modifications to multiple runs at once
- Configuration files: Save preferred tag modification rules