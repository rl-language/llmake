.PHONY: all clean
all:multiple_cmds.txt
clean:
	 rm -f multiple_cmds.txt multiple_cmds.prompt
multiple_cmds.prompt: /Users/raffaelerusso/Desktop/LLMake/test_output/test4_validator_20250224_185123/test4_validator.llmake 
	/Library/Frameworks/Python.framework/Versions/3.9/bin/python3 /Users/raffaelerusso/Desktop/LLMake/llmake.py /Users/raffaelerusso/Desktop/LLMake/test_output/test4_validator_20250224_185123/test4_validator.llmake multiple_cmds -o multiple_cmds.prompt

multiple_cmds.txt: multiple_cmds.prompt
	@retry=0; max_retry=2; \
	until ( echo 'Hello main file' > multiple_cmds.txt && echo 'Hello alt file' > multiple_cmds.alt.txt && grep -q 'Hello main file' multiple_cmds.txt || (echo 'Validator failed' >&2; exit 1) ); do \
		retry=$$((retry+1)); \
		echo "Validation failed, retrying ($$retry/$$max_retry)"; \
		if [ $$retry -ge $$max_retry ]; then echo "Maximum retry attempts reached"; exit 1; fi; \
	done

