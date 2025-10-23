"""Test executing notebooks against running Jupyter servers."""

import json
import os
import subprocess
import tempfile
import time
from pathlib import Path
from typing import Tuple

import jupyter_core
import nbformat
import requests
from jupyter_client.blocking.client import BlockingKernelClient


class JupyterServerManager:
    """A manager a Jupyter server.

    The manager is responsible for starting and stopping the Jupyter server,
    and for creating and deleting Jupyter sessions.
    """

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_value, traceback):
        self.stop()

    def __init__(
        self,
        server_dir: Path,
        port: int = 8891,
        token: str = "test_token",
    ):
        self.port = port
        self.token = token
        self.server_url = f"http://localhost:{self.port}"

        self.root_dir = server_dir
        self.runtime_dir = server_dir / "runtime"
        self.root_dir.mkdir(parents=True, exist_ok=True)
        self.runtime_dir.mkdir(parents=True, exist_ok=True)

        self.server_proc = self.start()
        assert self._is_ready(), "Server failed to start"

    def start(self) -> subprocess.Popen:
        """Start the jupyter server process."""
        return subprocess.Popen(
            [
                "jupyter",
                "lab",
                "--port",
                str(self.port),
                f"--ServerApp.token={self.token}",
                "--ServerApp.disable_check_xsrf=True",
                "--no-browser",
                f"--ServerApp.root_dir={self.root_dir}",
                "--ServerApp.port_retries=0",
            ],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            env=os.environ.copy(),
        )

    def _is_ready(self) -> bool:
        """Wait for Jupyter server to be ready."""
        start_time = time.monotonic()
        timeout = 30
        while True:
            try:
                response = requests.get(
                    f"{self.server_url}/api/status",
                    headers={"Authorization": f"token {self.token}"},
                )
                if response.status_code == 200:
                    return True
            except requests.ConnectionError:
                pass

            if time.monotonic() - start_time > timeout:
                return False

            time.sleep(1)

    def create_session(self, notebook_path: str) -> Tuple[str, str]:
        """Create a Jupyter session starting a new kernel using the jupyter API.

        Args:
            notebook_path: Path to the notebook relative to root_dir
        """
        response = requests.post(
            f"{self.server_url}/api/sessions",
            json={
                "path": notebook_path,
                "type": "notebook",
                "kernel": {"name": "python3"},
            },
            headers={"Authorization": f"token {self.token}"},
        )
        assert response.status_code == 201, f"Failed to create session: {response.text}"

        session_info = response.json()
        kernel_id = session_info["kernel"]["id"]
        session_id = session_info["id"]

        return session_id, kernel_id

    def delete_session(self, session_id: str):
        """Delete a Jupyter session using the jupyter API."""
        try:
            requests.delete(
                f"{self.server_url}/api/sessions/{session_id}",
                headers={"Authorization": f"token {self.token}"},
                timeout=5,
            )
        except Exception:
            pass  # Ignore errors during cleanup

    def cleanup_all_sessions(self):
        """Delete all active sessions."""
        try:
            response = requests.get(
                f"http://localhost:{self.port}/api/sessions",
                headers={"Authorization": f"token {self.token}"},
                timeout=5,
            )
            if response.status_code == 200:
                sessions = response.json()
                for session in sessions:
                    self.delete_session(session["id"])
        except Exception:
            pass  # Ignore cleanup errors

    def stop(self):
        """Cleans up all sessions and stops the jupyter server process."""

        self.cleanup_all_sessions()
        self.server_proc.terminate()
        try:
            self.server_proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            self.server_proc.kill()


class NotebookClient:
    """A client for executing notebooks against a Jupyter server.

    The client is tied to a specific session and kernel
    created by the Jupyter server.
    """

    def __init__(self, session_id: str, kernel_id: str):
        self.session_id = session_id
        self.kernel_id = kernel_id
        self.connection_file = self._get_connection_file(kernel_id)
        self.nb_client = self._create_nb_client(self.connection_file)

    def _get_connection_file(self, kernel_id: str) -> str:
        """Find the connection file for a kernel in the default runtime directory."""
        max_retries = 30
        default_runtime_dir = Path(jupyter_core.paths.jupyter_runtime_dir())

        for _ in range(max_retries):
            matching = list(default_runtime_dir.glob(f"kernel-{kernel_id}*.json"))
            if matching:
                return str(matching[0])
            time.sleep(0.5)

        raise AssertionError(
            f"No connection file found for kernel {kernel_id} after {max_retries * 0.5}s"
        )

    def _create_nb_client(self, connection_file: str) -> BlockingKernelClient:
        with open(connection_file) as f:
            connection_info = json.load(f)
        client = BlockingKernelClient()
        client.load_connection_info(connection_info)
        client.start_channels()
        client.wait_for_ready(timeout=10)

        return client

    def execute_notebook(self, notebook: nbformat.NotebookNode):
        """Execute a notebook in the notebook."""
        executed_notebook = notebook.copy()
        for cell in executed_notebook.cells:
            self.execute_cell(cell)
        return executed_notebook

    def execute_cell(self, cell):
        """Execute a cell in the notebook."""
        return self.collect_outputs(cell, self.nb_client.execute(cell.source))

    def collect_outputs(self, cell, msg_id: str):
        """Collect outputs from a cell execution."""
        while True:
            msg = self.nb_client.get_iopub_msg()

            if msg["parent_header"].get("msg_id") != msg_id:
                continue

            msg_type = msg["msg_type"]
            content = msg["content"]

            if msg_type == "stream":
                output = nbformat.v4.new_output(
                    output_type="stream",
                    name=content["name"],
                    text=content["text"],
                )
                cell.outputs.append(output)
            elif msg_type == "error":
                output = nbformat.v4.new_output(
                    output_type="error",
                    ename=content["ename"],
                    evalue=content["evalue"],
                    traceback=content["traceback"],
                )
                cell.outputs.append(output)
            elif msg_type == "status":
                if content["execution_state"] == "idle":
                    break
            elif msg_type == "display_data":
                output = nbformat.v4.new_output(
                    output_type="display_data",
                    data=content["data"],
                    metadata=content["metadata"],
                )
                cell.outputs.append(output)
            elif msg_type == "update_display_data":
                output = nbformat.v4.new_output(
                    output_type="display_data",
                    data=content["data"],
                    metadata=content["metadata"],
                )
                cell.outputs.append(output)


def test_jupyter_server_code_saving(wandb_backend_spy):
    with JupyterServerManager(server_dir=Path(tempfile.mkdtemp())) as jupyter_server:
        notebook_name = "test_metadata.ipynb"
        nb = nbformat.v4.new_notebook()
        nb.cells = [
            nbformat.v4.new_code_cell(
                """
                    import wandb

                    with wandb.init(project="test_project", save_code=True) as run:
                        run.log({"test": 1})
                    """
            ),
        ]
        with open(jupyter_server.root_dir / notebook_name, "w") as f:
            nbformat.write(nb, f)
        session_id, kernel_id = jupyter_server.create_session(
            notebook_path=notebook_name
        )
        client = NotebookClient(session_id, kernel_id)

        client.execute_notebook(nb)

        with wandb_backend_spy.freeze() as snapshot:
            run_ids = snapshot.run_ids()
            assert len(run_ids) == 1, f"Expected 1 run, got {len(run_ids)}"
            run_id = run_ids.pop()
            saved_files = snapshot.uploaded_files(run_id=run_id)
            print(f"saved_files: {saved_files}")
            assert "code/test_metadata.ipynb" in saved_files


def test_jupyter_server_code_saving_nested_notebook(wandb_backend_spy):
    with JupyterServerManager(server_dir=Path(tempfile.mkdtemp())) as jupyter_server:
        notebook_name = "test_metadata.ipynb"
        nb_dir = jupyter_server.root_dir / "nested"
        nb_dir.mkdir(parents=True, exist_ok=True)
        nb = nbformat.v4.new_notebook()
        nb.cells = [
            nbformat.v4.new_code_cell(
                """
                import wandb

                with wandb.init(project="test_project", save_code=True) as run:
                    run.log({"test": 1})
                """
            ),
        ]
        with open(nb_dir / notebook_name, "w") as f:
            nbformat.write(nb, f)

        session_id, kernel_id = jupyter_server.create_session(
            notebook_path=f"nested/{notebook_name}"
        )
        client = NotebookClient(session_id, kernel_id)

        client.execute_notebook(nb)

        with wandb_backend_spy.freeze() as snapshot:
            run_ids = snapshot.run_ids()
            assert len(run_ids) == 1, f"Expected 1 run, got {len(run_ids)}"
            run_id = run_ids.pop()
            saved_files = snapshot.uploaded_files(run_id=run_id)
            assert "code/nested/test_metadata.ipynb" in saved_files
