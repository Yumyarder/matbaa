"""Reading from, and adding to, a Kindle connected by cable.

A current Kindle is not a drive on Windows: it is a "portable device"
(MTP), reachable through the shell's namespace 17 ("This PC"). Files are
copied off the device into a scratch folder (My Clippings.txt, the
vocabulary of looked-up words), and the few files Matbaa gives the Kindle
(its typefaces, a dictionary) are copied onto it. Nothing on the Kindle is
ever moved or deleted, and nothing is overwritten but a file Matbaa itself
put there and has made again (its dictionary); a file of the same name
otherwise is left as it is.

A Kindle that is plugged in but locked shows up as a device with nothing
inside it; that is told apart from "no Kindle", because the remedy is
different (unlock it, not plug it in).

MATBAA_KINDLE_DIR names a folder that stands in for the Kindle's storage:
the tests use it, and so can a Kindle that does mount as a drive.
"""
from __future__ import annotations

import os
import shutil
import subprocess
import sys
import tempfile
import time
from dataclasses import dataclass
from typing import Dict, List, Optional, Tuple

LOCAL_ENV = "MATBAA_KINDLE_DIR"

# What the reader is told for each state the device can be in.
MESSAGES = {
    "NO_KINDLE": "Kindle bulunamadı. Kabloyla bağlayın.",
    "LOCKED": "Kindle bağlı ama içi görünmüyor: Kindle'ın kilidini açın. Ekranda bilgisayara bağlı "
              "olduğunu söyleyen yazı çıkınca tekrar deneyin.",
    "NO_DOCS": "Kindle bağlı ama 'documents' klasörü görünmüyor; kabloyu çıkarıp yeniden takın.",
    "NO_FILE": "Kindle'da My Clippings.txt yok — henüz hiç vurgu yapılmamış olabilir.",
    "TIMEOUT": "Kindle'dan dosya alınamadı (zaman aşımı); kabloyu çıkarıp yeniden takıp deneyin.",
}

# the device and its storage, the same walk for every script
_DEVICE = r"""
$sh = New-Object -ComObject Shell.Application
$k = $sh.NameSpace(17).Items() | Where-Object { $_.Name -like '*Kindle*' } | Select-Object -First 1
if (-not $k) { Write-Output 'NO_KINDLE'; exit 0 }
$storage = $null
try { $storage = $k.GetFolder.Items() | Select-Object -First 1 } catch {}
if (-not $storage) { Write-Output 'LOCKED'; exit 0 }
function Walk($parts, [bool]$make) {
  $folder = $storage.GetFolder
  foreach ($p in $parts) {
    if (-not $p) { continue }
    $it = $folder.Items() | Where-Object { $_.Name -eq $p } | Select-Object -First 1
    if (-not $it -and $make) {
      $folder.NewFolder($p)
      for ($n = 0; $n -lt 20 -and -not $it; $n++) {
        Start-Sleep -Milliseconds 300
        $it = $folder.Items() | Where-Object { $_.Name -eq $p } | Select-Object -First 1
      }
    }
    if (-not $it) { return $null }
    $folder = $it.GetFolder
  }
  return $folder
}
function Parent($parts) { if ($parts.Length -gt 1) { return $parts[0..($parts.Length - 2)] } return @() }
"""

_PROBE = _DEVICE + r"""
$docs = $null
try { $docs = Walk @('documents') $false } catch {}
if (-not $docs) { Write-Output 'NO_DOCS'; exit 0 }
Write-Output 'READY'
"""

_LIST = _DEVICE + r"""
$f = Walk ($args[0] -split '/') $false
if (-not $f) { Write-Output 'NO_PATH'; exit 0 }
foreach ($it in @($f.Items())) {
  Write-Output ("ITEM`t" + $it.Name + "`t" + $it.ExtendedProperty('System.Size') + "`t" + $it.IsFolder)
}
Write-Output 'READY'
"""

_GET = _DEVICE + r"""
$parts = $args[0] -split '/'
$dest = $args[1]
$name = $parts[-1]
$f = Walk (Parent $parts) $false
if (-not $f) { Write-Output 'NO_PATH'; exit 0 }
$it = $f.Items() | Where-Object { $_.Name -eq $name } | Select-Object -First 1
if (-not $it) { Write-Output 'NO_FILE'; exit 0 }
$size = [int64]$it.ExtendedProperty('System.Size')
$sh.NameSpace($dest).CopyHere($it, 16)
$out = Join-Path $dest $name
for ($n = 0; $n -lt 1200; $n++) {
  Start-Sleep -Milliseconds 500
  if (Test-Path -LiteralPath $out) {
    $now = (Get-Item -LiteralPath $out).Length
    if ($now -eq $size) { Write-Output 'OK'; exit 0 }
    if ($size -le 0) {
      Start-Sleep -Milliseconds 700
      if ((Get-Item -LiteralPath $out).Length -eq $now) { Write-Output 'OK'; exit 0 }
    }
  }
}
Write-Output 'TIMEOUT'
"""

_PUT = _DEVICE + r"""
$f = Walk ($args[0] -split '/') $true
if (-not $f) { Write-Output 'NO_PATH'; exit 0 }
$replace = @($args[1] -split '\|')
for ($i = 2; $i -lt $args.Length; $i++) {
  $src = $args[$i]
  $name = [System.IO.Path]::GetFileName($src)
  $size = (Get-Item -LiteralPath $src).Length
  $have = $f.Items() | Where-Object { $_.Name -eq $name } | Select-Object -First 1
  if ($have -and ($replace -notcontains $name)) { Write-Output ("SKIP`t" + $name); continue }
  if ($have -and [int64]$have.ExtendedProperty('System.Size') -eq $size) { Write-Output ("SAME`t" + $name); continue }
  # 16: answer "yes to all", so a file Matbaa itself put there is replaced without a dialog
  $f.CopyHere($src, 16)
  $done = $false
  for ($n = 0; $n -lt 1200 -and -not $done; $n++) {
    Start-Sleep -Milliseconds 500
    $it = $f.Items() | Where-Object { $_.Name -eq $name } | Select-Object -First 1
    if ($it -and [int64]$it.ExtendedProperty('System.Size') -eq $size) { $done = $true }
  }
  if ($done) { Write-Output ("OK`t" + $name) } else { Write-Output ("TIMEOUT`t" + $name) }
}
Write-Output 'READY'
"""

DEVICE_STATES = ("NO_KINDLE", "LOCKED", "NO_DOCS")


class KindleNotFound(Exception):
    pass


@dataclass
class Item:
    name: str
    size: int
    folder: bool


def _local() -> Optional[str]:
    root = os.environ.get(LOCAL_ENV, "").strip()
    return root or None


def _run(script_text: str, *args: str, timeout: int = 90) -> Tuple[List[str], str]:
    """The script's output lines (the last is its status) and its errors."""
    folder = tempfile.mkdtemp(prefix="matbaa-kindle-")
    script = os.path.join(folder, "kindle.ps1")
    with open(script, "w", encoding="utf-8-sig") as f:
        f.write(script_text)
    out = subprocess.run(["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-STA", "-File", script, *args],
                         capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=timeout)
    lines = [line.strip() for line in (out.stdout or "").splitlines() if line.strip()]
    return lines, (out.stderr or "")


def _device_only() -> None:
    if sys.platform != "win32":
        raise KindleNotFound("Kindle'a doğrudan erişim şimdilik yalnız Windows'ta.")


def _raise_for(status: str, err: str = "") -> None:
    if status in MESSAGES:
        raise KindleNotFound(MESSAGES[status])
    if status != "READY" and status != "OK":
        raise KindleNotFound("Kindle'a erişilemedi" + (f": {err.strip()[:200]}" if err.strip() else "."))


def state() -> str:
    """What the plugged-in Kindle allows right now: READY, LOCKED, NO_DOCS
    or NO_KINDLE (a quick look, nothing copied)."""
    root = _local()
    if root:
        if not os.path.isdir(root):
            return "NO_KINDLE"
        return "READY" if os.path.isdir(os.path.join(root, "documents")) else "NO_DOCS"
    if sys.platform != "win32":
        return "NO_KINDLE"
    try:
        lines, _ = _run(_PROBE, timeout=20)
    except Exception:  # noqa: BLE001
        return "NO_KINDLE"
    status = lines[-1] if lines else ""
    return status if status in ("READY", "LOCKED", "NO_DOCS") else "NO_KINDLE"


def connected() -> bool:
    return state() != "NO_KINDLE"


def list_folder(path: str) -> Optional[List[Item]]:
    """What a folder on the Kindle holds ("fonts", "documents/dictionaries"),
    or None when there is no such folder."""
    root = _local()
    if root:
        if not os.path.isdir(root):
            raise KindleNotFound(MESSAGES["NO_KINDLE"])
        full = os.path.join(root, *path.split("/"))
        if not os.path.isdir(full):
            return None
        return [Item(n, os.path.getsize(os.path.join(full, n)) if os.path.isfile(os.path.join(full, n)) else 0,
                     os.path.isdir(os.path.join(full, n))) for n in sorted(os.listdir(full))]
    _device_only()
    lines, err = _run(_LIST, path, timeout=60)
    status = lines[-1] if lines else ""
    if status == "NO_PATH":
        return None
    _raise_for(status, err)
    items = []
    for line in lines[:-1]:
        parts = line.split("\t")
        if len(parts) == 4 and parts[0] == "ITEM":
            items.append(Item(parts[1], int(parts[2]) if parts[2].isdigit() else 0, parts[3] == "True"))
    return items


def fetch_file(path: str) -> str:
    """A copy of one file on the Kindle ("system/vocabulary/vocab.db"), in a
    scratch folder; its local path."""
    dest = tempfile.mkdtemp(prefix="matbaa-kindle-")
    name = path.split("/")[-1]
    out = os.path.join(dest, name)
    root = _local()
    if root:
        if not os.path.isdir(root):
            raise KindleNotFound(MESSAGES["NO_KINDLE"])
        src = os.path.join(root, *path.split("/"))
        if not os.path.isfile(src):
            raise FileNotFoundError(path)
        shutil.copyfile(src, out)
        return out
    _device_only()
    lines, err = _run(_GET, path, dest, timeout=660)
    status = lines[-1] if lines else ""
    if status in ("NO_PATH", "NO_FILE"):
        raise FileNotFoundError(path)
    _raise_for(status, err)
    for _ in range(10):
        if os.path.exists(out):
            return out
        time.sleep(0.3)
    raise KindleNotFound("Kindle'dan dosya alınamadı" + (f": {err.strip()[:200]}" if err.strip() else "."))


def fetch_clippings() -> bytes:
    """The connected Kindle's My Clippings.txt."""
    if not _local() and sys.platform != "win32":
        raise KindleNotFound("Kindle'dan doğrudan okuma şimdilik yalnız Windows'ta; dosyayı yükleyin.")
    if state() == "NO_DOCS":
        raise KindleNotFound(MESSAGES["NO_DOCS"])
    try:
        path = fetch_file("documents/My Clippings.txt")
    except FileNotFoundError:
        raise KindleNotFound(MESSAGES["NO_FILE"]) from None
    with open(path, "rb") as f:
        return f.read()


def put_files(folder: str, files: List[str], replace: Tuple[str, ...] = ()) -> Dict[str, str]:
    """Copy `files` into `folder` on the Kindle (made if missing): file name
    -> OK, SKIP (one of that name is already there, left untouched),
    SAME (already there, the same size) or TIMEOUT. A name in `replace` — a
    file Matbaa itself put there, made again — takes the place of the old
    one; nothing else on the Kindle is ever overwritten."""
    root = _local()
    if root:
        if not os.path.isdir(root):
            raise KindleNotFound(MESSAGES["NO_KINDLE"])
        full = os.path.join(root, *folder.split("/"))
        os.makedirs(full, exist_ok=True)
        done = {}
        for src in files:
            name = os.path.basename(src)
            target = os.path.join(full, name)
            if os.path.exists(target) and name not in replace:
                done[name] = "SKIP"
                continue
            if os.path.exists(target) and os.path.getsize(target) == os.path.getsize(src):
                done[name] = "SAME"
                continue
            shutil.copyfile(src, target)
            done[name] = "OK"
        return done
    _device_only()
    if not files:
        return {}
    timeout = 120 + 600 * len(files)
    lines, err = _run(_PUT, folder, "|".join(replace) or "-", *[os.path.abspath(f) for f in files], timeout=timeout)
    status = lines[-1] if lines else ""
    _raise_for("READY" if status == "READY" else status, err)
    done = {}
    for line in lines[:-1]:
        parts = line.split("\t")
        if len(parts) == 2 and parts[0] in ("OK", "SKIP", "SAME", "TIMEOUT"):
            done[parts[1]] = parts[0]
    return done
