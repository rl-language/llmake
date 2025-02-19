#!/usr/bin/env python3
"""
test_llmake.py

Deterministic tests for LLMake features:
1. Validator commands
2. Custom LLM commands (multiple per prompt)
3. Improved parse errors
"""

import unittest
from io import StringIO
from llmake import Parser, ParseError

class TestLLMakeFeatures(unittest.TestCase):
    
    def test_good_prompts(self):
        """
        Test a well-formed prompt file with multiple dependencies, multiple commands,
        validators, and auto-retry. Ensures correct parsing, no errors, and that
        generated makefile output is as expected.
        """
        good_prompts = """\
_global:
    text: "Shared context"

landscape: _global
    text: "Describe a natural landscape with mountains."
    command: "ollama run mistral < {name}.prompt | tee {name}.txt"
    command: "ollama run deepseek-r1:14b < {name}.prompt | tee {name}.alt.txt"
    validator: "grep -q 'mountains' {name}.txt || (echo 'Validation failed: No mountains mentioned.' >&2; exit 1)"
    auto_retry: "2"

village: _global, landscape
    text: "Describe a small village inside the previously described landscape."
    command: "ollama run gemma:2b < {name}.prompt | tee {name}.txt"
    validator: "grep -q 'village' {name}.txt || (echo 'Validation failed: No village mentioned.' >&2; exit 1)"
    auto_retry: "3"
"""
        # Parse the in-memory prompt file
        parser_obj = Parser(good_prompts)
        prompts = parser_obj.parse_entries()
        # Verify that we have the correct entries
        self.assertIsNotNone(prompts)
        self.assertIn("landscape", prompts.entries)
        self.assertIn("village", prompts.entries)

        # Generate a makefile into a string buffer
        output = StringIO()
        prompts.to_make(output, "dummy.llmake")
        makefile_content = output.getvalue()

        # Check if auto_retry is present
        self.assertIn("max_retry=2", makefile_content)
        self.assertIn("max_retry=3", makefile_content)
        # Check if multiple commands appear for 'landscape'
        self.assertIn("ollama run mistral < landscape.prompt", makefile_content)
        self.assertIn("ollama run deepseek-r1:14b < landscape.prompt", makefile_content)
        # Check if the validator is present
        self.assertIn("Validation failed: No mountains mentioned.", makefile_content)


    def test_parse_error_missing_colon(self):
        bad_prompts = """\
city:
    text: "Describe a futuristic city"
    command "ollama run deepseek-r1:14b < {name}.prompt | tee {name}.txt"  # Missing colon
    validator: "grep -q 'city' {name}.txt || (echo 'Validation failed: No city mentioned.' >&2; exit 1)"
"""
        parser_obj = Parser(bad_prompts)
        with self.assertRaises(ParseError) as cm:
            parser_obj.parse_entries()
        err_msg = str(cm.exception)
        
        # We expect the parse error to mention a missing colon:
        self.assertIn("Expected ':'", err_msg)

        # We expect the offending command or partial content to appear:
        self.assertIn("ollama run deepseek-r1:14b < {name}.prompt | tee {name}.txt", err_msg)

        # We expect the parser to say it was a STRING:
        self.assertIn("(type: STRING)", err_msg)


    def test_parse_error_trailing_comma(self):
        bad_prompts = """\
forest: city,
    text: "Describe the nearby forest"
    command: "ollama run mistral < {name}.prompt | tee {name}.txt"
"""
        parser_obj = Parser(bad_prompts)
        with self.assertRaises(ParseError) as cm:
            parser_obj.parse_entries()
        err_msg = str(cm.exception)
        # The parser sees the comma, tries to parse a second dependency name, but finds a newline
        self.assertIn("Expected a NAME", err_msg)
        self.assertIn("got token '\\n' (type: NEWLINE)", err_msg)

if __name__ == '__main__':
    unittest.main()