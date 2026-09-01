# -*- coding: utf-8 -*-
"""Codex 위임 헬퍼 — 같은 세션을 계속 이어가며 구조화된 완료보고를 받는다.

왜 스크립트로 만드는가 (직접 CLI를 치면 반드시 걸리는 함정들)
  1. `codex exec` 옵션은 반드시 `resume` **앞**에 와야 한다.
     `codex exec resume <id> --sandbox ...` 는 `unexpected argument '--sandbox'` 로 exit 2.
  2. stdin 을 닫지 않으면 `Reading additional input from stdin...` 에서 멈춘다.
     자동화에서 이유 없이 정지하는 원인이 된다.
  3. thread_id 는 `--json` 스트림 첫 줄 `{"type":"thread.started","thread_id":"..."}` 에만 나온다.
     이걸 놓치면 다음 턴에 세션을 이어받을 수 없고, Codex 는 맥락을 잃은 채 새로 시작한다.

상태 파일: <work_dir>/.claude-codex/state.json
  작업(task)마다 thread_id 와 턴 이력을 보관한다. 여러 작업을 병행해도 세션이 섞이지 않는다.

사용법
  python codex_task.py start  <task> --dir <work_dir> --prompt-file <파일> [--sandbox ...]
  python codex_task.py send   <task> --dir <work_dir> --prompt-file <파일> [--sandbox ...]
  python codex_task.py status         --dir <work_dir> [<task>]
  python codex_task.py report  <task> --dir <work_dir> [--turn -1]

프롬프트는 항상 파일로 넘긴다 — 긴 작업지시서를 명령행에 넣으면 Windows 인자 한도에 걸린다.
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
from datetime import datetime
from pathlib import Path

import codex_usage                      # 같은 scripts/ 폴더 — 점유율·한도를 읽는 공용 모듈

SKILL_DIR = Path(__file__).resolve().parent.parent
DEFAULT_SCHEMA = SKILL_DIR / "schema" / "completion_report.json"
STATE_REL = Path(".claude-codex") / "state.json"

# codex 는 PATH 에 없을 수 있다(Windows 기본 설치 경로가 PATH 밖).
KNOWN_CODEX = Path.home() / "AppData/Local/Programs/OpenAI/Codex/bin/codex.exe"


def find_codex() -> str:
    found = shutil.which("codex")
    if found:
        return found
    if KNOWN_CODEX.exists():
        return str(KNOWN_CODEX)
    alt = KNOWN_CODEX.with_suffix("")
    if alt.exists():
        return str(alt)
    sys.exit("codex CLI 를 찾지 못했습니다. PATH 에 추가하거나 설치 경로를 확인하세요.")


def state_path(work_dir: Path) -> Path:
    return work_dir / STATE_REL


def load_state(work_dir: Path) -> dict:
    p = state_path(work_dir)
    if not p.exists():
        return {"version": 1, "tasks": {}}
    return json.loads(p.read_text(encoding="utf-8"))


def save_state(work_dir: Path, state: dict) -> None:
    p = state_path(work_dir)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")


def now() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def decide_fast(args) -> list[str]:
    """이번 실행을 fast 모드로 걸지 정하고, 붙일 인자를 돌려준다.

    한도는 계정 단위라 **가장 최근 롤아웃**을 본다 — 이 작업의 세션이 아니어도
    되고, 오히려 그쪽이 더 최신이다. 새 세션을 시작할 때는 자기 롤아웃이 아직
    없으므로 이 방식이어야 판단이 선다.
    """
    if getattr(args, "no_fast_gate", False):
        return []
    usage = codex_usage.read_usage()
    use, why = codex_usage.fast_decision(
        usage, min_percent=args.fast_min_percent, within_minutes=args.fast_within_minutes)
    print(f"[속도] {why}")
    if use:
        print("[속도] fast 모드 — 속도 1.5배, 크레딧 2.5배로 소모됩니다.")
    return list(codex_usage.FAST_ARGS) if use else []


def run_codex(codex: str, work_dir: Path, prompt: str, *, schema: Path,
              sandbox: str, resume_id: str | None, run_dir: Path,
              extra_args: list[str] | None = None) -> tuple[dict | None, str, str | None]:
    """codex exec 를 한 번 호출한다. (보고 dict, 원문, thread_id) 를 돌려준다."""
    run_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    out_file = run_dir / f"report_{stamp}.json"
    events_file = run_dir / f"events_{stamp}.jsonl"
    prompt_copy = run_dir / f"prompt_{stamp}.md"
    prompt_copy.write_text(prompt, encoding="utf-8")

    # 옵션은 전부 resume 앞에 둔다(함정 1).
    cmd = [codex, "exec", "--json",
           "--sandbox", sandbox,
           "--skip-git-repo-check",
           "-C", str(work_dir),
           "--output-schema", str(schema),
           "-o", str(out_file)]
    cmd += list(extra_args or [])       # fast 모드 등. resume 앞이어야 한다(함정 1).
    if resume_id:
        cmd += ["resume", resume_id]
    cmd += [prompt]

    with open(events_file, "w", encoding="utf-8") as ev:
        proc = subprocess.run(
            cmd,
            stdin=subprocess.DEVNULL,          # 함정 2: stdin 을 닫아야 멈추지 않는다
            stdout=ev, stderr=subprocess.STDOUT,
            text=True, encoding="utf-8", errors="replace",
        )

    raw = events_file.read_text(encoding="utf-8", errors="replace")

    thread_id = None
    turn_error = None
    for line in raw.splitlines():
        line = line.strip()
        if not line.startswith("{"):
            continue
        try:
            ev_obj = json.loads(line)
        except json.JSONDecodeError:
            continue
        kind = ev_obj.get("type")
        if kind == "thread.started" and ev_obj.get("thread_id"):
            thread_id = ev_obj["thread_id"]
        elif kind in ("turn.failed", "error"):
            # 턴이 실패하면 보고 파일이 안 생긴다. 조용히 넘기면 null 보고가 상태에 저장돼
            # "요청은 갔는데 아무 일도 안 일어난" 상태를 성공으로 착각하게 된다.
            msg = ev_obj.get("message") or (ev_obj.get("error") or {}).get("message") or str(ev_obj)
            turn_error = msg

    report = None
    if out_file.exists():
        text = out_file.read_text(encoding="utf-8", errors="replace").strip()
        if text:
            try:
                report = json.loads(text)
            except json.JSONDecodeError:
                report = {"_parse_error": True, "_raw": text[:4000]}

    if report is None:
        detail = turn_error or "\n".join(raw.splitlines()[-15:])
        print(f"[codex 실패] exit={proc.returncode}\n{detail}", file=sys.stderr)
        print(f"전체 로그: {events_file}", file=sys.stderr)

    return report, str(events_file), thread_id


def cmd_start(args) -> int:
    work_dir = Path(args.dir).resolve()
    codex = find_codex()
    state = load_state(work_dir)
    if args.task in state["tasks"] and not args.force:
        sys.exit(f"'{args.task}' 세션이 이미 있습니다. 이어가려면 send 를, 새로 시작하려면 --force 를 쓰세요.")

    prompt = Path(args.prompt_file).read_text(encoding="utf-8")
    run_dir = work_dir / ".claude-codex" / args.task
    report, events, thread_id = run_codex(
        codex, work_dir, prompt, schema=Path(args.schema),
        sandbox=args.sandbox, resume_id=None, run_dir=run_dir,
        extra_args=decide_fast(args))

    if not thread_id:
        sys.exit("thread_id 를 얻지 못했습니다. 세션을 이어갈 수 없으니 로그를 확인하세요: " + events)
    if report is None:
        # 세션은 열렸지만 첫 턴이 실패했다. 실패를 성공으로 기록하지 않는다.
        sys.exit(f"첫 턴이 실패했습니다(보고 없음). 상태를 저장하지 않았습니다. 로그: {events}")

    state["tasks"][args.task] = {
        "thread_id": thread_id,
        "work_dir": str(work_dir),
        "sandbox": args.sandbox,
        "created_at": now(),
        "turns": [{"at": now(), "kind": "start", "events": events, "report": report}],
    }
    save_state(work_dir, state)
    print(f"[start] task={args.task} thread_id={thread_id}")
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


def cmd_send(args) -> int:
    work_dir = Path(args.dir).resolve()
    codex = find_codex()
    state = load_state(work_dir)
    task = state["tasks"].get(args.task)
    if not task:
        sys.exit(f"'{args.task}' 세션이 없습니다. start 로 먼저 시작하세요.")

    prompt = Path(args.prompt_file).read_text(encoding="utf-8")
    run_dir = work_dir / ".claude-codex" / args.task
    sandbox = args.sandbox or task.get("sandbox", "workspace-write")
    report, events, _ = run_codex(
        codex, work_dir, prompt, schema=Path(args.schema),
        sandbox=sandbox, resume_id=task["thread_id"], run_dir=run_dir,
        extra_args=decide_fast(args))

    task["turns"].append({"at": now(), "kind": "send", "events": events, "report": report})
    save_state(work_dir, state)
    print(f"[send] task={args.task} thread_id={task['thread_id']} turn={len(task['turns'])}")
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


def cmd_status(args) -> int:
    work_dir = Path(args.dir).resolve()
    state = load_state(work_dir)
    if not state["tasks"]:
        print("(등록된 작업 없음)")
        return 0
    for name, t in state["tasks"].items():
        if args.task and name != args.task:
            continue
        last = t["turns"][-1]["report"] if t["turns"] else None
        flag = ""
        if isinstance(last, dict):
            if last.get("blocked"):
                flag = "  [BLOCKED]"
            elif last.get("unfinished"):
                flag = f"  [미완 {len(last['unfinished'])}건]"
        print(f"- {name}{flag}")
        print(f"    thread_id : {t['thread_id']}")
        print(f"    turns     : {len(t['turns'])}  (시작 {t['created_at']})")
    return 0


def cmd_report(args) -> int:
    work_dir = Path(args.dir).resolve()
    state = load_state(work_dir)
    task = state["tasks"].get(args.task)
    if not task or not task["turns"]:
        sys.exit(f"'{args.task}' 의 보고가 없습니다.")
    print(json.dumps(task["turns"][args.turn]["report"], ensure_ascii=False, indent=2))
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description="Codex 위임 헬퍼 (세션 유지 + 구조화 완료보고)")
    sub = ap.add_subparsers(dest="cmd", required=True)

    def common(p, need_prompt=True):
        p.add_argument("task")
        p.add_argument("--dir", default=".", help="작업 디렉토리 (Codex 의 작업 루트)")
        if need_prompt:
            p.add_argument("--prompt-file", required=True, help="작업지시서 파일 경로")
            p.add_argument("--schema", default=str(DEFAULT_SCHEMA))
            p.add_argument("--sandbox", default=None,
                           choices=["read-only", "workspace-write", "danger-full-access"])
            # fast 모드는 속도 1.5배 · 크레딧 2.5배다. 창이 곧 초기화돼 남은 할당량이
            # 어차피 사라질 때만 켠다 — 기본 기준은 사용자 확정값(30% / 15분).
            p.add_argument("--no-fast-gate", action="store_true",
                           help="사용량이 어떻든 항상 표준 모드로 실행한다")
            p.add_argument("--fast-min-percent", type=float, default=30.0,
                           help="5시간 사용량이 이 값 이상일 때만 fast 모드 (기본 30)")
            p.add_argument("--fast-within-minutes", type=float, default=15.0,
                           help="초기화가 이 분 안에 올 때만 fast 모드 (기본 15)")

    p = sub.add_parser("start", help="새 Codex 세션 시작")
    common(p)
    p.add_argument("--force", action="store_true", help="같은 이름의 기존 세션을 버리고 새로 시작")
    p.set_defaults(func=cmd_start)

    p = sub.add_parser("send", help="기존 세션에 이어서 요청")
    common(p)
    p.set_defaults(func=cmd_send)

    p = sub.add_parser("status", help="작업·세션 목록")
    p.add_argument("task", nargs="?")
    p.add_argument("--dir", default=".")
    p.set_defaults(func=cmd_status)

    p = sub.add_parser("report", help="특정 턴의 완료보고 출력")
    p.add_argument("task")
    p.add_argument("--dir", default=".")
    p.add_argument("--turn", type=int, default=-1)
    p.set_defaults(func=cmd_report)

    args = ap.parse_args()
    if getattr(args, "sandbox", None) is None and args.cmd == "start":
        args.sandbox = "workspace-write"
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
