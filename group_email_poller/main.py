import os
import threading

from fastapi import FastAPI
from fastapi.responses import JSONResponse
import uvicorn

from poller import fetch_group_email_threads
from drive_writer import upload_thread_to_drive

app = FastAPI()

_run_lock = threading.Lock()


@app.post("/poll-group-emails")
def poll_group_emails():
    if not _run_lock.acquire(blocking=False):
        return JSONResponse(content={"status": "ok", "message": "Poll already in progress"}, status_code=200)

    def background():
        try:
            threads = fetch_group_email_threads()
            for thread in threads:
                upload_thread_to_drive(thread)
        except Exception as e:
            print(f"Group email poll error: {e}")
        finally:
            _run_lock.release()

    threading.Thread(target=background, daemon=False).start()
    return JSONResponse(content={"status": "ok", "message": "Group email polling started"}, status_code=202)


@app.get("/health")
def health():
    return JSONResponse(content={"status": "ok"}, status_code=200)


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8081))
    uvicorn.run(app, host="0.0.0.0", port=port)
