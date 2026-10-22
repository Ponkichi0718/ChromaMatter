"""Download one reviewed same-repository source asset; never uploads or publishes."""
import hashlib
import os
from pathlib import Path
import re
import subprocess
import sys
from urllib.parse import urlsplit


def validate(url, asset_id, digest, label):
    if bool(url) == bool(asset_id):
        raise ValueError("Supply exactly one source URL or release asset ID")
    if not re.fullmatch(r"[a-fA-F0-9]{64}", digest):
        raise ValueError("Source SHA-256 must contain 64 hex digits")
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]{0,79}", label):
        raise ValueError("Invalid release label")
    if url:
        parts = urlsplit(url)
        if (parts.scheme != "https" or parts.netloc != "github.com" or parts.query or parts.fragment
                or not parts.path.startswith("/Ponkichi0718/ChromaMatter/releases/download/")
                or not parts.path.endswith(".tar.gz") or any(ord(c) <= 32 for c in url)):
            raise ValueError("Source URL must be an HTTPS release asset in Ponkichi0718/ChromaMatter")
    elif not re.fullmatch(r"[1-9][0-9]*", asset_id):
        raise ValueError("Release asset ID must be a positive integer")


def main():
    import argparse
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    url = os.environ.get("SOURCE_URL", "")
    asset_id = os.environ.get("SOURCE_ASSET_ID", "")
    digest = os.environ.get("SOURCE_SHA256", "")
    validate(url, asset_id, digest, os.environ.get("SORCA_RELEASE_LABEL", ""))
    # No token is placed in argv, files, error messages, or output.
    with args.output.open("xb") as stream:
        if url:
            command = ["curl", "--fail", "--location", "--retry", "2", "--proto", "=https", "--proto-redir", "=https", url]
        else:
            if not os.environ.get("GH_TOKEN"):
                raise RuntimeError("Authenticated release asset download requires GH_TOKEN")
            command = ["gh", "api", "--hostname", "github.com", "-H", "Accept: application/octet-stream",
                       f"repos/Ponkichi0718/ChromaMatter/releases/assets/{asset_id}"]
        subprocess.run(command, stdout=stream, check=True)
    with args.output.open("rb") as stream:
        actual = hashlib.file_digest(stream, "sha256").hexdigest()
    if actual != digest.lower():
        raise RuntimeError("Downloaded packet SHA-256 differs from the reviewed input")
    print("Verified source packet:", args.output.stat().st_size, "bytes; SHA-256", actual)


if __name__ == "__main__":
    main()
