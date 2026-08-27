---
name: docs-append
description: >-
  공유 Google 문서 본문 끝에 텍스트를 추가한다. gws CLI를 쓰며, 외부 쓰기이므로
  승인 절차를 거친다. "구글독스에 추가", "문서에 append", "독스에 기록" 같은
  명시적 지시에만 사용. 대상 문서 ID는 호출할 때 받는다.
audience: manager
disable-model-invocation: true
---

# Docs Append — 공유 Google 문서에 덧붙이기

`gws` CLI로 Google 문서 **본문 맨 끝에** 텍스트를 추가한다.

> **자동 발동하지 않는다.** 외부에 나가는 쓰기이므로 사용자가 명시적으로 지시할 때만
> 실행한다(`disable-model-invocation`). 무엇을 추가할지 불분명하면 **먼저 확인**한다.

## 대상 문서

문서 ID는 **이 스킬에 적지 않는다.** 호출 시 인자로 받거나, 프로젝트 문서·설정에
적어 둔 값을 읽는다. 스킬에 박아 두면 다른 문서에 쓸 수 없다.

```bash
DOC_ID="<대상 문서 ID>"     # 문서 URL 의 /document/d/<여기>/edit
```

## 절차

### 1. 인증 확인

```bash
gws auth status
```

`auth_method` 가 `none` 이면 **중단하고** 사용자에게 안내한다.

```bash
gcloud auth login
gws auth setup
gws auth login -s docs,drive
```

⚠️ **로그인 계정에 그 문서의 편집 권한(editor)이 있어야 한다.** 없으면 `403` 이 난다.
읽기 권한만으로는 append 가 되지 않는다 — 인증은 성공했는데 쓰기에서 막히므로
원인을 인증 문제로 오해하기 쉽다.

### 2. 추가 실행

```bash
gws docs +write --document "$DOC_ID" --text "<추가할 내용>"
```

외부 쓰기이므로 실행 직전 **승인 절차**가 걸린다(환경에 따라 hook·프롬프트).
승인 후 진행된다.

### 3. 결과 보고

무엇을 어느 문서에 추가했는지 밝힌다. 실패하면 원인(**편집 권한 / 인증**)과
해결책을 함께 알린다.

## 한계 — 이걸 넘어서면 다른 방법을 쓴다

| 하려는 것 | append 로 되는가 |
|---|---|
| 본문 끝에 평문 추가 | O |
| **특정 탭에 넣기** | X — 탭 지정 불가 |
| **서식·표·이미지** | X — plain text 만 |
| 기존 내용 수정 | X — 추가만 가능 |

위 X 항목이 필요하면 append 가 아니라 **raw `batchUpdate`** 를 쓴다.

```bash
gws docs documents batchUpdate --document "$DOC_ID" --params '<요청 JSON>'
```

탭 생성은 API 로 안 되는 경우가 있다. 그럴 때는 **사용자가 UI 에서 탭을 만든 뒤**
문서를 다시 조회해 `tabId` 를 얻는다.

## 연계
- 무엇을 올릴지 만드는 단계는 [[result-record]] · [[adoption-proposal]]
  — 둘 다 **로컬 작성이 먼저**이고 외부 반영은 별도 승인이다

## 이력 (필수 기록)
- 생성일: 2026-08-27
- 사용 이력:
  - 2026-08-27 — 프로젝트 전용 스킬을 일반화해 이관. 본문에 박혀 있던 대상 문서 ID를
    인자로 뺀 것이 변경의 전부다. 절차·함정(편집권한 403, plain text·본문 끝 한계,
    탭 지정 불가)은 그대로 유지했다.
