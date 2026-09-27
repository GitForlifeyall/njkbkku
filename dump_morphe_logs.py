#!/usr/bin/env python3
"""
Dump and stream logcat logs for Morphe YouTube (app.morphe.android.youtube) and MicroG (app.revanced.android.gms).
Usage:
    python dump_morphe_logs.py              # Dumps recent 500 relevant log lines
    python dump_morphe_logs.py -f           # Follow / stream live logs
    python dump_morphe_logs.py --all        # Dump entire buffer unfiltered
    python dump_morphe_logs.py --clear      # Clear logcat buffer
"""

import sys
import os
import subprocess
import argparse
import re

def resolve_adb_target(account="01"):
    port = 5800 + int(account)
    # Check if WSL IP is reachable
    try:
        wsl_ip_raw = subprocess.check_output(
            ["wsl", "-d", "Ubuntu", "-u", "root", "-e", "hostname", "-I"],
            text=True, stderr=subprocess.DEVNULL
        ).strip().split()
        if wsl_ip_raw:
            target = f"{wsl_ip_raw[0]}:{port}"
            res = subprocess.run(["adb", "connect", target], capture_output=True, text=True)
            if "connected" in res.stdout or "already" in res.stdout:
                return target
    except Exception:
        pass
    
    target = f"127.0.0.1:{port}"
    subprocess.run(["adb", "connect", target], capture_output=True, text=True)
    return target

def get_morphe_pids(target):
    try:
        out = subprocess.check_output(
            ["adb", "-s", target, "shell", "pidof", "app.morphe.android.youtube", "app.revanced.android.gms", "audioserver"],
            text=True, stderr=subprocess.DEVNULL
        ).strip().split()
        return set(out)
    except Exception:
        return set()

def main():
    parser = argparse.ArgumentParser(description="Dump and stream Morphe YouTube logs")
    parser.add_argument("-a", "--account", default="01", help="Redroid account (default: 01)")
    parser.add_argument("-f", "--follow", action="store_true", help="Stream logs live (continuous)")
    parser.add_argument("-n", "--lines", type=int, default=500, help="Number of recent log lines to inspect (default: 500)")
    parser.add_argument("--all", action="store_true", help="Do not filter by package name/keywords")
    parser.add_argument("--clear", action="store_true", help="Clear logcat buffer and exit")
    parser.add_argument("-o", "--output", help="Save dumped logs to a file")
    args = parser.parse_args()

    target = resolve_adb_target(args.account)
    print(f"[*] Target ADB Device: {target}")

    if args.clear:
        subprocess.run(["adb", "-s", target, "logcat", "-c"])
        print("[+] Logcat buffer cleared.")
        return

    pids = get_morphe_pids(target)
    if pids:
        print(f"[*] Active Target PIDs: {', '.join(pids)}")

    keywords = [
        "app.morphe.android.youtube",
        "app.revanced.android.gms",
        "AndroidRuntime",
        "FATAL",
        "ExoPlayer",
        "AudioTrack",
        "audioserver",
        "audio_hw",
        "MediaCodec",
        "Shorts",
        "CreateShortEngine"
    ]
    pattern = re.compile("|".join(keywords), re.IGNORECASE)

    cmd = ["adb", "-s", target, "logcat", "-v", "time"]
    if not args.follow:
        cmd.extend(["-d", "-t", str(args.lines)])

    out_file = None
    if args.output:
        out_file = open(args.output, "w", encoding="utf-8", errors="replace")

    print(f"[*] {'Streaming' if args.follow else 'Dumping'} Morphe logs (Filter: {'ALL' if args.all else 'Morphe/YouTube/Audio'})...\n" + "="*70)

    try:
        proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, encoding="utf-8", errors="replace")
        for line in proc.stdout:
            is_match = args.all or pattern.search(line)
            if not is_match and pids:
                # Check if PID is in line
                for pid in pids:
                    if f"({pid}):" in line or f" {pid} " in line:
                        is_match = True
                        break
            
            if is_match:
                sys.stdout.write(line)
                sys.stdout.flush()
                if out_file:
                    out_file.write(line)
                    out_file.flush()
    except KeyboardInterrupt:
        print("\n[*] Stopped log streaming.")
    finally:
        if out_file:
            out_file.close()
            print(f"[+] Logs saved to {args.output}")

if __name__ == "__main__":
    main()
