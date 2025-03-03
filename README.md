# **LLMake**

A system for managing **structured prompt generation** and **execution** for Large Language Models (LLMs) via **dependency-based** automation. This repository includes:

1. **`llmake.py`**: The core implementation for parsing `.llmake` files, generating a Makefile, and orchestrating prompt dependencies, command inheritance, validators, and auto-retry.
2. **`test_llmakes/`**: A series of **example test prompts** illustrating successful cases, parse errors, multiple parent issues, and more.
3. **`check/`**: A reference (“golden”) set of expected outputs for success scenarios and stderr logs for failure scenarios.
4. **`test_llmake_system.py`**: An automated test suite that runs each `.llmake` file, compares outputs/stderr to references, and preserves results in a unique subdirectory.

---

## **1. Features & Syntax**

### **1.1. Inheritance of Commands, Validators, and Auto-Retry**
- If a prompt (e.g., `child`) has **no** `command` lines, it **inherits** them from exactly one parent.
- If it has **two** parents that define commands, it raises an **error** (ambiguous inheritance).
- **Validators and auto-retry also inherit**, following the same rules.
- **For `auto_retry`, if multiple parents define a value, the child takes the maximum instead of raising an error**.

```plaintext
_global:
    "Hidden context with commands"
    command: "echo 'Hello from global' > {name}.txt"
    validator: "grep -q 'Hello' {name}.txt || (echo 'Validation failed' >&2; exit 1)" retry 1

landscape: _global
    "Describe a natural landscape. Inherits commands/validator from _global."
```

### **1.2. Validators with Inline Retry**
- **`validator: "..." retry N`** syntax.
- Example:
  ```plaintext
  validator: "grep -q 'Hello' {name}.txt || (echo 'Validation failed' >&2; exit 1)" retry 2
  ```
- If a prompt has multiple parents with different `auto_retry` values, it **takes the maximum**.

### **1.3. Parse Errors with Better Messaging**
- **Line & column** numbers.
- The **offending line** with a **caret (^)** marking the error position.
- E.g.:
  ```
  ParseError (line 3, column 12): Expected ':' – got token "..." (type: STRING)
    command "something"
           ^
  ```

### **1.4. Auto-Retry Logic with Parent Merging**
- If **retry** is set (or derived from `validator ... retry N`), the generated Makefile wraps commands in an `until` shell loop.
- If multiple parents define different `retry` values, **the child takes the maximum value**.
- E.g.:
  ```makefile
  @retry=0; max_retry=2; \
  until ( command && validator ... ); do
    ...
  done
  ```

---

## **2. Example Directory Structure**

```
.
├── llmake.py
├── test_llmake_system.py
├── test_llmakes/
│   ├── test1_simple.llmake
│   ├── test2_inheritance.llmake
│   ├── test3_multi_parents.llmake
│   ├── test4_validator.llmake
│   ├── test5_parse_error_missing_colon.llmake
│   └── test6_parse_error_trailing_comma.llmake
├── check/
│   ├── test1_simple/
│   │   ├── alone.txt
│   │   └── alone.prompt
│   ├── test2_inheritance/
│   │   ├── _global.txt
│   │   ├── landscape.txt
│   │   ...
│   ├── test4_validator/
│   │   ├── multiple_cmds.txt
│   │   ├── multiple_cmds.alt.txt
│   │   ...
│   └── errors/
│       ├── test3_multi_parents.stderr
│       ├── test5_parse_error_missing_colon.stderr
│       └── test6_parse_error_trailing_comma.stderr
└── test_output/
    └── ...
```

---

## **3. Usage**

### **3.1. Generating a Makefile Manually**

```bash
python3 llmake.py --makefile -o Makefile test_llmakes/test1_simple.llmake
make all
```

### **3.2. Inheritance Example**

```bash
python3 llmake.py --makefile -o Makefile test_llmakes/test2_inheritance.llmake
make all
```

---

## **4. Tests**

### **4.1. Running All Tests**

```bash
python3 test_llmake_system.py
```

### **4.2. Adding a New Test**

1. Place the `.llmake` file in `test_llmakes/<new_case>.llmake`.
2. Generate **reference outputs** in `check/<new_case>/`.
3. Store reference **stderr** in `check/errors/<new_case>.stderr` if needed.
4. Add an entry in `test_all_llmakes` array:
   ```python
   test_cases = [
     ...
     {'name': 'test7_new_case', 'should_succeed': True},
   ]
   ```

---

## **5. Common Pitfalls**

1. **`.DS_Store` on macOS**: We ignore hidden files in the reference directories.
2. **Missing Non-Hidden Entry**: If you only define `_global:` (hidden), the `Makefile` has no top-level target → `make all` fails.
3. **Multiple Parents**: If a child has two or more parents that define commands or validators, your code raises an error.
4. **Validation vs. Retry**: If your validator does not produce a non-zero exit code on failure, auto-retry will not trigger. We do `|| exit 1`.
5. **Auto-Retry Merging**: Unlike commands/validators, multiple parent `auto_retry` values **do not** cause an error—they merge by taking the **max value**.

---

## **6. License**

This project is licensed under the **Apache 2.0 License**.

---

## **7. Final Thoughts**

**LLMake** helps create structured prompt “chains” with dependencies, inheritance, and robust error checking. The included test suite ensures **determinism** across macOS and other platforms by using **simple shell commands** instead of real LLM calls (for example, `echo` and `grep`).

