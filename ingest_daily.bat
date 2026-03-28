@echo off
cd /d "%~dp0"
python ingestion.py >> ingest.log 2>&1
