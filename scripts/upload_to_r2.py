#!/usr/bin/env python3
"""Upload IMPACT-NCATS JSON data files to Cloudflare R2 (S3-compatible API).

Syncs docs/data/ to the R2 bucket under the R2_PREFIX ("ncats/"), skipping files
that haven't changed (checked by ETag/MD5).

IMPORTANT: this bucket is shared with IMPACT. Every object key MUST be prefixed,
or an unprefixed index.json would overwrite IMPACT's live production data. That
invariant is asserted before any upload happens.

Requirements:
    pip install boto3

Credentials (in .env):
    R2_ACCOUNT_ID, R2_BUCKET_NAME, R2_ACCESS_KEY_ID,
    R2_SECRET_ACCESS_KEY, R2_PUBLIC_URL, R2_PREFIX

Usage:
    python scripts/upload_to_r2.py            # sync changed files only
    python scripts/upload_to_r2.py --dry-run  # show what would change
    python scripts/upload_to_r2.py --force    # re-upload everything
"""

import sys
import os
import hashlib
import argparse
import logging
import time
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

try:
    import boto3
except ImportError:
    print("ERROR: boto3 not installed. Run: pip install boto3")
    sys.exit(1)

from src.ncats.config import (
    R2_ACCOUNT_ID, R2_BUCKET_NAME, R2_ACCESS_KEY_ID,
    R2_SECRET_ACCESS_KEY, R2_PUBLIC_URL, R2_PREFIX, WEBSITE_DATA_DIR,
)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("upload_r2")


def md5_hex(path: Path) -> str:
    h = hashlib.md5()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def build_key(path: Path, data_dir: Path, prefix: str) -> str:
    """Object key for a local file, always under the prefix."""
    return f"{prefix}/{path.relative_to(data_dir).as_posix()}"


def get_client():
    for var, val in [("R2_ACCOUNT_ID", R2_ACCOUNT_ID),
                     ("R2_ACCESS_KEY_ID", R2_ACCESS_KEY_ID),
                     ("R2_SECRET_ACCESS_KEY", R2_SECRET_ACCESS_KEY)]:
        if not val:
            print(f"ERROR: {var} not set in .env")
            sys.exit(1)
    return boto3.client(
        "s3",
        endpoint_url=f"https://{R2_ACCOUNT_ID}.r2.cloudflarestorage.com",
        aws_access_key_id=R2_ACCESS_KEY_ID,
        aws_secret_access_key=R2_SECRET_ACCESS_KEY,
        region_name="auto",
    )


def list_remote_etags(client, prefix: str) -> dict:
    """Remote ETags for objects under our prefix only."""
    etags = {}
    paginator = client.get_paginator("list_objects_v2")
    for page in paginator.paginate(Bucket=R2_BUCKET_NAME, Prefix=f"{prefix}/"):
        for obj in page.get("Contents", []):
            etags[obj["Key"]] = obj["ETag"].strip('"').lower()
    return etags


def main():
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--force", action="store_true")
    parser.add_argument("--prune-remote", action="store_true",
                        help="Delete objects under the prefix that no longer exist "
                             "locally. Only ever touches keys under R2_PREFIX.")
    args = parser.parse_args()

    prefix = (R2_PREFIX or "").strip("/")
    if not prefix:
        logger.error("R2_PREFIX is empty. Refusing to upload — unprefixed keys "
                     "would overwrite IMPACT's production data.")
        sys.exit(1)

    data_dir = Path(WEBSITE_DATA_DIR)
    local_files = sorted(data_dir.rglob("*.json"))
    if not local_files:
        logger.error("No JSON files in %s. Run export_ncats_json.py first.", data_dir)
        sys.exit(1)

    logger.info(f"Bucket:      {R2_BUCKET_NAME}")
    logger.info(f"Prefix:      {prefix}/")
    logger.info(f"Public URL:  {R2_PUBLIC_URL}/{prefix}")
    logger.info(f"Local files: {len(local_files):,} JSON files")

    client = get_client()

    remote_etags = {}
    if not args.force:
        logger.info("Fetching remote file list...")
        remote_etags = list_remote_etags(client, prefix)
        logger.info(f"  {len(remote_etags):,} files already on R2 under {prefix}/")

    to_upload = []
    for path in local_files:
        key = build_key(path, data_dir, prefix)
        if md5_hex(path) != remote_etags.get(key, ""):
            to_upload.append((path, key))

    # Safety net: never write a key outside our prefix.
    bad = [k for _, k in to_upload if not k.startswith(f"{prefix}/")]
    if bad:
        logger.error("ABORT: %d keys are not under %s/ — e.g. %s",
                     len(bad), prefix, bad[:3])
        sys.exit(1)

    logger.info(f"  {len(local_files) - len(to_upload):,} unchanged, "
                f"{len(to_upload):,} to upload")

    if args.dry_run:
        for _, key in to_upload[:20]:
            logger.info(f"  [dry-run] {key}")
        if len(to_upload) > 20:
            logger.info(f"  [dry-run] ... and {len(to_upload) - 20:,} more")
        return

    if not to_upload:
        logger.info("Already up to date.")
        return

    uploaded = errors = 0
    for path, key in to_upload:
        for attempt in range(1, 7):
            try:
                client.upload_file(
                    str(path), R2_BUCKET_NAME, key,
                    ExtraArgs={
                        "ContentType": "application/json",
                        "CacheControl": "public, max-age=3600",
                    },
                )
                uploaded += 1
                if uploaded % 100 == 0 or uploaded == len(to_upload):
                    logger.info(f"  {uploaded}/{len(to_upload)} uploaded")
                break
            except Exception as e:
                if attempt == 6:
                    logger.error(f"  FAILED {key}: {e}")
                    errors += 1
                else:
                    time.sleep(2 ** attempt)

    logger.info(f"Done. {uploaded:,} uploaded, {errors} errors.")

    if args.prune_remote:
        local_keys = {build_key(p, data_dir, prefix) for p in local_files}
        remote_now = remote_etags or list_remote_etags(client, prefix)
        stale = sorted(set(remote_now) - local_keys)
        # Belt and braces: never delete anything outside our own prefix.
        stale = [k for k in stale if k.startswith(f"{prefix}/")]
        if not stale:
            logger.info("No stale remote objects.")
        else:
            logger.info("Deleting %d stale objects under %s/", len(stale), prefix)
            for i in range(0, len(stale), 1000):
                client.delete_objects(
                    Bucket=R2_BUCKET_NAME,
                    Delete={"Objects": [{"Key": k} for k in stale[i:i + 1000]]},
                )
            logger.info("Deleted %d stale objects.", len(stale))

    if errors:
        sys.exit(1)


if __name__ == "__main__":
    main()
