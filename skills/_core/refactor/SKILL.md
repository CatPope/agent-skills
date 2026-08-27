---
name: refactor
description: Behavior-preserving refactoring with a read-first, plan-approve, one-chunk-at-a-time workflow. Use for extracting god files/components, renaming at scale, splitting large services, and untangling legacy code.
level: 3
audience: shared
---

# Refactor

A disciplined refactoring workflow. The premise: AI refactoring fails not because the model is weak, but because the workflow is unstructured. Without the callers in context, the model invents abstractions that break three files nobody showed it.

**Core rule: One thing at a time. One read. One proposal. One step. One test run. One commit.**

Individual steps get slower. Total delivery gets faster, because nothing has to be undone.

> **On the tool names below.** Names like `explore`, `critic`, `code-reviewer`, `executor`,
> `lsp_rename`, `AskUserQuestion` and `run_in_background` are what one particular setup
> (the oh-my-claudecode plugin on Claude Code) calls these capabilities. **Read them as
> roles**, and substitute whatever plays that role in your environment — a search pass, a
> second reviewer, a background test runner, a language server's rename. This skill does
> not require any specific plugin; only the discipline is required.
>
> Same for `/compact` and `/clear` below: read them as **"shrink the working context"** and
> **"start from a clean one"**. If your client has no such command, end the session and open
> a new one — that is the point being made, not the keystroke.

## When to Use

- The user says `refactor`, `리팩토링`, `리펙`, `구조 개선`, `코드 정리(구조적)`
- Splitting a god file / god component / oversized service
- Renaming a symbol, module, or convention across many files
- Extracting types, pure functions, state, or UI sections into their own units
- Untangling legacy or untested code before feature work lands on top of it
- Moving code between layers or modules without changing behavior

## When Not to Use

- New feature work or intentional behavior change → `executor` / `autopilot`
- Cleanup of AI-generated bloat, dead code, or wrapper layers → `ai-slop-cleaner`
- Pure readability polish with no structural move → `code-simplifier` agent
- The desired end-state architecture is unknown → `ralplan` or `architect` first, then return here
- A single trivial edit in one file with no callers → just do it

## Non-Negotiables

1. **Behavior is frozen.** A refactor that changes behavior is a bug with good intentions. If a behavior change is needed, stop and ask.
2. **No refactor without a safety net.** Tests, or characterization tests written first, or an explicit user waiver.
3. **No edit before the plan is approved.** The approval checkpoint is a real read, not a rubber stamp.
4. **Commit after every green step.** So step N+1 breaking costs one revert, not a whole session.

---

## Rule 0 — Read First, Always

Before proposing any change, the following must be in context:

| Must read | Why |
|---|---|
| The target file (fully) | Obvious, but read *all* of it, not the first screen |
| Every file that imports it | Interface breakage lives here |
| Every file it imports | Assumptions about dependencies live here |
| Relevant types / interfaces / schemas | Signature changes ripple through these |
| Existing tests touching it | These define the behavior contract to preserve |

Then **summarize back** before planning:

> Before touching anything: what does this module do, who calls it, what state does it own,
> and what breaks if its public interface changes? Summarize, do not change anything yet.

The summarization step is not ceremony. It is the check that comprehension happened instead of pattern matching.

Use `explore` (or the `Explore` agent) to build the caller/dependency map — that is exactly its job, and it keeps the raw grep output out of the main context.

### Large files

- Read in ~150-line sections rather than one giant dump.
- Extract the public interface (exports, signatures) separately from implementation bodies.
- `/compact` between major sections so the early reads survive.

---

## The Four Steps

### Step 1 — Understand

Map, do not touch.

- Dependency graph: who imports this, what does it import
- State ownership: what mutable state lives here, who else observes it
- Risk surface: side effects, I/O, globals, implicit ordering, timing assumptions
- Test coverage: what is actually protected today

Output: a short written map. If the map is fuzzy, keep reading. Do not proceed on a fuzzy map.

### Step 2 — Plan, then get approval

Propose the target structure **before** writing code:

- New files/modules/components and their responsibilities
- Public interfaces (props / signatures / exported names) of each new unit
- Migration order — which slice moves first, and why that one is safest
- What explicitly stays put (off-limits list)

Present it and stop. Use `AskUserQuestion` for the approval so the choice is one click, and offer a "revise the plan" option. Sixty seconds of real reading here prevents a whole session of architectural error.

For non-trivial plans, get a second pass from `critic` or `architect` before showing it — writer and reviewer stay separate lanes.

### Step 3 — Execute in vertical chunks

One chunk = one coherent slice, ideally one file changed.

For each chunk:
1. Make the change
2. Run the tests (`run_in_background` for slow suites)
3. Green → commit immediately, with a message naming the slice
4. Red → fix or revert *this chunk* before starting the next

Never batch three chunks and test once. The whole point of the discipline is that a failure has one obvious cause.

### Step 4 — Verify beyond "it compiles"

Compilation and green tests are the floor, not the ceiling. Read the diff and ask:

- Did any logic silently change owners (a check that used to run before now runs after)?
- Any behavior drift — default values, error paths, early returns, null handling?
- Any pattern in the old code that was dropped instead of moved?
- Any leftover: dead code, unused import, stale comment, orphaned test?

Hand the final diff to `code-reviewer` or `verifier`. Do not self-approve in the same context that wrote it.

**Then run the thing.** A green suite proves the paths someone already thought of. Execution finds the rest: entry-point scripts in their actual shell, a first-run from an empty state, the failure paths (stale state, missing arg, wrong location). Bugs that only surface here are routine — an opaque error where a helpful one belonged, a path argument misread as a file, a script whose encoding breaks the moment a non-ASCII character enters. If some environment can't be exercised (another OS, elevated privileges), **say it is unverified** rather than letting a passing suite imply otherwise.

---

## Playbooks

### God component / god file extraction

Decompose **in this order**. The order matters — each stage reduces the noise for the next.

1. **Types** → `types.ts` (zero risk, shrinks the file immediately)
2. **Pure functions** → `utils.ts` (no state, independently testable)
3. **State clusters** → custom hooks / service objects
4. **View sections** → sub-components (last, because the first three make the boundaries visible)

Each stage: separate session, separate commit. Between stages, `/clear` or `/compact`.

### Renaming at scale

Three stages, never collapsed into one:

1. **Locate** — `grep` for every occurrence, including strings, comments, docs, config, generated files
2. **Present** — show the full hit list, classify each as rename / skip / uncertain. Change nothing.
3. **Execute** — only the approved set

Stage 2 exists to catch the false positives: a comment mentioning the old name, a generated file that will be overwritten anyway, a same-named symbol in an unrelated module. Prefer `lsp_rename` for symbol renames when a language server is available — it is semantic, not textual — and reserve the grep pass for the strings and docs the LSP cannot see.

### Splitting a large service

One domain per session, one commit per session:

- Session 1: read the whole service, identify domain boundaries, write them down. **No code.**
- Session 2 (after `/clear`): extract domain A into its own service. Test. Commit.
- Session 3 (after `/clear`): extract domain B. Test. Commit.
- …

Fresh context per domain is deliberate. A session that has been running 90 minutes on complex work will have started forgetting the rules.

### Rebuild-and-reload (data stores)

For a schema change, "drop it and rebuild from source" is the cheapest path — **while it holds**. Before relying on it, prove it:

> Which rows in this store cannot be regenerated from their upstream source *today*?

Sources rot. Logs rotate, APIs age out, files get deleted. A store that was fully reproducible last month may now be the only copy of a third of its rows. Measure it — count rows whose source no longer exists — rather than assuming.

Once the answer is "some", rebuild is off the table and you need in-place migrations. Also audit anything that *tells* a user to rebuild: error messages, runbooks, READMEs. An instruction that was safe advice becomes a data-loss trigger, and it will still be sitting there saying "delete the database".

Before any destructive step, dump what won't come back. The dump list is not "data the UI creates" — it is **every row the current source cannot regenerate**.

### Untested legacy code

Write **characterization tests** first — tests that assert what the code *currently* does, bugs included, without judging it. They are a harness, not a spec.

1. Pin current behavior with characterization tests
2. Refactor against them
3. Replace them with proper intent-revealing tests once the structure is right

If characterization tests are impossible (heavy I/O, no seams), say so explicitly and get a waiver before proceeding. Do not refactor blind and hope.

---

## Persist the Plan in a File

For a multi-session refactor, put the state in a file the project already reads — its agent
instructions file, a `docs/plans/` entry, whatever it uses — not in chat history.
Chat history dies when the session is cleared; the file does not.

```markdown
## Refactoring: <name>

**Goal:** <one sentence, end-state>
**Architectural rules:** <e.g. all DB access goes through repositories; no direct fetch in components>
**Done:** <phase 1 — types extracted (commit abc123)>
**In progress:** <phase 2 — state → hooks>
**Off-limits:** <paths not to touch this refactor>
```

Update it at the end of each session. This is what makes starting a fresh session cheap.

---

## Anti-Patterns

| Anti-pattern | What it looks like | Fix |
|---|---|---|
| **Isolation** | Refactoring the target file without its callers in context | Rule 0 — read the importers first |
| **Context rot** | 90+ minute session; the model starts ignoring the project's standing rules | Compact aggressively, start a fresh session between phases, keep state in a file |
| **Rubber-stamp approval** | "Looks good" without reading the proposed interfaces | Actually read the plan. 60 seconds. |
| **Deferred commits** | Five chunks done, nothing committed, step 6 breaks | Commit every green step |
| **Big-bang chunk** | "I'll restructure all four files then run tests" | One file, one test run |
| **Silent scope creep** | Fixing a bug or adding a feature "while in there" | Note it, do not do it. Separate change, separate commit. |
| **Silently-wrong output** | The change makes something return fewer/empty results instead of erroring | Rank these above crashes. A crash gets fixed; a quiet wrong answer gets believed and propagated. |
| **Vacuous test** | A test that passes identically before and after the change | If it can't fail, it isn't verifying. Delete it or make it discriminate. |
| **Test drifts to a weaker assertion** | A catch-all matcher (`expect(anything)`, `except SomeBaseError`) now catches a different cause than the name claims | After changing a constraint, re-read every test that asserts on it. Coverage can vanish while the count stays green. |
| **Duplicated facts in docs** | The same number or schema written in N places | They will diverge — reliably. Keep one source and point at it. Fixing the copies just resets the clock. |
| **Rewriting history** | Updating a past record ("passed 43/43") to the current value | That sentence was true on its date. Mark it as of-then; only current-state claims get refreshed. |

---

## Tooling Map — one concrete setup (optional)

This is how the roles above map onto the oh-my-claudecode plugin. If you run something
else, keep the left column and substitute the right.


- **Mapping / caller discovery** → `explore` (or `Explore`) — keeps raw search output out of main context
- **Plan review before approval** → `critic` or `architect` (read-only)
- **Chunk execution** → `executor` (`model=opus` for tangled or high-risk slices)
- **Post-refactor review** → `code-reviewer`; **evidence of completion** → `verifier`
- **Commits** → `git-master` for atomic commit sequencing
- **Slop cleanup afterwards** → `ai-slop-cleaner` as a bounded follow-up on the changed files
- Long multi-phase refactors pair well with `ralph` (boulder loop) once the plan is locked, but the plan must be locked *first*.

## Completion Report

Report, in this order:

1. What moved, and to where (before → after structure)
2. Commits made, one line each
3. Test evidence — command run and result, not "tests pass"
4. Behavior deltas — ideally "none", otherwise listed explicitly
5. Deliberately deferred items and why

If any step was skipped (no tests existed, user waived the safety net, a chunk was batched), say so plainly. A refactor reported as clean when it was not is worse than one reported honestly as partial.

---

## 연계

- 구현 자체의 수칙(원본 보존·주석·로그·완료 기록)은 [[implementation-conduct]]
- 리팩터 계획을 남에게 넘긴다면 [[task-brief]], 돌아온 결과 검증은 [[work-review]]
- 리팩터 전후 성능·동작을 실측해 남긴다면 [[result-record]]

## 이력 (필수 기록)
- 생성일: 2026-08-27
- 업데이트 횟수: 0
- 사용 이력:
  - 2026-08-27 — 다른 저장소 작업에서 만들어진 것을 공용 스킬셋으로 이관.
    본문의 도구·에이전트 이름은 **지우지 않고** 앞부분에 한 번 "역할로 읽으라"는
    안내를 넣어 해결했다 — 어느 역할이 무엇을 맡는지가 이 스킬의 노하우이고,
    이름을 걷어내면 그 정보가 사라진다.
    "Rebuild-and-reload (data stores)" 절은 실제 사고에서 나온 것이다: 전부
    재생성 가능하다고 믿던 저장소의 3분의 1이 이미 유일본이었고, "DB를 지우고
    다시 만들라"는 안내문이 그대로 데이터 손실 지시가 되어 있었다.
