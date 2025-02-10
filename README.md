### LLMAKE

#### Syntax

a llmake file is a sequence of target declarations, for example, the following is a target declaration.
```
house:
    "describe a small house"
```

target may optionally have a list of dependencies that must have already been executed before the current target can be executed.

```
house:
    "describe a small house"

another_house: house
    "describe a small house that is next to the previous house"
```

targets may be optionally prefixed with _ to mark them as hidden targets that are not to be produced.

```
_global:
    "describe the following thing"

house: _global
    "a small house"

another_house: _global, house
    "a house next to the other one"
```

dependencies can optionally name a file, if they do the content of that file is concantenated to the prompt

```
house: owner_description.txt
    "describe the house that belongs to the just described owner"
```

#### Usage

To generate a make file and run it:
```
python llmake.py --makefile -o makefile
make all
```
To see a prompt of a given target
```
python llmake.py TARGETNAME
```
