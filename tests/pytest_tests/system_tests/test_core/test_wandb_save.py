import pathlib


def test_uploads_at_end(tmp_path, relay_server, wandb_init):
    file = tmp_path / "my_test_dir" / "my_test_file.txt"
    file.parent.mkdir()
    file.write_text("testing testing")

    with relay_server() as relay, wandb_init() as run:
        run.save(file, policy="end")

    uploaded_files = relay.context.get_run_uploaded_files(run.id)
    assert str(pathlib.Path("my_test_dir", "my_test_file.txt")) in uploaded_files
