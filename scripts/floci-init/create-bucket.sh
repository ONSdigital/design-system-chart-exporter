#!/bin/sh
# Floci init hook: create the charts bucket on startup so `make up` yields a
# ready-to-use bucket with no manual steps. Runs inside the Floci container
# (the -compat image ships the aws CLI). Idempotent across restarts.
set -eu

BUCKET="ons-charts"
ENDPOINT="http://localhost:4566"

if aws --endpoint-url "$ENDPOINT" s3api head-bucket --bucket "$BUCKET" 2>/dev/null; then
    echo "Bucket already exists: $BUCKET"
else
    aws --endpoint-url "$ENDPOINT" s3api create-bucket --bucket "$BUCKET"
    echo "Created bucket: $BUCKET"
fi
