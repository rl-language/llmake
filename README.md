# LLMake - Feature Additions

## 📌 Overview
This document outlines the newly added features to **LLMake**, a system that facilitates structured LLM invocations through dependency-based prompts. The following key features were added:

1. **Support for Validator Commands**
2. **Custom Commands for LLM Invocations**
3. **Improved Parsing Errors for Better Debugging**

Each feature is explained in detail below.

---

## 🛠️ 1. Support for Validator Commands
### **What It Does**
- Allows users to define **validation commands** to check the LLM-generated output.
- If validation fails, the system can **retry execution** automatically.

### **Implementation**
- **New `validator` field** in the prompt definition.
- Validators execute **shell commands** after the LLM command.
- If validation **fails**, an **exit code `1`** is returned, triggering a **retry** (if enabled).

### **Example Usage**
```yaml
village: _global, landscape
    text: "Describe a small village inside the previously described landscape."
    command: "ollama run mistral < {name}.prompt | tee {name}.txt"
    validator: "grep -q 'village' {name}.txt || (echo 'Validation failed: No village mentioned.' >&2; exit 1)"
    auto_retry: "3"
```

### **How It Works**
- After running the **LLM command**, the validator **checks if the word 'village'** exists in the output.
- If validation **fails**, it prints an error message and **triggers a retry** up to 3 times.

---

## ⚙️ 2. Custom Commands for LLM Invocations
### **What It Does**
- Allows users to specify **custom LLM commands** for each prompt.
- Supports **multiple commands per prompt**, executing them sequentially.

### **Implementation**
- **New `command` field**, supporting **one or more commands**.
- Commands are executed in **order**.

### **Example Usage**
```yaml
village: _global, landscape
    text: "Describe a small village inside the previously described landscape."
    command: "ollama run mistral < {name}.prompt | tee {name}.txt"
    command: "ollama run deepseek-r1:14b < {name}.prompt | tee {name}.alt.txt"
    validator: "grep -q 'village' {name}.txt || (echo 'Validation failed: No village mentioned.' >&2; exit 1)"
    auto_retry: "2"
```

### **How It Works**
- The **first command** runs `mistral` and saves output to `village.txt`.
- The **second command** runs `deepseek-r1:14b` and saves output to `village.alt.txt`.
- If validation fails, the system retries execution **up to 2 times**.

---

## 🔍 3. Improved Parsing Errors
### **What It Does**
- Makes error messages **more readable and descriptive**.
- Provides **exact token location (line/column)**.
- Shows **expected vs. actual token** to help users debug faster.

### **Implementation**
- **Custom `ParseError` exception** with a **token dictionary** for better messages.

#### **Before (Generic Error Message)**
```plaintext
ParseError: Expected colons
```

#### **After (Improved Error Message)**
```plaintext
ParseError (line 3, column 12): Expected ':' – got token "command" (type: NAME)
```

### **Code Changes**
#### **Added Token Name Mapping for Human-Readable Errors**
```python
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
```

#### **Updated `expect` Method to Use Human-Readable Symbols**
```python
def expect(self, element):
    to_return = element()
    if not to_return:
        expected_name = element.__name__
        expected_symbol = TOKEN_NAMES.get(expected_name, expected_name)
        raise ParseError(
            f"Expected {expected_symbol} – got token {self.current.string!r} (type: {tokenize.tok_name[self.current.type]})",
            token=self.current
        )
    self.next()
    return to_return
```

### **How It Works**
- Instead of showing `Expected colons`, it now displays `Expected ':'`.
- If the user makes a mistake, it shows **exact location + expected token**.

---

## 🎯 Summary of Features
| Feature | Description | Example |
|---------|-------------|----------|
| **Validator Commands** | Validates LLM output before proceeding | `validator: "grep -q 'village' {name}.txt || exit 1"` |
| **Custom Commands** | Allows multiple LLM execution commands per prompt | `command: "ollama run mistral < {name}.prompt"` |
| **Improved Errors** | Displays human-readable parse errors | `ParseError: Expected ':' – got token 'command'` |

---

## 🚀 **Final Thoughts**
These features significantly improve **LLMake’s usability** by allowing more flexible LLM execution, **automated validation**, and **clearer debugging messages**. Try running the **updated prompts and commands** and enjoy an improved AI-powered workflow!

---

