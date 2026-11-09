import os, platform, re, time
from pathlib import Path

PROC = Path("/proc")
SYS = Path("/sys")
DMI = SYS / "class/dmi/id"

def _read(path, default=None):
    try:
        return Path(path).read_text().strip()
    except (OSError, UnicodeError):
        return default

class SystemInventoryProvider:
    """Slow-changing, read-only Linux system inventory."""
    def collect(self):
        cpu = {}
        try:
            blocks = (PROC / "cpuinfo").read_text().split("\n\n")
            for block in blocks:
                row = dict(line.split(":", 1) for line in block.splitlines() if ":" in line)
                if row:
                    for key in ("vendor_id", "model name", "cpu family", "model", "stepping", "microcode"):
                        if key in row:
                            cpu[key] = row[key].strip()
                    if "model name" in row:
                        break
        except OSError:
            pass
        logical = os.cpu_count()
        core_ids = set()
        try:
            for block in (PROC / "cpuinfo").read_text().split("\n\n"):
                row = dict(line.split(":", 1) for line in block.splitlines() if ":" in line)
                if "physical id" in row and "core id" in row:
                    core_ids.add((row["physical id"].strip(), row["core id"].strip()))
        except OSError:
            pass
        numa = sorted(p.name for p in (SYS / "devices/system/node").glob("node[0-9]*"))
        os_release = {}
        try:
            for line in Path("/etc/os-release").read_text().splitlines():
                if "=" in line:
                    k, v = line.split("=", 1)
                    os_release[k] = v.strip().strip('"')
        except OSError:
            pass
        board = {k: _read(DMI / name) for k, name in {
            "manufacturer": "board_vendor", "product": "board_name",
            "version": "board_version", "bios_vendor": "bios_vendor",
            "bios_version": "bios_version", "bios_date": "bios_date"
        }.items()}
        board = {k: v for k, v in board.items() if v}
        disks = []
        for p in sorted((SYS / "block").glob("*")):
            name = p.name
            if name.startswith(("loop", "ram", "zram", "dm-", "md")):
                continue
            sectors = _read(p / "size")
            if not sectors or not sectors.isdigit():
                continue
            disks.append({"name": name, "model": _read(p / "device/model"),
                          "size_bytes": int(sectors) * 512,
                          "rotational": _read(p / "queue/rotational"),
                          "removable": _read(p / "removable")})
        mounts = []
        try:
            for line in (PROC / "mounts").read_text().splitlines():
                cols = line.split()
                if len(cols) >= 3 and (cols[0].startswith("/dev/") or cols[1] == "/"):
                    mounts.append({"device": cols[0], "mountpoint": cols[1], "filesystem": cols[2]})
        except OSError:
            pass
        interfaces = []
        for p in sorted((SYS / "class/net").glob("*")):
            if p.name == "lo":
                continue
            speed = _read(p / "speed")
            interfaces.append({"name": p.name, "state": _read(p / "operstate"),
                               "mtu": _read(p / "mtu"),
                               "speed_mbps": int(speed) if speed and speed.isdigit() and int(speed) > 0 else None})
        try:
            uptime = float((PROC / "uptime").read_text().split()[0])
        except (OSError, ValueError, IndexError):
            uptime = None
        return {
            "os": {"name": os_release.get("PRETTY_NAME", platform.platform()),
                   "id": os_release.get("ID"), "version": os_release.get("VERSION_ID"),
                   "kernel": platform.release(), "architecture": platform.machine()},
            "host": {"hostname": platform.node(), "uptime_seconds": uptime},
            "cpu": {"model": cpu.get("model name"), "vendor": cpu.get("vendor_id"),
                    "family": cpu.get("cpu family"), "model_id": cpu.get("model"),
                    "stepping": cpu.get("stepping"), "microcode": cpu.get("microcode"),
                    "logical_processors": logical, "physical_cores": len(core_ids) or None,
                    "online_cpus": _read(SYS / "devices/system/cpu/online"),
                    "numa_nodes": numa},
            "motherboard": board, "storage_devices": disks,
            "mounts": mounts, "network_interfaces": interfaces
        }

class LinuxMemoryProvider:
    """Detailed host RAM and top-process accounting from procfs."""
    FIELDS = {
        "MemTotal": "total", "MemFree": "free", "MemAvailable": "available",
        "Buffers": "buffers", "Cached": "cached", "SwapCached": "swap_cached",
        "Active": "active", "Inactive": "inactive", "Active(anon)": "active_anon",
        "Inactive(anon)": "inactive_anon", "Active(file)": "active_file",
        "Inactive(file)": "inactive_file", "Unevictable": "unevictable",
        "Mlocked": "mlocked", "SwapTotal": "swap_total", "SwapFree": "swap_free",
        "Dirty": "dirty", "Writeback": "writeback", "AnonPages": "anonymous",
        "Mapped": "mapped", "Shmem": "shared_memory", "Slab": "slab",
        "SReclaimable": "slab_reclaimable", "SUnreclaim": "slab_unreclaimable",
        "KernelStack": "kernel_stack", "PageTables": "page_tables",
        "Committed_AS": "committed", "CommitLimit": "commit_limit",
        "VmallocTotal": "vmalloc_total", "VmallocUsed": "vmalloc_used",
        "HugePages_Total": "hugepages_total", "HugePages_Free": "hugepages_free",
        "Hugepagesize": "hugepage_size"
    }
    def __init__(self, process_limit=20, pss_limit=12, refresh_seconds=5):
        self.process_limit, self.pss_limit = process_limit, pss_limit
        self.refresh_seconds = refresh_seconds
        self.cached = None
        self.cached_at = 0.0

    def _processes(self):
        rows = []
        for p in PROC.iterdir():
            if not p.name.isdigit():
                continue
            try:
                status = {}
                for line in (p / "status").read_text().splitlines():
                    if ":" in line:
                        k, v = line.split(":", 1)
                        status[k] = v.strip()
                def kb(key):
                    value = status.get(key, "0").split()[0]
                    return int(value) * 1024
                pid = int(p.name)
                try:
                    cmd = (p / "cmdline").read_bytes().replace(b"\x00", b" ").decode("utf-8", "replace").strip()
                except OSError:
                    cmd = ""
                row = {"pid": pid, "name": status.get("Name", "unknown"),
                       "cmdline": cmd or None,
                       "rss_bytes": kb("VmRSS"), "rss_anon_bytes": kb("RssAnon"),
                       "rss_file_bytes": kb("RssFile"), "rss_shmem_bytes": kb("RssShmem"),
                       "swap_bytes": kb("VmSwap"), "pss_bytes": None,
                       "private_bytes": None, "shared_bytes": None,
                       "identity_start_time": None}
                try:
                    stat = (p / "stat").read_text().split(")", 1)[1].split()
                    row["identity_start_time"] = stat[19]
                except (OSError, IndexError, ValueError):
                    pass
                rows.append(row)
            except (OSError, ValueError, IndexError, PermissionError):
                continue
        rows.sort(key=lambda x: x["rss_bytes"], reverse=True)
        for row in rows[:self.pss_limit]:
            try:
                values = {}
                for line in (PROC / str(row["pid"]) / "smaps_rollup").read_text().splitlines():
                    if ":" in line:
                        k, v = line.split(":", 1)
                        parts = v.split()
                        if parts and parts[0].isdigit():
                            values[k] = int(parts[0]) * 1024
                row["pss_bytes"] = values.get("Pss")
                row["private_bytes"] = values.get("Private_Clean", 0) + values.get("Private_Dirty", 0)
                row["shared_bytes"] = values.get("Shared_Clean", 0) + values.get("Shared_Dirty", 0)
            except (OSError, ValueError, PermissionError):
                pass
        return rows[:self.process_limit]

    def collect(self):
        now = time.monotonic()
        if self.cached is None or now - self.cached_at >= self.refresh_seconds:
            self.cached = self._processes()
            self.cached_at = now
        raw = {}
        try:
            for line in (PROC / "meminfo").read_text().splitlines():
                if ":" not in line:
                    continue
                key, value = line.split(":", 1)
                parts = value.split()
                if parts and parts[0].isdigit():
                    raw[key] = int(parts[0]) * (1024 if len(parts) > 1 and parts[1] == "kB" else 1)
        except OSError:
            pass
        memory = {self.FIELDS[k]: v for k, v in raw.items() if k in self.FIELDS}
        total, available = memory.get("total"), memory.get("available")
        if total is not None and available is not None:
            memory["used_estimate"] = max(0, total - available)
            memory["used_estimate_semantics"] = "MemTotal - MemAvailable; derived estimate, not sum of exclusive buckets"
        if memory.get("swap_total") is not None and memory.get("swap_free") is not None:
            memory["swap_used"] = max(0, memory["swap_total"] - memory["swap_free"])
        return {"state": "ACTIVE" if memory else "DEGRADED", "unit": "bytes",
                "fields": memory, "processes": self.cached or [],
                "processes_limit": self.process_limit,
                "processes_semantics": "Top processes by VmRSS; cmdline is the exact command line from /proc/<pid>/cmdline (empty for kernel threads); PSS/private/shared read from smaps_rollup for the top subset. Permission or process-exit races can leave fields unavailable."}

class AmdRocmProcessProvider:
    """Best-effort per-process GPU memory attribution via AMD SMI process JSON."""
    def __init__(self, refresh_seconds=5):
        self.refresh_seconds = refresh_seconds
        self.cached_at = 0.0
        self.cached = None
    @staticmethod
    def _number(value):
        if isinstance(value, (int, float)) and not isinstance(value, bool):
            return value, "bytes"
        if isinstance(value, str):
            m = re.fullmatch(r"\s*([0-9]+(?:\.[0-9]+)?)\s*(B|KB|MB|GB|KiB|MiB|GiB)\s*", value, re.I)
            if m:
                n, unit = float(m.group(1)), m.group(2).lower()
                scale = {"b":1,"kb":1000,"mb":1000**2,"gb":1000**3,
                         "kib":1024,"mib":1024**2,"gib":1024**3}[unit]
                return int(n * scale), "bytes"
        return None, None
    def collect(self):
        now = time.monotonic()
        if self.cached is not None and now - self.cached_at < self.refresh_seconds:
            return self.cached
        result = self._collect_uncached()
        self.cached, self.cached_at = result, now
        return result
    def _collect_uncached(self):
        import shutil, subprocess, json
        cmd = shutil.which("amd-smi")
        if not cmd:
            return {"state": "UNAVAILABLE", "processes": [], "error": "amd-smi process telemetry unavailable"}
        try:
            result = subprocess.run([cmd, "process", "--json"], capture_output=True,
                                    text=True, timeout=3, check=False)
            if result.returncode:
                raise RuntimeError((result.stderr or "amd-smi process failed")[:240])
            payload = json.loads(result.stdout)
            records = []
            def find_value(obj, keys):
                if isinstance(obj, dict):
                    for k, v in obj.items():
                        if k.lower() in keys:
                            return v
                    for v in obj.values():
                        found = find_value(v, keys)
                        if found is not None:
                            return found
                return None
            def walk(node, gpu=None):
                if isinstance(node, list):
                    for item in node:
                        walk(item, gpu)
                elif isinstance(node, dict):
                    lowered = {str(k).lower(): v for k, v in node.items()}
                    local_gpu = lowered.get("gpu", lowered.get("gpu_index", gpu))
                    pid = lowered.get("pid", lowered.get("process_id"))
                    if pid is not None:
                        memory = lowered.get("memory_usage", node)
                        vram = find_value(memory, {"vram_mem", "vram_usage", "vram"})
                        gtt = find_value(memory, {"gtt_mem", "gtt_usage"})
                        cpu_mem = find_value(memory, {"cpu_mem"})
                        vram_bytes, _ = self._number(vram)
                        gtt_bytes, _ = self._number(gtt)
                        cpu_bytes, _ = self._number(cpu_mem)
                        records.append({"gpu_index": local_gpu, "pid": int(pid),
                                        "name": lowered.get("name", lowered.get("process_name")),
                                        "vram_bytes": vram_bytes, "gtt_bytes": gtt_bytes,
                                        "cpu_memory_bytes": cpu_bytes,
                                        "source": "amd-smi process --json",
                                        "unit": "bytes" if vram_bytes is not None else None})
                    for value in node.values():
                        if isinstance(value, (dict, list)):
                            walk(value, local_gpu)
            walk(payload)
            unique = {(str(x["gpu_index"]), x["pid"]): x for x in records}
            return {"state": "ACTIVE", "processes": list(unique.values()),
                    "semantics": "Per-process VRAM/GTT from AMD SMI; process totals are not expected to sum to device-wide VRAM usage."}
        except Exception as e:
            return {"state": "DEGRADED", "processes": [], "error": str(e)}
