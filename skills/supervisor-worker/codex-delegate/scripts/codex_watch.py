#!/usr/bin/env python3
"""실행 중인 위임 작업을 주기적으로 들여다본다.

완료 알림만 기다리면 실패를 늦게 안다. 이 스크립트는 세션이 남기는 이벤트 로그를
읽어 **지금 무엇을 하고 있는지**와 **헤매고 있는지**를 요약한다.

    python codex_watch.py --dir <작업디렉토리>              # 10분마다 반복
    python codex_watch.py --dir <작업디렉토리> --once       # 한 번만
    python codex_watch.py --dir <작업디렉토리> --task sim-cell --interval 300

병렬로 여러 작업이 돌면 인자 없이도 **전부** 훑는다. 작업마다 세션이 분리돼 있으므로
한 번에 보는 것이 맞다.

출력은 화면과 `--out` 로그에 함께 쌓인다. 로그를 프로젝트 폴더에 두면 나중에
"언제부터 막혔나"를 되짚을 수 있다.
"""
import argparse
import collections
import glob
import io
import json
import os
import sys
import time

STATE_DIR = ".claude-codex"


def read_events(path):
    """마지막 줄은 기록 중이라 잘려 있을 수 있다 — 조용히 버린다."""
    rows = []
    for line in io.open(path, encoding="utf-8", errors="replace"):
        line = line.strip()
        if not line:
            continue
        try:
            rows.append(json.loads(line))
        except ValueError:
            pass
    return rows


READ_VERBS = (
    "get-content", "get-item", "get-childitem", "test-path", "select-string",
    "cat ", "head ", "tail ", "ls ", "rg ", "grep ", "find ", "type ",
)


def is_read_only(cmd):
    """읽기만 하는 명령인가. 검증 루프와 막힌 상태를 가르는 데 쓴다."""
    low = str(cmd).lower().lstrip("$& (\"'")
    return any(v in low[:120] for v in READ_VERBS)


def latest_log(base, task):
    files = sorted(glob.glob(os.path.join(base, task, "events_*.jsonl")))
    return files[-1] if files else None


def normalize(cmd):
    """반복 판정용. 셸 래퍼를 먼저 걷어내지 않으면 서로 다른 명령이 같아 보인다.

    실측 사고: PowerShell 경로+`-Command` 접두사만 90자가 넘어, 앞에서 자르는 방식으로는
    전혀 다른 명령 12건이 하나로 뭉쳐 "같은 명령 12회 반복" 오탐이 났다.
    """
    text = " ".join(str(cmd).split())
    for marker in ("-Command ", "-c ", "bash -lc "):
        idx = text.find(marker)
        if 0 <= idx < 200:                     # 래퍼는 앞쪽에만 온다
            text = text[idx + len(marker):]
            break
    return text.strip("\"' ")[:200]


def snapshot(base, task, tail):
    path = latest_log(base, task)
    if not path:
        return None

    rows = read_events(path)
    age = time.time() - os.path.getmtime(path)

    cmds, changed, searches, messages = [], [], 0, []
    for d in rows:
        item = d.get("item") or {}
        kind = item.get("type")
        if kind == "command_execution":
            cmds.append(normalize(item.get("command", "")))
        elif kind == "file_change":
            for ch in item.get("changes", []):
                changed.append((ch.get("kind"), os.path.basename(ch.get("path", ""))))
        elif kind == "web_search":
            searches += 1
        elif kind == "agent_message":
            messages.append(item.get("text", ""))

    # --- 방황 징후. 확정이 아니라 "열어볼 이유"다.
    flags = []
    repeats = collections.Counter(cmds)
    worst, n = (repeats.most_common(1) or [("", 0)])[0]
    # 산출물을 다시 읽어보는 검증 루프는 원래 같은 명령을 반복한다 — 방황이 아니다.
    verifying = bool(changed) and is_read_only(worst)
    if n >= 4 and not verifying:
        flags.append(f"같은 명령 {n}회 반복 — 같은 벽에 부딪히는 중일 수 있다")
    if len(cmds) >= 20 and not changed:
        flags.append(f"명령 {len(cmds)}건인데 파일 변경 0 — 조사만 하고 못 쓰고 있다")
    # 이미 끝난 작업은 "기록 없음"이 정상이다. 완료보고 파일이 있으면 침묵한다.
    finished = bool(glob.glob(os.path.join(os.path.dirname(path), "report_*.json")))
    if age > 900 and not finished:
        flags.append(f"{age/60:.0f}분째 기록 없음 — 멈췄거나 긴 작업 중")
    if searches >= 12 and not changed:
        flags.append(f"웹검색 {searches}회에 산출물 0 — 찾는 것이 없을 수 있다")

    blocked = [m for m in messages if '"blocked":true' in m.replace(" ", "")]
    if blocked:
        flags.append("blocked 보고가 올라왔다 — 결정 요청이다. 즉시 확인하라")

    return {
        "task": task, "log": os.path.basename(path), "age": age,
        "cmds": cmds, "changed": changed, "searches": searches,
        "messages": messages, "flags": flags, "tail": tail,
    }


def render(s):
    out = []
    out.append(f"=== {s['task']}   ({s['age']:.0f}초 전 기록 · {s['log']})")
    out.append(f"    명령 {len(s['cmds'])} · 파일변경 {len(s['changed'])} · "
               f"웹검색 {s['searches']} · 메시지 {len(s['messages'])}")

    if s["changed"]:
        seen, uniq = set(), []
        for kind, name in s["changed"]:
            if (kind, name) not in seen:
                seen.add((kind, name))
                uniq.append(f"{name}({kind})")
        out.append("    파일: " + ", ".join(uniq[-8:]))

    for line in s["cmds"][-s["tail"]:]:
        out.append("      $ " + line[:130])

    for f in s["flags"]:
        out.append("    ⚠ " + f)
    if not s["flags"]:
        out.append("    정상 진행으로 보임")
    return "\n".join(out)


def main():
    ap = argparse.ArgumentParser(description="위임 작업 실행 중 감시")
    ap.add_argument("--dir", required=True, help="작업 디렉토리(.claude-codex 의 부모)")
    ap.add_argument("--task", action="append", help="감시할 작업명. 생략하면 전부")
    ap.add_argument("--interval", type=int, default=600, help="주기(초). 기본 600 = 10분")
    ap.add_argument("--once", action="store_true", help="한 번만 확인하고 끝낸다")
    ap.add_argument("--tail", type=int, default=5, help="표시할 최근 명령 수")
    ap.add_argument("--out", help="스냅샷을 덧붙일 로그 파일")
    ap.add_argument("--max-rounds", type=int, default=0, help="0이면 무한. 안전장치")
    args = ap.parse_args()

    base = os.path.join(args.dir, STATE_DIR)
    if not os.path.isdir(base):
        print(f"상태 폴더가 없습니다: {base}", file=sys.stderr)
        return 2

    rounds = 0
    while True:
        tasks = args.task or sorted(
            d for d in os.listdir(base) if os.path.isdir(os.path.join(base, d))
        )
        stamp = time.strftime("%Y-%m-%d %H:%M:%S")
        blocks = [f"\n----- {stamp}"]
        for t in tasks:
            s = snapshot(base, t, args.tail)
            blocks.append(render(s) if s else f"=== {t}  이벤트 로그 없음")
        text = "\n".join(blocks)

        print(text, flush=True)
        if args.out:
            os.makedirs(os.path.dirname(os.path.abspath(args.out)), exist_ok=True)
            with io.open(args.out, "a", encoding="utf-8") as f:
                f.write(text + "\n")

        rounds += 1
        if args.once or (args.max_rounds and rounds >= args.max_rounds):
            return 0
        time.sleep(args.interval)


if __name__ == "__main__":
    sys.exit(main())
