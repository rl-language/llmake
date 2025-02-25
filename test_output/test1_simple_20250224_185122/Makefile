.PHONY: all clean
all:alone.txt
clean:
	 rm -f alone.txt alone.prompt
alone.prompt: /Users/raffaelerusso/Desktop/LLMake/test_output/test1_simple_20250224_185122/test1_simple.llmake 
	/Library/Frameworks/Python.framework/Versions/3.9/bin/python3 /Users/raffaelerusso/Desktop/LLMake/llmake.py /Users/raffaelerusso/Desktop/LLMake/test_output/test1_simple_20250224_185122/test1_simple.llmake alone -o alone.prompt

alone.txt: alone.prompt
	@retry=0; max_retry=1; \
	until ( echo 'Hello from alone' > alone.txt && grep -q 'Hello' alone.txt || (echo 'Validator failed' >&2; exit 1) ); do \
		retry=$$((retry+1)); \
		echo "Validation failed, retrying ($$retry/$$max_retry)"; \
		if [ $$retry -ge $$max_retry ]; then echo "Maximum retry attempts reached"; exit 1; fi; \
	done

