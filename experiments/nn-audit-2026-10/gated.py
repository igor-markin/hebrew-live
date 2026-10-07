"""Gates for timing runs on a shared Mac: CPU idle and memory pressure.

Other apps (and other sessions) skew timings, and a model job on a 16 GB machine that is already
swapping makes everything slower, the job and the user's apps alike. Heavy jobs therefore start
only when the CPU is idle AND memory pressure is normal, and they never run two at once.
"""
import re
import subprocess
import time

MIN_FREE_PERCENT = 40      # `memory_pressure`: share of memory free or reclaimable
NORMAL_PRESSURE_LEVEL = 1  # kern.memorystatus_vm_pressure_level: 1 normal, 2 warning, 4 critical


def idle():
    out = subprocess.run(['top', '-l', '2', '-n', '0', '-s', '1'], capture_output=True, text=True).stdout
    m = re.findall(r'([\d.]+)% idle', out)
    return float(m[-1]) if m else 0.


def memory():
    """(pressure level, free percent); (None, None) when it cannot be read."""
    level = subprocess.run(['sysctl', '-n', 'kern.memorystatus_vm_pressure_level'], capture_output=True, text=True).stdout.strip()
    text = subprocess.run(['memory_pressure'], capture_output=True, text=True).stdout
    free = re.search(r'free percentage: (\d+)%', text)
    return (int(level) if level.isdigit() else None), (int(free.group(1)) if free else None)


def memory_ok():
    level, free = memory()
    return level == NORMAL_PRESSURE_LEVEL and free is not None and free >= MIN_FREE_PERCENT


def wait_until_quiet(need_idle=60, timeout=3600, poll=20):
    """Block until CPU is idle and memory pressure is normal; False if that never happens."""
    end = time.time() + timeout
    while time.time() < end:
        if memory_ok() and idle() >= need_idle:
            return True
        time.sleep(poll)
    return False


def run_gated(round_fn, want=8, budget=420, need=62):
    """round_fn() -> dict of timings; a round counts only if CPU idle >= need and memory is
    fine before and after."""
    acc = []
    tried = 0
    t_end = time.time() + budget
    while time.time() < t_end and len(acc) < want:
        if not memory_ok() or idle() < need:
            time.sleep(5)
            continue
        tried += 1
        r = round_fn()
        if memory_ok() and idle() >= need:
            acc.append(r)
    return acc, tried
