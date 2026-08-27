# agent-skills

여러 PC·여러 프로젝트에서 그대로 쓰는 **에이전트 워크플로우 스킬 모음**입니다.
워크플로우를 골라 설치하면, 공통 스킬 한 벌과 그 워크플로우 고유 스킬이 함께 링크됩니다.

포터빌리티 규약과 린터는 [`CatPope/doc-skills`](https://github.com/CatPope/doc-skills)의
`portable-skill-authoring`을 따릅니다. 이 레포의 모든 스킬은 그 린터를 통과합니다.

## 구조

```
agent-skills/
  workflows/          워크플로우 매니페스트 (어떤 스킬을 묶을지)
  skills/
    _core/            워크플로우와 무관하게 항상 설치되는 공통 스킬
    <workflow-id>/    해당 워크플로우에서만 설치되는 고유 스킬
  docs/workflows/     워크플로우별 다이어그램·설명
  install.ps1         Windows
  install.sh          macOS / Linux
```

## 설치

```powershell
# Windows
.\install.ps1 -List
.\install.ps1 -Workflow supervisor-worker
.\install.ps1 -Status
```

```bash
# macOS / Linux
./install.sh --list
./install.sh --workflow supervisor-worker
./install.sh --status
```

두 스토어(`~/.claude/skills`, `~/.agents/skills`) 모두 이 레포를 **링크**합니다.
복사가 아니므로 레포에서 고친 순간 반영되고, "어느 쪽이 최신인가" 문제가 생기지 않습니다.

전환은 `-Workflow` 를 다시 실행하면 됩니다. 이미 있는 링크는 기본적으로 건너뛰며,
교체하려면 `-Force` / `--force` 를 붙입니다.

### Windows에서 관리자 권한이 필요 없는 이유

Windows에서 **심볼릭 링크는 관리자 권한을 요구**합니다
(`New-Item -ItemType SymbolicLink`, `ln -s` 모두 실패).
반면 **디렉터리 정션(`mklink /J`)은 일반 권한으로 생성**됩니다.
그래서 `install.ps1`은 정션을 씁니다. 이 차이를 모르면 새 PC에서 설치가 막힙니다.

## 워크플로우

| id | 상태 | 내용 |
|----|------|------|
| `supervisor-worker` | active | Claude가 명세·역할배분·검수, Codex가 정밀 구현. 같은 Codex 세션을 유지하며 구조화 완료보고(JSON)를 받는다. |
| `codex-review` | planned | 역할이 뒤집힌 구성. Claude가 설계·개발, Codex가 적대적 검토. `openai/codex-plugin-cc` 경유. |

`status`가 `active`가 아니면 설치되지 않습니다.

## 스킬

### `_core` — 항상 설치

| 스킬 | 역할 |
|------|------|
| `task-brief` | 넘길 작업지시서를 쓴다. 완료 기준·금지사항·권한 경계를 갖춰 받는 쪽이 추측하지 않게 한다 |
| `work-review` | 받은 결과를 검증한다. "완료했습니다"를 믿지 않고 증거와 대조한다 |
| `progress-log` | 결정·정정을 진행상황 문서에 반영한다. 요청을 기다리지 않는다 |
| `compact-checkpoint` | 대화 압축 예고를 받으면 그 전에 문서·스킬을 먼저 갱신한다 |
| `agent-operations` | 서브에이전트 운영 규칙을 정본 스킬에 기록해 세션 후에도 복구되게 한다 |
| `skill-generalize` | 프로젝트에서 자란 스킬을 다른 곳에서도 쓰게 일반화한다. 노하우는 남기고 그때의 결정만 걷어낸다 |
| `result-record` | 실험·테스트 결과를 **재현·비교 가능하게** 남긴다 |
| `adoption-proposal` | 근거를 갖춰 **채택을 요청**한다. 읽는 사람은 결정권자 |
| `docs-append` | 공유 Google 문서 끝에 덧붙인다. 외부 쓰기라 명시적 지시에만 동작 |

`result-record` 와 `adoption-proposal` 은 둘 다 "보고서"지만 **목적이 다르다** —
전자는 우리가 나중에 다시 보려는 기록이고, 후자는 남에게 판단을 요청하는 문서다.
요구되는 내용도 다르므로 섞지 않는다.

일을 넘기고, 검증하고, 기록하는 일은 상대가 Codex든 사람이든 서브에이전트든 같기 때문에
공통입니다.

### `supervisor-worker` — 선택 시 설치

| 스킬 | 역할 |
|------|------|
| `role-split` | 무엇을 Claude가 직접 하고 무엇을 넘길지 가른다. 가장 되돌리기 비싼 분기 |
| `codex-delegate` | 같은 Codex 세션을 유지하며 위임하고 구조화 완료보고를 받는 메커니즘 |
| `codex-completion-report` | 실행자가 남기는 완료 보고서 형식 |

셋 다 **"Codex가 실행자"라는 전제**에 묶여 있어 공통이 아닙니다.

## 규약

- `audience:` — `manager` / `executor` / `shared`. 누가 쓰는 스킬인지 프론트매터에 명시합니다.
- `## 이력 (필수 기록)` — 생성일·업데이트 횟수·사용 이력. **왜 그렇게 바뀌었는지**를 남깁니다.
- 스킬끼리는 `[[skill-name]]` 로 참조합니다. 함수 호출이 아니라 "이 시점에 저걸 읽어라"입니다.
- 특정 프로젝트의 경로·인명·문서 ID를 스킬 본문에 적지 않습니다. 프로젝트 문서로 넘깁니다.

## 검증

커밋 전에 포터빌리티 린터를 돌립니다.

```bash
python <doc-skills>/skills/portable-skill-authoring/scripts/check_skill.py skills/_core
python <doc-skills>/skills/portable-skill-authoring/scripts/check_skill.py skills/supervisor-worker
```

`FAIL`이 하나라도 있으면 커밋하지 않습니다.
