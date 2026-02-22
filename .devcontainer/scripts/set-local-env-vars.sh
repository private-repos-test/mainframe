#!/bin/sh
set -e

ENV_FILE=/workspaces/mainframe/src/mainframe/.env
# Clear existing environment variables in the file
> $ENV_FILE

{
  echo "CORS_ALLOW_ALL_ORIGINS=True"
  echo "DB_DATABASE=local_db"
  echo "DB_HOST=localhost"
  echo "DB_PASSWORD=local_pass"
  echo "DB_PORT=5432"
  echo "DB_NAME=local_db"
  echo "DB_USER=local_user"
  echo "DEBUG=True"
  echo "EARTHQUAKE_DEFAULT_COORDINATES=0,0"
  echo "ENV=local"
} >> $ENV_FILE
