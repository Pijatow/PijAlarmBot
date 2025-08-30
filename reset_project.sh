#!/bin/bash

# This script resets the project to a clean state by deleting the database,
# the logs directory, and all files inside the migrations directory.
# WARNING: This action is irreversible.

echo "--- Starting Project Data Reset ---"

# Define file and directory names
DB_FILE="alerts.db"
LOG_DIR="logs"
MIGRATIONS_DIR="migrations"

# 1. Delete the database file
echo "Attempting to delete database file..."
if [ -f "$DB_FILE" ]; then
    rm -f "$DB_FILE"
    echo "✅ Database file '$DB_FILE' deleted."
else
    echo "ℹ️ Database file '$DB_FILE' not found, skipping."
fi

# 2. Delete the logs directory
echo "Attempting to delete logs directory..."
if [ -d "$LOG_DIR" ]; then
    rm -rf "$LOG_DIR"
    echo "✅ Logs directory '$LOG_DIR' deleted."
else
    echo "ℹ️ Logs directory '$LOG_DIR' not found, skipping."
fi

# 3. Delete files inside the migrations directory
echo "Attempting to delete files inside migrations directory..."
if [ -d "$MIGRATIONS_DIR" ]; then
    # Check if there are any files to delete to avoid error messages
    if [ -n "$(ls -A $MIGRATIONS_DIR)" ]; then
       rm -f "$MIGRATIONS_DIR"/*
       echo "✅ All files inside '$MIGRATIONS_DIR' have been deleted."
    else
       echo "ℹ️ Migrations directory '$MIGRATIONS_DIR' is already empty, skipping."
    fi
else
    echo "ℹ️ Migrations directory '$MIGRATIONS_DIR' not found, skipping."
fi

echo ""
echo "--- Project Reset Complete! ---"
