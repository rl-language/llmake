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
    def __init__(self, message, token=None):
        """
        Custom exception for parsing errors, including token information.

        Args:
            message (str): The error message.
            token (tokenize.TokenInfo, optional): The token that caused the error.
        """
        self.message = message
        self.token = token
        super().__init__(message)

    def __str__(self):
        """
        Formats the error message to include line/column details and the incorrect token.
        """
        if self.token and hasattr(self.token, 'start'):
            line, col = self.token.start
            token_value = self.token.string
            token_type = tokenize.tok_name.get(self.token.type, "UNKNOWN")
            return f"ParseError (line {line}, column {col}): {self.message}"
        return f"ParseError: {self.message}"

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
        out.write(f"\tpython {script} {prompts_file} {self.name} -o {self.name}.prompt\n\n")
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
        return self.current.string[1:-1]  # strip the quotes

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
            expected_symbol = TOKEN_NAMES.get(expected_name, expected_name)  # Use dictionary, fallback to function name
            raise ParseError(
                f"Expected {expected_symbol} – got token {self.current.string!r} (type: {tokenize.tok_name[self.current.type]})",
                token=self.current
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
        name = self.expect(self.name)
        self.expect(self.colons)
        dependencies = []

        if not self.accept(self.newline):
            while True:
                dependencies.append(self.parse_depency())
                if not self.accept(self.comma):
                    break
            self.expect(self.newline)

        self.expect(self.indent)
        while self.current.type in (tokenize.NEWLINE, tokenize.NL):
            self.next()

        if self.current.type == tokenize.STRING:
            field_text = self.expect(self.string)
            fields = {'text': field_text}
        else:
            fields = {}
            while self.current.type != tokenize.DEDENT:
                if self.accept(self.newline):
                    continue
                key = self.expect(self.name)
                self.expect(self.colons)
                value = self.expect(self.string)
                if key in fields:
                    if isinstance(fields[key], list):
                        fields[key].append(value)
                    else:
                        fields[key] = [fields[key], value]
                else:
                    fields[key] = value

                while self.accept(self.newline):
                    pass

        self.expect(self.deindent)

        if 'text' not in fields:
            raise ParseError("Missing 'text' field in entry.", self.current)
        if 'command' in fields:
            if isinstance(fields['command'], list):
                llm_commands = fields['command']
            else:
                llm_commands = [fields['command']]
        else:
            llm_commands = []

        if 'validator' in fields:
            if isinstance(fields['validator'], list):
                validator_commands = fields['validator']
            else:
                validator_commands = [fields['validator']]
        else:
            validator_commands = []

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
Good prompt:

_global:
    text: "This is a shared context that will apply to multiple prompts."

landscape: _global
    text: "Describe a natural landscape with mountains and rivers."
    command: "ollama run deepseek-r1:14b < {name}.prompt | tee {name}.txt"
    validator: "grep -q 'mountains' {name}.txt || (echo 'Validation failed: No mountains mentioned.' >&2; exit 1)'"
    auto_retry: "2"


village: _global, landscape
    text: "Describe a small village inside the previously described landscape."
    command: "ollama run deepseek-r1:14b < {name}.prompt | tee {name}.txt"
    validator: "grep -q 'village' {name}.txt || (echo 'Validation failed: No village mentioned.' >&2; exit 1)'"
    auto_retry: "3"

people: _global, village
    text: "Describe the people living in the previously described village."
    command: "ollama run deepseek-r1:14b < {name}.prompt | tee {name}.txt"
    validator: "grep -q 'people' {name}.txt || (echo 'Validation failed: No people mentioned.' >&2; exit 1)'"
    auto_retry: "2"

    
What Happens?
_global is a hidden dependency that contains shared context.
landscape depends on _global and describes mountains/rivers.
village depends on _global and landscape, ensuring continuity.
people depends on _global and village, linking all descriptions.
Each prompt includes a validator that checks for expected keywords.
If validation fails, the system automatically retries up to the specified attempts.

Bad prompt:

city:
    text: "Describe a futuristic city"
    command "ollama run deepseek-r1:14b < {name}.prompt | tee {name}.txt" 
    validator: "grep -q 'city' {name}.txt || echo 'Validation failed: No city mentioned.'"

forest: city,
    text: "Describe the nearby forest"
    command: "ollama run deepseek-r1:14b < {name}.prompt | tee {name}.txt"

What’s Wrong?
Missing Colon (:) After command in city
Correct format: command: "...", but we wrote command "...".
Trailing Comma in forest Dependencies
forest: city, should not have a comma at the end if there are no additional dependencies.
validator: wrote in a wrong manner (in this way the exit code of the command will be zero, the auto_retry will not be triggered)

Expected Output from ParseError:

If we run:

python llmake.py bad_prompt.llmake --makefile


The parser will generate the following error:

ParseError (line 3, column 12): Expected ':' – got token '"ollama run deepseek-r1:14b < {name}.prompt | tee {name}.txt"' (type: STRING)


Second Error Example (Trailing Comma in forest)
If we fix the first error but leave the trailing comma in forest, the parser will detect it and generate:

ParseError (line 6, column 13): Expected a NAME (e.g., variable or keyword) – got token '\n' (type: NEWLINE)



'''