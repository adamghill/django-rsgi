import os
import random
import re
import signal
import socket
import statistics
import subprocess
import sys
import time

# Configuration
PORT = 8001
DURATION = "10s"
CONNECTIONS = 100
THREADS = 2
NUM_RUNS = 3
WRK_PATH = "wrk"
CWD = os.path.join(os.path.dirname(__file__), "example")

CONFIGS = [
    {"name": "WSGI", "interface": "wsgi", "target": "config.wsgi:application"},
    {"name": "ASGI", "interface": "asgi", "target": "config.asgi:application"},
    {"name": "RSGI", "interface": "rsgi", "target": "config.rsgi:application"},
]


def wait_for_port(port, timeout=5):
    start = time.time()
    while time.time() - start < timeout:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            if s.connect_ex(("127.0.0.1", port)) == 0:
                return True
        time.sleep(0.1)
    return False


def run_benchmark(config):
    print(f"--- Benchmarking {config['name']} ---")

    # Start Server
    cmd = [
        "granian",
        "--interface",
        config["interface"],
        config["target"],
        "--port",
        str(PORT),
        "--workers",
        "1",
        "--threads",
        "1",
        "--log-level",
        "warning",
    ]

    try:
        # Start the server process
        # We use a new session to easily kill the process tree later
        server_process = subprocess.Popen(
            cmd,
            cwd=CWD,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.PIPE,
            preexec_fn=os.setsid,
        )
    except FileNotFoundError:
        print("Error: 'granian' command not found. Please install dependencies.")
        return None

    if not wait_for_port(PORT):
        print(f"Failed to start server for {config['name']}")
        # Try to read stderr
        _, stderr = server_process.communicate()
        if stderr:
            print("Server error output:")
            print(stderr.decode("utf-8") if isinstance(stderr, bytes) else stderr)

        try:
            os.killpg(os.getpgid(server_process.pid), signal.SIGTERM)
        except ProcessLookupError:
            pass
        return None

    # Run wrk
    wrk_cmd = [
        WRK_PATH,
        "-t",
        str(THREADS),
        "-c",
        str(CONNECTIONS),
        "-d",
        DURATION,
        f"http://127.0.0.1:{PORT}/",
    ]

    try:
        result = subprocess.run(wrk_cmd, capture_output=True, text=True)
        output = result.stdout
    except FileNotFoundError:
        print("Error: 'wrk' not found or not executable. Please install 'wrk'.")
        # Kill server
        try:
            os.killpg(os.getpgid(server_process.pid), signal.SIGTERM)
        except ProcessLookupError:
            pass
        sys.exit(1)

    # Stop Server
    try:
        os.killpg(os.getpgid(server_process.pid), signal.SIGTERM)
        server_process.wait(timeout=5)
    except (ProcessLookupError, subprocess.TimeoutExpired):
        pass

    # Parse RPS
    # Output example: requests/sec:  49392.34
    match = re.search(r"Requests/sec:\s+([\d.]+)", output)
    if match:
        rps = float(match.group(1))
        print(f"Result: {rps:,.2f} req/sec")
        return rps
    else:
        print("Could not parse wrk output")
        print(output)
        return 0


def main():
    print(f"Running benchmarks (Duration: {DURATION}, Connections: {CONNECTIONS})...")
    print(f"Command used: granian --workers 1 --threads 1 ...")
    print(f"Averaging over {NUM_RUNS} runs in random order.")

    # Dictionary to store list of results for each interface
    all_results = {c["name"]: [] for c in CONFIGS}

    for i in range(NUM_RUNS):
        print(f"\n=== Run {i + 1}/{NUM_RUNS} ===")
        # Shuffle a copy of the configs to randomize order
        run_configs = list(CONFIGS)
        random.shuffle(run_configs)

        for config in run_configs:
            rps = run_benchmark(config)
            if rps is not None:
                all_results[config["name"]].append(rps)

    print("\n\n=== Final Results (Average) ===")

    # Calculate averages
    final_stats = []
    for name, values in all_results.items():
        if values:
            avg_rps = statistics.mean(values)
            final_stats.append((name, avg_rps))
        else:
            print(f"No successful runs for {name}")

    if not final_stats:
        print("No results obtained.")
        return

    final_stats.sort(key=lambda x: x[1], reverse=True)
    baseline = final_stats[0][1]

    print(f"{'Interface':<10} {'Req/Sec (Avg)':<15} {'% relative':<12}")
    print("-" * 45)
    for name, rps in final_stats:
        pct = (rps / baseline) * 100
        print(f"{name:<10} {rps:10,.2f}      {pct:6.1f}%")


if __name__ == "__main__":
    main()
