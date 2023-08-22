from wandb.sdk.artifacts.artifact_manifest_entry import ArtifactManifestEntry


def test_repr():
    entry = ArtifactManifestEntry(
        path="foo",
        digest="",
        ref="baz",
        birth_artifact_id="qux",
        size=123,
        extra={"quux": "corge"},
        local_path="grault",
    )
    assert eval(repr(entry)) == entry

    blank_entry = ArtifactManifestEntry(
        path="foo", digest="bar", ref="", birth_artifact_id="", size=0
    )
    assert (
        repr(blank_entry) == "ArtifactManifestEntry"
        "(path='foo', digest='bar', ref='', birth_artifact_id='', size=0)"
    )
    assert entry != blank_entry
    assert entry != repr(entry)

    short_entry = ArtifactManifestEntry(path="foo", digest="bar")
    assert repr(short_entry) == "ArtifactManifestEntry(path='foo', digest='bar')"
    assert entry != short_entry
