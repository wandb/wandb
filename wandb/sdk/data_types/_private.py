import tempfile

# Staging directory, so we can encode raw data into files, then hash them before
# we put them into the Run directory to be uploaded.
MEDIA_TMP = tempfile.TemporaryDirectory("wandb-media")
print("Created new media tmpdir", MEDIA_TMP.name)


# clear the tmpdir on exit
def cleanup() -> None:
    print("Cleaning up media tmpdir", MEDIA_TMP.name)
    MEDIA_TMP.cleanup()
