import collections
import hashlib
import tempfile

# Like md5_file in util but not b64 encoded.
# TODO(artifacts): decide what we actually want
# TODO(artifacts): duplicated from artifacts.py
def hash_file(path):
    hash_md5 = hashlib.md5()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(4096), b""):
            hash_md5.update(chunk)
    return hash_md5.hexdigest()

# TODO(artifacts): define has format (b64 encode or not?)
ArtifactManifestEntry = collections.namedtuple('ArtifactManifestEntry', ('path', 'hash'))

# This MUST match the server implementation!
# TODO(artifacts): limit to X entries with error
class ArtifactManifestV1(object):
    """This is the actual thing we checksum to get a digest."""
    def __init__(self, entries):
        # TODO(artifacts): define sort order
        #   I like something that we can do with low memory when os.walk'ing.
        self._entries = sorted(entries)

    def dump(self, fp):
        # TODO(artifacts): what encoding?
        fp.write('version: 1\n')
        for entry in self._entries:
            fp.write('%s %s\n' % (entry.path, entry.hash))

    @property
    def digest(self):
        with tempfile.NamedTemporaryFile('w+') as fp:
            self.dump(fp)
            # TODO: what format for md5
            fp.seek(0)
            return hash_file(fp.name)