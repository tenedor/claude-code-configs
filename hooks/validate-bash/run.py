#!/usr/bin/env python3
"""
Bash command validation hook for Claude Code.
Validates bash commands to prevent dangerous operations and restrict file access.
"""

import sys
import json
import re
import os
from datetime import datetime

try:
    import bashlex
    BASHLEX_AVAILABLE = True
except ImportError:
    BASHLEX_AVAILABLE = False


def load_approved_patterns():
    """Load approved command patterns from JSON file."""
    script_dir = os.path.dirname(os.path.abspath(__file__))
    patterns_file = os.path.join(script_dir, 'approved-patterns.json')

    try:
        with open(patterns_file, 'r') as f:
            data = json.load(f)
            return data.get('patterns', [])
    except Exception as e:
        # If we can't load the patterns file, return empty list
        # Note: Can't use log_debug here as it's not defined yet
        print(f"ERROR loading approved patterns: {e}", file=sys.stderr)
        return []


# Load approved patterns from JSON file
APPROVED_PATTERNS = load_approved_patterns()


def log_debug(message):
    """Log debug message to file."""
    try:
        with open('/tmp/claude-hook-debug.log', 'a') as f:
            f.write(f"=== Hook called at {datetime.now()} ===\n")
            f.write(f"{message}\n\n")
    except:
        pass


def send_permission_response(decision, reason, command):
    """Send permission response as JSON."""
    log_debug(f"DECISION: {decision} - {reason}\nCOMMAND WAS: {command}")

    response = {
        "hookSpecificOutput": {
            "hookEventName": "PreToolUse",
            "permissionDecision": decision
        }
    }

    # Only include reason when not approved
    if decision != "allow":
        response["hookSpecificOutput"]["permissionDecisionReason"] = reason

    print(json.dumps(response))


def defer_permission_decision(command):
    """Pass on making a permissioning decision, deferring to other rules."""
    log_debug(f"DECISION: defer\nCOMMAND WAS: {command}")
    # Exit with code 0 and no output = defer


def validate_text_for_dangerous_patterns(text, context_name):
    """
    Check a text string (filename, argument, etc.) for dangerous patterns.
    Returns (is_safe, violation_message).
    """
    # Check for absolute paths
    if re.search(r'(^|\s)/', text):
        return False, f"{context_name} uses absolute path"

    # Check for parent directory access
    if '..' in text:
        return False, f"{context_name} accesses parent directory"

    # Check for tilde expansion
    if '~' in text:
        return False, f"{context_name} uses tilde expansion"

    # Check for .git access
    if '.git' in text:
        return False, f"{context_name} accesses .git files"

    return True, None


def matches_pattern(command_name, command_args, pattern):
    """
    Check if a command matches an approval pattern.

    Pattern formats:
    - "command:*" - matches command with any args
    - "command" - matches command with no args
    - "command subcommand:*" - matches command with subcommand and any additional args
    - "npm run build:*" - matches "npm" with args starting with "run build"
    """
    # Split pattern into command part and args part
    if ':' in pattern:
        pattern_cmd_part, pattern_args_wildcard = pattern.split(':', 1)
    else:
        pattern_cmd_part = pattern
        pattern_args_wildcard = ''

    # Split the command part into command and required args/subcommand
    pattern_parts = pattern_cmd_part.split()
    pattern_cmd = pattern_parts[0]
    pattern_required_args = ' '.join(pattern_parts[1:]) if len(pattern_parts) > 1 else ''

    # Check if command name matches
    if command_name != pattern_cmd:
        return False

    # If pattern has required args (e.g., "git add"), check if command args start with them
    if pattern_required_args:
        if not command_args.startswith(pattern_required_args):
            return False

        # If the pattern ends with :*, any additional args after the required part are allowed
        if pattern_args_wildcard == '*':
            return True

        # Otherwise, args must match exactly (required args only, no additional args)
        return command_args == pattern_required_args

    # No required args in pattern
    # If pattern has no args or args is "*", it matches anything
    if not pattern_args_wildcard or pattern_args_wildcard == '*':
        return True

    # Otherwise, check if args match exactly
    return command_args == pattern_args_wildcard


class CommandContext:
    """
    Represents a parsed command with its semantic context.
    Stores command name, parts, arguments, and AST node reference.
    """
    def __init__(self, name, parts, node):
        self.name = name
        self.parts = parts  # List of word parts (includes command name)
        self.node = node
        self.args = ' '.join(parts[1:]) if len(parts) > 1 else ''
        self.full_command = ' '.join(parts)


class BashASTVisitor:
    """
    Visitor pattern for traversing bashlex AST.

    Performs semantic analysis in a single pass over the AST, collecting:
    - All commands with their arguments
    - Dangerous patterns (background tasks, variable expansions, etc.)
    - Redirect targets for validation
    - Contextual information about where tokens appear

    This replaces multiple separate recursive traversals with a single unified visitor.
    """

    def __init__(self):
        # Collected command information
        self.commands = []  # List of CommandContext objects

        # Validation violations found during traversal
        self.violations = []

        # Semantic checks (boolean flags)
        self.has_background = False
        self.has_var_expansion = False
        self.has_process_sub = False

        # Context tracking for semantic awareness
        self.in_command_substitution = False
        self.in_redirect = False

    def visit(self, node):
        """
        Dispatch to appropriate visit method based on node kind.
        This is the main entry point for traversing the AST.
        """
        kind = getattr(node, 'kind', None)
        if kind:
            method_name = f'visit_{kind}'
            visitor = getattr(self, method_name, self.generic_visit)
            return visitor(node)
        return self.generic_visit(node)

    def generic_visit(self, node):
        """
        Default visitor: traverse all children.
        This handles any node types we don't have specific visitors for.
        """
        if hasattr(node, 'parts') and node.parts:
            for part in node.parts:
                self.visit(part)
        if hasattr(node, 'list') and node.list:
            for item in node.list:
                self.visit(item)
        if hasattr(node, 'command') and node.command:
            self.visit(node.command)

    def visit_command(self, node):
        """
        Visit a command node and extract command information.

        A command node represents an actual executable command with its arguments.
        We extract the command name and all word arguments, storing them as a
        CommandContext for later validation.
        """
        if hasattr(node, 'parts') and node.parts:
            first_part = node.parts[0]
            if hasattr(first_part, 'word'):
                cmd_name = first_part.word
                # Extract only word parts (filter out redirects, which are separate nodes)
                cmd_parts = []
                for part in node.parts:
                    if hasattr(part, 'word'):
                        cmd_parts.append(part.word)

                self.commands.append(CommandContext(cmd_name, cmd_parts, node))

        # Continue traversing children (for redirects, etc.)
        self.generic_visit(node)

    def visit_redirect(self, node):
        """
        Visit a redirect node and validate the target path.

        Redirects (>, >>, <, etc.) can write to or read from files.
        We need to ensure redirect targets don't escape the project directory.
        """
        old_in_redirect = self.in_redirect
        self.in_redirect = True

        if hasattr(node, 'output') and node.output:
            if hasattr(node.output, 'word'):
                target = node.output.word
                is_safe, violation = validate_text_for_dangerous_patterns(
                    target, "redirect target"
                )
                if not is_safe:
                    self.violations.append(violation)

        # Visit children
        self.generic_visit(node)
        self.in_redirect = old_in_redirect

    def visit_operator(self, node):
        """
        Visit an operator node.

        Operators include &, &&, ||, ;, |, etc.
        We specifically check for & (background execution).
        """
        op = getattr(node, 'op', None)
        if op == '&':
            self.has_background = True

        # Visit children
        self.generic_visit(node)

    def visit_parameter(self, node):
        """
        Visit a parameter node (variable expansion like $VAR or ${VAR}).

        Variable expansions are dangerous because they can contain absolute paths,
        commands, or other unsafe content that bypasses our static analysis.
        """
        self.has_var_expansion = True

        # Visit children
        self.generic_visit(node)

    def visit_processsubstitution(self, node):
        """
        Visit a process substitution node (<() or >()).

        Process substitution spawns parallel processes and can hide command execution.
        """
        self.has_process_sub = True

        # Visit children
        self.generic_visit(node)

    def visit_commandsubstitution(self, node):
        """
        Visit a command substitution node ($(cmd) or `cmd`).

        Command substitutions execute commands and capture their output.
        We track this context to understand semantic meaning of nested commands.
        Note: These are currently blocked by has_commandsubstitution check,
        but we handle them for completeness.
        """
        old_in_subst = self.in_command_substitution
        self.in_command_substitution = True

        # Visit the command inside the substitution
        if hasattr(node, 'command') and node.command:
            self.visit(node.command)

        self.in_command_substitution = old_in_subst

    def visit_word(self, node):
        """
        Visit a word node (literal text token).

        Word nodes are leaf nodes containing actual text.
        The semantic meaning depends on context (command name, argument, redirect target, etc.)
        which we track through our context flags.
        """
        # Word nodes are typically leaves, but we'll be defensive
        self.generic_visit(node)

    def visit_compound(self, node):
        """
        Visit a compound command node (if/while/for/case statements).

        These are control flow structures that contain other commands.
        """
        self.generic_visit(node)

    def visit_pipeline(self, node):
        """
        Visit a pipeline node (commands connected with |).

        Pipelines are allowed - we just need to validate each command in the pipeline.
        """
        self.generic_visit(node)

    def visit_list(self, node):
        """
        Visit a list node (commands separated by ; or && or ||).

        Lists represent sequential execution of commands.
        """
        self.generic_visit(node)


def check_command(command):
    """
    Check if a compound command (with pipes, &&, etc.) is approved.
    Returns (decision, reason).

    decision can be:
    - "allow": command is approved
    - "ask": command requires user permission (default for violations)
    - "deny": command is invalid and should be rejected with instructions

    Uses BashASTVisitor to perform semantic analysis in a single pass.
    """
    if not BASHLEX_AVAILABLE:
        return "ask", "bashlex not available - cannot parse compound commands"

    # TODO: Implement a user-configurable, flexible flag permissions model.

    # Dangerous flags that enable arbitrary code execution
    # These require user permission regardless of which command uses them
    DANGEROUS_EXEC_FLAGS = {
        '--command',
        '-exec',
        '--exec',
        '--execute',
        '--eval'
    }

    try:
        # Parse the bash command into AST
        parts = bashlex.parse(command)

        # Create visitor and traverse the AST
        visitor = BashASTVisitor()
        for part in parts:
            visitor.visit(part)

        # Check for dangerous patterns found during traversal
        if visitor.has_background:
            return "ask", "contains backgrounded task (&). Background processes require permission."

        if visitor.has_var_expansion:
            return "ask", "contains variable expansion ($VAR or ${VAR}). Variables could reference dangerous paths."

        if visitor.has_process_sub:
            return "ask", "contains process substitution (<() or >()). Process substitution spawns parallel processes."

        # Check each command found during traversal
        for cmd_ctx in visitor.commands:
            # Validate command arguments for dangerous patterns
            is_safe, violation = validate_text_for_dangerous_patterns(
                cmd_ctx.full_command,
                f"'{cmd_ctx.name}'"
            )
            if not is_safe:
                visitor.violations.append(violation)
                continue

            # Check for dangerous code execution flags
            # Note: This is a simple substring check and may have false positives
            # (e.g., `echo --exec` will trigger this check)
            # False positives are acceptable since we're asking for permission, not blocking
            for arg in cmd_ctx.parts[1:]:  # Skip command name, check arguments only
                if arg in DANGEROUS_EXEC_FLAGS:
                    visitor.violations.append(
                        f"'{cmd_ctx.name}' uses dangerous flag '{arg}' (enables arbitrary code execution)"
                    )
                    break

            # Check if this command matches approved patterns
            is_approved = False
            for pattern in APPROVED_PATTERNS:
                if matches_pattern(cmd_ctx.name, cmd_ctx.args, pattern):
                    is_approved = True
                    break

            if not is_approved:
                visitor.violations.append(f"'{cmd_ctx.name}' not in approved list")

        # Combine all violations
        if not visitor.violations:
            return "allow", ""
        else:
            # Format violations nicely
            if len(visitor.violations) == 1:
                return "ask", visitor.violations[0]
            else:
                formatted = "multiple issues: " + " ".join([f"{i+1}. {v}." for i, v in enumerate(visitor.violations)])
                return "ask", formatted

    except Exception as e:
        error_msg = str(e)

        # Check if this is a heredoc parsing error with quoted delimiters
        # Error format: "here-document at line X delimited by end-of-file (wanted 'DELIM' or "DELIM")"
        if "here-document" in error_msg and "wanted" in error_msg:
            # Check if the command contains quoted heredoc delimiters
            if re.search(r'<<-?\s*["\'][A-Za-z_][A-Za-z0-9_]*["\']', command):
                return "deny", (
                    "heredoc with quoted delimiter detected (e.g., <<'EOF' or <<\"EOF\"). "
                    "The bash parser cannot handle quoted heredoc delimiters. "
                    "Please rewrite the command using an unquoted heredoc delimiter (e.g., <<EOF) instead. "
                    "Note: Unquoted heredocs still prevent variable expansion when the content is properly quoted."
                )

        return "ask", f"failed to parse compound command: {error_msg}"


def validate_command(command):
    """
    Validate a bash command.
    Returns: None to defer, or calls send_permission_response() and returns True.
    """
    # Block null bytes (no legitimate use, could confuse parser)
    if '\x00' in command:
        send_permission_response("ask", "contains null byte", command)
        return True

    # Warn about escape sequences (potential log obfuscation, but not blocking)
    if '\x1b' in command:
        log_debug(f"WARNING: Command contains escape sequences (potential log obfuscation): {command}")

    # Semantic command validation
    decision, reason = check_command(command)
    send_permission_response(decision, reason, command)
    return True


def main():
    """Main entry point."""
    # Read hook input from stdin
    try:
        input_data = json.load(sys.stdin)
        log_debug(json.dumps(input_data, indent=2))
    except Exception as e:
        log_debug(f"ERROR reading input: {e}")
        sys.exit(1)

    # Extract tool name and command
    tool_name = input_data.get('tool_name', '')
    command = input_data.get('tool_input', {}).get('command', '')

    # Only validate Bash commands
    if tool_name != "Bash":
        defer_permission_decision(command)
        sys.exit(0)

    # Validate the command
    result = validate_command(command)

    # If result is None, defer (exit 0 with no output)
    if result is None:
        defer_permission_decision(command)
        sys.exit(0)

    # Otherwise, we already sent the response
    sys.exit(0)


if __name__ == '__main__':
    main()
