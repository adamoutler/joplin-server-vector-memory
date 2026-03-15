from fastapi import FastAPI, Request
app = FastAPI()
@app.api_route("/{path:path}", methods=["GET", "POST", "PUT", "DELETE"])
async def echo(request: Request, path: str):
    return {"path": request.url.path, "method": request.method}
