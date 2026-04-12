from tree_sitter import Language, Parser
from typing import Optional, Dict

                          
try:
    import tree_sitter_python as tspython
except ImportError:
    tspython = None

try:
    import tree_sitter_javascript as tsjavascript
except ImportError:
    tsjavascript = None

try:
    import tree_sitter_typescript as tstypescript
except ImportError:
    tstypescript = None

try:
    import tree_sitter_java as tsjava
except ImportError:
    tsjava = None

try:
    import tree_sitter_go as tsgo
except ImportError:
    tsgo = None

try:
    import tree_sitter_rust as tsrust
except ImportError:
    tsrust = None

try:
    import tree_sitter_cpp as tscpp
except ImportError:
    tscpp = None

try:
    import tree_sitter_c as tsc
except ImportError:
    tsc = None

                        
_grammar_cache: Dict[str, Language] = {}

                                    
EXTENSION_TO_LANGUAGE: Dict[str, str] = {
    '.py': 'python',
    '.js': 'javascript',
    '.jsx': 'javascript',
    '.ts': 'typescript',
    '.tsx': 'tsx',                              
    '.java': 'java',
    '.go': 'go',
    '.rs': 'rust',
    '.cpp': 'cpp',
    '.cc': 'cpp',
    '.cxx': 'cpp',
    '.c': 'c',
    '.h': 'c',
    '.hpp': 'cpp',
}

                     
SUPPORTED_LANGUAGES = {
    'python', 'javascript', 'typescript', 'tsx', 'java', 'go', 'rust', 'cpp', 'c'
}


def detect_language(file_path: str, language_hint: Optional[str] = None) -> Optional[str]:
    
                                    
    if language_hint:
        lang_lower = language_hint.lower()
        if lang_lower in SUPPORTED_LANGUAGES:
            return lang_lower
    
                                
    file_path_lower = file_path.lower()
    for ext, lang in EXTENSION_TO_LANGUAGE.items():
        if file_path_lower.endswith(ext):
            return lang
    
    return None


def is_language_supported(language: str) -> bool:
    
    return language.lower() in SUPPORTED_LANGUAGES


def get_language_grammar(language: str) -> Optional[Language]:
    
    lang_lower = language.lower()
    
                       
    if lang_lower in _grammar_cache:
        return _grammar_cache[lang_lower]
    
                                    
    grammar = None
    try:
        if lang_lower == 'python' and tspython:
                                                       
            if hasattr(tspython, 'language'):
                grammar = tspython.language() if callable(tspython.language) else tspython.language
            elif hasattr(tspython, 'language_path'):
                grammar = Language(tspython.language_path)
        elif lang_lower == 'javascript' and tsjavascript:
            if hasattr(tsjavascript, 'language'):
                js_grammar = tsjavascript.language() if callable(tsjavascript.language) else tsjavascript.language
                                                              
                if isinstance(js_grammar, Language):
                    grammar = js_grammar
                else:
                    grammar = Language(js_grammar)
            elif hasattr(tsjavascript, 'language_path'):
                grammar = Language(tsjavascript.language_path)
        elif lang_lower == 'typescript':
                                                          
            if tstypescript:
                try:
                    if hasattr(tstypescript, 'typescript') and callable(tstypescript.typescript):
                        grammar = Language(tstypescript.typescript())
                    elif hasattr(tstypescript, 'language') and callable(tstypescript.language):
                        grammar = Language(tstypescript.language())
                    else:
                                                    
                        ts_grammar = getattr(tstypescript, 'typescript', None) or getattr(tstypescript, 'language', None)
                        if ts_grammar:
                            grammar = Language(ts_grammar) if not isinstance(ts_grammar, Language) else ts_grammar
                        else:
                            grammar = None
                except Exception as e:
                    grammar = None
            
                                                        
            if not grammar and tsjavascript:
                try:
                    if hasattr(tsjavascript, 'language'):
                        js_grammar = tsjavascript.language() if callable(tsjavascript.language) else tsjavascript.language
                                                                      
                        if isinstance(js_grammar, Language):
                            grammar = js_grammar
                        else:
                            grammar = Language(js_grammar)
                    elif hasattr(tsjavascript, 'language_path'):
                        grammar = Language(tsjavascript.language_path)
                    if grammar:
                                                             
                        if lang_lower not in _grammar_cache:
                            print(f"[LanguageSupport] TypeScript grammar not available, using JavaScript as fallback")
                except Exception:
                    grammar = None
        
        elif lang_lower == 'tsx':
                                                   
            if tstypescript:
                try:
                    if hasattr(tstypescript, 'tsx') and callable(tstypescript.tsx):
                        grammar = Language(tstypescript.tsx())
                    else:
                        tsx_grammar = getattr(tstypescript, 'tsx', None)
                        if tsx_grammar:
                            grammar = Language(tsx_grammar) if not isinstance(tsx_grammar, Language) else tsx_grammar
                        else:
                            grammar = None
                except Exception:
                    grammar = None
            
                                                 
            if not grammar and tsjavascript:
                try:
                    if hasattr(tsjavascript, 'language'):
                        js_grammar = tsjavascript.language() if callable(tsjavascript.language) else tsjavascript.language
                                                                      
                        if isinstance(js_grammar, Language):
                            grammar = js_grammar
                        else:
                            grammar = Language(js_grammar)
                    elif hasattr(tsjavascript, 'language_path'):
                        grammar = Language(tsjavascript.language_path)
                    if grammar:
                                                             
                        if lang_lower not in _grammar_cache:
                            print(f"[LanguageSupport] TSX grammar not available, using JavaScript as fallback")
                except Exception:
                    grammar = None
        elif lang_lower == 'java' and tsjava:
            if hasattr(tsjava, 'language'):
                grammar = tsjava.language() if callable(tsjava.language) else tsjava.language
            elif hasattr(tsjava, 'language_path'):
                grammar = Language(tsjava.language_path)
        elif lang_lower == 'go' and tsgo:
            if hasattr(tsgo, 'language'):
                grammar = tsgo.language() if callable(tsgo.language) else tsgo.language
            elif hasattr(tsgo, 'language_path'):
                grammar = Language(tsgo.language_path)
        elif lang_lower == 'rust' and tsrust:
            if hasattr(tsrust, 'language'):
                grammar = tsrust.language() if callable(tsrust.language) else tsrust.language
            elif hasattr(tsrust, 'language_path'):
                grammar = Language(tsrust.language_path)
        elif lang_lower == 'cpp' and tscpp:
            if hasattr(tscpp, 'language'):
                grammar = tscpp.language() if callable(tscpp.language) else tscpp.language
            elif hasattr(tscpp, 'language_path'):
                grammar = Language(tscpp.language_path)
        elif lang_lower == 'c' and tsc:
            if hasattr(tsc, 'language'):
                grammar = tsc.language() if callable(tsc.language) else tsc.language
            elif hasattr(tsc, 'language_path'):
                grammar = Language(tsc.language_path)
        
                           
        if grammar:
            _grammar_cache[lang_lower] = grammar
        
    except Exception as e:
                                                              
        if lang_lower not in ('typescript', 'tsx'):
            print(f"[LanguageSupport] Failed to load grammar for {language}: {e}")
        return grammar
    
    return grammar


def initialize_parser() -> Parser:
    
    return Parser()

