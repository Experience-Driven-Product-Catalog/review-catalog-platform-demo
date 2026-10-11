#!/bin/bash
export PYTHONPATH="$LAMBDA_TASK_ROOT:$LAMBDA_TASK_ROOT/lib:$PYTHONPATH"
exec python -m uvicorn demo.app:app --host 0.0.0.0 --port "${PORT:-8000}" --no-access-log --log-level warning
