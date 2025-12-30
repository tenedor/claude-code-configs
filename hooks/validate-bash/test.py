#!/usr/bin/env python3
"""
Test script for validate-bash hook with combinatorial test generation

This test uses a combinatorial pattern where:
- Combinators: Control structures (both analyzable and non-analyzable)
- Atoms: Safe and unsafe command patterns

Combinators include:
- Analyzable: Command chaining (&&, ||, ;), Piping (|), Redirects (>, >>, <, 2>)
- Non-analyzable: Command substitution $(), Variable expansion $VAR, Process substitution <(), Multiline

Unsafe atoms include:
- Control characters (null bytes)
- Process backgrounding (&)
- Unapproved command patterns (not in approved-patterns.json)
- Unallowed file access: absolute paths, parent dirs (..), tilde (~), git metadata (.git)
"""

import subprocess
import json
import sys
import os
from itertools import combinations, product

# Color codes for output
class Colors:
    RED = '\033[0;31m'
    GREEN = '\033[0;32m'
    YELLOW = '\033[1;33m'
    GRAY = '\033[0;90m'
    NC = '\033[0m'  # No Color

# Test counters
pass_count = 0
fail_count = 0


# ===== Helper Functions =====

def print_header(text):
    """Print a major section header with double lines."""
    print()
    print("=" * 60)
    print(text)
    print("=" * 60)


def print_subheader(text):
    print()
    """Print a subsection header."""
    print(f"--- {text} ---")


# ===== Minimal Combinator Functions =====

def command_chain_combinator(cmd1, cmd2, chaining_op):
    """
    Combine two commands with a chaining operator.

    Args:
        cmd1: (command, allowed) tuple
        cmd2: (command, allowed) tuple
        chaining_op: One of '&&', '||', ';'

    Returns:
        (command, allowed) tuple
    """
    command1, allowed1 = cmd1
    command2, allowed2 = cmd2
    combined_cmd = f"{command1} {chaining_op} {command2}"
    # Only allowed if both commands are allowed
    combined_allowed = allowed1 and allowed2
    return (combined_cmd, combined_allowed)


def pipe_combinator(cmd1, cmd2):
    """
    Combine two commands with a pipe.

    Args:
        cmd1: (command, allowed) tuple
        cmd2: (command, allowed) tuple

    Returns:
        (command, allowed) tuple
    """
    command1, allowed1 = cmd1
    command2, allowed2 = cmd2
    combined_cmd = f"{command1} | {command2}"
    # Only allowed if both commands are allowed
    combined_allowed = allowed1 and allowed2
    return (combined_cmd, combined_allowed)


def redirect_combinator(cmd, target, redirect_op):
    """
    Combine a command with a redirect operation.

    Args:
        cmd: (command, allowed) tuple
        target: (file_path, allowed) tuple
        redirect_op: One of '>', '>>', '<', '2>', '2>&1'

    Returns:
        (command, allowed) tuple
    """
    command, cmd_allowed = cmd
    file_path, file_allowed = target

    if redirect_op == '2>&1':
        combined_cmd = f"{command} 2>&1"
        # No file target, so only depends on command
        combined_allowed = cmd_allowed
    else:
        combined_cmd = f"{command} {redirect_op} {file_path}"
        # Only allowed if both command and target are allowed
        combined_allowed = cmd_allowed and file_allowed

    return (combined_cmd, combined_allowed)


def command_substitution_combinator(cmd, style='$()'):
    """
    Wrap a command in command substitution syntax.

    Args:
        cmd: (command, allowed) tuple
        style: Either '$()' or '``' for the substitution style

    Returns:
        (command, allowed) tuple - allowed if nested command is allowed
    """
    command, allowed = cmd

    if style == '``':
        combined_cmd = f"echo `{command}`"
    else:  # $()
        combined_cmd = f"echo $({command})"

    # Command substitution is allowed if nested commands are allowed
    return (combined_cmd, allowed)


def process_substitution_combinator(cmd, ps_op):
    """
    Wrap a command in process substitution syntax.

    Args:
        cmd: (command, allowed) tuple
        ps_op: Either '<' or '>' for input/output process substitution

    Returns:
        (command, allowed) tuple - always blocked because spawning parallel processes requires user permission
    """
    command, _ = cmd

    if ps_op == '<':
        # Input process substitution
        combined_cmd = f"diff <({command}) file.txt"
    else:  # '>'
        # Output process substitution
        combined_cmd = f"tee >({command})"

    # Process substitution is non-analyzable, always requires permission
    return (combined_cmd, False)


def multiline_combinator(cmd1, cmd2):
    """
    Combine two commands with a newline.

    Args:
        cmd1: (command, allowed) tuple
        cmd2: (command, allowed) tuple

    Returns:
        (command, allowed) tuple - always non-analyzable (False)
    """
    command1, allowed1 = cmd1
    command2, allowed2 = cmd2
    combined_cmd = f"{command1}\n{command2}"
    allowed = allowed1 and allowed2

    # Multiline is non-analyzable, always requires permission
    return (combined_cmd, allowed)


def variable_expansion_combinator(var, style='$'):
    """
    Create a command with variable expansion.

    Args:
        var: Variable name (string)
        style: Either '$' or '${' for the expansion style

    Returns:
        (command, allowed) tuple - always non-analyzable (False)
    """
    if style == '${':
        combined_cmd = f"cat ${{{var}}}"
    else:  # $
        combined_cmd = f"cd ${var}"

    # Variable expansion is non-analyzable, always requires permission
    return (combined_cmd, False)


# ===== Combinator Generators =====

def apply_command_chaining(atoms, expected_for_safe):
    """
    Combinator: Command chaining with &&, ||, ;

    Args:
        atoms: List of (command, is_safe) tuples
        expected_for_safe: Expected result when all atoms are safe

    Yields:
        (command, expected) tuples
    """
    operators = ['&&', '||', ';']

    for op in operators:
        # Test with 2 atoms
        for atom1, safe1 in atoms:
            for atom2, safe2 in atoms:
                cmd = f"{atom1} {op} {atom2}"
                # If any atom is unsafe, expect 'ask'
                expected = expected_for_safe if (safe1 and safe2) else "ask"
                yield (cmd, expected)


def apply_piping(atoms, expected_for_safe):
    """
    Combinator: Piping with |

    Args:
        atoms: List of (command, is_safe) tuples
        expected_for_safe: Expected result when all atoms are safe

    Yields:
        (command, expected) tuples
    """
    # Test with 2 atoms
    for atom1, safe1 in atoms:
        for atom2, safe2 in atoms:
            cmd = f"{atom1} | {atom2}"
            expected = expected_for_safe if (safe1 and safe2) else "ask"
            yield (cmd, expected)


def apply_redirects(safe_atoms, unsafe_targets):
    """
    Combinator: Redirects with >, >>, <, 2>, 2>&1

    Args:
        safe_atoms: List of safe command strings
        unsafe_targets: List of (target, description) tuples for unsafe redirect targets

    Yields:
        (command, expected, description) tuples
    """
    redirect_ops = ['>', '>>', '<', '2>']
    safe_targets = ['output.txt', 'data/result.log', 'temp.tmp']

    # Safe redirects: safe command + safe target
    for cmd in safe_atoms:
        for target in safe_targets:
            for op in redirect_ops:
                if op == '<':
                    yield (f"{cmd} {op} {target}", "allow", f"Safe redirect {op}")
                else:
                    yield (f"{cmd} {op} {target}", "allow", f"Safe redirect {op}")

    # Unsafe redirects: safe command + unsafe target
    for cmd in safe_atoms:
        for target, desc in unsafe_targets:
            for op in redirect_ops:
                yield (f"{cmd} {op} {target}", "ask", f"Unsafe redirect to {desc}")

    # Special case: 2>&1 (stderr to stdout - always safe if base command is safe)
    for cmd in safe_atoms[:2]:
        yield (f"{cmd} 2>&1", "allow", "stderr to stdout redirect")


def apply_command_substitution(atoms):
    """
    Combinator: Command substitution $() and ``
    Non-analyzable - should always ask for permission

    Args:
        atoms: List of (command, is_safe) tuples

    Yields:
        (command, expected, description) tuples
    """
    for atom, is_safe in atoms:
        # $() syntax
        cmd = f"echo $({atom})"
        yield (cmd, "ask", f"Command substitution $() with {'safe' if is_safe else 'unsafe'} atom")

        # Backtick syntax (avoid issues with string escaping)
        cmd = f"echo `{atom}`"
        yield (cmd, "ask", f"Command substitution `` with {'safe' if is_safe else 'unsafe'} atom")


def apply_variable_expansion(unsafe_vars):
    """
    Combinator: Variable expansion $VAR, ${VAR}
    Non-analyzable - should always ask for permission

    Args:
        unsafe_vars: List of (var_name, description) tuples

    Yields:
        (command, expected, description) tuples
    """
    for var, desc in unsafe_vars:
        # Simple expansion
        cmd = f"cd ${var}"
        yield (cmd, "ask", f"Variable expansion ${desc}")

        # Brace expansion
        cmd = f"cat ${{{var}}}"
        yield (cmd, "ask", f"Variable expansion (braces) ${desc}")


def apply_process_substitution(atoms):
    """
    Combinator: Process substitution <() and >()
    Non-analyzable - should always ask for permission

    Args:
        atoms: List of (command, is_safe) tuples

    Yields:
        (command, expected, description) tuples
    """
    safe_base = "cat file.txt"

    for atom, is_safe in atoms:
        # Input process substitution
        cmd = f"diff <({atom}) {safe_base}"
        yield (cmd, "ask", f"Process substitution <() with {'safe' if is_safe else 'unsafe'} atom")

        # Output process substitution
        cmd = f"tee >({atom})"
        yield (cmd, "ask", f"Process substitution >() with {'safe' if is_safe else 'unsafe'} atom")


def apply_multiline(atoms):
    """
    Combinator: Multiline commands (newline characters)
    Non-analyzable - should always ask for permission

    Args:
        atoms: List of (command, is_safe) tuples

    Yields:
        (command, expected, description) tuples
    """
    for atom1, safe1 in atoms:
        for atom2, safe2 in atoms:
            cmd = f"{atom1}\n{atom2}"
            # Multiline is always non-analyzable, so always ask
            desc1 = 'safe' if safe1 else 'unsafe'
            desc2 = 'safe' if safe2 else 'unsafe'
            yield (cmd, "ask", f"Multiline with {desc1}/{desc2} atoms")


# ===== Simple Test Generator =====

def generate_simple_tests(commands, expected):
    """
    Generate simple single-command tests.

    Args:
        commands: List of command strings or (command, description) tuples
        expected: Expected permission decision for all these commands

    Yields:
        (command, expected) tuples
    """
    for item in commands:
        if isinstance(item, tuple):
            cmd, desc = item
        else:
            cmd = item
        yield (cmd, expected)

def test_command(cmd, expected):
    """
    Test a command and check if the permission decision matches expected.

    Args:
        cmd: The bash command to test
        expected: Expected permission decision ('allow', 'ask', or 'deny')
    """
    global pass_count, fail_count

    # Get the directory where this script is located
    script_dir = os.path.dirname(os.path.abspath(__file__))
    hook_script = os.path.join(script_dir, 'run.sh')

    # Create test input JSON
    input_data = {
        "tool_name": "Bash",
        "tool_input": {
            "command": cmd
        }
    }

    # Run the hook
    try:
        result = subprocess.run(
            [hook_script],
            input=json.dumps(input_data),
            capture_output=True,
            text=True
        )
        output = result.stdout
        exit_code = result.returncode
    except Exception as e:
        print(f"{Colors.RED}✗ FAIL{Colors.NC}: Error running hook: {e}: {cmd}")
        fail_count += 1
        return

    # Determine actual decision
    actual_decision = ""
    reason = ""

    if exit_code == 0 and output and "permissionDecision" in output:
        # Hook returned JSON with a decision
        try:
            output_json = json.loads(output)
            hook_output = output_json.get('hookSpecificOutput', {})
            actual_decision = hook_output.get('permissionDecision', '')
            reason = hook_output.get('permissionDecisionReason', '')
        except json.JSONDecodeError:
            actual_decision = "error"
            reason = f"Invalid JSON: {output}"
    elif exit_code == 0:
        # Exit 0 with no JSON = allow
        actual_decision = "allow"
    elif exit_code == 2:
        # Exit 2 = blocking error (treated as deny)
        actual_decision = "deny"
        reason = output
    else:
        # Other exit codes = error
        actual_decision = "error"
        reason = f"Exit code {exit_code}: {output}"

    # Compare actual vs expected
    if actual_decision == expected:
        print(f"{Colors.GREEN}✓ PASS{Colors.NC}: Correctly returned '{actual_decision}': {cmd}")
        if reason:
            print(f"  {Colors.GRAY}Reason{Colors.NC}: {reason}")
        pass_count += 1
    else:
        print(f"{Colors.RED}✗ FAIL{Colors.NC}: Expected '{expected}' but got '{actual_decision}': {cmd}")
        if reason:
            print(f"  {Colors.GRAY}Reason{Colors.NC}: {reason}")
        fail_count += 1


def test_command_with_cwd(cmd, cwd, expected, description):
    """
    Test a command with a specific cwd and check if the permission decision matches expected.

    Args:
        cmd: The bash command to test
        cwd: Current working directory for the command
        expected: Expected permission decision ('allow', 'ask', or 'deny')
        description: Human-readable description of the test
    """
    global pass_count, fail_count

    # Get the directory where this script is located
    script_dir = os.path.dirname(os.path.abspath(__file__))
    hook_script = os.path.join(script_dir, 'run.sh')

    # Create test input JSON
    test_input = {
        'tool_name': 'Bash',
        'tool_input': {'command': cmd},
        'cwd': cwd
    }

    # Run the hook
    result = subprocess.run(
        [hook_script],
        input=json.dumps(test_input),
        capture_output=True,
        text=True
    )

    # Parse result
    if result.returncode == 0:
        if result.stdout:
            try:
                output = json.loads(result.stdout)
                decision = output.get('hookSpecificOutput', {}).get('permissionDecision', 'allow')
                reason = output.get('hookSpecificOutput', {}).get('permissionDecisionReason', '')
            except json.JSONDecodeError:
                decision = 'error'
                reason = 'Invalid JSON output'
        else:
            decision = 'allow'
            reason = ''
    else:
        decision = 'error'
        reason = f'Exit code {result.returncode}'

    # Check result
    if decision == expected:
        print(f"{Colors.GREEN}✓ PASS{Colors.NC}: {description}")
        if reason and expected == 'ask':  # Only show reason for blocked commands
            print(f"  {Colors.GRAY}Reason{Colors.NC}: {reason}")
        pass_count += 1
    else:
        print(f"{Colors.RED}✗ FAIL{Colors.NC}: Expected '{expected}' but got '{decision}': {description}")
        if reason:
            print(f"  {Colors.GRAY}Reason{Colors.NC}: {reason}")
        fail_count += 1


def main():
    """Run all tests using combinatorial test generation."""
    global pass_count, fail_count

    print("Testing validate-bash.sh hook with combinatorial test generation...")

    # ===== Define Safe Atoms (from approved-patterns.json) =====
    safe_atoms = [
        "ls -la",
        "cat file.txt",
        "mkdir test",
        "git status",
        "git diff",
        "npm install",
        "npm run build",
        "find . -name '*.js'",
        "grep -r 'pattern' src/",
        "echo hello",
        "touch newfile.txt",
        "rm temp.txt",
        "mkdir /tmp/test", 
    ]

    # ===== Define Unsafe Atoms =====

    # Unapproved command patterns (not in approved-patterns.json)
    unapproved_commands = [
        "python script.py",
        "curl https://example.com",
        "ssh user@host",
        "docker run alpine",
    ]

    # File access violations - Absolute paths
    absolute_paths = [
        "ls /etc/passwd",
        "cat /Users/atlas/file.txt",
        "rm /var/log/test.log",
    ]

    # File access violations - Parent directory references
    parent_dirs = [
        "mkdir ../escape",
        "cat ../../secrets.txt",
        "cd ./../../../etc",
        "ls subdir/../../secrets",
    ]

    # File access violations - Tilde expansion
    tilde_expansion = [
        "ls ~/Documents",
        "mkdir ~/test",
        "cat ~/.bashrc",
    ]

    # File access violations - Git metadata
    git_metadata = [
        "rm -rf .git",
        "rm .gitignore",
        "mv .gitignore .gitignore.bak",
        "cat .git/config",
    ]

    # Process backgrounding
    backgrounded = [
        "sleep 100 &",
        "npm start &",
        "long-running-task &",
    ]

    # Control characters (null bytes)
    control_chars = [
        'ls\x00rm -rf ./',
        'echo "test"\x00malicious',
    ]

    # ===== Define Atomic File Paths =====

    # Allowed file paths (safe for file operations)
    allowed_file_paths = [
        "output.txt",
        "data/result.log",
        "input.txt",
    ]

    # Disallowed file paths (require permission)
    disallowed_file_paths = [
        "/etc/passwd",                  # absolute path
        "../secrets.txt",               # parent directory
        "./subdir/../../secrets.txt",   # nested parent directory
        "~/.bashrc",                    # tilde expansion
        ".git/config",                  # git metadata
    ]

    selected_unsafe_atoms = [
        unapproved_commands[0],
        absolute_paths[0],
        parent_dirs[0],
        tilde_expansion[0],
        git_metadata[0],
        backgrounded[0],
        control_chars[0],
    ]

    # ===== Compound Command Tests =====
    print_header("PART 1: Atomic Command Tests")

    print_subheader("Safe commands (should allow)")
    for cmd, expected in generate_simple_tests(safe_atoms, "allow"):
        test_command(cmd, expected)

    print_subheader("Unapproved command patterns (should ask)")
    for cmd, expected in generate_simple_tests(unapproved_commands, "ask"):
        test_command(cmd, expected)

    print_subheader("Absolute paths (should ask)")
    for cmd, expected in generate_simple_tests(absolute_paths, "ask"):
        test_command(cmd, expected)

    print_subheader("Parent directory access (should ask)")
    for cmd, expected in generate_simple_tests(parent_dirs, "ask"):
        test_command(cmd, expected)

    print_subheader("Tilde expansion (should ask)")
    for cmd, expected in generate_simple_tests(tilde_expansion, "ask"):
        test_command(cmd, expected)

    print_subheader("Git metadata tampering (should ask)")
    for cmd, expected in generate_simple_tests(git_metadata, "ask"):
        test_command(cmd, expected)

    print_subheader("Backgrounded processes (should ask)")
    for cmd, expected in generate_simple_tests(backgrounded, "ask"):
        test_command(cmd, expected)

    print_subheader("Control characters (should ask)")
    for cmd, expected in generate_simple_tests(control_chars, "ask"):
        test_command(cmd, expected)

    print_subheader("Variable Expansion $VAR, ${VAR} (should ask)")
    # Test with $ style
    cmd, allowed = variable_expansion_combinator('HOME', style='$')
    test_command(cmd, "allow" if allowed else "ask")

    # Test with ${ style
    cmd, allowed = variable_expansion_combinator('HOME', style='${')
    test_command(cmd, "allow" if allowed else "ask")

    print_subheader("Dangerous flags (code execution)")
    # Dangerous flags should ask
    test_command("find . -name '*.txt' -exec rm {} \\;", "ask")
    test_command("find . -exec cat {} \\;", "ask")
    test_command("npm install --eval 'malicious()'", "ask")
    test_command("echo test --command something", "ask")

    # Safe usage: dangerous flag strings inside quoted arguments
    test_command("echo 'use --exec flag'", "allow")
    test_command("echo \"--eval is mentioned here\"", "allow")
    test_command("git commit -m 'Added --command flag'", "allow")

    # False positive cases: flag-like argument in non-flag position
    # These will ask for permission even though they're arguably safe
    # This is acceptable since we're being conservative
    test_command("git commit -m --exec", "ask")
    test_command("echo --eval", "ask")

    # ===== Compound Command Tests =====
    print_header("PART 2: Compound Command Tests")

    print_subheader("Command Chaining (&&, ||, ;) (should judge nested commands)")
    # Test with approved commands
    for op in ['&&', '||', ';']:
        cmd, allowed = command_chain_combinator(
            (safe_atoms[0], True),
            (safe_atoms[1], True),
            op
        )
        test_command(cmd, "allow" if allowed else "ask")

    # Test with one approved, one unapproved
    for op in ['&&', '||', ';']:
        cmd, allowed = command_chain_combinator(
            (safe_atoms[0], True),
            (unapproved_commands[0], False),
            op
        )
        test_command(cmd, "allow" if allowed else "ask")

    print_subheader("Piping (|) (should judge nested commands)")
    # Test with approved commands
    cmd, allowed = pipe_combinator(
        (safe_atoms[0], True),
        (safe_atoms[1], True)
    )
    test_command(cmd, "allow" if allowed else "ask")

    # Test with one approved, one unapproved
    cmd, allowed = pipe_combinator(
        (safe_atoms[0], True),
        (unapproved_commands[0], False)
    )
    test_command(cmd, "allow" if allowed else "ask")

    print_subheader("Redirects (>, >>, <, 2>, 2>&1) (should judge nested commands)")
    # Test with approved command + approved file
    for op in ['>', '>>', '<', '2>']:
        cmd, allowed = redirect_combinator(
            (safe_atoms[0], True),
            (allowed_file_paths[0], True),
            op
        )
        test_command(cmd, "allow" if allowed else "ask")

    # Test 2>&1 (no file target)
    cmd, allowed = redirect_combinator(
        (safe_atoms[0], True),
        ("", True),
        '2>&1'
    )
    test_command(cmd, "allow" if allowed else "ask")

    # Test with approved command + unapproved file
    for op in ['>', '<']:
        cmd, allowed = redirect_combinator(
            (safe_atoms[0], True),
            (disallowed_file_paths[0], False),
            op
        )
        test_command(cmd, "allow" if allowed else "ask")

    # Test with unapproved command + approved file
    for op in ['>', '<']:
        cmd, allowed = redirect_combinator(
            (unapproved_commands[0], False),
            (allowed_file_paths[0], True),
            op
        )
        test_command(cmd, "allow" if allowed else "ask")

    print_subheader("Command Substitution $() and `` (should judge nested commands)")
    # Test with safe command in $() style
    cmd, allowed = command_substitution_combinator(
        (safe_atoms[0], True),
        style='$()'
    )
    test_command(cmd, "allow" if allowed else "ask")

    # Test with safe command in `` style
    cmd, allowed = command_substitution_combinator(
        (safe_atoms[0], True),
        style='``'
    )
    test_command(cmd, "allow" if allowed else "ask")

    # Test with unsafe command (absolute path) in $() style
    cmd, allowed = command_substitution_combinator(
        (absolute_paths[0], False),
        style='$()'
    )
    test_command(cmd, "allow" if allowed else "ask")

    # Test with unapproved command in $() style
    cmd, allowed = command_substitution_combinator(
        (unapproved_commands[0], False),
        style='$()'
    )
    test_command(cmd, "allow" if allowed else "ask")

    print_subheader("Process Substitution <() and >() (should ask)")
    # Test with < (input)
    cmd, allowed = process_substitution_combinator(
        (safe_atoms[0], True),
        ps_op='<'
    )
    test_command(cmd, "allow" if allowed else "ask")

    # Test with > (output)
    cmd, allowed = process_substitution_combinator(
        (safe_atoms[0], True),
        ps_op='>'
    )
    test_command(cmd, "allow" if allowed else "ask")

    print_subheader("Multiline Commands (should judge nested commands)")
    # Test with approved commands
    cmd, allowed = multiline_combinator(
        (safe_atoms[0], True),
        (safe_atoms[1], True)
    )
    test_command(cmd, "allow" if allowed else "ask")
    # Test with unapproved command
    cmd, allowed = multiline_combinator(
        (safe_atoms[0], True),
        (unapproved_commands[1], False)
    )
    test_command(cmd, "allow" if allowed else "ask")

    # ===== Path-Based Tests =====
    print_header("PART 3: Path-Based Validation Tests (with cwd provided)")

    # Setup test directory structure
    import tempfile
    import shutil

    script_dir = os.path.dirname(os.path.abspath(__file__))
    testdata_dir = os.path.join(script_dir, 'tmp-testdata')

    # Clean up any existing test data
    if os.path.exists(testdata_dir):
        shutil.rmtree(testdata_dir)

    # Create test directory structure
    os.makedirs(testdata_dir, exist_ok=True)
    project_dir = os.path.join(testdata_dir, 'project')
    os.makedirs(project_dir, exist_ok=True)
    subdir = os.path.join(project_dir, 'subdir')
    os.makedirs(subdir, exist_ok=True)

    # Create some test files
    open(os.path.join(project_dir, 'file.txt'), 'w').close()
    open(os.path.join(subdir, 'nested.txt'), 'w').close()
    open(os.path.join(testdata_dir, 'outside.txt'), 'w').close()

    print_subheader("Absolute paths")

    # Standalone slash (root directory) - should ask
    test_command_with_cwd('ls /', project_dir, 'ask', "Standalone slash (root) blocked: ls /")

    # Absolute path inside project - should allow
    abs_inside = os.path.join(project_dir, 'file.txt')
    test_command_with_cwd(f'cat {abs_inside}', project_dir, 'allow', f"Absolute path inside project allowed: cat {abs_inside}")

    # Absolute path outside project - should ask
    abs_outside = os.path.join(testdata_dir, 'outside.txt')
    test_command_with_cwd(f'cat {abs_outside}', project_dir, 'ask', f"Absolute path outside project blocked: cat {abs_outside}")

    # /tmp directory - should allow
    test_command_with_cwd('ls /tmp/some-file.txt', project_dir, 'allow', "/tmp directory allowed: ls /tmp/some-file.txt")

    # /dev/null - should allow
    test_command_with_cwd('mkdir ./x/y/z > /dev/null', project_dir, 'allow', "/dev/null allowed: mkdir ./x/y/z > /dev/null")

    print_subheader("Parent directory references")

    # Parent dir from subdir - blocks because it escapes the cwd boundary
    test_command_with_cwd('cat ../file.txt', subdir, 'ask', "Parent dir from subdir blocked: cat ../file.txt (escapes cwd)")

    # Parent dir that escapes project - should ask
    test_command_with_cwd('cat ../outside.txt', project_dir, 'ask', "Parent dir escaping project blocked: cat ../outside.txt (from project)")

    # Parent dir in middle of path, stays inside cwd - should allow
    test_command_with_cwd('cat subdir/../file.txt', project_dir, 'allow', "Parent dir in middle of path, stays in cwd: cat subdir/../file.txt")

    # Parent dir in middle of path, escapes cwd - should ask
    test_command_with_cwd('cat subdir/../../outside.txt', project_dir, 'ask', "Parent dir in middle escapes cwd: cat subdir/../../outside.txt")

    print_subheader("Relative paths")

    # Simple relative path in project - should allow
    test_command_with_cwd('cat file.txt', project_dir, 'allow', "Relative path in project allowed: cat file.txt")

    # Subdirectory relative path - should allow
    test_command_with_cwd('cat subdir/nested.txt', project_dir, 'allow', "Subdirectory relative path allowed: cat subdir/nested.txt")

    print_subheader("Tilde expansion")

    # Tilde to home directory - should ask
    test_command_with_cwd('cat ~/.bashrc', project_dir, 'ask', "Tilde expansion blocked: cat ~/.bashrc")

    # Standalone tilde - should ask
    test_command_with_cwd('cat ~', project_dir, 'ask', "Standalone tilde blocked: cat ~")

    # Check if cwd is inside home directory
    home_dir = os.path.expanduser('~')
    if project_dir.startswith(home_dir + os.sep):
        # Calculate relative path from home to a file in project
        rel_from_home = os.path.relpath(os.path.join(project_dir, 'file.txt'), home_dir)
        tilde_path = os.path.join('~', rel_from_home)
        test_command_with_cwd(f'cat {tilde_path}', project_dir, 'allow', f"Tilde path inside project allowed: cat {tilde_path}")

    print_subheader("Edge cases")

    # Word with .. but no slash (not a path) - should allow
    test_command_with_cwd('echo foo..bar', project_dir, 'allow', "Non-path with .. allowed: echo foo..bar")

    # Redirects with paths
    redirect_file = os.path.join(project_dir, 'output.txt')
    test_command_with_cwd(f'echo test > {redirect_file}', project_dir, 'allow', "Redirect to absolute path in project allowed")

    # Clean up test data
    shutil.rmtree(testdata_dir)

    # ===== Summary =====
    print_header("Testing complete!")

    total_count = pass_count + fail_count
    print()
    print(f"Total tests: {total_count}")
    print(f"{Colors.GREEN}Passed: {pass_count}{Colors.NC}")
    print(f"{Colors.RED}Failed: {fail_count}{Colors.NC}")

    # Exit with appropriate code
    if fail_count == 0:
        print()
        print(f"{Colors.GREEN}All tests passed!{Colors.NC}")
        sys.exit(0)
    else:
        print()
        print(f"{Colors.RED}Some tests failed.{Colors.NC}")
        sys.exit(1)


if __name__ == '__main__':
    main()
