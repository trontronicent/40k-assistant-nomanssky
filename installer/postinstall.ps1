# Sets up the optional parts the wizard asked for.
#
# Judged by exit codes only: this machine's console output is German-localised, so matching English
# words ("LISTENING", "SUCCESS", "Running") would be a silent failure. Everything is logged to
# <data>\install.log, and a failure leaves the feature off rather than a broken install.
[CmdletBinding()]
param([switch]$WithAi, [switch]$WithVoice)
$ErrorActionPreference = "Stop"
$install = $PSScriptRoot
$data = Join-Path $env:LOCALAPPDATA "NMS Companion"
New-Item -ItemType Directory -Force $data | Out-Null
$log = Join-Path $data "install.log"
function Write-Log($message) {
    Add-Content -Path $log -Value "$(Get-Date -Format s) $message" -Encoding utf8
}
Write-Log "postinstall started (ai=$WithAi, voice=$WithVoice)"

$settingsPath = Join-Path $data "standalone.json"
$settings = [ordered]@{
    ai_enabled  = $false
    tts_enabled = $false
    chat_model  = ""
    voice       = "en_GB-cori-high"
}
if (Test-Path $settingsPath) {
    try {
        (Get-Content $settingsPath -Raw | ConvertFrom-Json).PSObject.Properties |
            ForEach-Object { $settings[$_.Name] = $_.Value }
    } catch {
        Write-Log "the existing settings file was unreadable; starting from the defaults"
    }
}

if ($WithAi) {
    $ollama = Get-Command ollama -ErrorAction SilentlyContinue
    if (-not $ollama) {
        Write-Log "Ollama is not installed; downloading its installer"
        try {
            $exe = Join-Path $env:TEMP "OllamaSetup.exe"
            Invoke-WebRequest -Uri "https://ollama.com/download/OllamaSetup.exe" -OutFile $exe
            Start-Process -FilePath $exe -ArgumentList "/silent" -Wait
            $env:Path = "$env:Path;$env:LOCALAPPDATA\Programs\Ollama"
            $ollama = Get-Command ollama -ErrorAction SilentlyContinue
        } catch {
            Write-Log "Ollama could not be installed: $($_.Exception.Message)"
        }
    }
    if ($ollama) {
        $base = "gemma4:12b"
        $model = "40k-12b-companion"
        & ollama pull $base
        if ($LASTEXITCODE -eq 0) {
            & ollama create $model -f (Join-Path $install "40k-12b-companion.Modelfile")
            if ($LASTEXITCODE -eq 0) {
                $settings.chat_model = $model
                $settings.ai_enabled = $true
                Write-Log "created $model from $base"
            } else {
                Write-Log "creating $model failed ($LASTEXITCODE); falling back to $base"
                $settings.chat_model = $base
                $settings.ai_enabled = $true
            }
        } else {
            Write-Log "pulling $base failed with exit code $LASTEXITCODE"
        }
        & ollama pull "nomic-embed-text"
        if ($LASTEXITCODE -ne 0) {
            Write-Log "pulling nomic-embed-text failed ($LASTEXITCODE); the Codex will use full-text search"
        }
    } else {
        Write-Log "no ollama on PATH; the AI assistant stays off"
    }
}

if ($WithVoice) {
    $piper = Join-Path $data "piper"
    New-Item -ItemType Directory -Force $piper | Out-Null
    try {
        $zip = Join-Path $env:TEMP "piper_windows_amd64.zip"
        Invoke-WebRequest -OutFile $zip `
            -Uri "https://github.com/rhasspy/piper/releases/latest/download/piper_windows_amd64.zip"
        Expand-Archive -Path $zip -DestinationPath $piper -Force
        # Piper's archive has a piper\ folder; the host expects piper.exe directly in <data>\piper.
        $inner = Join-Path $piper "piper"
        if (Test-Path (Join-Path $inner "piper.exe")) {
            Get-ChildItem -Path $inner -Force | Move-Item -Destination $piper -Force
            Remove-Item -Recurse -Force $inner
        }
        $voice = $settings.voice
        $base = "https://huggingface.co/rhasspy/piper-voices/resolve/main/en/en_GB/cori/high/$voice"
        Invoke-WebRequest -OutFile (Join-Path $piper "$voice.onnx")      -Uri "$base.onnx"
        Invoke-WebRequest -OutFile (Join-Path $piper "$voice.onnx.json") -Uri "$base.onnx.json"
        if ((Test-Path (Join-Path $piper "piper.exe")) -and (Test-Path (Join-Path $piper "$voice.onnx"))) {
            $settings.tts_enabled = $true
            Write-Log "installed the voice $voice"
        } else {
            Write-Log "the voice files are incomplete; spoken replies stay off"
        }
    } catch {
        Write-Log "the voice could not be set up: $($_.Exception.Message)"
    }
}

$settings | ConvertTo-Json | Out-File -FilePath $settingsPath -Encoding utf8
Write-Log "postinstall finished (ai=$($settings.ai_enabled), voice=$($settings.tts_enabled))"
