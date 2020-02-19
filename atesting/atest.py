import sys

from wandb.apis import artifacts
from wandb import util
from wandb import InternalApi
from wandb.file_pusher import FilePusher

api = InternalApi()
api.set_current_run_id('ebhnc140')
file_pusher = FilePusher(api)

la = artifacts.LocalArtifact(sys.argv, file_pusher=file_pusher)
print('LA LOCAL ENTRIES', la._local_manifest.entries)
print('LA LOCAL DIGEST ', la._local_manifest._manifest.digest)
print('LA LOCAL MANFIEST ENTRIES', la._local_manifest._manifest._entries)
la.save('new-artifact2')
la.wait()

print("Waiting for filepusher to shutdown")
file_pusher.shutdown()
print("Donest")


# Sync flow
#   check if server has artifact
#   if it does, do nothing
# 
# If you use the run APIs, you don't get a digest
#   if you run in online mode, let the back-half just compute the digest
#   if you're in dryrun mode, compute the digest in the user thread? (so we have a snapshot of it)

