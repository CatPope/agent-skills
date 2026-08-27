---
name: codex-delegate
description: >-
  구현 작업을 Codex에게 위임하고, 같은 세션을 계속 이어가며, 구조화된 완료보고
  (수정 파일 목록·실행 명령·테스트 여부·미완 항목)를 받는다.
  "코덱스에게 시켜", "codex한테 맡겨", "구현은 위임", "Codex 위임", "코덱스 이어서"
  같은 요청이나, 설계는 끝났고 구현만 남았을 때 사용.
audience: manager
---

# Codex 위임 — 세션 유지 + 구조화 완료보고

**이 스킬은 "어떻게 넘기는가"(메커니즘)만 다룬다.** 나머지는 위임한다.

- 누가 할지 가르는 법 → **[[role-split]]** (이 스킬로 오기 전 단계)
- 지시서를 쓰는 법 → **[[task-brief]]** 를 먼저 읽는다
- 받은 결과를 검증하는 법 → **[[work-review]]** 를 읽는다

## 왜 이 방식인가

에이전트는 못 하면 멈추는 게 아니라 **그럴듯하게 틀린 걸 내놓는다.** 자유 서술로
"완료했습니다"를 받으면 검증할 수가 없다. 그래서 두 가지를 강제한다.

1. **같은 세션 유지** — 매번 새 세션이면 맥락을 다시 설명해야 하고, Codex는 앞 턴에
   자기가 뭘 했는지 모른다. `thread_id`를 붙들고 이어간다.
2. **구조화 완료보고** — `modified_files`, `commands_run`, `tests.ran`, `unfinished`를
   JSON 스키마로 **강제**한다. 특히 `unfinished`가 비어 있지 않으면 그게 진짜 상태다.

## 작업 흐름

```
작업 명세 → 사용자와 논의 → 역할 구분
                              ├─ 설계·계획·조율 → Claude가 직접  ─┐
                              └─ 정밀 코드·모듈  → Codex(같은 세션) ┤→ 완료보고
                                    │                              │
                                    └─ blocked:true → 사용자에게 직행 (검토를 건너뜀)
                                                                   ↓
                                                            검토  ← work-review
                                        ├─ NO 재작업 → 작업 진행 단계로
                                        ├─ NO 재설계 → 역할 구분으로
                                        ├─ OK·Claude 몫  → 작업문서·skills 갱신 → 종료
                                        └─ OK·Codex 몫   → 문서·skills 갱신 하달
                                                            → Codex 결과 재검토
                                                              ├─ NO → 다시 하달
                                                              └─ OK → 종료
```

**Claude가 직접 한 작업(설계·계획)도 F(Codex)와 동일하게 완료보고 → 검토를 거친다.**
"내가 했으니 검토 생략"은 하지 않는다 — `work-review` §6.

**Codex에게 문서·skill 갱신을 하달한 뒤에도 끝이 아니다.** 하달 자체를 완료로 착각하지
않도록, 실제로 뭘 고쳤는지 재검토 루프를 한 번 더 거친다.

## 사용법

헬퍼 스크립트가 CLI 함정을 흡수한다. **`codex` 명령을 직접 조립하지 말 것**(아래 §함정).

```bash
PY="${CODEX_DELEGATE_PY:-python}"   # 필요하면 이 환경변수로 인터프리터 지정
S="$HOME/.agents/skills/codex-delegate/scripts/codex_task.py"

# 새 작업 시작 — 지시서는 반드시 파일로 (긴 지시서는 명령행 한도에 걸린다)
$PY "$S" start <작업명> --dir <작업디렉토리> --prompt-file 지시서.md

# 같은 세션에 이어서 (검토 피드백, 추가 지시, 문서·skill 갱신 하달)
$PY "$S" send <작업명> --dir <작업디렉토리> --prompt-file 피드백.md

$PY "$S" status --dir <작업디렉토리>
$PY "$S" report <작업명> --dir <작업디렉토리> --turn -1
```

`--sandbox` = `read-only` / `workspace-write`(기본) / `danger-full-access`.
조사·검토만 시킬 때는 `read-only`로 시작한다.

**오래 걸리는 작업은 백그라운드로 돌린다.** Bash 도구의 `run_in_background`를 쓰면
Codex가 끝나는 시점에 알림이 와서 **대화가 자동으로 재개**된다. 폴링할 필요 없다.

## 상태 관리

`<작업디렉토리>/.claude-codex/state.json`

```
tasks.<작업명> = { thread_id, work_dir, sandbox, created_at, turns[] }
turns[] = { at, kind(start|send), events(로그경로), report(완료보고 JSON) }
```

작업마다 세션이 분리되므로 **여러 작업을 병행해도 맥락이 섞이지 않는다.**
프롬프트 원문과 이벤트 로그는 `.claude-codex/<작업명>/` 에 타임스탬프로 남는다.

`modified_files`는 **세션 전체 누적**이다(1턴에 고친 파일이 3턴 보고에도 나온다).
이번 턴에 무엇이 바뀌었는지 보려면 `git status`나 파일 수정시각과 대조한다.

## 완료 보고는 2층이다 — 섞지 말 것

같은 "완료 보고"라는 이름의 산출물이 두 개 있다. **역할이 다르므로 둘 다 필요하다.**

| | JSON 완료보고 | 마크다운 완료 보고서 |
|---|---|---|
| 정본 | 이 스킬의 `--output-schema` | `codex-completion-report`(패널 작업은 `panel-completion-report`) |
| 목적 | **기계 검증** — 검토자가 필드로 대조 | **사람이 읽는 상세 기록** — 근거·수치·재현 방법 |
| 위치 | `.claude-codex/state.json` 의 `turns[].report` | `<프로젝트루트>/reports/YYYY-MM-DD_<작업명>/report.md` |
| 누가 | 스키마가 강제 (Codex가 못 빠뜨림) | Codex가 스킬에 따라 작성 |

**JSON이 검토의 입구다.** [[work-review]] §1의 필드 점검은 JSON을 전제로 한다.
마크다운 보고서만 오고 JSON이 없으면 검토 절차가 헛돈다 — 그때는 완료로 처리하지 말고
같은 세션에 JSON 보고를 다시 요구한다.

**마크다운 보고서 경로는 JSON의 `modified_files` 에도 잡힌다.** 두 산출물이 서로를
가리키므로, 한쪽만 있으면 그 자체가 이상 신호다.

## 권한 경계 — 양방향

**Codex → 관리자 (실행자가 결정하려 할 때)**

결정은 위임하지 않는다. 아키텍처·범위·우선순위·데이터셋/모델 선택은 사람과 관리자가
정하고, Codex에는 **이미 정해진 것만** 넘긴다. 선택지를 물으면 그럴듯한 답을 만들어낸다.

**Codex가 스스로 멈추게 하려면 지시서에 트리거를 박아야 한다** —
[[task-brief]] §6의 문구를 지시서에 그대로 넣는다. 넣지 않으면 추측하고 진행한다.
보고에 `blocked: true`가 오면 **대신 결정하지 말고 사용자에게 올린다.**

**관리자 → Codex (내가 구현하려 할 때)**

반대 방향도 경계 침범이다. 다음이면 손을 떼고 이 스킬로 넘긴다.

- 모델 학습·평가 스크립트, 파이프라인, 대규모 실행 코드
- 프로젝트의 **구현 코드 자산**이 되는 것

예외는 문서 변환용 소규모 스크립트나 분석을 위한 즉석 조회다.
기준은 **"결과물이 프로젝트의 구현 코드 자산인가"**. 애매하면 위임한다.

**되돌릴 수 없는 작업**(삭제·배포·외부 전송)은 `--sandbox`로 막거나 사람이 직접 한다.

## 함정 — 직접 CLI를 칠 때만 해당 (스크립트가 이미 처리함)

1. **옵션은 `resume` 앞에 와야 한다.**
   `codex exec resume <id> --sandbox ...` → `error: unexpected argument '--sandbox'`, exit 2.
   반드시 `codex exec --sandbox ... resume <id> "<프롬프트>"` 순서.
2. **stdin을 닫아야 한다.** 안 닫으면 `Reading additional input from stdin...`에서 대기한다.
3. **`thread_id`는 `--json` 스트림 첫 줄에만 나온다.**
   `{"type":"thread.started","thread_id":"..."}` — 놓치면 세션을 이어갈 수 없다.
4. **출력 스키마는 `properties`의 모든 키가 `required`에 있어야 한다.**
   빠지면 `invalid_json_schema` 400. 선택 필드는 `"type": ["string","null"]`로 표현한다.
5. **턴이 실패하면 보고 파일이 아예 안 생긴다.** null 보고를 성공으로 기록하면
   "요청은 갔는데 아무 일도 없었던" 상태를 완료로 착각한다.

## 이력 (필수 기록)
- 생성일: 2026-08-26
- 업데이트 횟수: 2
- 최근 업데이트: 2026-08-27
- 사용 이력:
  - 2026-08-27 — `Claude_Codex_Supervisor_Worker_워크플로우.md`(Codex 검토 완료본)에 맞춰
    작업흐름도 갱신: blocked는 검토를 건너뛰고 사용자에게 직행, NO를 재작업/재설계로 분리,
    Codex에 하달한 문서·skill 갱신도 재검토 루프 추가, Claude 직접 작업도 완료보고→검토
    거치도록 명시.
  - 2026-08-26 — 신규 생성. `codex exec` / `resume` / `--output-schema` 조합으로
    별도 프레임워크 없이 위임 루프가 성립함을 실증하고 스킬로 굳혔다.
    검증: 세션 유지(토큰 회수 성공), 파일 수정 누적 보고, 상태 파일 관리 모두 확인.
  - 2026-08-26 — 지시서 작성과 결과 검증을 [[task-brief]]·[[work-review]] 로 분리하고
    메커니즘만 남겼다. 두 기능은 Codex 위임이 아닐 때도 쓰이기 때문.
    실제 조사 업무에 적용해 `unfinished` 8건이 정직하게 올라오는 것을 확인.
    저장 위치를 `~/.agents/skills` 로 옮기고 `~/.claude/skills` 는 정션으로 연결(규약 일치).
