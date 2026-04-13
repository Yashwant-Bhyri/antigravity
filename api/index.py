import sys
import os
import traceback
import json

# Pure ASGI entrypoint - requires ZERO external dependencies to boot.
# If Vercel fails to install FastAPI, pydantic, or any C-extensions on its Amazon Linux containers,
# this code will perfectly survive the boot sequence and trap the error.
async def app(scope, receive, send):
    try:
        # Ensure Vercel can resolve sibling directories dynamically
        current_dir = os.path.dirname(os.path.abspath(__file__))
        root_dir = os.path.dirname(current_dir)
        if root_dir not in sys.path:
            sys.path.insert(0, root_dir)

        from backend.main import app as master_app
        # Delegate request natively to FastAPI if imports succeeded
        await master_app(scope, receive, send)
        
    except Exception as e:
        # Hand-craft a pure ASGI 500 response without relying on FastAPI/Starlette
        body = json.dumps({
            "error": "Backend App Crashed during ASGI Handshake",
            "exception": str(e),
            "traceback": traceback.format_exc().splitlines(),
            "sys_path": sys.path
        }).encode("utf-8")
        
        await send({
            "type": "http.response.start",
            "status": 500,
            "headers": [
                (b"content-type", b"application/json"),
                (b"access-control-allow-origin", b"*")
            ]
        })
        await send({
            "type": "http.response.body",
            "body": body
        })

