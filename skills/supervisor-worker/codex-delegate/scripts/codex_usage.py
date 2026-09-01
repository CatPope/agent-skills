# -*- coding: utf-8 -*-
"""세션의 컨텍스트 점유율과 사용량 한도를 한 곳에서 읽는다.

`codex exec --json` 스트림에는 이 값이 없다(실측: 이벤트 14개 파일 전수 검사에서
`token_count` 0건, `rate_limits` 0건). Codex 는 별도로

    ~/.codex/sessions/<년>/<월>/<일>/rollout-<시각>-<thread_id>.jsonl

에 요청마다 `token_count` 를 남기고, **거기에만** `model_context_window` 와
`rate_limits` 가 붙는다. 점유율도 한도도 여기서만 읽을 수 있다.

세 스크립트(codex_task / codex_watch / codex_compact)가 같은 값을 봐야 하므로
읽는 코드는 이 모듈 하나로 둔다. 복사본이 갈라지면 감시자가 보는 수치와 실행기가
판단하는 수치가 달라진다.

실측으로 확인한 형태:
    "rate_limits": {
      "primary":   {"used_percent": 92.0, "window_minutes": 300,   "resets_at": 1788163917},
      "secondary": {"used_percent": 14.0, "window_minutes": 10080, "resets_at": ...}}

`resets_at` 은 **절대 epoch 초(UTC)** 다. primary 가 5시간 창, secondary 가 주간 창이다.
"""
from __future__ import annotations

import calendar
import glob
import io
import json
import os
import time

STATE_DIR = ".claude-codex"

_SESSIONS = os.path.join(os.path.expanduser("~"), ".codex", "sessions")
ROLLOUT_FOR_THREAD = os.path.join(_SESSIONS, "*", "*", "*", "rollout-*-%s.jsonl")
ROLLOUT_FOR_SUBTHREAD = os.path.join(_SESSIONS, "*", "*", "*", "rollout-*_%s.jsonl")
ROLLOUT_ANY = os.path.join(_SESSIONS, "*", "*", "*", "rollout-*.jsonl")

# 롤아웃은 100MB 를 넘긴다(실측 107MB). 전부 읽으면 감시 한 바퀴가 수십 초로 늘어진다.
TAIL_BYTES = 8 * 1024 * 1024


def thread_of(work_dir: str, task: str) -> str | None:
    """state.json 에서 작업의 thread_id 를 꺼낸다. 없으면 None."""
    p = os.path.join(work_dir, STATE_DIR, "state.json")
    if not os.path.exists(p):
        return None
    try:
        return json.load(io.open(p, encoding="utf-8"))["tasks"][task]["thread_id"]
    except (ValueError, KeyError, OSError):
        return None


def _newest(*patterns: str) -> str | None:
    files = [f for p in patterns for f in glob.glob(p)]
    return max(files, key=os.path.getmtime) if files else None


def _rollouts_for(thread_id: str) -> tuple[str, str]:
    """세션 파일 이름은 두 가지다.

        rollout-<시각>-<thread_id>.jsonl              보통의 세션
        rollout-<시각>-<부모id>_<thread_id>.jsonl     하위 에이전트 세션

    뒤쪽을 빠뜨리면 하위 세션에서 "사용량 기록 없음"이 조용히 나온다.
    """
    return (ROLLOUT_FOR_THREAD % thread_id, ROLLOUT_FOR_SUBTHREAD % thread_id)


def _last_token_count(path: str) -> dict | None:
    """파일 끝에서부터 마지막 token_count 줄을 찾는다."""
    size = os.path.getsize(path)
    with io.open(path, "rb") as f:
        f.seek(max(0, size - TAIL_BYTES))
        chunk = f.read()
    if size > TAIL_BYTES:
        chunk = chunk.split(b"\n", 1)[-1]          # 잘린 첫 줄은 버린다
    for line in reversed(chunk.decode("utf-8", errors="replace").splitlines()):
        if '"token_count"' not in line or not line.startswith("{"):
            continue
        try:
            return json.loads(line)
        except ValueError:
            continue
    return None


def _epoch(iso: str) -> float | None:
    """롤아웃 timestamp('2026-08-31T07:24:42.212Z') 를 epoch 초로."""
    try:
        return calendar.timegm(time.strptime(iso[:19], "%Y-%m-%dT%H:%M:%S"))
    except (ValueError, TypeError):
        return None


def read_usage(thread_id: str | None = None) -> dict | None:
    """점유율과 사용량 한도를 읽는다.

    thread_id 를 주면 그 세션의 롤아웃을, 주지 않으면 **가장 최근 롤아웃**을 본다.
    사용량 한도는 계정 단위라 어느 세션에서 읽어도 같다 — 새 세션을 시작하기 직전
    (아직 자기 롤아웃이 없을 때) 한도를 보려면 이쪽을 쓴다.
    """
    path = _newest(*_rollouts_for(thread_id)) if thread_id else _newest(ROLLOUT_ANY)
    if not path:
        return None
    ev = _last_token_count(path)
    if not ev:
        return None

    payload = ev.get("payload") or {}
    info = payload.get("info") or {}
    rl = payload.get("rate_limits") or {}
    primary = rl.get("primary") or {}
    secondary = rl.get("secondary") or {}

    ctx = (info.get("last_token_usage") or {}).get("input_tokens") or 0
    win = info.get("model_context_window") or 0
    at_iso = (ev.get("timestamp") or "")

    return {
        "path": path,
        "at": at_iso[:19].replace("T", " "),
        "at_epoch": _epoch(at_iso),
        "ctx": ctx,
        "window": win,
        "pct": (ctx / win * 100) if win else 0.0,
        "p5": primary.get("used_percent"),
        "p5_window_minutes": primary.get("window_minutes"),
        "p5_resets_at": primary.get("resets_at"),
        "weekly": secondary.get("used_percent"),
        "weekly_resets_at": secondary.get("resets_at"),
    }


def minutes_to_reset(usage: dict | None, now: float | None = None) -> float | None:
    """5시간 창이 초기화되기까지 남은 분. 이미 지났으면 음수, 알 수 없으면 None."""
    if not usage or not usage.get("p5_resets_at"):
        return None
    return (usage["p5_resets_at"] - (time.time() if now is None else now)) / 60.0


def fast_decision(usage: dict | None, min_percent: float = 30.0,
                  within_minutes: float = 15.0, now: float | None = None) -> tuple[bool, str]:
    """fast 모드로 실행할지 정한다. (쓸지, 이유) 를 돌려준다.

    규칙(사용자 확정): **5시간 사용량이 `min_percent`% 이상이고, 그 창이
    `within_minutes` 분 안에 초기화되면** fast 모드로 실행한다.
    남은 할당량은 초기화되면 어차피 사라지므로, 그 직전에는 아껴 쓸 이유가 없고
    빨리 끝내는 편이 낫다는 판단이다.

    fast 모드는 **속도 1.5배 · 크레딧 2.5배**다(GPT-5.6 기준). 그래서 조건이
    하나라도 어긋나면 쓰지 않는다 — 특히 창이 한참 남았을 때 켜면 그냥 2.5배 손해다.

    한도 기록은 **지난 요청 시점의 값**이라 오래됐을 수 있다. `resets_at` 이 이미
    지났다면 그 창은 벌써 초기화됐고 `used_percent` 는 옛 창의 값이므로 믿지 않는다.
    """
    if not usage:
        return False, "사용량 기록을 찾지 못했다(롤아웃 없음) — 표준 모드"

    used = usage.get("p5")
    if used is None:
        return False, "5시간 한도 값이 기록에 없다 — 표준 모드"

    left = minutes_to_reset(usage, now)
    if left is None:
        return False, "초기화 시각이 기록에 없다 — 표준 모드"
    if left <= 0:
        return False, (f"기록된 창은 이미 초기화됐다({usage['at']} UTC 기준 {used}%) — "
                       "지금 사용량을 알 수 없으므로 표준 모드")

    if used >= min_percent and left <= within_minutes:
        return True, (f"5시간 한도 {used}% (기준 {min_percent}% 이상) · "
                      f"초기화까지 {left:.0f}분 (기준 {within_minutes:.0f}분 이내) — "
                      "곧 사라질 할당량이라 fast 모드")

    why = []
    if used < min_percent:
        why.append(f"사용량 {used}% < {min_percent}%")
    if left > within_minutes:
        why.append(f"초기화까지 {left:.0f}분 > {within_minutes:.0f}분")
    return False, "표준 모드 (" + ", ".join(why) + ")"


# fast 모드를 켜는 인자. `service_tier="fast"` 는 TOML 문자열로 파싱된다.
# 두 가지를 함께 준다 — 서비스 티어만 바꾸면 기능 플래그가 꺼진 채로 남는다.
FAST_ARGS = ["-c", 'service_tier="fast"', "--enable", "fast_mode"]


def is_stale(usage: dict | None, now: float | None = None) -> bool:
    """기록된 5시간 창이 이미 초기화됐는가.

    한도 값은 **지난 요청 시점**의 것이다. 창이 지났으면 그 숫자는 옛 창의 값이라
    지금 사용량과 무관하다. 이걸 구분하지 않으면 하루 전 92% 를 보고 "곧 끊긴다"고
    경고하게 된다.
    """
    left = minutes_to_reset(usage, now)
    return left is None or left <= 0


def format_usage(usage: dict | None, now: float | None = None) -> str:
    """감시 출력용 한 줄."""
    if not usage:
        return "사용량 기록 없음"
    left = minutes_to_reset(usage, now)
    if usage.get("p5") is None:
        limits = "5시간한도 기록없음"
    elif left is not None and left > 0:
        limits = f"5시간한도 {usage['p5']}% ({left:.0f}분 뒤 초기화)"
    else:
        limits = f"5시간한도 {usage['p5']}% (지난 창의 값 — 현재값 아님)"
    weekly = "-" if usage.get("weekly") is None else f"{usage['weekly']}%"
    return (f"컨텍스트 {usage['ctx']:,}/{usage['window']:,} ({usage['pct']:.0f}%)"
            f" · {limits} · 주간 {weekly}"
            f"   [{usage['at']} UTC 기준]")
