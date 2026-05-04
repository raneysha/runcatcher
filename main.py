from fastapi import FastAPI
import json
import matching
from fastapi.concurrency import run_in_threadpool

app = FastAPI()


@app.get("/")
def read_root():
    return {"Hello": "World"}


@app.get("/items/{item_id}")
def read_item(item_id: int, q: str | None = None):
    return {"item_id": item_id, "q": q}

@app.get("/recognize")
async def recognize_faces():
    result_json = await run_in_threadpool(matching.recognize_to_json, matching.input_image, matching.db_path)
    return json.loads(result_json)