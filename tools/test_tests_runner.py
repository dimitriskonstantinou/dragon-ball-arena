"""
Unit tests for the gates in tests.py: each one must catch exactly the problem it
exists for, and stay quiet on a clean run. (tests.py runs this file itself.)

    python tools/test_tests_runner.py
"""
import copy
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import tests  # noqa: E402  (the runner at the repo root)

FAILURES = []


def check(name, condition, detail=""):
    if condition:
        print(f"  PASS: {name}")
    else:
        FAILURES.append(name)
        print(f"  FAIL: {name}  {detail}")


BASE = {
    'suites': {'engine': {'pass': 200, 'skipped': 0}, 'smoke': {'pass': 150, 'skipped': 0}},
    'probe_confirmed': ["reflect ignores attacker's invulnerability/defense"],
    'payload_bytes': 8600, 'coverage': 92.0, 'lint_issues': 2, 'turn_ms': 0.3,
}
CLEAN = {
    'suites': {'engine': {'pass': 200, 'fail': 0, 'skipped': 0, 'exit': 0},
               'smoke': {'pass': 150, 'fail': 0, 'skipped': 0, 'exit': 0}},
    'probe_confirmed': ["reflect ignores attacker's invulnerability/defense"],
    'payload_bytes': 8600, 'coverage': 92.0, 'lint_issues': 2, 'turn_ms': 0.31, 'real_db_changed': False,
}


def problems_for(change):
    results = copy.deepcopy(CLEAN)
    change(results)
    return tests.compare(results, BASE)


def test_parsing():
    text = "test_x:\n  PASS: a\n  PASS: b\nPASS: c\n  FAIL: d  detail\n  SKIPPED: e not in roster\nnot a PASS line\n"
    check("counts PASS / FAIL / SKIPPED lines (only at line start for PASS/FAIL)",
          tests.count_checks(text) == (3, 1, 1), tests.count_checks(text))
    probe = ("[CONFIRMED] reflect ignores attacker's invulnerability/defense (by inspection: x)\n"
             "[not reproduced] free skills Payment doesn't match\n"
             "[CONFIRMED] new hole (detail (nested))\n")
    check("reads the probe's confirmed titles without their details",
          tests.probe_confirmed(probe) == ['new hole', "reflect ignores attacker's invulnerability/defense"],
          tests.probe_confirmed(probe))


def test_clean_run_is_green():
    problems, warnings = tests.compare(CLEAN, BASE)
    check("a run matching the baseline has no problems and no warnings", (problems, warnings) == ([], []),
          (problems, warnings))


def test_each_gate_catches_its_problem():
    cases = [
        ("a failing check", lambda r: r['suites']['engine'].update(fail=1), 'FAILED'),
        ("a crashed suite", lambda r: r['suites']['smoke'].update(exit=1), 'exited with code 1'),
        ("fewer checks than the baseline (a test silently removed)",
         lambda r: r['suites']['engine'].update(**{'pass': 199}), 'only 199 checks passed'),
        ("a newly skipped test", lambda r: r['suites']['engine'].update(skipped=1), 'SKIPPED'),
        ("a suite that couldn't run", lambda r: r['suites'].update(browser={'not_run': 'no chromium'}),
         "couldn't run"),
        ("a NEW confirmed exploit", lambda r: r['probe_confirmed'].append('free skills'), 'NEW confirmed problem'),
        ("payload growth (even 1 byte)", lambda r: r.update(payload_bytes=8601), 'grew by 1 bytes'),
        ("a coverage drop of more than 1 point", lambda r: r.update(coverage=90.5), 'coverage dropped'),
        ("a new lint issue", lambda r: r.update(lint_issues=3), 'lint'),
        ("the real game.db being touched", lambda r: r.update(real_db_changed=True), 'game.db'),
    ]
    for name, change, expected in cases:
        problems, _ = problems_for(change)
        check(f"fails on {name}", any(expected in p for p in problems), problems)


def test_harmless_changes_only_warn():
    for name, change, expected in [
        ("new checks", lambda r: r['suites']['engine'].update(**{'pass': 205}), 'new check'),
        ("a fixed exploit", lambda r: r.update(probe_confirmed=[]), 'no longer confirmed'),
        ("a smaller payload", lambda r: r.update(payload_bytes=8500), 'smaller'),
        ("a slower engine (timing is noisy)", lambda r: r.update(turn_ms=0.6), 'speed'),
    ]:
        problems, warnings = problems_for(change)
        check(f"{name}: a warning, not a failure", problems == [] and any(expected in w for w in warnings),
              (problems, warnings))
    problems, _ = problems_for(lambda r: r.update(coverage=91.5))
    check("a coverage wobble within 1 point is fine", problems == [], problems)


TESTS = [v for k, v in list(globals().items()) if k.startswith('test_')]

if __name__ == '__main__':
    for t in TESTS:
        print(f"{t.__name__}:")
        t()
    print()
    if FAILURES:
        print(f"{len(FAILURES)} FAILURE(S): {FAILURES}")
        raise SystemExit(1)
    print(f"All {len(TESTS)} test functions passed.")
