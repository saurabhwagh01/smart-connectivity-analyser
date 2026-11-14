"""Runtime startup test with optional PyTorch/AI imports unavailable."""
import os
import pathlib
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request


ROOT = pathlib.Path(__file__).resolve().parents[1]
PORT = 8765
SITE_CUSTOMIZE = """
import builtins
_original_import = builtins.__import__
def _without_optional_torch(name, globals=None, locals=None, fromlist=(), level=0):
    if name == "torch" or name.startswith("torch."):
        raise ImportError("PyTorch intentionally disabled for startup test")
    return _original_import(name, globals, locals, fromlist, level)
builtins.__import__ = _without_optional_torch
"""


def main():
    with tempfile.TemporaryDirectory(prefix="issue5-no-ai-") as temp_dir:
        pathlib.Path(temp_dir, "sitecustomize.py").write_text(
            SITE_CUSTOMIZE, encoding="utf-8"
        )
        env = os.environ.copy()
        env["PYTHONPATH"] = os.pathsep.join(
            [temp_dir, str(ROOT), env.get("PYTHONPATH", "")]
        )
        command = [
            sys.executable,
            "-c",
            (
                "import uvicorn; "
                f'uvicorn.run("backend.main:app", host="127.0.0.1", port={PORT}, '
                'log_level="error")'
            ),
        ]
        process = subprocess.Popen(
            command,
            cwd=ROOT,
            env=env,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
        )
        try:
            deadline = time.monotonic() + 20
            last_error = None
            while time.monotonic() < deadline:
                if process.poll() is not None:
                    output = process.stdout.read() if process.stdout else ""
                    raise AssertionError(
                        "Backend exited before becoming healthy.\n" + output
                    )
                try:
                    with urllib.request.urlopen(
                        f"http://127.0.0.1:{PORT}/api/health", timeout=1
                    ) as response:
                        import json
                        payload = json.loads(response.read().decode("utf-8"))
                        assert response.status == 200
                        assert payload["status"] == "ok"
                        assert payload["service"] == (
                            "Smart Internet Connectivity Analyser"
                        )
                        print(
                            "Backend startup passed with optional PyTorch/AI "
                            "dependencies unavailable."
                        )
                        return
                except (urllib.error.URLError, TimeoutError, OSError) as error:
                    last_error = error
                    time.sleep(0.25)
            raise AssertionError(
                f"Backend did not become healthy within 20 seconds: {last_error}"
            )
        finally:
            process.terminate()
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=5)


if __name__ == "__main__":
    main()
