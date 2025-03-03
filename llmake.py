###
# Copyright 2024 Massimo Fioravanti

# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at

   # http://www.apache.org/licenses/LICENSE-2.0

# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
###

import tokenize
import argparse
from io import BytesIO
import os
import sys
import filecmp
from sys import stderr, stdout
from tempfile import NamedTemporaryFile
from dataclasses import dataclass, field
import shutil
import pathlib

# dictonary to make tokens more clear to users
TOKEN_NAMES = {
    "colons": "':'",
    "comma": "','",
    "period": "'.'",
    "indent": "INDENT (⏩ expected indentation)",
    "deindent": "DEDENT (⏪ expected dedentation)",
    "newline": "NEWLINE (expected end of line)",
    "string": 'a "string" (e.g., "text here")',
    "name": "a NAME (e.g., variable or keyword)"
}

# ParseError Exception
class ParseError(Exception):
    def __init__(self, message, token=None, source_lines=None):
        # Custom exception for parsing errors, including token information and source lines.
        self.message = message
        self.token = token
        self.source_lines = source_lines
        super().__init__(message)

    def __str__(self):
        """
        Formats the error message to include line/column details,
        shows the exact line from the source, and marks the error column with ^.
        """
        base_msg = f"ParseError: {self.message}"

        if self.token and hasattr(self.token, 'start') and self.source_lines:
            line_num, col_num = self.token.start  # 1-based line, 0-based col
            token_type = tokenize.tok_name.get(self.token.type, "UNKNOWN")

            # Ensure line_num is within the source_lines range
            if 1 <= line_num <= len(self.source_lines):
                line_content = self.source_lines[line_num - 1]
            else:
                line_content = ""

            # Clamp col_num if it's beyond line length
            if col_num > len(line_content):
                col_num = len(line_content)

            # Construct a pointer line with ^
            pointer_line = " " * col_num + "^"

            # Return a more detailed error
            return (
                f"ParseError (line {line_num}, column {col_num}): {self.message} "
                f"– got token {self.token.string!r} (type: {token_type})\n"
                f"  {line_content}\n"
                f"  {pointer_line}\n"
            )
        else:
            return base_msg


def copy_if_different(src, dst):
    # Check if the destination file exists
    if not os.path.exists(dst) or not filecmp.cmp(src, dst, shallow=False):
        # If the file doesn't exist or is different, copy it
        shutil.copy2(src, dst)  # shutil.copy2 preserves metadata

def dependency_to_str(dep):
    if "." in dep:
        return dep
    return dep + ".txt"


@dataclass
class Entry:
    name: str
    dependencies: list  # list of dependency names (str)
    text: str
    source_position: list
    llm_commands: list = field(default_factory=list)       # List of custom LLM invocation commands
    validator_commands: list = field(default_factory=list)  # List of commands to validate output
    auto_retry: int = 0                                     # Maximum number of retry attempts (0 means no auto-retry)


    def to_make(self, out, prompts_file):
        if self.name.startswith("_"):
            return
        script = pathlib.Path(__file__)
        dep = " ".join(dependency_to_str(dep) for dep in self.dependencies if not dep.startswith("_"))
        out.write(f"{self.name}.prompt: {prompts_file} {dep}\n")
        out.write(f"\t{sys.executable} {script} {prompts_file} {self.name} -o {self.name}.prompt\n\n")
        out.write(f"{self.name}.txt: {self.name}.prompt\n")
        command_lines = []

        # append commands and validators in a command list
        if self.llm_commands:
            for cmd in self.llm_commands:
                command_lines.append(cmd.format(name=self.name))
        else:
            # run the default command
            default_cmd = f"ollama run deepseek-r1:14b < {self.name}.prompt | tee {self.name}.txt"
            command_lines.append(default_cmd)
            command_lines.append(f"sed -i '1,/<\\/think>/d' {self.name}.txt")

        if self.validator_commands:
            for vcmd in self.validator_commands:
                command_lines.append(vcmd.format(name=self.name))

        # join all commands
        combined_cmd = " && ".join(command_lines)

        # retry logic implementation
        if self.auto_retry > 0:
            out.write("\t@retry=0; max_retry={0}; \\\n".format(self.auto_retry))
            out.write("\tuntil ( {0} ); do \\\n".format(combined_cmd))
            out.write("\t\tretry=$$((retry+1)); \\\n")
            out.write("\t\techo \"Validation failed, retrying ($$retry/$$max_retry)\"; \\\n")
            out.write("\t\tif [ $$retry -ge $$max_retry ]; then echo \"Maximum retry attempts reached\"; exit 1; fi; \\\n")
            out.write("\tdone\n")
        else:
            for line in command_lines:
                out.write(f"\t{line}\n")
        out.write("\n")


@dataclass
class Prompts:
    entries: dict

    def validate_dependencies(self):
        for name, entry in self.entries.items():
            for dep in entry.dependencies:
                if dep == name:
                    stderr.write(f"Error: {entry.source_position} prompt {name} names itself as a dependency.\n")
                    return False
                if dep not in self.entries and "." not in dep:
                    stderr.write(f"Error: {entry.source_position} dependency {dep} in prompt {entry.name} does not exist.\n")
                    return False
        return True
    
    def inherit_properties(self):
        """
        Inherit commands, validators, and auto_retry from a single parent if
        the child doesn't define them. For auto_retry, if multiple parents define it,
        we take the maximum value instead of raising an error.
        """
        # 1. Build adjacency for topological sort
        deps_graph = {}
        indeg = {}
        for name in self.entries:
            deps_graph[name] = []
            indeg[name] = 0

        # For each child, add edge (parent -> child)
        for child_name, entry in self.entries.items():
            for parent_name in entry.dependencies:
                if "." not in parent_name:  # ignore file-based dependencies
                    deps_graph[parent_name].append(child_name)
                    indeg[child_name] += 1

        # 2) Topological sort
        queue = [n for n in self.entries if indeg[n] == 0]
        topo_order = []
        while queue:
            node = queue.pop()
            topo_order.append(node)
            for nxt in deps_graph[node]:
                indeg[nxt] -= 1
                if indeg[nxt] == 0:
                    queue.append(nxt)

        # Prepare to store final resolved properties
        resolved_cmds = {}
        resolved_validators = {}
        resolved_retry = {}

        # 3. Inherit logic
        for name in topo_order:
            entry = self.entries[name]

            # ---------- Commands ----------
            if entry.llm_commands:
                resolved_cmds[name] = entry.llm_commands
            else:
                # gather from parents
                parents_with_cmds = []
                for parent_name in entry.dependencies:
                    if "." in parent_name:
                        continue
                    p_cmds = resolved_cmds.get(parent_name, [])
                    if p_cmds:
                        parents_with_cmds.append(p_cmds)

                if len(parents_with_cmds) > 1:
                    stderr.write(f"Error: multiple parents of '{name}' define commands. Ambiguous.\n")
                    return False
                elif len(parents_with_cmds) == 1:
                    resolved_cmds[name] = parents_with_cmds[0]
                else:
                    resolved_cmds[name] = []

            # ---------- Validators ----------
            if entry.validator_commands:
                resolved_validators[name] = entry.validator_commands
            else:
                parents_with_validators = []
                for parent_name in entry.dependencies:
                    if "." in parent_name:
                        continue
                    p_valids = resolved_validators.get(parent_name, [])
                    if p_valids:
                        parents_with_validators.append(p_valids)

                if len(parents_with_validators) > 1:
                    stderr.write(f"Error: multiple parents of '{name}' define validators. Ambiguous.\n")
                    return False
                elif len(parents_with_validators) == 1:
                    resolved_validators[name] = parents_with_validators[0]
                else:
                    resolved_validators[name] = []

            # ---------- Auto-Retry (TAKE MAX) ----------
            if entry.auto_retry > 0:
                # Child defines a retry
                resolved_retry[name] = entry.auto_retry
            else:
                # Collect all non-zero parent retries
                parent_retries = []
                for parent_name in entry.dependencies:
                    if "." in parent_name:
                        continue
                    p_retry = resolved_retry.get(parent_name, 0)
                    if p_retry > 0:
                        parent_retries.append(p_retry)

                if parent_retries:
                    # TAKE THE MAX if multiple parents define different retry
                    resolved_retry[name] = max(parent_retries)
                else:
                    resolved_retry[name] = 0

        # 4) Write the resolved properties back into each entry
        for name in self.entries:
            self.entries[name].llm_commands = resolved_cmds[name]
            self.entries[name].validator_commands = resolved_validators[name]
            self.entries[name].auto_retry = resolved_retry[name]

        return True


    def get_prompt(self, name):
        prompts = []
        frontier = [name]
        explored = {}
        while frontier:
            current_name = frontier.pop(0)
            if current_name not in self.entries and "." not in current_name:
                stderr.write(f"Error: no known prompt {current_name}\n")
                return None
            if "." not in current_name:
                entry = self.entries[current_name]
                if entry.name in explored:
                    continue
                # skipp over dependencies that name files on disk
                explored[entry.name] = entry
                for dependency in entry.dependencies:
                    frontier.append(dependency)
            if (current_name == name or current_name.startswith("_")) and not "." in current_name:
                entry = self.entries[current_name]
                prompts.append(entry.text)
            else:
                with open(dependency_to_str(current_name), "r") as file:
                    prompts.append("\n\t".join(file.readlines()))
                    prompts.append(current_name + ":")
        return reversed(prompts)

    def to_make(self, out, prompts_file):
        out.write(".PHONY: all clean\n")
        out.write("all:")
        out.write(" ".join(name+".txt" for name in self.entries if not name.startswith("_")) + "\n")
        out.write("clean:\n\t rm -f ")
        out.write(" ".join(name+".txt "+name+".prompt" for name in self.entries if not name.startswith("_")) + "\n")
        
        for name, entry in self.entries.items():
            entry.to_make(out, prompts_file)


class Parser:
    def __init__(self, text):

        # snapshot of the original lines for error display
        self.source_lines = text.splitlines()  
        
        self.tokens = [token for token in tokenize.tokenize(BytesIO(text.encode('utf-8')).readline)]
        self.index = 1
        self.current = self.tokens[1]

    def next(self):
        self.index += 1
        if len(self.tokens) != self.index:
            self.current = self.tokens[self.index]

    def name(self):
        if self.current.type != tokenize.NAME:
            return None
        return self.current.string

    def colons(self):
        return self.current.type == tokenize.OP and self.current.string == ':'

    def newline(self):
        return self.current.type in (tokenize.NEWLINE, tokenize.NL)

    def string(self):
        if self.current.type != tokenize.STRING:
            return None
        return self.current.string[1:-1]

    def end(self):
        return self.current.type == tokenize.ENDMARKER

    def indent(self):
        return self.current.type == tokenize.INDENT

    def period(self):
        return self.current.type == tokenize.OP and self.current.string == '.'

    def comma(self):
        return self.current.type == tokenize.OP and self.current.string == ','

    def deindent(self):
        return self.current.type == tokenize.DEDENT

    def accept(self, element):
        to_return = element()
        if to_return:
            self.next()
        return to_return

    # Ensures the expected element is present; raises ParseError if not
    def expect(self, element):
        to_return = element()
        if not to_return:
            expected_name = element.__name__
            expected_symbol = TOKEN_NAMES.get(expected_name, expected_name)  # use dictionary
            raise ParseError(
                f"Expected {expected_symbol} – got token {self.current.string!r} (type: {tokenize.tok_name[self.current.type]})",
                token=self.current,
                source_lines=self.source_lines
            )
        self.next()
        return to_return

    def parse_depency(self):
        text = self.expect(self.name)
        while self.accept(self.period):
            text = text + "."
            text = text + self.expect(self.name)
        return text

    def parse_entry(self):
        position = self.current.start
        name = self.expect(self.name)          # e.g. 'landscape'
        self.expect(self.colons)              # the colon after name

        # Dependencies
        dependencies = []
        if not self.accept(self.newline):
            while True:
                dependencies.append(self.parse_depency())
                if not self.accept(self.comma):
                    break
            self.expect(self.newline)

        # Expect indent
        self.expect(self.indent)

        # Skip extra blank lines
        while self.current.type in (tokenize.NEWLINE, tokenize.NL):
            self.next()

        # The first line in this syntax MUST be the string for text
        field_text = self.expect(self.string)
        fields = {'text': field_text}

        # Parse the rest of the lines: command, validator, etc.
        while self.current.type != tokenize.DEDENT:
            if self.accept(self.newline):
                continue

            key = self.expect(self.name)      # e.g. 'validator', 'command', etc.
            self.expect(self.colons)
            line_str = self.expect(self.string)

            # special check if the key == 'validator'
            if key == 'validator':
                # By default, we do not have a retry
                line_retry = 0

                # Check if there's a trailing 'retry' <number>
                # We'll accept the next token if it is 'retry'
                if self.accept(self.name) == 'retry':
                    # Next token must be a number
                    if self.current.type == tokenize.NUMBER:
                        line_retry = int(self.current.string)
                        self.next()
                    else:
                        raise ParseError("Expected a number after 'retry'", self.current)

                # store the command (line_str) in fields['validator']
                # store multiple validators in a list
                # we store each validator as a dict with 'command' & 'retry'
                if 'validator' not in fields:
                    fields['validator'] = []
                fields['validator'].append({'cmd': line_str, 'retry': line_retry})

                # Set auto_retry to the largest
                if line_retry > 0:
                    # if the user had a previous auto_retry, pick the max
                    old_retry = int(fields.get('auto_retry', 0))
                    fields['auto_retry'] = str(max(old_retry, line_retry))

            else:
                # Normal key: e.g. "command"
                # If it's command, we do the usual append
                if key not in fields:
                    fields[key] = line_str
                else:
                    # if key is repeated, store as list
                    if isinstance(fields[key], list):
                        fields[key].append(line_str)
                    else:
                        fields[key] = [fields[key], line_str]

            # skip extra newlines
            while self.accept(self.newline):
                pass

        # Expect deindent
        self.expect(self.deindent)

        # Build final data
        # Check if there's 'text'
        if 'text' not in fields:
            raise ParseError("Missing 'text' field in entry.", self.current)

        # Convert 'command' fields to a list
        llm_commands = []
        if 'command' in fields:
            if isinstance(fields['command'], list):
                llm_commands = fields['command']
            else:
                llm_commands = [fields['command']]

        # Convert 'validator' fields into a dictionary 
        validator_commands = []
        if 'validator' in fields:
            # we stored each validator as {'cmd': ..., 'retry': ...}
            # we want the command strings for each validator
            # the retry is handled in auto_retry
            v_list = fields['validator']
            if not isinstance(v_list, list):
                v_list = [v_list]
            for v_obj in v_list:
                validator_commands.append(v_obj['cmd'])

        # If user typed a raw number in auto_retry, parse it
        auto_retry = int(fields['auto_retry']) if 'auto_retry' in fields else 0

        return Entry(
            name,
            dependencies,
            fields['text'],
            position,
            llm_commands=llm_commands,
            validator_commands=validator_commands,
            auto_retry=auto_retry
        )

    def parse_entries(self):
        entries = {}
        while not self.accept(self.end):
            while self.accept(self.newline):
                pass
            entry = self.parse_entry()
            if entry.name in entries:
                stderr.write(f"Error: Multiple definitions of prompt {entry.name}.\n")
                return None
            entries[entry.name] = entry
        return Prompts(entries)


def main():
    parser_arg = argparse.ArgumentParser(description="Load and display content of a text file.")
    parser_arg.add_argument("file", type=str, help="Path to prompts file")
    parser_arg.add_argument("prompt", type=str, help="Prompt to print", default="", nargs="?")
    parser_arg.add_argument("--makefile", help="generate a make file", default=False, action="store_true")
    parser_arg.add_argument("-o", help="output", default="-")

    args = parser_arg.parse_args()
    content = ""
    try:
        with open(args.file, 'r') as file:
            content = file.read()
    except FileNotFoundError:
        print(f"Error: File '{args.file}' not found.")
    except IOError as e:
        print(f"Error reading file '{args.file}': {e}")

    output = stdout if args.o == "-" else NamedTemporaryFile("w+")

    parser_obj = Parser(content)
    try:
        prompts = parser_obj.parse_entries()
    except ParseError as pe:
        stderr.write(str(pe) + "\n")
        exit(1)
    if not prompts:
        exit(1)
    if not prompts.validate_dependencies():
        exit(1)
    if not prompts.inherit_properties():
        exit(1)

    if args.makefile:
        prompts.to_make(output, args.file)
        output.flush()
        if args.o != "-":
            copy_if_different(output.name, args.o)
        exit(0)
    if args.prompt == "":
        for entry in prompts.entries:
            print(entry)
        exit(0)
    prompt = prompts.get_prompt(args.prompt)
    if not prompt:
        exit(1)
    output.write("\n\n".join(prompt))
    output.flush()
    if args.o != "-":
        copy_if_different(output.name, args.o)
    exit(0)

if __name__ == "__main__":
    main()




'''
-----------------Good prompt-----------------

_global:
    "This is a shared context that will apply to multiple prompts."
    command: "ollama run deepseek-r1:14b < {name}.prompt | tee {name}.txt"

landscape: _global
    "Describe a natural landscape with mountains and rivers."
    validator: "grep -q 'mountains' {name}.txt" retry 2

village: landscape
    "Describe a small village inside the previously described landscape."
    validator: "grep -q 'village' {name}.txt" retry 3

people: village
    "Describe the people living in the previously described village."
    command: "ollama run deepseek-r1:14b < {name}.prompt | tee {name}.txt"
    validator: "grep -q 'people' {name}.txt" retry 2

    

-----------------Bad prompt-----------------

city:
    "Describe a futuristic city"
    command "ollama run deepseek-r1:14b < {name}.prompt | tee {name}.txt" 
    validator: "grep -q 'city' {name}.txt"

forest: city
    command: "ollama run deepseek-r1:14b < {name}.prompt | tee {name}.txt"
    "Describe the nearby forest"

Missing colons (':') after "command".
Text "Describe the nearby forest" should be before everithing else


  
-----------------Example hierarchy-----------------

_global:
    "This is a shared context that will apply to multiple prompts."
    command: "ollama run deepseek-r1:14b < {name}.prompt | tee {name}.txt"
    command: "ollama run mistral < {name}.prompt | tee {name}.alt.txt"

landscape: _global
    "Describe a natural landscape with mountains, rivers, and forests."
    # No 'command:' lines => inherits from _global

desert: _global
    "Describe a harsh desert environment."
    # Also no commands => inherits from _global

forest: landscape
    "Describe a lush forest that transitions from the mountains."
    # Inherits from 'landscape' => which inherits from '_global'
'''
