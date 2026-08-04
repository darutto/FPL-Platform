#!/usr/bin/env python3
"""Loopback-only exact-response server for FI-7e UI capture."""
from __future__ import annotations

import argparse
import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from ipaddress import ip_address
from pathlib import Path
from urllib.parse import urlparse


def is_loopback(value: str) -> bool:
    try:
        return ip_address(value).is_loopback
    except ValueError:
        return value == "localhost"


def main() -> int:
    parser=argparse.ArgumentParser()
    parser.add_argument("--responses",type=Path,required=True)
    parser.add_argument("--host",default="127.0.0.1")
    parser.add_argument("--port",type=int,default=8765)
    args=parser.parse_args()
    if not is_loopback(args.host):
        raise SystemExit("FI-7e fixture server refuses non-loopback binding")
    payloads=json.loads(args.responses.read_text(encoding="utf-8"))
    prompt_map={"captain score for Saka":"A","player intelligence for Saka":"B","compare Saka and Palmer":"C_ON","player intelligence for Saka and what gameweek is it?":"D","show stored replay":"E"}

    class Handler(BaseHTTPRequestHandler):
        server_version="FI7EFixture/1"
        def log_message(self, fmt: str, *values: object) -> None:
            print(fmt % values)
        def _send(self,status:int,value:object)->None:
            body=json.dumps(value,sort_keys=True,separators=(",",":"),ensure_ascii=False).encode("utf-8")
            self.send_response(status); self.send_header("Content-Type","application/json; charset=utf-8"); self.send_header("Content-Length",str(len(body))); self.end_headers(); self.wfile.write(body)
        def _check(self)->bool:
            host=self.headers.get("Host","").split(":",1)[0]
            client=self.client_address[0]
            return is_loopback(host) and is_loopback(client)
        def do_GET(self)->None:
            if not self._check(): self._send(403,{"detail":"loopback only"}); return
            if self.path=="/health": self._send(200,{"fixture":"fi7e-demo-input-v1","status":"ok"}); return
            if self.path.startswith("/session/"): self._send(200,{"session_id":"fi7e-session","turn_count":1}); return
            self._send(404,{"detail":"not found"})
        def do_DELETE(self)->None:
            if not self._check(): self._send(403,{"detail":"loopback only"}); return
            self._send(204,{})
        def do_POST(self)->None:
            if not self._check(): self._send(403,{"detail":"loopback only"}); return
            length=int(self.headers.get("Content-Length","0")); data=json.loads(self.rfile.read(length) or b"{}")
            if self.path=="/session": self._send(200,{"created_at":0,"expires_after_seconds":1800,"session_id":"fi7e-session"}); return
            if self.path=="/ask" or self.path.endswith("/ask"):
                sid=prompt_map.get(data.get("question"))
                if sid is None: self._send(422,{"detail":"unknown frozen prompt"}); return
                value=payloads[sid]["replay"] if sid=="E" else payloads[sid]
                self._send(200,value); return
            self._send(404,{"detail":"not found"})

    with ThreadingHTTPServer((args.host,args.port),Handler) as server:
        print(f"FI-7e fixture server ready at http://{args.host}:{args.port}",flush=True)
        server.serve_forever()
    return 0


if __name__=="__main__":
    raise SystemExit(main())
