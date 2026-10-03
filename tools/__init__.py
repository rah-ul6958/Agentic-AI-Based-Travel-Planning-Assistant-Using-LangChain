# Compatibility shim: langchain-core 0.3.x reads `langchain.debug`, `langchain.verbose`
# and `langchain.llm_cache` whenever the `langchain` package is importable, but
# langchain 1.x removed those attributes (-> AttributeError on every tool call).
# Restoring the defaults lets the app run with either version combination.
try:
    import langchain as _langchain

    for _name, _default in (("debug", False), ("verbose", False), ("llm_cache", None)):
        if not hasattr(_langchain, _name):
            setattr(_langchain, _name, _default)
except ImportError:
    pass
