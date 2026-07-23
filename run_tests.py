#!/usr/bin/env python3
"""Day 3 Testing — Unified test runner.

Usage:
    python run_tests.py                # Run all tests
    python run_tests.py --level unit   # Only unit tests
    python run_tests.py --level smoke  # Only smoke tests (requires server)
    python run_tests.py --report       # Generate report file
"""

import argparse
import contextlib
import json
import os
import subprocess
import sys
from datetime import datetime


def run_cmd(cmd, description):
    print(f"\n{'='*60}")
    print(f"  {description}")
    print(f"{'='*60}")
    result = subprocess.run(
        cmd,
        shell=True,
        capture_output=True,
        text=True,
        cwd=os.path.dirname(os.path.abspath(__file__)),
    )
    print(result.stdout)
    if result.stderr:
        print("STDERR:", result.stderr)
    return result.returncode, result.stdout


def parse_pytest_output(output):
    passed = failed = 0
    for line in output.split("\n"):
        if "passed" in line and "failed" in line:
            parts = line.split(",")
            for p in parts:
                p = p.strip()
                if "passed" in p:
                    passed = int(p.split()[0])
                elif "failed" in p:
                    failed = int(p.split()[0])
        elif "passed" in line and "failed" not in line:
            parts = line.split()
            for i, p in enumerate(parts):
                if p == "passed":
                    with contextlib.suppress(ValueError, IndexError):
                        passed = int(parts[i - 1])
        elif line.strip().startswith("=") and "passed" in line:
            tokens = line.split()
            for i, t in enumerate(tokens):
                if t == "passed" and i > 0:
                    with contextlib.suppress(ValueError, IndexError):
                        passed = int(tokens[i - 1])
    return passed, failed


def main():
    parser = argparse.ArgumentParser(description="Day 3 Testing Runner")
    parser.add_argument("--level", choices=["unit", "smoke", "all"], default="all")
    parser.add_argument("--report", action="store_true", help="Save report to file")
    args = parser.parse_args()

    base_dir = os.path.dirname(os.path.abspath(__file__))
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    results = {"timestamp": timestamp, "unit": {}, "smoke": {}}

    print(f"\n{'#'*60}")
    print(f"  DAY 3 TESTING — {timestamp}")
    print(f"{'#'*60}")

    if args.level in ("unit", "all"):
        code, output = run_cmd(
            f"{sys.executable} -m pytest tests/test_server_utils.py tests/test_js_utils.py -v --tb=short",
            "Level 1: Unit Tests (utils + JS)",
        )
        p, f = parse_pytest_output(output)
        results["unit"]["utils"] = {"passed": p, "failed": f, "exit_code": code}

        code, output = run_cmd(
            f"{sys.executable} -m pytest tests/test_server_routes.py -v --tb=short",
            "Level 1: Integration Tests (server routes)",
        )
        p, f = parse_pytest_output(output)
        results["unit"]["routes"] = {"passed": p, "failed": f, "exit_code": code}

        code, output = run_cmd(
            f"{sys.executable} -m pytest tests/test_mcp_server.py -v --tb=short",
            "Level 1: Integration Tests (MCP server)",
        )
        p, f = parse_pytest_output(output)
        results["unit"]["mcp"] = {"passed": p, "failed": f, "exit_code": code}

    if args.level in ("smoke", "all"):
        code, output = run_cmd(
            f"{sys.executable} -m pytest tests/test_smoke_playwright.py -v --tb=short",
            "Level 2: Smoke Tests (Playwright)",
        )
        p, f = parse_pytest_output(output)
        results["smoke"]["playwright"] = {"passed": p, "failed": f, "exit_code": code}

    total_passed = sum(r.get("passed", 0) for r in list(results["unit"].values()) + list(results["smoke"].values()))
    total_failed = sum(r.get("failed", 0) for r in list(results["unit"].values()) + list(results["smoke"].values()))

    print(f"\n{'#'*60}")
    print("  REPORT SUMMARY")
    print(f"{'#'*60}")
    print(f"  Date: {timestamp}")
    print(f"  Total: {total_passed} passed, {total_failed} failed")

    for level_name, level_data in results.items():
        if isinstance(level_data, dict) and level_data:
            print(f"\n  [{level_name.upper()}]")
            for test_name, test_data in level_data.items():
                status = "PASSED" if test_data["failed"] == 0 else "FAILED"
                print(f"    {test_name}: {test_data['passed']} passed, {test_data['failed']} failed [{status}]")

    screenshots_dir = os.path.join(base_dir, "test-reports", "screenshots")
    if os.path.exists(screenshots_dir):
        screenshots = os.listdir(screenshots_dir)
        print(f"\n  Screenshots: {len(screenshots)} files in {screenshots_dir}")

    if args.report:
        report_path = os.path.join(base_dir, "test-reports", "test-report.json")
        os.makedirs(os.path.dirname(report_path), exist_ok=True)
        results["summary"] = {"total_passed": total_passed, "total_failed": total_failed}
        with open(report_path, "w", encoding="utf-8") as f:
            json.dump(results, f, indent=2, ensure_ascii=False)
        print(f"\n  Report saved: {report_path}")

    print(f"\n{'#'*60}")
    exit_code = 0 if total_failed == 0 else 1
    print(f"  RESULT: {'ALL PASSED' if exit_code == 0 else 'SOME FAILURES'}")
    print(f"{'#'*60}\n")
    return exit_code


if __name__ == "__main__":
    sys.exit(main())
