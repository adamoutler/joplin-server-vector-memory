from fastapi import FastAPI
from starlette.requests import Request

app = FastAPI()

async def sub_app(scope, receive, send):
    assert scope['type'] == 'http'
    await send({
        'type': 'http.response.start',
        'status': 200,
        'headers': [[b'content-type', b'text/plain']]
    })
    await send({
        'type': 'http.response.body',
        'body': f"Sub app path: {scope['path']}".encode()
    })

app.mount("/sub", sub_app)

class RewriteMiddleware:
    def __init__(self, app):
        self.app = app
    async def __call__(self, scope, receive, send):
        if scope["type"] == "http":
            if scope["path"] in ["/sub"]:
                scope["path"] = scope["path"] + "/"
        await self.app(scope, receive, send)

app = RewriteMiddleware(app)

if __name__ == "__main__":
    import uvicorn
    import threading
    import time
    import requests
    
    def run():
        uvicorn.run(app, host="127.0.0.1", port=8002, log_level="error")
    
    t = threading.Thread(target=run, daemon=True)
    t.start()
    time.sleep(1)
    
    r1 = requests.get("http://127.0.0.1:8002/sub", allow_redirects=False)
    print("GET /sub:", r1.status_code, r1.text)
    
    r2 = requests.get("http://127.0.0.1:8002/sub/", allow_redirects=False)
    print("GET /sub/:", r2.status_code, r2.text)
