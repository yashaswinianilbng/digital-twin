import os
import shutil
import zipfile
import subprocess


def _install_deps_lambda_image():
    """Install Linux wheels into lambda-package using the Lambda runtime image.

    Pip stages ``--target`` installs under ``/tmp/pip-target-*`` then renames into
    the destination. A Windows bind mount for the destination is a different
    filesystem than ``/tmp``, so rename fails (EXDEV) and the fallback hits
    permission errors. Installing to ``/build`` inside the container keeps temp
    and target on one filesystem; we copy the result out with ``docker cp``.
    """
    req = os.path.abspath("requirements.txt")
    if not os.path.isfile(req):
        raise FileNotFoundError(f"Missing {req}")

    pip_cmd = (
        "pip install --target /build -r /req.txt "
        "--platform manylinux2014_x86_64 --only-binary=:all: --upgrade"
    )
    create = subprocess.run(
        [
            "docker",
            "create",
            "--platform",
            "linux/amd64",
            "-v",
            f"{req}:/req.txt:ro",
            # Windows Docker often rejects --entrypoint ""; use /bin/sh explicitly.
            "--entrypoint",
            "/bin/sh",
            "public.ecr.aws/lambda/python:3.12",
            "-c",
            pip_cmd,
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    if create.returncode != 0:
        err = (create.stderr or "").strip() or (create.stdout or "").strip()
        raise RuntimeError(
            "docker create failed (is Docker Desktop running?). "
            f"exit={create.returncode}\n{err}"
        )
    cid = create.stdout.strip()
    try:
        subprocess.run(["docker", "start", "-a", cid], check=True)
        os.makedirs("lambda-package", exist_ok=True)
        dest = os.path.abspath("lambda-package")
        subprocess.run(
            ["docker", "cp", f"{cid}:/build/.", dest + os.sep],
            check=True,
        )
    finally:
        subprocess.run(["docker", "rm", "-f", cid], check=False)


def main():
    print("Creating Lambda deployment package...")

    # Clean up
    if os.path.exists("lambda-package"):
        shutil.rmtree("lambda-package")
    if os.path.exists("lambda-deployment.zip"):
        os.remove("lambda-deployment.zip")

    print("Installing dependencies for Lambda runtime...")
    _install_deps_lambda_image()

    # Copy application files
    print("Copying application files...")
    for file in ["server.py", "lambda_handler.py", "context.py", "resources.py"]:
        if os.path.exists(file):
            shutil.copy2(file, "lambda-package/")

    # Copy data directory
    if os.path.exists("data"):
        shutil.copytree("data", "lambda-package/data")

    # Create zip
    print("Creating zip file...")
    with zipfile.ZipFile("lambda-deployment.zip", "w", zipfile.ZIP_DEFLATED) as zipf:
        for root, dirs, files in os.walk("lambda-package"):
            for file in files:
                file_path = os.path.join(root, file)
                arcname = os.path.relpath(file_path, "lambda-package")
                zipf.write(file_path, arcname)

    # Show package size
    size_mb = os.path.getsize("lambda-deployment.zip") / (1024 * 1024)
    print(f"Created lambda-deployment.zip ({size_mb:.2f} MB)")


if __name__ == "__main__":
    main()
