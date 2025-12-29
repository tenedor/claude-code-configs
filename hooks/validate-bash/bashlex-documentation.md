# Bashlex Library Documentation

This document explains how the `bashlex` library works and how our validation script uses it to parse bash commands.

## What `bashlex.parse()` returns

**Returns:** A **list of nodes** representing the top-level AST (Abstract Syntax Tree) of the bash command.

For most simple commands, this list contains a single node, but it can contain multiple nodes for certain constructs.

**Example:**
```python
import bashlex
parts = bashlex.parse("ls -la")
# Returns: [node(kind='command', ...)]
```

---

## All possible `node.kind` values

Based on empirical testing, here are all the node kinds discovered:

### Top-level/structural nodes:
- **`command`** - A simple command (e.g., `ls -la`)
- **`pipeline`** - Commands connected by pipes (e.g., `ls | grep foo`)
- **`list`** - Commands connected by `;`, `&&`, or `||`
- **`compound`** - Shell constructs like `{ }`, `( )`, if/for/while

### Control structures (appear inside compound):
- **`if`** - If statement
- **`for`** - For loop
- **`while`** - While loop
- **`function`** - Function definition

### Leaf/terminal nodes:
- **`word`** - A literal word, argument, or string
- **`parameter`** - Variable reference (e.g., `$HOME`)
- **`commandsubstitution`** - Command substitution (`` `cmd` `` or `$(cmd)`)
- **`redirect`** - Input/output redirection (`<`, `>`, `>>`, etc.)
- **`operator`** - Operators like `;`, `&&`, `||`
- **`pipe`** - The `|` operator
- **`reservedword`** - Shell keywords (`if`, `then`, `do`, etc.)

---

## Properties that store AST children

Different node kinds have different properties for storing child nodes:

| Node Kind | Child Properties | What They Store |
|-----------|-----------------|-----------------|
| `command` | `parts` | List of words and redirects making up the command |
| `pipeline` | `parts` | Commands separated by pipe operators |
| `list` | `parts` | Commands separated by operators (`;`, `&&`, `||`) |
| `compound` | `list` | The commands inside the compound construct |
| `if` / `for` / `while` | `parts` | All parts of the construct (keywords, conditions, body) |
| `word` | `parts` | Sub-components like parameter expansions or command substitutions |
| `commandsubstitution` | `command` | The parsed command inside the substitution |
| `redirect` | `output` | The target of the redirection |

---

## When `kind='command'`: Semantic meaning and structure

### Semantic Meaning

A `command` node represents a **simple command** - the basic unit of execution in bash. It's what you'd think of as "running a program with arguments."

### Structure of a command node

- **`parts` attribute:** An ordered list containing:
  1. **First element:** Always a `word` node with the command name (e.g., `'ls'`, `'git'`, `'npm'`)
  2. **Remaining elements:** Zero or more of:
     - `word` nodes for arguments/flags (e.g., `'-la'`, `'add'`, `'-A'`)
     - `redirect` nodes for I/O redirection (e.g., `<`, `>`)

### Examples

```
"ls" → command.parts = [word('ls')]

"ls -la" → command.parts = [word('ls'), word('-la')]

"git add -A" → command.parts = [word('git'), word('add'), word('-A')]

"cat < in.txt > out.txt" → command.parts = [word('cat'), redirect, redirect]
```

### Important Note about Word Nodes

Each `word` node can itself contain children (in its `parts` attribute) for things like:
- **Variable expansions:** `word('$HOME')` has a child `parameter` node
- **Command substitutions:** ``word('`pwd`')`` has a child `commandsubstitution` node

This is why the validation script finds backticks in `ls \`pwd\`` - the backticks are preserved in the word's text, and the word also has a `commandsubstitution` child node.

---

## Examples of AST Structure

### Simple Command
```
Command: "ls -la"

Node(kind=command)
  parts: [2 items]
    Node(kind=word)
      word: 'ls'
    Node(kind=word)
      word: '-la'
```

### Pipeline
```
Command: "ls | grep foo"

Node(kind=pipeline)
  parts: [3 items]
    Node(kind=command)
      parts: [1 items]
        Node(kind=word)
          word: 'ls'
    Node(kind=pipe)
    Node(kind=command)
      parts: [2 items]
        Node(kind=word)
          word: 'grep'
        Node(kind=word)
          word: 'foo'
```

### List with Operators
```
Command: "ls && echo ok"

Node(kind=list)
  parts: [3 items]
    Node(kind=command)
      parts: [1 items]
        Node(kind=word)
          word: 'ls'
    Node(kind=operator)
    Node(kind=command)
      parts: [2 items]
        Node(kind=word)
          word: 'echo'
        Node(kind=word)
          word: 'ok'
```

### Command with Substitution
```
Command: "echo `pwd`"

Node(kind=command)
  parts: [2 items]
    Node(kind=word)
      word: 'echo'
    Node(kind=word)
      word: '`pwd`'
      parts: [1 items]
        Node(kind=commandsubstitution)
```

---

## How Our Validation Script Uses Bashlex

The `run.py` script uses bashlex to:

1. **Parse compound commands** that contain `|`, `&&`, `||`, or `;`
2. **Extract individual commands** by recursively walking the AST looking for nodes with `kind='command'`
3. **Validate each component** by checking:
   - If the command matches an approved pattern (e.g., `git add:*`)
   - If the command or its arguments contain dangerous patterns (absolute paths, `..`, etc.)
   - If the arguments contain shell metacharacters (like backticks in words)

This allows us to auto-approve compound commands like `ls | tail -n 20` when both `ls` and `tail` are approved, while still blocking dangerous combinations like `ls; rm -rf /`.
