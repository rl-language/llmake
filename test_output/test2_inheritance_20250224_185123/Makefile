.PHONY: all clean
all:landscape.txt
clean:
	 rm -f landscape.txt landscape.prompt
landscape.prompt: /Users/raffaelerusso/Desktop/LLMake/test_output/test2_inheritance_20250224_185123/test2_inheritance.llmake 
	/Library/Frameworks/Python.framework/Versions/3.9/bin/python3 /Users/raffaelerusso/Desktop/LLMake/llmake.py /Users/raffaelerusso/Desktop/LLMake/test_output/test2_inheritance_20250224_185123/test2_inheritance.llmake landscape -o landscape.prompt

landscape.txt: landscape.prompt
	echo 'Hello from _global' > landscape.txt

