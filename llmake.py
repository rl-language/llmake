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
from dataclasses import dataclass
import shutil
import pathlib

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
    dependencies: []
    text: str
    source_position: []

    def to_make(self, out, prompts_file):
        if self.name.startswith("_"):
            return
        script = pathlib.Path(__file__)
        dep = " ".join(dependency_to_str(dep) for dep in self.dependencies if not dep.startswith("_"))
        out.write(f"{self.name}.prompt: {prompts_file} {dep}\n")
        out.write(f"\tpython {script} {prompts_file} {self.name} -o {self.name}.prompt\n\n")
        out.write(f"{self.name}.txt: {self.name}.prompt\n")
        command = f"ollama run deepseek-r1:14b < {self.name}.prompt | tee {self.name}.txt"
        out.write(f"\t{command}\n")
        out.write(f"\tsed -i '1,/<\/think>/d' {self.name}.txt\n\n")

@dataclass
class Prompts:
    entries: {}

    def validate_dependencies(self):
        for name, entry in self.entries.items():
            for dep in entry.dependencies:
                if dep == name:
                    stderr.write(f"Error: {entry.source_position} prompt {name} names itself as a dependency.")
                    return False
                if dep not in self.entries and "." not in dep:
                    stderr.write(f"Error: {entry.source_position} dependency {dep} in prompt {entry.name} does not exist.")
                    return False

        return True

    def get_prompt(self, name):
        prompts = []
        frontier = [name]
        explored = {}
        while len(frontier) != 0:
            current_name = frontier[0]
            frontier.pop(0)
            if current_name not in self.entries and "." not in current_name:
                stderr.write(f"Error: no known prompt {current_name}")
                return None
            if not "." in current_name:
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
        out.write("clean:\n\trm -f ")
        out.write(" ".join(name+".txt "+name+".prompt" for name in self.entries if not name.startswith("_")) + "\n")

        for name, entry in self.entries.items():
            entry.to_make(out, prompts_file)


class Parser:
    def __init__(self, text):
        self.tokens = [token for token in tokenize.tokenize(BytesIO(text.encode('utf-8')).readline)]
        self.index = 1
        self.current = self.tokens[1]

    def next(self):
        self.index = self.index + 1
        if len(self.tokens) != self.index:
            self.current = self.tokens[self.index]

    def name(self):
        if not self.current.type == tokenize.NAME:
            return None
        return self.current.string

    def colons(self):
        return self.current.type == tokenize.OP and self.current.string == ':'

    def newline(self):
        return self.current.type == tokenize.NEWLINE or self.current.type == tokenize.NL

    def string(self):
        if not self.current.type == tokenize.STRING:
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

    def expect(self, element):
        to_return = element()
        if not to_return:
            raise Exception(f"expected something but got{self.current}")
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
        text = self.expect(self.string)
        while self.accept(self.newline):
            pass
        self.expect(self.deindent)
        return Entry(name, dependencies, text, position)


    def parse_entries(self):
        entries = {}
        while not self.accept(self.end):
            while self.accept(self.newline):
                pass
            entry = self.parse_entry()
            if entry.name in entries:
                stderr.write(f"Error: Multiple definitions of prompt {entry.name}.")
                return None
            entries[entry.name] = entry
        return Prompts(entries)


def main():
    parser = argparse.ArgumentParser(description="Load and display content of a text file.")
    parser.add_argument("file", type=str, help="Path to prompts file")
    parser.add_argument("prompt", type=str, help="Prompt to print", default="", nargs="?")
    parser.add_argument("--makefile", help="generate a make file", default=False, action="store_true")
    parser.add_argument("-o", help="output", default="-")

    args = parser.parse_args()
    content = ""
    try:
        with open(args.file, 'r') as file:
            content = file.read()
    except FileNotFoundError:
        print(f"Error: File '{args.file}' not found.")
    except IOError as e:
        print(f"Error reading file '{args.file}': {e}")

    output = stdout if args.o == "-" else NamedTemporaryFile("w+")

    parser = Parser(content)
    prompts = parser.parse_entries()
    if not prompts:
        exit(-1)
    if not prompts.validate_dependencies():
        exit(-1)
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
        exit(-1)
    output.write("\n\n".join(prompt))
    output.flush()
    if args.o != "-":
        copy_if_different(output.name, args.o)
    exit(0)


if __name__ == "__main__":
    main()
