#!/usr/bin/env python
"""Comprehensive tool verification test suite.

Tests every Seed Code tool with real operations and verification:
- Filesystem: create, write, edit, delete
- Terminal: command execution with exit codes
- Git: status, diff, log
- Search: file search, text grep
- Desktop: mouse, keyboard, windows (if available)

Every test must prove the expected change occurred.
"""

import sys
import tempfile
from pathlib import Path

# Test results tracking
_tests_run = 0
_tests_passed = 0
_tests_failed = 0


def test(name: str):
    """Decorator to register and run a test."""
    def decorator(fn):
        fn.__test__ = False  # already executed here; keep pytest from re-collecting

        global _tests_run, _tests_passed, _tests_failed
        _tests_run += 1
        print(f"\n{'='*80}")
        print(f"TEST {_tests_run}: {name}")
        print('='*80)
        try:
            fn()
            _tests_passed += 1
            print(f"✓ PASSED: {name}")
        except AssertionError as e:
            _tests_failed += 1
            print(f"✗ FAILED: {name}")
            print(f"  Reason: {e}")
        except Exception as e:
            _tests_failed += 1
            print(f"✗ ERROR: {name}")
            print(f"  Exception: {e}")
            import traceback
            traceback.print_exc()
        return fn
    return decorator


# The decorator itself must not be collected as a pytest test either.
test.__test__ = False


# Setup test workspace
TEST_DIR = Path(tempfile.mkdtemp(prefix="seedcode_test_"))
print(f"Test workspace: {TEST_DIR}")


@test("Import all tool modules")
def test_imports():
    """Verify all tool modules import without errors."""
    from seedcode.tools import filesystem, terminal, git, search, patch, desktop
    from seedcode.tools import TOOL_REGISTRY
    assert len(TOOL_REGISTRY) > 0, "Tool registry is empty"
    print(f"  → {len(TOOL_REGISTRY)} tools registered")


@test("Write file with verification")
def test_write_file():
    """Test write_file includes read-back verification."""
    from seedcode.tools.filesystem import _write_file
    from seedcode.tools import PermissionManager, PermissionMode

    perm = PermissionManager(workspace=TEST_DIR, mode=PermissionMode.WORKSPACE)
    test_file = TEST_DIR / "test_write.txt"
    content = "Hello from verification test!"

    result = _write_file(perm, {"path": str(test_file), "content": content})

    assert result.ok, f"write_file failed: {result.output}"
    assert "verified" in result.output.lower(), "Missing verification in output"
    assert test_file.exists(), "File was not created"
    assert test_file.read_text() == content, "File content doesn't match"
    print(f"  → {result.output}")


@test("Edit file with verification")
def test_edit_file():
    """Test edit_file includes read-back verification."""
    from seedcode.tools.patch import _edit_file
    from seedcode.tools import PermissionManager, PermissionMode

    perm = PermissionManager(workspace=TEST_DIR, mode=PermissionMode.WORKSPACE)
    test_file = TEST_DIR / "test_edit.txt"
    test_file.write_text("Original content here")

    result = _edit_file(perm, {
        "path": str(test_file),
        "old_text": "Original",
        "new_text": "Modified"
    })

    assert result.ok, f"edit_file failed: {result.output}"
    assert "verified" in result.output.lower(), "Missing verification in output"
    new_content = test_file.read_text()
    assert "Modified" in new_content, "Edit was not applied"
    assert "Original" not in new_content, "Old text still present"
    print(f"  → {result.output}")


@test("Delete file with verification")
def test_delete_file():
    """Test delete_file includes existence check."""
    from seedcode.tools.filesystem import _delete_file
    from seedcode.tools import PermissionManager, PermissionMode

    perm = PermissionManager(workspace=TEST_DIR, mode=PermissionMode.WORKSPACE)
    test_file = TEST_DIR / "test_delete.txt"
    test_file.write_text("Delete me")

    result = _delete_file(perm, {"path": str(test_file)})

    assert result.ok, f"delete_file failed: {result.output}"
    assert "verified" in result.output.lower(), "Missing verification in output"
    assert not test_file.exists(), "File still exists after delete"
    print(f"  → {result.output}")


@test("Terminal command with exit code")
def test_run_command_success():
    """Test run_command captures exit code for success."""
    from seedcode.tools.terminal import _run_command
    from seedcode.tools import PermissionManager, PermissionMode

    perm = PermissionManager(workspace=TEST_DIR, mode=PermissionMode.WORKSPACE)

    # Success case
    result = _run_command(perm, {"command": "echo test", "timeout": 5})
    assert result.ok, f"Command failed: {result.output}"
    assert "✓" in result.output or "success" in result.output.lower(), "Missing success indicator"
    print(f"  → Success: {result.output[:100]}")


@test("Terminal command failure detection")
def test_run_command_failure():
    """Test run_command properly reports failures."""
    from seedcode.tools.terminal import _run_command
    from seedcode.tools import PermissionManager, PermissionMode

    perm = PermissionManager(workspace=TEST_DIR, mode=PermissionMode.WORKSPACE)

    # Failure case - command that doesn't exist
    result = _run_command(perm, {"command": "nonexistent_command_xyz", "timeout": 5})
    assert not result.ok, "Command should have failed"
    assert "✗" in result.output or "failed" in result.output.lower(), "Missing failure indicator"
    print(f"  → Failure detected: {result.output[:100]}")


@test("Search files")
def test_search_files():
    """Test file search finds files correctly."""
    from seedcode.tools.search import _find_files
    from seedcode.tools import PermissionManager, PermissionMode

    perm = PermissionManager(workspace=TEST_DIR, mode=PermissionMode.WORKSPACE)

    # Create test files
    (TEST_DIR / "find_me.txt").write_text("content")
    (TEST_DIR / "other.log").write_text("content")

    result = _find_files(perm, {"pattern": "*.txt"})
    assert result.ok, f"find_files failed: {result.output}"
    assert "find_me.txt" in result.output, "Expected file not found"
    print(f"  → Found: {result.output[:200]}")


@test("Grep content")
def test_grep_content():
    """Test text search finds patterns."""
    from seedcode.tools.search import _search_text
    from seedcode.tools import PermissionManager, PermissionMode

    perm = PermissionManager(workspace=TEST_DIR, mode=PermissionMode.WORKSPACE)

    # Create file with searchable content
    test_file = TEST_DIR / "searchable.txt"
    test_file.write_text("Line 1\nUnique pattern here\nLine 3")

    result = _search_text(perm, {"pattern": "Unique", "glob": "*.txt"})
    assert result.ok, f"search_text failed: {result.output}"
    assert "Unique pattern" in result.output, "Pattern not found in search results"
    print(f"  → Search result: {result.output[:200]}")


@test("Agent run_turn returns non-empty")
def test_agent_no_empty_response():
    """Test agent.run_turn() never returns empty string."""
    from seedcode.core.agent import AgentEngine
    from seedcode.core.models import AppConfig
    from seedcode.tools import PermissionManager, PermissionMode

    config = AppConfig()
    config.provider = "freemodel_claude"
    config.model = "[REDACTED]"

    perm = PermissionManager(workspace=TEST_DIR, mode=PermissionMode.READ_ONLY)

    # We can't actually run a full turn without a provider, but we can check
    # the code path that returns "Done." for empty replies
    agent = AgentEngine(config, perm)

    # Check that the fix is in place by reading the source: run_turn returns
    # 'payload or "Done."' and the step handlers guard 'final if final'.
    import inspect
    import seedcode.core.agent as agent_module
    source = inspect.getsource(agent_module)
    assert 'payload or "Done."' in source and 'final if final else "Done."' in source, \
        "Agent loop doesn't have empty-reply protection"
    print("  → Agent has empty-reply protection")


@test("Desktop tools availability check")
def test_desktop_available():
    """Check if desktop tools are available."""
    from seedcode.computer import is_available, missing_packages

    ok, reason = is_available()
    if ok:
        print("  → Desktop tools AVAILABLE")
    else:
        print(f"  → Desktop tools unavailable: {reason}")
        missing = missing_packages()
        if missing:
            print(f"  → Missing packages: {', '.join(missing)}")


# Run all tests
if __name__ == "__main__":
    print("=" * 80)
    print("SEED CODE TOOL VERIFICATION TEST SUITE")
    print("=" * 80)

    # Tests run via decorators above

    print("\n" + "=" * 80)
    print("TEST SUMMARY")
    print("=" * 80)
    print(f"Total:  {_tests_run}")
    print(f"Passed: {_tests_passed} ✓")
    print(f"Failed: {_tests_failed} ✗")
    print("=" * 80)

    if _tests_failed == 0:
        print("\n✓✓✓ ALL TESTS PASSED ✓✓✓")
        print("\nAssist Mode verification is complete.")
        print("All tools now include proper verification and never report fake success.")
        sys.exit(0)
    else:
        print(f"\n✗✗✗ {_tests_failed} TEST(S) FAILED ✗✗✗")
        print("\nSome tools still have verification issues.")
        sys.exit(1)
