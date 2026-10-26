#!/usr/bin/env python3
"""Reject unsupervised Ninja/Siso launch sites in repository-owned tooling.

This regression check recognizes literal commands and simple assignments. It
is not a sandbox or a proof about arbitrarily generated command strings.
"""
from __future__ import annotations

import argparse
import ast
from pathlib import Path
import re
import shlex
import subprocess

ROOT = Path(__file__).resolve().parents[1]
# Exact functions only. Changes to this list require architecture review.
APPROVED = {('devutils/he/resources.py', 'build_command'),
            ('devutils/cloud_build/smoke.py', 'main'),
            ('devutils/command-bar-studio/sdk.py', 'build')}
READ_ONLY = {'commands', 'query', 'targets', 'graph', 'deps', 'inputs', 'compdb', 'list', 'rules'}
TOOLS = re.compile(r'^(?:ninja(?:-build)?|ninja\.py|autoninja(?:\.py)?|siso)(?:\.exe|\.bat)?$')
LAUNCH = {'run', 'Popen', 'call', 'check_call', 'check_output', 'execv', 'execve', 'execvp',
          'execvpe', 'execl', 'execlp', 'execlpe', 'system', 'create_subprocess_exec',
          'create_subprocess_shell'}


def executable(value):
    return value.replace('\\', '/').rsplit('/', 1)[-1]


def unsafe_command(words):
    """Inspect executable positions, preserving install/echo arguments."""
    words = list(words)
    while words and (words[0] in ('!', 'if', 'then', 'elif', 'else', 'do', '--', 'nohup')
                     or re.match(r'^\w+=', words[0])):
        words.pop(0)
    if not words:
        return False
    name = executable(words[0])
    if name in ('timeout', 'gtimeout', 'env', 'sudo', 'nice', 'command', 'exec', 'time'):
        words.pop(0)
        if name == 'command':
            for option in words:
                if option == '--' or not option.startswith('-'):
                    break
                if re.fullmatch(r'-[pvV]+', option) and ('v' in option or 'V' in option):
                    return False
        arguments = {'timeout': {'-k', '--kill-after', '-s', '--signal'},
                     'gtimeout': {'-k', '--kill-after', '-s', '--signal'},
                     'env': {'-u', '--unset', '-C', '--chdir'},
                     'sudo': {'-u', '--user', '-g', '--group', '-h', '--host', '-p', '--prompt',
                              '-C', '--close-from', '-r', '--role', '-t', '--type'},
                     'nice': {'-n', '--adjustment'}, 'exec': {'-a'},
                     'time': {'-f', '-o'}}.get(name, set())
        while words:
            if name == 'env' and (words[0] in ('-S', '--split-string') or
                                  words[0].startswith(('-S', '--split-string='))):
                option = words.pop(0)
                payload = words.pop(0) if option in ('-S', '--split-string') and words else (
                    option[2:] if option.startswith('-S') else option.partition('=')[2])
                try:
                    return unsafe_command([*shlex.split(payload), *words])
                except ValueError:
                    return False
            if words[0] in arguments:
                words = words[2:]
            elif words[0].startswith('-') or re.match(r'^\w+=', words[0]):
                words.pop(0)
            else:
                break
        if name in ('timeout', 'gtimeout'):
            words = words[1:]
        return unsafe_command(words)
    if re.fullmatch(r'(?:python[0-9.]*)', name) or name == '__DYNAMIC__':
        if '-c' in words:
            index = words.index('-c') + 1
            if index < len(words):
                try:
                    return bool(violations('<inline>.py', words[index]))
                except SyntaxError:
                    return False  # Dynamic shell substitutions are outside this check.
        # Python-launched autoninja.py and a dynamic Python interpreter path.
        for i, word in enumerate(words[1:], 1):
            if word == '-m':
                return False
            if TOOLS.fullmatch(executable(word)):
                return unsafe_command(words[i:])
    if name in ('bash', 'sh', 'zsh'):
        for index, word in enumerate(words[1:], 1):
            if re.fullmatch(r'-[A-Za-z]*c[A-Za-z]*', word):
                return bool(index + 1 < len(words) and shell_violations(words[index + 1]))
    if not TOOLS.fullmatch(name):
        return False
    args = words[1:]
    if args in (['--version'], ['-version'], ['--help'], ['-h'], ['help'], ['version']):
        return False
    subtools = []
    for i, arg in enumerate(args):
        if arg == '-t' and i + 1 < len(args):
            subtools.append(args[i + 1])
        elif arg.startswith('-t') and len(arg) > 2:
            subtools.append(arg[2:])
    return len(subtools) != 1 or subtools[0] not in READ_ONLY


def shell_violations(source):
    found, variables = [], {}
    logical, pending, start = [], '', 1
    for number, line in enumerate(source.splitlines(), 1):
        if not pending:
            start = number
        pending += line.rstrip('\\') if line.endswith('\\') else line
        if line.endswith('\\'):
            pending += ' '
        else:
            logical.append((start, pending))
            pending = ''
    if pending:
        logical.append((start, pending))
    for number, line in logical:
        # YAML run scalars and shell lines share executable token positions.
        yaml_run = bool(re.match(r'^\s*(?:-\s*)?run:', line))
        line = re.sub(r'^\s*(?:-\s*)?run:\s*', '', line)
        try:
            lexer = shlex.shlex(line, posix=True, punctuation_chars=';&|()')
            lexer.whitespace_split = True
            words = list(lexer)
        except ValueError:
            continue  # A multi-line shell literal is checked by its own lines.
        if yaml_run and len(words) == 1 and shell_violations(words[0]):
            found.append(number)
        command = []
        for word in [*words, ';']:
            if word in (';', '&&', '||', '|', '(', ')'):
                expanded = [re.sub(r'\$(?:\{(\w+)\}|(\w+))',
                                   lambda m: variables.get(m[1] or m[2], m[0]), w) for w in command]
                if unsafe_command(expanded):
                    found.append(number)
                for value in command:
                    match = re.fullmatch(r'(\w+)=(.*)', value)
                    if match:
                        variables[match[1]] = match[2]
                command = []
            else:
                command.append(word)
    return found


class PythonCommands(ast.NodeVisitor):
    def __init__(self, path):
        self.path, self.function, self.values, self.found = path, '', {}, set()
        self.aliases = {}

    def visit_ImportFrom(self, node):
        if node.module in ('subprocess', 'os', 'asyncio'):
            for item in node.names:
                self.aliases[item.asname or item.name] = item.name

    def value(self, node, seen=frozenset()):
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            return node.value
        if isinstance(node, ast.Name) and node.id not in seen and node.id in self.values:
            return self.value(self.values[node.id], seen | {node.id})
        if isinstance(node, (ast.List, ast.Tuple)):
            result = []
            for item in node.elts:
                value = self.value(item.value if isinstance(item, ast.Starred) else item, seen)
                result.extend(value if isinstance(value, list) else [value])
            return result
        if isinstance(node, ast.BinOp) and isinstance(node.op, (ast.Add, ast.Div)):
            left, right = self.value(node.left, seen), self.value(node.right, seen)
            if isinstance(left, list) and isinstance(right, list):
                return left + right
            return str(left) + ('/' if isinstance(node.op, ast.Div) else '') + str(right)
        if isinstance(node, ast.JoinedStr):
            return ''.join(str(self.value(v.value if isinstance(v, ast.FormattedValue) else v, seen))
                           for v in node.values)
        if isinstance(node, ast.Call) and node.args and isinstance(node.func, ast.Name) and node.func.id in ('str', 'Path'):
            return self.value(node.args[0], seen)
        return '__DYNAMIC__'

    def check(self, node):
        if (self.path, self.function) in APPROVED:
            return
        value = self.value(node)
        unsafe = unsafe_command(value) if isinstance(value, list) else shell_violations(value)
        if unsafe:
            self.found.add(node.lineno)

    def visit_FunctionDef(self, node):
        previous, values = self.function, self.values.copy()
        self.function = node.name
        self.generic_visit(node)
        self.function, self.values = previous, values

    visit_AsyncFunctionDef = visit_FunctionDef

    def visit_Assign(self, node):
        for target in node.targets:
            if isinstance(target, ast.Name):
                self.values[target.id] = node.value
        self.generic_visit(node)

    def visit_List(self, node):
        self.check(node)  # Also catch command builders passed to another module.
        self.generic_visit(node)

    visit_Tuple = visit_List

    def visit_Call(self, node):
        name = node.func.attr if isinstance(node.func, ast.Attribute) else getattr(node.func, 'id', '')
        name = self.aliases.get(name, name)
        if name in LAUNCH:
            command = node.args[0] if node.args else next((k.value for k in node.keywords if k.arg == 'args'), None)
            if command is not None:
                self.check(command)
        self.generic_visit(node)


def violations(path, source):
    if path.startswith('devutils/tests/') or '/fixtures/' in path:
        return []
    if path.endswith('.py'):
        visitor = PythonCommands(path)
        visitor.visit(ast.parse(source, filename=path))
        return sorted(visitor.found)
    if path.endswith('.md'):
        # Explanatory mentions are fine; executable fenced examples are checked.
        found, inside = [], False
        for number, line in enumerate(source.splitlines(), 1):
            if line.startswith('```'):
                inside = not inside
            elif inside and shell_violations(line):
                found.append(number)
        return found
    return sorted(set(shell_violations(source)))


def check(root):
    result = subprocess.run(['git', '-C', str(root), 'ls-files', '--cached', '--others',
                             '--exclude-standard', '-z'], capture_output=True, check=True)
    found = []
    for name in sorted(set(result.stdout.decode().split('\0')) - {''}):
        path = root / name
        if path.is_file() and path.suffix in ('.py', '.sh', '.yml', '.yaml', '.md'):
            for line in violations(name, path.read_text()):
                found.append(f'{name}:{line}: direct Ninja/Siso command; use he agent build or the release router')
    return found


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', type=Path, default=ROOT)
    args = parser.parse_args()
    found = check(args.root)
    print('\n'.join(found) if found else 'Build entry points: no unsupervised compiler launches found.')
    return bool(found)


if __name__ == '__main__':
    raise SystemExit(main())
