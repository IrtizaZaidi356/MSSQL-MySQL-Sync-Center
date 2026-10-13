"""Run one sync script as a separate process and collect its result."""

from __future__ import annotations

import os
import queue
import subprocess
import threading
import time
from datetime import datetime
from pathlib import Path
from typing import Callable

from manager.result_parser import parse_output

LineCallback = Callable[[str], None]
ProcessCallback = Callable[[subprocess.Popen[str] | None], None]


def run_script(
    script_path: Path,
    python_executable: str,
    working_directory: Path,
    timeout_seconds: int,
    stop_event: threading.Event,
    output_callback: LineCallback,
    process_callback: ProcessCallback,
) -> dict:
    """Execute a script with streaming output, timeout, and stop support."""
    started_at = datetime.now()
    start_clock = time.monotonic()
    output_lines: list[str] = []
    process: subprocess.Popen[str] | None = None
    final_status = "SUCCESS"
    return_code: int | None = None
    summary = ""

    environment = os.environ.copy()
    environment["PYTHONUNBUFFERED"] = "1"

    try:
        process = subprocess.Popen(
            [python_executable, "-u", str(script_path)],
            cwd=str(working_directory),
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            encoding="utf-8",
            errors="replace",
            bufsize=1,
            env=environment,
        )
        process_callback(process)

        line_queue: queue.Queue[str | None] = queue.Queue()

        def read_output() -> None:
            """Read output separately so timeout/stop checks remain responsive."""
            assert process is not None and process.stdout is not None
            try:
                for output_line in process.stdout:
                    line_queue.put(output_line.rstrip("\r\n"))
            finally:
                line_queue.put(None)

        reader = threading.Thread(
            target=read_output,
            name=f"output-reader-{script_path.stem}",
            daemon=True,
        )
        reader.start()
        output_finished = False
        timed_out = False
        stopped = False

        while process.poll() is None or not output_finished:
            if stop_event.is_set() and process.poll() is None:
                stopped = True
                process.terminate()
                try:
                    process.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    process.kill()
                break

            if timeout_seconds > 0 and time.monotonic() - start_clock > timeout_seconds:
                timed_out = True
                process.terminate()
                try:
                    process.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    process.kill()
                break

            try:
                item = line_queue.get(timeout=0.2)
                if item is None:
                    output_finished = True
                else:
                    output_lines.append(item)
                    output_callback(item)
            except queue.Empty:
                pass

        # Drain remaining lines after the process ends.
        if process.stdout is not None:
            try:
                process.stdout.close()
            except OSError:
                pass
        reader.join(timeout=1)
        while True:
            try:
                item = line_queue.get_nowait()
            except queue.Empty:
                break
            if item is not None:
                output_lines.append(item)
                output_callback(item)

        return_code = process.poll()
        parsed = parse_output(output_lines)

        if stopped:
            final_status = "STOPPED"
            summary = "Stopped by user"
        elif timed_out:
            final_status = "TIMEOUT"
            summary = f"Timed out after {timeout_seconds // 60} minute(s)"
        elif return_code != 0:
            final_status = "FAILED"
            last_line = next((line for line in reversed(output_lines) if line.strip()), "")
            summary = f"Exit code {return_code}"
            if last_line:
                summary += f" — {last_line[:180]}"
        else:
            final_status = "NO NEW RECORDS" if parsed.new_records == 0 else "SUCCESS"
            summary = parsed.message

        return {
            "started_at": started_at.isoformat(sep=" ", timespec="seconds"),
            "script": script_path.name,
            "status": final_status,
            "new_records": parsed.new_records,
            "count_source": parsed.count_source,
            "duration_seconds": round(time.monotonic() - start_clock, 2),
            "return_code": return_code,
            "message": summary,
            "output": output_lines,
        }

    except FileNotFoundError as error:
        return {
            "started_at": started_at.isoformat(sep=" ", timespec="seconds"),
            "script": script_path.name,
            "status": "FAILED",
            "new_records": None,
            "count_source": "unknown",
            "duration_seconds": round(time.monotonic() - start_clock, 2),
            "return_code": None,
            "message": str(error),
            "output": output_lines,
        }
    except Exception as error:  # Keep one script failure from crashing the UI.
        return {
            "started_at": started_at.isoformat(sep=" ", timespec="seconds"),
            "script": script_path.name,
            "status": "FAILED",
            "new_records": None,
            "count_source": "unknown",
            "duration_seconds": round(time.monotonic() - start_clock, 2),
            "return_code": return_code,
            "message": f"{type(error).__name__}: {error}",
            "output": output_lines,
        }
    finally:
        process_callback(None)
