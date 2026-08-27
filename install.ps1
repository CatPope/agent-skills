<#
  agent-skills installer (Windows / PowerShell 5.1+)

  .\install.ps1 -List
  .\install.ps1 -Workflow supervisor-worker
  .\install.ps1 -Status

  Links the _core skills plus the chosen workflow's skills into both agent
  skill stores. Uses directory Junctions, which do NOT require administrator
  rights (plain symlinks on Windows do - see README).
#>
[CmdletBinding()]
param(
  [string]$Workflow,
  [switch]$List,
  [switch]$Status,
  [switch]$Force,
  [string]$ClaudeDir = "$HOME\.claude\skills",
  [string]$AgentsDir = "$HOME\.agents\skills"
)

$ErrorActionPreference = "Stop"
$Root   = $PSScriptRoot
$Marker = Join-Path $AgentsDir ".agent-skills-active"

function Get-Workflows {
  Get-ChildItem (Join-Path $Root "workflows") -Filter *.json | ForEach-Object {
    # -Encoding UTF8 필수: PowerShell 5.1 은 BOM 없는 파일을 ANSI 로 읽어 한글이 깨진다
    $w = Get-Content $_.FullName -Raw -Encoding UTF8 | ConvertFrom-Json
    $w | Add-Member -NotePropertyName _file -NotePropertyValue $_.Name -Force
    $w
  }
}

if ($List) {
  Write-Host ""
  Write-Host "사용 가능한 워크플로우"
  Write-Host ""
  foreach ($w in Get-Workflows) {
    Write-Host ("  {0,-20} [{1}] {2}" -f $w.id, $w.status, $w.name)
    Write-Host ("  {0,-20}   {1}" -f "", $w.summary)
    Write-Host ""
  }
  Write-Host "설치:  .\install.ps1 -Workflow <id>"
  return
}

if ($Status) {
  if (Test-Path $Marker) {
    Write-Host ("활성 워크플로우: " + (Get-Content $Marker -Raw).Trim())
  } else {
    Write-Host "활성 워크플로우 없음 (아직 설치하지 않았습니다)"
  }
  return
}

if (-not $Workflow) { throw "-Workflow <id> 를 지정하거나 -List 로 목록을 보세요." }

$wf = Get-Workflows | Where-Object { $_.id -eq $Workflow }
if (-not $wf) { throw "알 수 없는 워크플로우: $Workflow  (-List 로 확인)" }
if ($wf.status -ne "active") {
  throw "'$Workflow' 는 status=$($wf.status) 입니다. 아직 설치할 수 없습니다."
}

# 설치 대상 = _core 전부 + 워크플로우 고유 스킬
$targets = @()
Get-ChildItem (Join-Path $Root "skills\_core") -Directory | ForEach-Object { $targets += $_.FullName }
foreach ($s in $wf.skills) {
  $p = Join-Path $Root ("skills\" + $wf.id + "\" + $s)
  if (-not (Test-Path $p)) { throw "매니페스트에 있으나 폴더가 없습니다: $p" }
  $targets += $p
}

foreach ($dir in @($ClaudeDir, $AgentsDir)) {
  if (-not (Test-Path $dir)) { New-Item -ItemType Directory -Path $dir -Force | Out-Null }
}

$linked = 0; $skipped = 0
foreach ($src in $targets) {
  $name = Split-Path $src -Leaf
  foreach ($dir in @($ClaudeDir, $AgentsDir)) {
    $link = Join-Path $dir $name
    if (Test-Path $link) {
      $item = Get-Item $link -Force
      if ($item.LinkType -eq "Junction" -and $item.Target -contains $src) {
        $skipped++
        continue
      }
      if (-not $Force) {
        Write-Warning "이미 있음(건너뜀): $link  -> 교체하려면 -Force"
        $skipped++
        continue
      }
      cmd /c rd /q "$link" | Out-Null
    }
    cmd /c mklink /J "$link" "$src" | Out-Null
    $linked++
  }
}

Set-Content -Path $Marker -Value $wf.id -Encoding utf8
Write-Host ""
Write-Host ("설치 완료: {0}" -f $wf.name)
Write-Host ("  링크 {0}개 생성, {1}개 건너뜀" -f $linked, $skipped)
Write-Host ("  대상: {0} / {1}" -f $ClaudeDir, $AgentsDir)
Write-Host ("  스킬: {0}" -f (($targets | ForEach-Object { Split-Path $_ -Leaf }) -join ", "))
Write-Host ""
