import json
import socket
import tempfile
import threading
import time
from pathlib import Path
from typing import Callable, Generator, Tuple

import jupyter_core
import nbformat
import nest_asyncio
import pytest
import requests
from jupyter_client.blocking.client import BlockingKernelClient
from jupyter_server.serverapp import ServerApp

# Since Jupyter uses asyncio, this is necessary to allow the server to run
# with wandb_backend which uses asyncio as well.
nest_asyncio.apply()


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
    ):
        self.port = self.get_port()
        self.root_dir = server_dir
        self.runtime_dir = server_dir / "runtime"
        self.root_dir.mkdir(parents=True, exist_ok=True)
        self.runtime_dir.mkdir(parents=True, exist_ok=True)

        self.server_app = ServerApp()

        self.server_app.initialize(
            argv=[
                "--port",
                str(self.port),
                "--port-retries",
                "50",
                "--no-browser",
                f"--ServerApp.root_dir={server_dir}",
                "--ServerApp.disable_check_xsrf=True",
                "--allow-root",  # CircleCI runs as root
            ]
        )
        self.server_thread = threading.Thread(target=self.server_app.start, daemon=True)
        self.server_thread.start()

        self.port = self.server_app.port
        self.server_url = self.server_app.connection_url
        self.token = self.server_app.token

        assert self._is_ready(), "Server failed to start"

    def get_port(self) -> int:
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        s.bind(("127.0.0.1", 0))
        s.listen(1)
        port = s.getsockname()[1]
        s.close()
        return port

    def _is_ready(self) -> bool:
        """Wait for Jupyter server to be ready."""
        start_time = time.monotonic()
        timeout = 30
        while True:
            self.port = self.server_app.port
            self.server_url = self.server_app.connection_url
            self.token = self.server_app.token
            try:
                response = requests.get(
                    f"{self.server_url}/api/status",
                    headers={"Authorization": f"token {self.token}"},
                )
                if response.status_code == 200:
                    return True
                else:
                    print(f"Server status: {response.status_code} {response.text}")
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
        self.server_app.stop()
        self.server_thread.join()


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


@pytest.fixture(scope="session")
def jupyter_server() -> Generator[JupyterServerManager, None, None]:
    with JupyterServerManager(server_dir=Path(tempfile.mkdtemp())) as jupyter_server:
        yield jupyter_server


@pytest.fixture()
def notebook_client(
    jupyter_server: JupyterServerManager,
) -> Generator[Callable[[str], NotebookClient], None, None]:
    def _new_notebook_client(notebook_path: str) -> NotebookClient:
        session_id, kernel_id = jupyter_server.create_session(
            notebook_path=notebook_path
        )
        return NotebookClient(session_id, kernel_id)

    yield _new_notebook_client
