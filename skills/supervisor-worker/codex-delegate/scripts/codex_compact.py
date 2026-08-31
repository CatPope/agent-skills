#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""위임 세션의 히스토리를 **원하는 시점에** 압축한다.

왜 필요한가
  Codex 는 컨텍스트가 한도의 88~89% 에 닿으면 알아서 압축한다. 그런데 그 시점은
  대개 작업 한복판이다 — 조사하다 말고, 고치다 말고 잘린다. 무엇을 남길지 고를 수
  없고, 잘린 자리가 하필 중요한 결정 근처면 다음 턴에 같은 것을 다시 묻는다.

  이 스크립트는 **작업이 한 매듭 지어진 순간**(한 게이트 완료, 검수 통과, 지시서 교체
  직전)에 압축을 직접 걸어, 손실 지점을 우리가 고르게 한다.

왜 `codex exec` 로는 안 되는가
  `codex exec` 에는 압축 명령이 없다. 압축은 app-server 프로토콜의
  `thread/compact/start` 로만 요청할 수 있어서, 여기서는 JSON-RPC 로 직접 말한다.
  (실증: 압축 요청 → pre-compact 훅 → item `contextCompaction` → post-compact 훅
   → turn/completed, 약 14초. 롤아웃에 `type:"compacted"` 레코드가 남는다.)

사용법
  python codex_compact.py --dir <작업디렉토리> --task sim-cell
  python codex_compact.py --thread <uuid> --cwd <작업디렉토리>
  python codex_compact.py --dir <작업디렉토리> --task sim-cell --dry-run   # 점유율만 본다

압축은 **되돌릴 수 없다.** 지금 점유율이 낮으면 굳이 하지 마라 — 먼저 `--dry-run`.
"""
from __future__ import annotations

import argparse
import glob
import io
import json
import os
import queue
import shutil
import subprocess
import sys
import threading
import time

STATE_DIR = ".claude-codex"
KNOWN_CODEX = os.path.join(os.path.expanduser("~"),
                           "AppData", "Local", "Programs", "OpenAI", "Codex", "bin", "codex.exe")
ROLLOUT_GLOB = os.path.join(os.path.expanduser("~"),
                            ".codex", "sessions", "*", "*", "*", "rollout-*-%s.jsonl")


def find_codex() -> str:
    found = shutil.which("codex")
    if found:
        return found
    for cand in (KNOWN_CODEX, KNOWN_CODEX[:-4]):
        if os.path.exists(cand):
            return cand
    sys.exit("codex CLI 를 찾지 못했습니다.")


def thread_of(work_dir: str, task: str) -> tuple[str, str]:
    """state.json 에서 thread_id 와 작업 루트를 꺼낸다."""
    p = os.path.join(work_dir, STATE_DIR, "state.json")
    if not os.path.exists(p):
        sys.exit(f"상태 파일이 없습니다: {p}")
    state = json.load(io.open(p, encoding="utf-8"))
    t = state.get("tasks", {}).get(task)
    if not t:
        sys.exit(f"'{task}' 세션이 없습니다. 등록된 작업: {', '.join(state.get('tasks', {})) or '(없음)'}")
    return t["thread_id"], t.get("work_dir") or work_dir


def occupancy(thread_id: str):
    """롤아웃 끝에서 마지막 token_count 를 읽어 점유율·사용량 한도를 돌려준다.

    롤아웃은 100MB 를 넘길 수 있다(실측 107MB). 뒤에서 8MB 만 읽는다.
    """
    files = glob.glob(ROLLOUT_GLOB % thread_id)
    if not files:
        return None
    path = max(files, key=os.path.getmtime)
    size = os.path.getsize(path)
    cap = 8 * 1024 * 1024
    with io.open(path, "rb") as f:
        f.seek(max(0, size - cap))
        chunk = f.read()
    if size > cap:
        chunk = chunk.split(b"\n", 1)[-1]
    for line in reversed(chunk.decode("utf-8", errors="replace").splitlines()):
        if '"token_count"' not in line or not line.startswith("{"):
            continue
        try:
            ev = json.loads(line)
        except ValueError:
            continue
        info = (ev.get("payload") or {}).get("info") or {}
        rl = (ev.get("payload") or {}).get("rate_limits") or {}
        ctx = (info.get("last_token_usage") or {}).get("input_tokens") or 0
        win = info.get("model_context_window") or 0
        return {"at": (ev.get("timestamp") or "")[:19].replace("T", " "),
                "ctx": ctx, "window": win, "pct": (ctx / win * 100) if win else 0,
                "p5": (rl.get("primary") or {}).get("used_percent"),
                "weekly": (rl.get("secondary") or {}).get("used_percent"),
                "path": path}
    return None


class AppServer:
    """codex app-server 와 줄 단위 JSON-RPC 로 이야기한다."""

    def __init__(self, codex: str, verbose: bool = False):
        self.verbose = verbose
        self.proc = subprocess.Popen(
            [codex, "app-server"],
            stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
            text=True, encoding="utf-8", errors="replace", bufsize=1)
        self.q: queue.Queue = queue.Queue()
        threading.Thread(target=self._pump, daemon=True).start()
        self._id = 0

    def _pump(self):
        for line in self.proc.stdout:
            self.q.put(line.rstrip("\n"))
        self.q.put(None)

    def send(self, method, params=None, notify=False):
        msg = {"jsonrpc": "2.0", "method": method}
        if params is not None:
            msg["params"] = params
        if not notify:
            self._id += 1
            msg["id"] = self._id
        self.proc.stdin.write(json.dumps(msg, ensure_ascii=False) + "\n")
        self.proc.stdin.flush()
        return None if notify else self._id

    def wait(self, pred, timeout=300, label=""):
        end = time.time() + timeout
        while time.time() < end:
            try:
                line = self.q.get(timeout=1)
            except queue.Empty:
                continue
            if line is None:
                sys.exit(f"app-server 가 먼저 끊겼습니다 ({label}).")
            try:
                msg = json.loads(line)
            except ValueError:
                continue
            if self.verbose:
                print("   <<<", msg.get("method") or f"result#{msg.get('id')}", flush=True)
            if msg.get("error"):
                sys.exit("app-server 오류: " + json.dumps(msg["error"], ensure_ascii=False))
            got = pred(msg)
            if got is not None:
                return got
        sys.exit(f"응답을 기다리다 시간이 지났습니다 ({label}, {timeout}초).")

    def close(self):
        try:
            self.proc.terminate()
        except Exception:
            pass


def main() -> int:
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass

    ap = argparse.ArgumentParser(description="위임 세션을 지금 압축한다")
    ap.add_argument("--dir", help="작업 디렉토리(.claude-codex 의 부모)")
    ap.add_argument("--task", help="작업명. --dir 과 함께 쓴다")
    ap.add_argument("--thread", help="thread_id 를 직접 지정")
    ap.add_argument("--cwd", help="--thread 와 함께 쓸 작업 루트")
    ap.add_argument("--dry-run", action="store_true", help="점유율만 보고 압축하지 않는다")
    ap.add_argument("--min-percent", type=float, default=0.0,
                    help="점유율이 이 값 미만이면 압축하지 않는다(낭비 방지)")
    ap.add_argument("--verbose", action="store_true")
    args = ap.parse_args()

    if args.thread:
        tid, cwd = args.thread, args.cwd or os.getcwd()
    elif args.dir and args.task:
        tid, cwd = thread_of(os.path.abspath(args.dir), args.task)
    else:
        return ap.error("--dir 과 --task 를 같이 주거나 --thread 를 주세요")

    before = occupancy(tid)
    if before:
        print(f"[압축 전] 컨텍스트 {before['ctx']:,}/{before['window']:,} ({before['pct']:.1f}%)"
              f" · 5시간한도 {before['p5']}% · 주간 {before['weekly']}%"
              f"   [{before['at']} UTC 기준]")
    else:
        print("[압축 전] 롤아웃에서 점유율을 읽지 못했습니다(첫 턴 이전일 수 있음)")

    if args.dry_run:
        return 0
    if before and before["pct"] < args.min_percent:
        print(f"점유율 {before['pct']:.1f}% < 기준 {args.min_percent}% — 압축하지 않습니다.")
        return 0

    srv = AppServer(find_codex(), args.verbose)
    try:
        rid = srv.send("initialize", {"clientInfo": {"name": "codex-compact", "version": "1.0"}})
        srv.wait(lambda m: True if m.get("id") == rid else None, 60, "initialize")
        srv.send("initialized", {}, notify=True)

        rid = srv.send("thread/resume", {"threadId": tid, "cwd": cwd})
        srv.wait(lambda m: m.get("result") if m.get("id") == rid else None, 180, "thread/resume")
        print(f"[세션] {tid} 이어받음")

        t0 = time.time()
        srv.send("thread/compact/start", {"threadId": tid})
        # 완료 신호는 `thread/compacted` 가 아니라 contextCompaction 아이템의 완료다.
        srv.wait(lambda m: True if (m.get("method") == "item/completed" and
                                    ((m.get("params") or {}).get("item") or {}).get("type")
                                    == "contextCompaction") else None, 600, "압축 완료")
        srv.wait(lambda m: True if m.get("method") == "turn/completed" else None, 120, "turn/completed")
        print(f"[압축] 완료 ({time.time() - t0:.1f}초)")
    finally:
        srv.close()

    time.sleep(2)                       # 롤아웃 flush 를 기다린다
    after = occupancy(tid)
    if after and before:
        print(f"[압축 후] 컨텍스트 {after['ctx']:,}/{after['window']:,} ({after['pct']:.1f}%)"
              f"  ← {before['pct']:.1f}%")
    print("다음 턴부터 줄어든 히스토리로 진행합니다. 압축은 되돌릴 수 없습니다.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
