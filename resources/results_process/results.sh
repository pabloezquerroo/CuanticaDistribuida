#!/bin/bash

# Extract data
aws dynamodb scan \
    --table-name results_dynamodb \
    --endpoint-url http://localhost:8001 \
    --no-paginate \
    --output json > results.json && \
    uv run json_to_parquet_and_csv.py