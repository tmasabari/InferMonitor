# Phase 2 — System inventory and memory accounting

## Delivered scope
- Static Linux inventory: distribution, kernel, architecture, CPU model/topology, NUMA nodes, motherboard/BIOS where exposed by sysfs DMI, block devices, mounted filesystems, network interface state/speed, uptime.
- Host RAM breakdown from /proc/meminfo: total/free/available, buffers, page cache, active/inactive anonymous and file-backed memory, shared memory, slab, kernel stacks, page tables, dirty/writeback, swap and huge-page counters when present.
- Host process memory: top 20 processes by RSS, the exact command line (`/proc/<pid>/cmdline`), RSS anonymous/file/shared breakdown, swap, and PSS/private/shared from smaps_rollup for the top 12. Process scans are cached for five seconds to limit overhead.
- GPU process attribution: best-effort amd-smi process --json parser for per-process VRAM/GTT. It preserves unavailable values and does not assume that process totals equal device-wide allocation.
- Static inventory refreshes every 30 seconds; telemetry remains sampled with the existing collector.

## Memory semantics
- MemAvailable is the kernel's estimate of memory available to new applications without swapping. It is not the same as MemFree.
- used_estimate = MemTotal - MemAvailable is explicitly labelled as a derived estimate. Cached, active, anonymous, slab and other meminfo buckets overlap and must not be added together as an exclusive partition.
- RSS includes resident anonymous, file-backed and shared-memory pages. PSS apportions shared pages across processes and is therefore more useful for estimating proportional process footprint. smaps_rollup is read only for a bounded top-process subset.
- AMD SMI documents per-process memory fields (including VRAM and GTT) and notes that per-process sums are not expected to equal device-wide VRAM. Device-level VRAM remains authoritative for total/used capacity; process attribution is an explanatory breakdown, not a reconciliation equation.
- AMD SMI may require elevated permissions for process names. InferMonitor does not request root privileges or use sudo.

## Known limitations
- DMI fields, storage topology, NUMA and network speed are platform/permission dependent.
- Process RSS is sampled from procfs and can race process exit; PSS can be unavailable for protected processes.
- GPU process JSON varies by AMD SMI version. The parser is defensive, but the installed ROCm 7.16 JSON output must be captured and checked on the target workstation.
- No claim is made that GTT is dedicated VRAM. No GPU memory is attributed to a PID unless AMD SMI reports it.
- No cgroup/container memory accounting, per-allocation GPU tracing, pinned-host allocation tracing, or memory attribution to individual model tensors in this phase.
