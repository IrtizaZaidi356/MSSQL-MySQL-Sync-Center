# MSSQL → MySQL Sync Center

A Windows-friendly Tkinter desktop manager for running multiple existing SQL Server → MySQL Python sync scripts. It runs jobs sequentially, captures their terminal output, shows per-script status and reported record counts, supports manual and scheduled runs, and stores logs plus CSV run history.

## 1. Project structure

```text
MSSQL_MySQL_Sync_Manager/
├── main.py                    # Tkinter desktop UI and job orchestration
├── manager/
│   ├── __init__.py
│   ├── settings.py             # Load/save UI settings
│   ├── result_parser.py        # Parse result messages from existing scripts
│   ├── runner.py               # Run scripts, capture output, timeout/stop support
│   └── history.py              # Rotating log and CSV history
├── config/
│   └── settings.json           # UI preferences and script folder settings
├── logs/
│   └── .gitkeep
├── requirements.txt
├── run_manager.bat              # Windows launcher
├── .gitignore
└── README.md
```

Keep this manager in its own folder. Your existing sync scripts can remain in their current folder; you do not need to paste every query into this project.

## 2. Install on Windows

1. Install Python 3.10 or newer. During installation, enable **Add Python to PATH**.
2. Open Command Prompt in the `MSSQL_MySQL_Sync_Manager` folder.
3. Install the packages used by the existing scripts:

   ```bat
   python -m pip install -r requirements.txt
   ```

4. Ensure the Microsoft **ODBC Driver 18 for SQL Server** is installed if your scripts use it.
5. Double-click `run_manager.bat` or run:

   ```bat
   python main.py
   ```

Tkinter is included with most standard Windows Python installations. If Python reports that `tkinter` is missing, repair/reinstall Python with the Tcl/Tk component enabled.

## 3. Configure your script folder and .env base

The included settings use the folder layout discussed in the project conversation:

- **Scripts folder:** `D:\Python\MSSQL_MYSQL_Sync`
- **Working directory (.env base):** `D:\Python`
- **Python executable:** `python` (or browse to the exact `python.exe` used to install your sync dependencies)
- **Patterns:** `transfer_*.py, sync_*.py, update_*.py`
- **Auto interval:** 15 minutes
- **Per-script timeout:** 60 minutes

Adjust these on the UI if your folder structure differs, then click **Save Settings** and **Scan Scripts**.

The working directory matters. For example, if a script calls `load_dotenv("config/.env")`, the manager runs it with the selected working directory so that relative paths resolve as expected. The manager does not read, display, or edit your `.env` credentials.

The script patterns intentionally avoid running every `.py` file in a folder. If you use different file names, update **Script patterns** (comma-separated), for example:

```text
transfer_*.py, sync_*.py, update_*.py, import_*.py
```

The manager executes matching Python files as scripts. Do not include helper modules, scratch/test scripts, or unrelated Python files in the patterns.

## 4. How to run jobs

- **Run All:** run every discovered sync script in alphabetical order, one at a time.
- **Run Selected:** select a row and run only that script. Double-clicking a row also runs it.
- **Stop Run:** asks the active script process to terminate and skips remaining jobs in that batch.
- **Start Auto Sync:** schedule a batch after the selected interval; subsequent runs are scheduled after each batch finishes.
- **Stop Auto Sync:** turns off future scheduled runs. It does not terminate a batch already running.
- **Open Logs Folder:** opens the folder containing the log and CSV history.

The application continues to the next script when a script fails, so one failed view/table transfer does not prevent other scripts from running. The active script has a timeout; a timed-out script is stopped and marked `TIMEOUT`.

## 5. How record counts are shown

The UI looks for common messages emitted by your existing scripts:

- `New records inserted: 125` → **New Records = 125**
- `New records found: 125` → **New Records = 125** (the message states that the inserted count was not separately reported)
- `NO NEW RECORDS FOUND` → **New Records = 0**, status **NO NEW RECORDS**
- `Transferred: 1000 rows` or `Total rows transferred: 2500` → **New Records = —** and the result states the transferred-row count. Full-transfer counts are not necessarily new records.

For consistent reporting, have each incremental script print an explicit final line after a successful commit, such as:

```python
print(f"New records inserted: {inserted_count}")
```

If no rows are inserted, print:

```python
print("NO NEW RECORDS FOUND")
```

Only use those messages when they accurately describe what the script did. If the script does not report an explicit record count, the manager will not guess one.

## 6. Logging and history

- `logs/sync_manager.log` — timestamped application and job messages. The file rotates when it grows to roughly 2 MB, retaining up to five backups.
- `logs/run_history.csv` — one row per completed script, including start time, filename, status, count source, duration, exit code, and summary message.

A script's full standard output and errors are streamed into the Live Output panel and application log. Do not print secrets (database passwords, access tokens, connection strings) from scripts; output is recorded in logs.

## 7. Important safety checks before enabling automation

This manager orchestrates existing scripts; it does not rewrite their SQL or change their insert/update strategy. Before enabling auto sync:

1. Test each script manually and verify its source query and target table/view.
2. Confirm that repeated execution is safe. Incremental jobs should identify existing rows using a stable unique key and insert only missing rows, or use a deliberate upsert strategy. A script that always inserts the entire source table can create duplicates on each run.
3. Ensure MySQL target columns have compatible data types with SQL Server source columns, especially dates, decimals, and nullable values.
4. Start with a longer auto interval while checking the results. Do not schedule two copies of the same batch concurrently; this application prevents overlapping batches within the same manager instance.
5. Keep backups and use an account with only the database permissions the sync jobs require.

The manager controls only the subprocess it starts. If a sync script starts its own child processes, or a database transaction is already committed, stopping the script cannot automatically undo those operations.

## 8. Troubleshooting

### No scripts found
Check the scripts folder and comma-separated patterns. For example, `transfer_vwPurOrderDesignPrint.py` matches `transfer_*.py`.

### Script cannot find `.env`
Set **Working directory (.env base)** to the directory from which the script's relative `.env` path should resolve. Confirm the path exists. The manager does not copy the `.env` file.

### Python package/module not found
Set **Python executable** to the `python.exe` in the environment where `pyodbc`, `mysql-connector-python`, and `python-dotenv` are installed.

### `New Records` shows `—`
The script did not print a recognized new-record count. Add a truthful final status line after a successful commit, or use the result message if the script only reports full-transfer rows.

### Script fails
Open the output panel and `logs/sync_manager.log`, then run that script individually. The manager reports the subprocess exit code and its last output line, but the actual database/data-type error must be fixed in the script or target schema.




https://github.com/user-attachments/assets/3c764a26-b179-43c9-a1f1-1d7875048f7e



