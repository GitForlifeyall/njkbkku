<#
.SYNOPSIS
    Redroid Android Instance Manager on Windows 11 / WSL2
.DESCRIPTION
    Manages persistent Redroid Android containers (Start, Stop, Restart, Status, Scrcpy, ADB).
.EXAMPLE
    .\redroid.ps1 start 01
    .\redroid.ps1 stop 01
    .\redroid.ps1 restart 01
    .\redroid.ps1 status 01
    .\redroid.ps1 scrcpy 01
    .\redroid.ps1 adb 01 shell getprop ro.build.version.release
#>

param(
    [Parameter(Position=0, Mandatory=$true)]
    [ValidateSet("start", "stop", "restart", "status", "scrcpy", "adb", "health", "help")]
    [string]$Action,

    [Parameter(Position=1, Mandatory=$false)]
    [string]$Account = "01",

    [Parameter(Position=2, ValueFromRemainingArguments=$true)]
    [string[]]$ExtraArgs
)

$ErrorActionPreference = "Continue"
if (Test-Path Variable:PSNativeCommandUseErrorActionPreference) {
    $PSNativeCommandUseErrorActionPreference = $false
}

# Resolve ADB and Scrcpy paths dynamically
$AdbExe = "adb"
$ScrcpyExe = "scrcpy"

$foundAdb = Get-Command adb -ErrorAction SilentlyContinue
if ($foundAdb) { $AdbExe = $foundAdb.Source }
$foundScrcpy = Get-Command scrcpy -ErrorAction SilentlyContinue
if ($foundScrcpy) { $ScrcpyExe = $foundScrcpy.Source }

# Container and Port mapping (Account 01 -> 5801, or Brand Name / Container Name)
if ($Account -match '^\d+$') {
    $AccountNum = [int]$Account
    $HostPort = 5800 + $AccountNum
    $ContainerName = "redroid-$Account"
    $VolumeName = "redroid-account-$Account-data"
} else {
    $cleanName = $Account -replace '^redroid-', ''
    $ContainerName = if ($Account.StartsWith("redroid-")) { $Account } else { "redroid-$Account" }
    $VolumeName = "$ContainerName-data"
    
    $brandsJsonPath = Join-Path $PSScriptRoot "..\redroid_manager\config\brands.json"
    $foundPort = $null
    if (Test-Path $brandsJsonPath) {
        try {
            $brandsConfig = Get-Content $brandsJsonPath -Raw | ConvertFrom-Json
            foreach ($b in $brandsConfig.brands) {
                if ($b.container_name -eq $ContainerName -or $b.brand_id -eq $cleanName -or $b.name -eq $cleanName) {
                    $foundPort = [int]$b.host_port
                    $ContainerName = $b.container_name
                    break
                }
            }
        } catch {}
    }
    
    if ($foundPort) {
        $HostPort = $foundPort
    } elseif ($ExtraArgs -and $ExtraArgs[0] -match '^\d+$') {
        $HostPort = [int]$ExtraArgs[0]
    } else {
        $HostPort = 5555
    }
}

# Auto-detect ADB target (Defaults to 127.0.0.1 for stable Windows/WSL2 port forwarding)
$AdbTarget = "127.0.0.1:$HostPort"

# Clean up any duplicate connection to WSL internal IP which causes dual-socket scrcpy disconnects
try {
    $wslRaw = ((wsl.exe -d Ubuntu -u root --exec hostname -I 2>$null) -join "") -replace "`0",""
    if ($wslRaw) {
        $foundIp = ($wslRaw.Trim() -split "\s+")[0]
        if ($foundIp) {
            $duplicateTarget = "$foundIp`:$HostPort"
            $devices = ((& $AdbExe devices 2>$null) -join "`n")
            if ($devices -match [regex]::Escape($duplicateTarget)) {
                & $AdbExe disconnect $duplicateTarget 2>$null | Out-Null
            }
        }
    }
} catch {}

function Invoke-DockerCmd {
    param([string[]]$DockerArgs)
    $escaped = ($DockerArgs | ForEach-Object { if ($_ -match '\s') { "'$_'" } else { $_ } }) -join " "
    $res = & wsl.exe -d Ubuntu -u root --exec /bin/bash -c "docker $escaped" 2>&1
    return (($res -join "`n") -replace "`0","")
}

function Ensure-DockerRunning {
    $wslCheck = (((wsl.exe -d Ubuntu -u root --exec bash -c "echo WSL_OK" 2>$null) -join "") -replace "`0","").Trim()
    if ($wslCheck -ne "WSL_OK") {
        Write-Host "[*] Starting WSL2 Ubuntu..." -ForegroundColor Cyan
        wsl.exe -d Ubuntu -u root --exec true | Out-Null
    }
    # Keep WSL alive in background so Windows does not shut down the VM when no console is open
    try {
        $hasKeepAlive = (((wsl.exe -d Ubuntu -u root --exec bash -c "pgrep -f redroid-keepalive" 2>$null) -join "") -replace "`0","").Trim()
        if (-not $hasKeepAlive) {
            Start-Process wsl.exe -ArgumentList "-d", "Ubuntu", "-u", "root", "--exec", "bash", "-c", "exec -a redroid-keepalive sleep infinity" -WindowStyle Hidden
        }
    } catch {}

    # Check if Docker daemon is already healthy and responsive. NEVER restart if already running!
    $dockerHealthy = (((wsl.exe -d Ubuntu -u root --exec bash -c "docker info >/dev/null 2>&1 && echo OK" 2>$null) -join "") -replace "`0","").Trim()
    if ($dockerHealthy -ne "OK") {
        Write-Host "[*] Starting Docker daemon inside WSL..." -ForegroundColor Cyan
        wsl.exe -d Ubuntu -u root --exec bash -c "systemctl start docker >/dev/null 2>&1 || service docker start >/dev/null 2>&1" | Out-Null
        Start-Sleep -Seconds 2
    }
}

function Ensure-NetworkRouting {
    # Ensure WSL kernel IP forwarding and Docker NAT masquerade are active
    wsl.exe -d Ubuntu -u root --exec bash -c "sysctl -w net.ipv4.ip_forward=1 >/dev/null 2>&1; iptables -t nat -C POSTROUTING -s 172.17.0.0/16 ! -o docker0 -j MASQUERADE 2>/dev/null || iptables -t nat -A POSTROUTING -s 172.17.0.0/16 ! -o docker0 -j MASQUERADE 2>/dev/null || true" | Out-Null
    # Ensure default gateway and DNS are set inside container
    Invoke-DockerCmd @("exec", $ContainerName, "ip", "route", "add", "default", "via", "172.17.0.1", "dev", "eth0") 2>$null | Out-Null
    Invoke-DockerCmd @("exec", $ContainerName, "setprop", "net.dns1", "8.8.8.8") 2>$null | Out-Null
    Invoke-DockerCmd @("exec", $ContainerName, "setprop", "net.dns2", "1.1.1.1") 2>$null | Out-Null
}

function Connect-Adb {
    param([int]$MaxAttempts = 20)
    Write-Host "[*] Connecting ADB to $AdbTarget..." -ForegroundColor Cyan
    for ($i = 1; $i -le $MaxAttempts; $i++) {
        $devices = ((& $AdbExe devices 2>$null) -join "`n")
        if ($devices -match [regex]::Escape($AdbTarget) + "\s+offline") {
            & $AdbExe disconnect $AdbTarget 2>$null | Out-Null
            Start-Sleep -Milliseconds 400
        }
        & $AdbExe connect $AdbTarget 2>$null | Out-Null
        $devices = ((& $AdbExe devices 2>$null) -join "`n")
        if ($devices -match [regex]::Escape($AdbTarget) + "\s+device" -or ($HostPort -eq 5555 -and $devices -match "emulator-5554\s+device")) {
            $effectiveTarget = if ($HostPort -eq 5555 -and $devices -match "emulator-5554\s+device") { "emulator-5554" } else { $AdbTarget }
            $boot1 = (((& $AdbExe -s $effectiveTarget shell getprop sys.boot_completed 2>$null) -join "") -replace "`0","").Trim()
            $boot2 = (((& $AdbExe -s $effectiveTarget shell getprop dev.bootcomplete 2>$null) -join "") -replace "`0","").Trim()
            if ($boot1 -eq "1" -or $boot2 -eq "1") {
                Write-Host "[+] Android boot completed and ADB is online!" -ForegroundColor Green
                return $true
            }
        }
        Start-Sleep -Seconds 1
    }
    Write-Host "[!] ADB connected, but Android is still initializing..." -ForegroundColor Yellow
    return $false
}

switch ($Action.ToLower()) {
    "start" {
        Write-Host "======================================================" -ForegroundColor Cyan
        Write-Host "  STARTING REDROID ACCOUNT $Account" -ForegroundColor Cyan
        Write-Host "======================================================" -ForegroundColor Cyan

        Ensure-DockerRunning

        # Check if container exists
        $containerExists = (Invoke-DockerCmd @("ps", "-a", "-q", "-f", "name=^/${ContainerName}$")).Trim()
        if ([string]::IsNullOrWhiteSpace($containerExists)) {
            Write-Host "[*] Creating persistent volume: $VolumeName" -ForegroundColor Cyan
            Invoke-DockerCmd @("volume", "create", $VolumeName) | Out-Null

            # Clone master template (redroid-account-01-data) with all apps & settings into the new brand volume
            $hasTemplate = (Invoke-DockerCmd @("volume", "ls", "-q", "-f", "name=^redroid-account-01-data$")).Trim()
            if (-not [string]::IsNullOrWhiteSpace($hasTemplate) -and $VolumeName -ne "redroid-account-01-data") {
                Write-Host "[*] Cloning master apps and settings template from redroid-01 to $VolumeName..." -ForegroundColor Cyan
                wsl.exe -d Ubuntu -u root --exec cp -au /var/lib/docker/volumes/redroid-account-01-data/_data/. /var/lib/docker/volumes/${VolumeName}/_data/ 2>$null | Out-Null
            }

            $targetImage = "redroid-instagram:ndk"
            $hasNdk = (Invoke-DockerCmd @("images", "-q", "redroid-instagram:ndk")).Trim()
            if ([string]::IsNullOrWhiteSpace($hasNdk)) {
                $targetImage = "redroid-instagram:latest"
            }

            $sndArgs = @()
            $hasSnd = (((wsl.exe -d Ubuntu -u root --exec bash -c "[ -d /dev/snd ] && echo HAS_SND" 2>$null) -join "") -replace "`0","").Trim()
            if ($hasSnd -eq "HAS_SND") {
                wsl.exe -d Ubuntu -u root --exec chmod -R 666 /dev/snd 2>$null | Out-Null
                $sndArgs = @("--device", "/dev/snd", "-v", "/dev/snd:/dev/snd")
            }

            Write-Host "[*] Creating and starting container: $ContainerName on port $HostPort using $targetImage..." -ForegroundColor Cyan
            $runArgs = @("run", "-d",
                "--name", $ContainerName,
                "--restart", "always",
                "--memory=1800m",
                "--memory-swap=1800m",
                "--privileged") + $sndArgs + @(
                "-v", "${VolumeName}:/data",
                "-p", "${HostPort}:5555",
                $targetImage,
                "androidboot.redroid_width=720",
                "androidboot.redroid_height=1280",
                "androidboot.redroid_dpi=320",
                "androidboot.redroid_fps=30",
                "androidboot.redroid_gpu_mode=guest",
                "androidboot.use_memfd=1",
                "androidboot.selinux=permissive",
                "ro.dalvik.vm.native.bridge=libndk_translation.so",
                "ro.enable.native.bridge.exec=1",
                "ro.product.cpu.abilist=x86_64,arm64-v8a,x86,armeabi-v7a,armeabi",
                "ro.product.cpu.abilist32=x86,armeabi-v7a,armeabi",
                "ro.product.cpu.abilist64=x86_64,arm64-v8a",
                "ro.dalvik.vm.isa.arm=x86",
                "ro.dalvik.vm.isa.arm64=x86_64",
                "ro.product.brand=google",
                "ro.product.model=Pixel 8 Pro",
                "ro.product.name=husky",
                "ro.product.device=husky",
                "ro.product.manufacturer=Google",
                "ro.build.fingerprint=google/husky/husky:14/UD1A.230803.041/10808477:user/release-keys",
                "ro.build.type=user",
                "ro.build.tags=release-keys"
            )
            Invoke-DockerCmd $runArgs | Out-Null
        } else {
            Write-Host "[*] Starting existing container: $ContainerName..." -ForegroundColor Cyan
            Invoke-DockerCmd @("start", $ContainerName) | Out-Null
        }

        Connect-Adb -MaxAttempts 30 | Out-Null

        # Configure Network NAT, Default Gateway, and DNS
        wsl.exe -d Ubuntu -u root --exec bash -c "sysctl -w net.ipv4.ip_forward=1 >/dev/null 2>&1; modprobe xt_MASQUERADE >/dev/null 2>&1; iptables -t nat -A POSTROUTING -s 172.17.0.0/16 -j MASQUERADE 2>/dev/null || true" | Out-Null
        Invoke-DockerCmd @("exec", $ContainerName, "ip", "route", "add", "default", "via", "172.17.0.1", "dev", "eth0") 2>$null | Out-Null
        Invoke-DockerCmd @("exec", $ContainerName, "setprop", "net.dns1", "8.8.8.8") 2>$null | Out-Null
        Invoke-DockerCmd @("exec", $ContainerName, "setprop", "net.dns2", "1.1.1.1") 2>$null | Out-Null
        Invoke-DockerCmd @("exec", $ContainerName, "settings", "put", "global", "captive_portal_mode", "0") 2>$null | Out-Null

        # Provisioning and disable crashing background apps
        Invoke-DockerCmd @("exec", $ContainerName, "settings", "put", "global", "setup_wizard_has_run", "1") 2>$null | Out-Null
        Invoke-DockerCmd @("exec", $ContainerName, "settings", "put", "secure", "user_setup_complete", "1") 2>$null | Out-Null
        Invoke-DockerCmd @("exec", $ContainerName, "settings", "put", "global", "device_provisioned", "1") 2>$null | Out-Null
        Invoke-DockerCmd @("exec", $ContainerName, "pm", "disable-user", "--user", "0", "com.google.android.setupwizard") 2>$null | Out-Null
        Invoke-DockerCmd @("exec", $ContainerName, "pm", "disable-user", "--user", "0", "com.google.android.apps.restore") 2>$null | Out-Null
        Invoke-DockerCmd @("exec", $ContainerName, "pm", "disable-user", "--user", "0", "com.google.android.tts") 2>$null | Out-Null
        Invoke-DockerCmd @("exec", $ContainerName, "pm", "disable-user", "--user", "0", "com.instagram.android") 2>$null | Out-Null
        Invoke-DockerCmd @("exec", $ContainerName, "pm", "disable-user", "--user", "0", "com.instander.android") 2>$null | Out-Null
        Invoke-DockerCmd @("exec", $ContainerName, "pm", "disable-user", "--user", "0", "com.facebook.katana") 2>$null | Out-Null
        Invoke-DockerCmd @("exec", $ContainerName, "pm", "disable-user", "--user", "0", "com.android.phone") 2>$null | Out-Null
        Invoke-DockerCmd @("exec", $ContainerName, "pm", "disable-user", "--user", "0", "com.android.smspush") 2>$null | Out-Null
        Invoke-DockerCmd @("exec", $ContainerName, "pm", "disable-user", "--user", "0", "com.android.printspooler") 2>$null | Out-Null
        Invoke-DockerCmd @("exec", $ContainerName, "pm", "disable-user", "--user", "0", "com.android.se") 2>$null | Out-Null

        # Keep screen awake and prevent timeout
        & $AdbExe -s $AdbTarget shell settings put system screen_off_timeout 2147483647 2>$null | Out-Null
        & $AdbExe -s $AdbTarget shell settings put global stay_on_while_plugged_in 3 2>$null | Out-Null

        Write-Host ""
        Write-Host "[+] Redroid Account $Account is ACTIVE!" -ForegroundColor Green
        Write-Host "    - Container:  $ContainerName"
        Write-Host "    - Volume:     $VolumeName (Persistent)"
        Write-Host "    - ADB Target: $AdbTarget"
        Write-Host "    - Resolution: 720x1280 @ 320 dpi (30 fps)"
    }

    "stop" {
        Write-Host "======================================================" -ForegroundColor Yellow
        Write-Host "  STOPPING REDROID ACCOUNT $Account" -ForegroundColor Yellow
        Write-Host "======================================================" -ForegroundColor Yellow

        & $AdbExe disconnect $AdbTarget 2>$null | Out-Null
        Write-Host "[*] Stopping container: $ContainerName..." -ForegroundColor Yellow
        Invoke-DockerCmd @("stop", $ContainerName) 2>$null | Out-Null
        Write-Host "[+] Redroid Account $Account STOPPED." -ForegroundColor Green
    }

    "restart" {
        & $MyInvocation.MyCommand.Path "stop" $Account
        Start-Sleep -Seconds 2
        & $MyInvocation.MyCommand.Path "start" $Account
    }

    "status" {
        Write-Host "======================================================" -ForegroundColor Cyan
        Write-Host "  STATUS FOR REDROID ACCOUNT $Account" -ForegroundColor Cyan
        Write-Host "======================================================" -ForegroundColor Cyan

        Ensure-DockerRunning

        $containerInfo = (Invoke-DockerCmd @("ps", "-a", "-f", "name=^/${ContainerName}$", "--format", "{{.Status}}")).Trim()
        if ([string]::IsNullOrWhiteSpace($containerInfo)) {
            Write-Host "Container State: NOT CREATED" -ForegroundColor DarkGray
            return
        }

        Write-Host "Container State: $containerInfo"
        if ($containerInfo -like "*Up*") {
            & $AdbExe connect $AdbTarget 2>$null | Out-Null
            $androidVer = (((& $AdbExe -s $AdbTarget shell getprop ro.build.version.release 2>$null) -join "") -replace "`0","").Trim()
            $screenSize = (((& $AdbExe -s $AdbTarget shell wm size 2>$null) -join " ") -replace "`0","").Trim()
            $screenDensity = (((& $AdbExe -s $AdbTarget shell wm density 2>$null) -join " ") -replace "`0","").Trim()
            $bootComplete = (((& $AdbExe -s $AdbTarget shell getprop sys.boot_completed 2>$null) -join "") -replace "`0","").Trim()

            Write-Host "Android Version: $androidVer"
            Write-Host "Boot Completed:  $bootComplete"
            Write-Host "Display Size:    $screenSize"
            Write-Host "Display Density: $screenDensity"
            Write-Host "ADB Connection:  $AdbTarget (ONLINE)" -ForegroundColor Green
        } else {
            Write-Host "ADB Connection:  OFFLINE" -ForegroundColor Yellow
        }
    }

    "scrcpy" {
        Ensure-DockerRunning
        $isRunning = (Invoke-DockerCmd @("ps", "-q", "-f", "name=^/${ContainerName}$", "-f", "status=running")).Trim()
        if ([string]::IsNullOrWhiteSpace($isRunning)) {
            Write-Host "[*] Container $ContainerName is not running. Starting it now..." -ForegroundColor Cyan
            & $MyInvocation.MyCommand.Path "start" $Account
        }
        Connect-Adb -MaxAttempts 20 | Out-Null
        Ensure-NetworkRouting
        Write-Host "[*] Launching scrcpy visual interface for Account $Account ($AdbTarget)..." -ForegroundColor Green
        & $ScrcpyExe -s $AdbTarget --force-adb-forward --video-codec=h264 --video-encoder=OMX.google.h264.encoder --no-audio --video-bit-rate=4M --max-fps=30 --stay-awake --window-title "Redroid Account $Account ($AdbTarget)"
    }

    "adb" {
        if (-not $ExtraArgs) {
            Write-Host "Usage: .\redroid.ps1 adb $Account <command>" -ForegroundColor Yellow
            return
        }
        Ensure-DockerRunning
        & $AdbExe connect $AdbTarget 2>$null | Out-Null
        $cmdLine = $ExtraArgs -join " "
        cmd /c "`"$AdbExe`" -s $AdbTarget $cmdLine"
    }

    "health" {
        $healthScript = Join-Path $PSScriptRoot "scripts\utils\redroid-health.ps1"
        if (-not (Test-Path $healthScript)) {
            $healthScript = Join-Path $PSScriptRoot "redroid-health.ps1"
        }
        & $healthScript $Account
    }

    "help" {
        Get-Help $MyInvocation.MyCommand.Path -Detailed
    }
}
