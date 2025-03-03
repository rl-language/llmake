###
# Copyright 2024 Attilio Polito, Raffaele Russo

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

#!/usr/bin/env python3
import unittest
import subprocess
import os
import sys
import filecmp
import shutil
from datetime import datetime

class TestLLMakeSystem(unittest.TestCase):
    def setUp(self):
        """
        Ensure the test output directory exists
        Each test run creates a unique subdirectory inside 'test_output'
        """
        self.base_work_dir = "test_output"
        os.makedirs(self.base_work_dir, exist_ok=True) 

    def get_test_work_dir(self, test_name):
        # Create a unique directory for each test inside 'test_output/'
        
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        work_dir = os.path.join(self.base_work_dir, f"{test_name}_{timestamp}")
        os.makedirs(work_dir, exist_ok=True)
        return work_dir

    def run_success_test(self, test_name):
        """
        1. Copy <test_name>.llmake to a unique working directory
        2. Run 'llmake.py <test_name>.llmake --makefile -o Makefile' => expect success
        3. Run 'make all' => expect success
        4. Store results uniquely and compare to expected outputs.
        """
        check_dir = f"check/{test_name}"
        work_dir = self.get_test_work_dir(test_name)

        # Step 1: Copy .llmake file
        llmake_file = f"test_llmakes/{test_name}.llmake"
        shutil.copy(llmake_file, work_dir)

        # Step 2: Generate the Makefile
        llmake_abs = os.path.abspath(os.path.join(work_dir, f"{test_name}.llmake"))
        cmd = [
            f"{sys.executable}", os.path.abspath("llmake.py"),  
            "--makefile", "-o", "Makefile",
            llmake_abs
        ]
        proc = subprocess.run(cmd, capture_output=True, text=True, cwd=work_dir)

        self.assertEqual(
            proc.returncode, 0,
            msg=f"llmake.py failed for {test_name}. Stderr:\n{proc.stderr}"
        )

        # Step 3: Run 'make all'
        make_proc = subprocess.run(["make", "all"], capture_output=True, text=True, cwd=work_dir)
        self.assertEqual(
            make_proc.returncode, 0,
            msg=f"make all failed for {test_name}. Stderr:\n{make_proc.stderr}"
        )

        # Step 4: Compare outputs to 'check/<test_name>/'
        if os.path.exists(check_dir):
            for ref_file in os.listdir(check_dir):
                # Skip system files e.g. .DS_Store
                if ref_file.startswith('.'):
                    continue

                ref_path = os.path.join(check_dir, ref_file)
                out_path = os.path.join(work_dir, ref_file)

                # Check if expected file is produced
                self.assertTrue(
                    os.path.isfile(out_path),
                    msg=f"Expected file {ref_file} not produced by test {test_name}"
                )

                # Compare content
                self.assertTrue(
                    filecmp.cmp(ref_path, out_path, shallow=False),
                    msg=f"File {ref_file} does not match expected output for test {test_name}"
                )

    def run_failure_test(self, test_name):
        """
        1. Copy <test_name>.llmake to a unique working directory
        2. Run 'llmake.py <test_name>.llmake --makefile -o Makefile' => expect error (parse error or inheritance error, etc)
        3. Store stderr in test output directory.
        4. Compare stderr to check/errors/<test_name>.stderr (if it exists).
        """
        check_dir = f"check/errors"
        work_dir = self.get_test_work_dir(test_name)

        # Step 1: Copy
        llmake_file = f"test_llmakes/{test_name}.llmake"
        shutil.copy(llmake_file, work_dir)

        # Step 2: Run command, expect failure
        llmake_abs = os.path.abspath(os.path.join(work_dir, f"{test_name}.llmake"))
        cmd = [
            f"{sys.executable}", os.path.abspath("llmake.py"),  
            "--makefile", "-o", "Makefile",
            llmake_abs
        ]
        proc = subprocess.run(cmd, capture_output=True, text=True, cwd=work_dir)

        # We expect a nonzero return code
        self.assertNotEqual(
            proc.returncode, 0,
            msg=f"llmake.py unexpectedly succeeded for {test_name}. Output:\n{proc.stdout}\nErr:\n{proc.stderr}"
        )

        # Step 3: Save stderr output in the test's directory
        stderr_path = os.path.join(work_dir, f"{test_name}.stderr")
        with open(stderr_path, "w") as f:
            f.write(proc.stderr)

        # Step 4: Compare with expected stderr, if exists
        expected_stderr_path = os.path.join(check_dir, f"{test_name}.stderr")
        if os.path.isfile(expected_stderr_path):
            with open(expected_stderr_path, "r") as f:
                expected_err = f.read()

            self.assertIn(
                expected_err.strip(),
                proc.stderr.strip(),
                msg=f"Error output for {test_name} does not contain the expected error.\nStderr was:\n{proc.stderr}"
            )

    def test_all_llmakes(self):
        """
        Run all test cases in a single function.
        """
        test_cases = [
            {'name': 'test1_simple', 'should_succeed': True},
            {'name': 'test2_inheritance', 'should_succeed': True},
            {'name': 'test3_multi_parents', 'should_succeed': False},
            {'name': 'test4_validator', 'should_succeed': True},
            {'name': 'test5_parse_error_missing_colon', 'should_succeed': False},
            {'name': 'test6_parse_error_trailing_comma', 'should_succeed': False},
        ]

        for tc in test_cases:
            with self.subTest(test_name=tc['name'], should_succeed=tc['should_succeed']):
                if tc['should_succeed']:
                    self.run_success_test(tc['name'])
                else:
                    self.run_failure_test(tc['name'])

if __name__ == '__main__':
    unittest.main()
