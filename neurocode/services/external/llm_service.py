"""
LLM Service for documentation generation using Claude
"""
import os
import json
import re
from pathlib import Path
from typing import List, Dict, Any, Optional
from anthropic import Anthropic


def _enforce_max_connections_per_class(
    relationships: List[Dict[str, Any]], max_per_class: int = 3
) -> List[Dict[str, Any]]:
    """Drop relationships so no class has more than max_per_class connections (in + out)."""
    if not relationships:
        return relationships
    rels = list(relationships)
    while True:
        degree: Dict[str, int] = {}
        for r in rels:
            if isinstance(r, dict):
                src, tgt = r.get("source"), r.get("target")
                if src:
                    degree[src] = degree.get(src, 0) + 1
                if tgt and tgt != src:
                    degree[tgt] = degree.get(tgt, 0) + 1
        over = [cid for cid, d in degree.items() if d > max_per_class]
        if not over:
            break
        to_remove = None
        for r in rels:
            src, tgt = r.get("source"), r.get("target")
            if src in over or tgt in over:
                if r.get("relationship") == "dependency":
                    to_remove = r
                    break
        if to_remove is None:
            for r in rels:
                src, tgt = r.get("source"), r.get("target")
                if src in over or tgt in over:
                    to_remove = r
                    break
        if to_remove is None:
            break
        rels.remove(to_remove)
    return rels


class LLMService:
    """Service for generating documentation using Claude"""
    
    def __init__(self):
        api_key = os.getenv("ANTHROPIC_API_KEY")
        if not api_key:
            raise ValueError("ANTHROPIC_API_KEY environment variable is required")
        
        self.client = Anthropic(api_key=api_key)
        # Model names can be configured via environment variables.
        # Falls back to the default Claude Haiku model if not set.
        self.model = os.getenv("ANTHROPIC_MODEL", "claude-haiku-4-5-20251001")  # Premium model for main generation
        self.model_fast = os.getenv("ANTHROPIC_MODEL_FAST", self.model)  # Cheaper model for simple tasks (~10x cheaper)

    def chat_with_context(
        self,
        system_prompt: str,
        conversation_history: List[Dict[str, str]],
        user_message: str,
        max_tokens: int = 4096,
    ) -> str:
        """
        Chat with conversation history and a system prompt (e.g. RAG context).

        Args:
            system_prompt: System message (e.g. instructions + retrieved code chunks).
            conversation_history: List of {"role": "user"|"assistant", "content": str}.
            user_message: The new user message to respond to.
            max_tokens: Max tokens for the response.

        Returns:
            The assistant's reply text.
        """
        messages: List[Dict[str, str]] = []
        for turn in conversation_history:
            role = turn.get("role")
            content = turn.get("content")
            if role and content and role in ("user", "assistant"):
                messages.append({"role": role, "content": content})
        messages.append({"role": "user", "content": user_message})

        response = self.client.messages.create(
            model=self.model_fast,
            max_tokens=max_tokens,
            system=system_prompt,
            messages=messages,
        )
        if response.content and len(response.content) > 0:
            return response.content[0].text.strip()
        return ""
    
    def generate_documentation(
        self,
        prompt: str,
        context_chunks: List[Dict[str, Any]],
        repo_name: str = "repository"
    ) -> str:
        """
        Generate documentation using Claude with RAG context (legacy method)
        
        Args:
            prompt: User's query/prompt
            context_chunks: List of relevant code chunks from vector search
            repo_name: Name of the repository
        
        Returns:
            Generated documentation text
        """
        result = self.generate_structured_documentation(prompt, context_chunks, repo_name)
        return result.get("documentation", "")
    
    def generate_structured_documentation(
        self,
        prompt: str,
        context_chunks: List[Dict[str, Any]],
        repo_name: str = "repository"
    ) -> Dict[str, Any]:
        """
        Generate structured documentation with code references and glossary using Claude
        
        Args:
            prompt: User's query/prompt
            context_chunks: List of relevant code chunks from vector search
            repo_name: Name of the repository
            
        Returns:
            Dictionary with:
            - documentation: Main documentation content (markdown)
            - code_references: List of code reference objects
        """
        # Build context from chunks with enhanced metadata
        context_parts = []
        for i, chunk in enumerate(context_chunks, 1):
            file_path = chunk.get("metadata", {}).get("file_path", "unknown")
            function_name = chunk.get("metadata", {}).get("function_name", "")
            class_name = chunk.get("metadata", {}).get("class_name", "")
            language = chunk.get("metadata", {}).get("language", "")
            start_line = chunk.get("metadata", {}).get("start_line", 0)
            end_line = chunk.get("metadata", {}).get("end_line", 0)
            content = chunk.get("content", "")
            
            # Build detailed header with all metadata
            header = f"--- Code Chunk {i} ---\n"
            header += f"File: {file_path}\n"
            if class_name:
                header += f"Class: {class_name}\n"
            if function_name:
                header += f"Function/Method: {function_name}\n"
            header += f"Language: {language}\n"
            header += f"Lines: {start_line}-{end_line}\n"
            header += "---\n"
            
            context_parts.append(header + content + "\n")
        
        context = "\n".join(context_parts)
        
        # Load JSON schema template
        schema_path = Path(__file__).parent.parent / "config" / "documentation_schema.json"
        schema_template = ""
        if schema_path.exists():
            try:
                import json as json_module
                with open(schema_path, 'r', encoding='utf-8') as f:
                    schema_data = json_module.load(f)
                    schema_template = json_module.dumps(schema_data, indent=2)
            except Exception as e:
                print(f"[LLMService] Warning: Could not load schema template: {e}")
        
        # Build system and user messages for structured output
        schema_section = ""
        if schema_template:
            schema_section = f"""

**REQUIRED JSON SCHEMA (you MUST follow this exactly):**
```json
{schema_template}
```

**CRITICAL REQUIREMENTS:**
1. Return ONLY valid JSON - no markdown code blocks, no explanations, just pure JSON
2. The JSON must match the schema above exactly
3. All required fields must be present
4. Ensure all strings are properly escaped
5. Ensure all arrays and objects are properly closed
6. Do NOT truncate any content - if you're running out of tokens, prioritize completing the structure over adding more detail
"""
        
        system_prompt = f"""You are a technical documentation expert specializing in API reference documentation similar to scikit-learn, NumPy, and other scientific Python libraries.

Your task is to generate comprehensive documentation in a structured JSON format that includes:
1. Main documentation with hierarchical sections (numbered 1, 1.1, 2, 2.1, etc.) - **MUST include subsections**
2. Code references for all functions, classes, and methods mentioned

Your documentation should:
- Be code-focused and technical, highlighting specific methods, functions, classes, and code patterns
- Include detailed explanations of important conditional logic, control flow, and algorithmic decisions
- Reference specific code elements (function names, class names, parameters, return types) from the provided code
- Use proper code formatting with backticks for function names, class names, variables
- **Use Markdown tables whenever it helps**: For parameters, options, return values, configuration keys, comparisons, or any structured data—use tables to reduce wall-of-text and improve scannability. Example: parameter lists, API options, key-value configs.
- **Use fenced code blocks (triple backticks) liberally in descriptions**: Include short code examples, API usage snippets, config examples, and small code samples wherever they clarify the explanation. Prefer showing real code over long prose when it aids understanding. Use ```language for syntax highlighting when relevant.
- Include code examples showing how functions/methods are used
- Explain the "why" behind important if statements, loops, and design decisions
- Structure like API reference documentation with clear sections for classes, methods, parameters
- **CRITICAL**: Always include subsections in your documentation structure - not every section needs subsections, but the overall documentation MUST have at least some subsections (e.g., section "1" with "1.1", "1.2", or section "2" with "2.1", "2.2", etc.)
- Be precise and technical, not generic descriptions{schema_section}"""
        
        user_message = f"""Based on the following code from the {repo_name} repository, generate comprehensive, structured documentation that addresses this request:

**User Request:** {prompt}

**Relevant Code Context:**
{context}

**INSTRUCTIONS:**
1. Generate the main documentation in structured JSON format with hierarchical sections:
   - **REQUIRED**: Include a top-level `description` field (2-3 sentences) that briefly describes what this documentation is about. This should be a concise overview of the documentation's purpose and scope.
   - **REQUIRED**: The first section (id "1") MUST have a specific, detailed title that reflects the documentation topic and scope—e.g. "Authentication and session handling", "Payment flow and Stripe integration", "User API and request lifecycle". Do NOT use a generic title like "Introduction", "Overview", or "Documentation" for section 1. This title is used as the document title in the UI and must distinguish this doc from others.
   - MAXIMUM 10 sections total (including subsections count toward this limit) - use only as many as needed, up to 10
   - Create sections with IDs like "1", "1.1", "2", "2.1", "2.2", etc.
   - **CRITICAL REQUIREMENT**: The documentation MUST include subsections. Not every section needs subsections, but the overall documentation structure MUST have at least some subsections (e.g., section "1" should have "1.1", "1.2", etc., or section "2" should have "2.1", "2.2", etc.). This is REQUIRED - do not generate documentation without any subsections.
   - Each section has: id, title, description, code_references (array of IDs), and optional subsections (but remember: subsections MUST exist somewhere in the documentation)
   - The description field must be DETAILED and THOROUGH, similar to scikit-learn documentation style:
     * Explain concepts, algorithms, and processes in clear English
     * **TABLES**: Use Markdown tables whenever you have structured data so the doc feels less overwhelming and is easier to scan. Use tables for: parameter lists (name, type, description), options/flags, return value fields, configuration keys, comparisons (e.g. "Option A vs Option B"), or any repeated key-value or columnar information. Example: | Parameter | Type | Description | then rows.
     * **CODE SNIPPETS**: Use fenced code blocks (``` ... ```) often in descriptions. Include short code examples, usage snippets, config samples, and inline code to explain behavior. Prefer showing real code over long prose when it helps. Use ```python, ```javascript, etc. when the language is known. More code snippets = clearer, less overwhelming docs.
     * **FORMATTING GUIDELINES**: 
       - Use paragraph breaks (`\n\n`) to separate different ideas or topics. Each paragraph should focus on one main concept.
       - Write in a natural, flowing documentation style - use a mix of paragraphs, lists, tables, and code blocks as appropriate
       - **Use bullet points (`- ` or `* `) when appropriate** for:
         * Lists of distinct items, features, or components (especially when each item has details)
         * When breaking information into a list improves clarity and scannability
         * Quick reference lists that readers might want to scan
       - **Use numbered lists (`1. `, `2. `, `3. `) when appropriate** for:
         * Sequential steps or processes that must be followed in order
         * When the sequence or order is important to understanding
         * Step-by-step workflows or procedures
       - **Balance is key**: Use lists when they improve readability, but don't force everything into lists. Mix paragraphs and lists naturally based on what best communicates the information.
       - Example of good mixed style: "The system processes data through multiple stages. First, input validation ensures data integrity. Then, the transformation layer applies business rules. Finally, the output is formatted for display.\n\nThe system supports several file formats:\n\n- PDF: For document processing\n- DOCX: For editable documents\n- TXT: For plain text files"
     * Include mathematical formulations where relevant (like "2.4.2.1. Mathematical formulation")
     * **CRITICAL**: When mentioning code references (functions, classes, methods), ALWAYS use the format `[[functionName]]` (double brackets, no backticks, no parentheses). Example: "The `[[applyCitation]]` function processes citations. The `[[StructurePreservingEditor]]` class manages document structure." This format is REQUIRED and must be used consistently for ALL code references.
     * **CRITICAL CONSISTENCY RULE**: If you mention ANY function/class/method using the `[[functionName]]` format in the description, you MUST also include that function name in the `code_references` array for that section. Every `[[...]]` reference in the description MUST have a corresponding entry in the code_references array. This ensures consistency between what's mentioned in text and what's tracked as a code reference.
     * Be comprehensive - cover as much detail as possible conceptually
     * Subsections can vary in length but should be thorough
     * **Example of proper formatting**: "The system consists of three main components that work together to process user requests. The authentication component handles user verification and session management. The request processing component validates and routes incoming data requests. The database layer manages persistent storage and retrieval operations.\n\nThe workflow begins when a user submits a request. The system first validates the input to ensure data integrity and security. Once validated, the data is processed according to business rules and the results are returned to the user."
   - code_references: Array of code reference IDs mentioned in this section. **CRITICAL**: This array MUST include ALL function/class/method names that appear in `[[...]]` format anywhere in this section's description. If you write `[[fetch_metadata]]` in the description, you MUST include "fetch_metadata" in this array. **DO NOT duplicate references across sections unnecessarily** - if a function is mentioned in section 1, you don't need to list it again in section 1.1 unless it's specifically relevant there. Usually just list it once or twice total across the entire documentation.
   - Prioritize quality and detail over quantity

2. Extract code references (functions, classes, methods) from the ACTUAL CODE:
   - MAXIMUM 15 code references total (but use only as many as needed - don't force it to 15)
   - ONLY include actual, unique classes, functions, methods from the provided code context
   - DO NOT include generic names like "useEffect", "handleClick", "onSubmit", etc.
   - DO NOT make up function or class names that don't exist in the code
   - Create a unique referenceId matching the actual name from the code (e.g., if code has "applyCitation", use "applyCitation")
   - Add ONLY the IDs to the code_references array: ["applyCitation", "formatCitation"]
   - **CRITICAL**: These function names MUST appear in the description text using the format `[[functionName]]` (double brackets, no backticks, no parentheses). Example: "The `[[applyCitation]]` function processes..." This format is REQUIRED for all code references.
   - The full details (name, type, description, parameters, etc.) will be extracted from the code context and stored in MongoDB separately
   - Only include references that are actually relevant to the documentation topic
   - **DO NOT duplicate the same reference multiple times across different sections** - list it once or twice if it appears in multiple places, but don't overdo it


**CRITICAL:**
- Return ONLY valid JSON matching the schema
- NO markdown code blocks (no ```json)
- NO explanations before or after the JSON
- Ensure all JSON is properly formatted and complete
- The documentation.sections array must contain properly structured sections with content blocks
- If content is long, prioritize structure completeness over detail"""

        try:
            # Use streaming for large requests (required for max_tokens > 4096)
            with self.client.messages.stream(
                model=self.model,
                max_tokens=32000,  # Significantly increased to handle large structured output
                system=system_prompt,
                messages=[
                    {
                        "role": "user",
                        "content": user_message
                    }
                ]
            ) as stream:
                # Collect streamed response
                response_text = ""
                for event in stream:
                    if event.type == "content_block_delta":
                        if hasattr(event.delta, 'type') and event.delta.type == "text_delta":
                            if hasattr(event.delta, 'text'):
                                response_text += event.delta.text
                    elif event.type == "message_stop":
                        # Message complete
                        break
            
            # response_text now contains the full response
            # Try to parse JSON from response
            import json
            import re
            
            def extract_json_from_text(text):
                """Extract and clean JSON from text, handling markdown code blocks"""
                cleaned_text = text.strip()
                
                # Remove markdown code block markers
                if cleaned_text.startswith("```json"):
                    cleaned_text = cleaned_text[7:].strip()
                elif cleaned_text.startswith("```"):
                    cleaned_text = cleaned_text[3:].strip()
                
                if cleaned_text.endswith("```"):
                    cleaned_text = cleaned_text[:-3].strip()
                
                return cleaned_text
            
            def sanitize_control_characters(json_str):
                """Escape invalid control characters in JSON strings"""
                # Try to fix control characters in string values
                # Control characters (0x00-0x1F) need to be escaped
                
                result = []
                i = 0
                in_string = False
                escape_next = False
                
                while i < len(json_str):
                    char = json_str[i]
                    
                    if escape_next:
                        # Next character is escaped, so include it as-is
                        result.append(char)
                        escape_next = False
                    elif char == '\\':
                        # Escape sequence - check if it's already escaping something
                        result.append(char)
                        escape_next = True
                    elif char == '"':
                        # Check if this quote is escaped by counting backslashes
                        # Count consecutive backslashes before this quote
                        backslash_count = 0
                        j = i - 1
                        while j >= 0 and json_str[j] == '\\':
                            backslash_count += 1
                            j -= 1
                        
                        # If even number of backslashes (or zero), quote is not escaped
                        if backslash_count % 2 == 0:
                            in_string = not in_string
                        result.append(char)
                    elif in_string:
                        # Inside a string value
                        # Check if it's a control character (0x00-0x1F)
                        char_code = ord(char)
                        if char_code < 32:
                            # Control character - escape it
                            if char == '\n':
                                result.append('\\n')
                            elif char == '\r':
                                result.append('\\r')
                            elif char == '\t':
                                result.append('\\t')
                            else:
                                # Other control characters - escape as unicode
                                result.append(f'\\u{char_code:04x}')
                        else:
                            result.append(char)
                    else:
                        # Outside string - keep as-is
                        result.append(char)
                    
                    i += 1
                
                return ''.join(result)
            
            def fix_truncated_json(json_str):
                """Attempt to fix truncated JSON by closing open structures"""
                # Count open/close braces and brackets
                open_braces = json_str.count('{')
                close_braces = json_str.count('}')
                open_brackets = json_str.count('[')
                close_brackets = json_str.count(']')
                
                # Find the last complete structure
                fixed = json_str
                
                # If we're in the middle of a string, try to close it
                if json_str.count('"') % 2 != 0:
                    # Find the last unclosed quote and close the string
                    last_quote = json_str.rfind('"')
                    if last_quote > 0:
                        # Check if we're in a string value (not a key)
                        before_quote = json_str[:last_quote]
                        # Simple heuristic: if there's a colon before the quote, it's likely a value
                        if ':' in before_quote[-50:]:
                            fixed = json_str[:last_quote+1] + '"'
                
                # Close open arrays
                for _ in range(open_brackets - close_brackets):
                    fixed += ']'
                
                # Close open objects
                for _ in range(open_braces - close_braces):
                    fixed += '}'
                
                return fixed
            
            def extract_partial_data(json_str):
                """Extract what we can from incomplete JSON"""
                partial_data = {
                    "documentation": {"sections": []},
                    "code_reference_ids": []
                }
                
                try:
                    # Try to extract code_references array
                    code_refs_match = re.search(r'"code_references"\s*:\s*\[(.*?)\]', json_str, re.DOTALL)
                    if code_refs_match:
                        refs_content = code_refs_match.group(1)
                        # Extract quoted strings
                        ref_ids = re.findall(r'"([^"]+)"', refs_content)
                        partial_data["code_reference_ids"] = ref_ids
                    
                    # Try to extract glossary_terms array
                    glossary_match = re.search(r'"glossary_terms"\s*:\s*\[(.*?)\]', json_str, re.DOTALL)
                    if glossary_match:
                        terms_content = glossary_match.group(1)
                        # Extract quoted strings
                        term_ids = re.findall(r'"([^"]+)"', terms_content)
                        partial_data["glossary_term_ids"] = term_ids
                    
                    # Try to extract sections
                    sections_match = re.search(r'"sections"\s*:\s*\[(.*?)(?:\]|$)', json_str, re.DOTALL)
                    if sections_match:
                        sections_content = sections_match.group(1)
                        # Try to find section objects
                        section_objects = re.findall(r'\{\s*"id"\s*:\s*"([^"]+)"\s*,\s*"title"\s*:\s*"([^"]+)"', sections_content)
                        if section_objects:
                            sections = []
                            for section_id, title in section_objects:
                                sections.append({
                                    "id": section_id,
                                    "title": title,
                                    "description": "",  # Description might be truncated
                                    "code_references": []
                                })
                            partial_data["documentation"]["sections"] = sections
                except Exception as e:
                    print(f"[LLMService] Error extracting partial data: {e}")
                
                return partial_data
            
            # Clean the response text
            cleaned_text = extract_json_from_text(response_text)
            
            # Try to find JSON object
            json_match = re.search(r'\{.*', cleaned_text, re.DOTALL)
            if json_match:
                json_str = json_match.group(0)
                
                # First, try to parse as-is
                try:
                    parsed = json.loads(json_str)
                    
                    # Extract code reference IDs
                    code_refs = parsed.get("code_references", [])
                    code_ref_ids = []
                    for ref in code_refs:
                        if isinstance(ref, str):
                            code_ref_ids.append(ref)
                        elif isinstance(ref, dict):
                            ref_id = ref.get("referenceId")
                            if ref_id:
                                code_ref_ids.append(ref_id)
                    
                    return {
                        "documentation": parsed.get("documentation", {"sections": []}),
                        "code_reference_ids": code_ref_ids
                    }
                except json.JSONDecodeError as e:
                    print(f"[LLMService] JSON parse error: {e}")
                    print(f"[LLMService] Error at position: {e.pos if hasattr(e, 'pos') else 'unknown'}")
                    
                    # First, try to sanitize control characters
                    try:
                        sanitized_json = sanitize_control_characters(json_str)
                        parsed = json.loads(sanitized_json)
                        
                        code_refs = parsed.get("code_references", [])
                        code_ref_ids = [ref for ref in code_refs if isinstance(ref, str)]
                        
                        print(f"[LLMService] Successfully fixed control characters in JSON")
                        return {
                            "documentation": parsed.get("documentation", {"sections": []}),
                            "code_reference_ids": code_ref_ids
                        }
                    except Exception as sanitize_error:
                        # If sanitization didn't work, try to fix truncated JSON
                        try:
                            fixed_json = fix_truncated_json(json_str)
                            # Also sanitize the fixed JSON
                            fixed_json = sanitize_control_characters(fixed_json)
                            parsed = json.loads(fixed_json)
                            
                            code_refs = parsed.get("code_references", [])
                            code_ref_ids = [ref for ref in code_refs if isinstance(ref, str)]
                            
                            print(f"[LLMService] Successfully fixed truncated JSON with control character sanitization")
                            return {
                                "documentation": parsed.get("documentation", {"sections": []}),
                                "code_reference_ids": code_ref_ids
                            }
                        except Exception as fix_error:
                            print(f"[LLMService] Could not fix JSON, attempting partial extraction: {fix_error}")
                            
                            # Last resort: extract partial data using regex
                            partial_data = extract_partial_data(json_str)
                            print(f"[LLMService] Extracted partial data: {len(partial_data['code_reference_ids'])} refs, {len(partial_data['documentation']['sections'])} sections")
                            return partial_data
            else:
                # No JSON found
                print(f"[LLMService] No JSON object found in response")
                return {
                    "documentation": {"sections": []},
                    "code_reference_ids": []
                }
                
        except Exception as e:
            print(f"[LLMService] Error generating documentation: {e}")
            raise

    def generate_architecture_documentation(
        self,
        prompt: str,
        context_chunks: List[Dict[str, Any]],
        repo_name: str = "repository",
    ) -> Dict[str, Any]:
        """
        Generate System Architecture documentation as multiple sections.

        Structure (order matters):
        1. Overview (one section)
        2. Custom sections (as many as needed) that fully address the user's prompt — detailed
        3. Components, Data flow & communication, External dependencies,
           Design decisions & conventions, Deployment & runtime (one section each, at the end)

        Returns:
            { "title": str, "description": str, "sections": [ { "id", "title", "description" }, ... ] }
        """
        context_parts = []
        for i, chunk in enumerate(context_chunks, 1):
            meta = chunk.get("metadata", {})
            file_path = meta.get("file_path", "unknown")
            content = chunk.get("content", "")
            header = f"--- Code Chunk {i} ---\nFile: {file_path}\n---\n"
            context_parts.append(header + content + "\n")
        context = "\n".join(context_parts)

        schema_path = Path(__file__).parent.parent / "config" / "architecture_schema.json"
        schema_template = ""
        if schema_path.exists():
            try:
                with open(schema_path, "r", encoding="utf-8") as f:
                    schema_template = json.dumps(json.load(f), indent=2)
            except Exception as e:
                print(f"[LLMService] Warning: Could not load architecture schema: {e}")

        schema_section = ""
        if schema_template:
            schema_section = f"""

**REQUIRED JSON SCHEMA (you MUST follow this exactly):**
```json
{schema_template}
```

Return ONLY valid JSON matching this schema. No markdown code fence, no explanation. The root object must have "title", "description", and "sections" (array of objects with "id", "title", "description")."""

        system_prompt = f"""You are an expert technical writer who produces System Architecture documentation from codebases. The goal is to explain the system like a flowchart in text: clear, step-by-step, and easy for developers to follow—without relying on code. Balance is critical: enough detail and depth to be useful, but not so much that the doc feels overwhelming or hard to read.

**Format rules for section content (STRICT — this is architecture doc, not agent .md):**
- Do NOT use ### or any subheadings inside a section. The section title is the only heading. Use only paragraphs, and use bullet points or tables only where they add clarity—not everywhere.
- Balance prose and structure: write short, clear paragraphs that explain what things do and how they connect. Use bullet points only for discrete lists (e.g. a list of components, a list of steps in a flow). Use tables where they make information scannable (e.g. component name | role | path; or env var | purpose). Do not turn every sentence into a bullet—that is hard to read.
- Aim for detail and depth without walls of text: explain the flow (who calls whom, in what order), but keep paragraphs focused. If a section gets long, use one short table plus one or two paragraphs rather than a long bullet list.
- Do NOT include code blocks or code snippets unless strictly necessary (e.g. a single env var name in quotes). Prefer plain English descriptions.
- The doc should feel readable: a developer can grasp the architecture and flow without being overwhelmed. Avoid both excessive bullets and excessive prose.

**Section order (you MUST follow this):**

1. **Exactly one section: Overview** (id "1")
   - Purpose of the system, tech stack, high-level architecture style. One or two substantive paragraphs.

2. **Custom sections** (ids "2", "3", "4", ... — as many as needed)
   - One section per topic that addresses the user's prompt. Be thorough but concise: use paragraphs for explanation, bullets only for real lists, tables when they help (e.g. options, components).

3. **Reference sections** (one section each, at the end, in this order):
   - **Components** — a table (name, role, path) is ideal here; add one or two sentences before or after to explain how they relate.
   - **Data flow & communication** — short paragraphs and/or numbered steps for the flow. Not every step needs to be a bullet.
   - **External dependencies** — table or short bullet list with one line per dependency; avoid long paragraphs.
   - **Design decisions & conventions** — a few short paragraphs and/or a small table; keep it scannable.
   - **Deployment & runtime** — table for env vars (name, purpose) if helpful; short prose for how the app is run.

**Style:**
- Easy and detailed for developers. Factual and clear. No marketing language. No ### inside sections.
- If something is inferred, say so briefly (e.g. "Likely used for caching").
- Escape newlines in section description strings as \\n.{schema_section}"""

        user_message = f"""Generate System Architecture documentation for the {repo_name} repository.

**User request — create detailed custom sections that fully address this (use as many sections as needed):** {prompt}

**Code context:**
{context}

Return ONLY the JSON object with keys: title, description, sections (array of {{ id, title, description }})."""

        try:
            with self.client.messages.stream(
                model=self.model,
                max_tokens=24000,
                system=system_prompt,
                messages=[{"role": "user", "content": user_message}],
            ) as stream:
                response_text = ""
                for event in stream:
                    if event.type == "content_block_delta":
                        if hasattr(event.delta, "text"):
                            response_text += event.delta.text
                    elif event.type == "message_stop":
                        break

            response_text = response_text.strip()
            if response_text.startswith("```"):
                response_text = re.sub(r"^```(?:json)?\s*", "", response_text)
                response_text = re.sub(r"\s*```$", "", response_text)
            parsed = json.loads(response_text)
            title = parsed.get("title") or "System Architecture"
            description = parsed.get("description") or "System architecture overview."
            raw_sections = parsed.get("sections") or []
            sections = []
            for i, sec in enumerate(raw_sections):
                if not isinstance(sec, dict):
                    continue
                sec_id = sec.get("id") or str(i + 1)
                sec_title = sec.get("title") or f"Section {sec_id}"
                sec_desc = sec.get("description") or ""
                sections.append({
                    "id": sec_id,
                    "title": sec_title,
                    "description": sec_desc,
                    "code_references": [],
                    "subsections": [],
                })
            if not sections:
                sections = [{
                    "id": "1",
                    "title": "Overview",
                    "description": "(No sections generated; please retry.)",
                    "code_references": [],
                    "subsections": [],
                }]
            return {
                "title": title,
                "description": description,
                "sections": sections,
            }
        except json.JSONDecodeError as e:
            print(f"[LLMService] Architecture doc JSON parse error: {e}")
            return {
                "title": "System Architecture",
                "description": "System architecture overview.",
                "sections": [{
                    "id": "1",
                    "title": "Overview",
                    "description": "(Generation produced invalid JSON; please retry.)",
                    "code_references": [],
                    "subsections": [],
                }],
            }
        except Exception as e:
            print(f"[LLMService] Error generating architecture documentation: {e}")
            raise

    def generate_agent_docs_bundle(
        self,
        prompt: str,
        context_chunks: List[Dict[str, Any]],
        repo_name: str = "repository",
        extra_instructions: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Generate an AI-Agent .md bundle (guide + rules) as JSON matching agent_docs_bundle_schema.
        Caller should validate with validate_agent_docs_bundle().
        """
        schema_path = Path(__file__).parent.parent / "config" / "agent_docs_bundle_schema.json"
        schema_template = ""
        if schema_path.exists():
            try:
                with open(schema_path, "r", encoding="utf-8") as f:
                    schema_template = json.dumps(json.load(f), indent=2)
            except Exception as e:
                print(f"[LLMService] Warning: Could not load agent docs bundle schema: {e}")

        context_parts = []
        for i, chunk in enumerate(context_chunks, 1):
            meta = chunk.get("metadata", {})
            file_path = meta.get("file_path", "unknown")
            content = chunk.get("content", "")
            header = f"--- Code Chunk {i} ---\nFile: {file_path}\n---\n"
            context_parts.append(header + content + "\n")
        context = "\n".join(context_parts)

        schema_section = ""
        if schema_template:
            schema_section = f"""

**REQUIRED JSON SCHEMA (you MUST follow this exactly):**
```json
{schema_template}
```

Return ONLY valid JSON matching this schema. No markdown code fence, no explanation. The root object must have "guide" and "rules" (array of at least one rule)."""
        instructions = extra_instructions or ""
        system_prompt = f"""You are an expert at writing AI-Agent documentation: structured .md files that explain a codebase or procedures for AI agents (e.g. Cursor, Claude). You output a bundle of one main guide and multiple rule/playbook files.

**Format rules (strict):**
- Do NOT use markdown tables anywhere. Use bullet lists, numbered lists, and short paragraphs instead.
- In both the guide and each rule, include clear English instructional text: explain what to do, when to use which file, and how to follow the rules in plain language. Code blocks and lists are good, but add brief prose so an AI agent knows how to apply the content.

**Guide (GUIDE.md):**
- At the very top, the guide MUST state what type of AI agent will use these .mds and what that agent is for (e.g. "This playbook is for an agent that integrates with LLM APIs" or "For coding assistants working on Remotion projects"). Put this in the first 1–2 sentences of when_to_use or in description so it appears at the top when rendered.
- Then: name, description, when_to_use (1–2 paragraphs), optional topic_pointers (sections that point to a rule file), and how_to_use (list of {{ path, description }} for every rule).

**Rules:**
- Each rule: name, description, optional role, optional prerequisites (array of strings), **body** (main markdown: sections, code blocks, steps, and short instructional prose—no tables), optional input, optional output.

Use the code context below to ground the guide and rules in the actual repository. Be specific and reference real paths, modules, and patterns. Use headers (e.g. ##), code blocks, and lists only—no tables.{schema_section}"""

        user_message = f"""Generate an AI-Agent documentation bundle for the {repo_name} repository.

**User request:** {prompt}
{f'**Additional instructions:** {instructions}' if instructions else ''}

**Code context:**
{context}

Return ONLY the JSON object (no ```json wrapper, no explanation)."""

        try:
            with self.client.messages.stream(
                model=self.model,
                max_tokens=32000,
                system=system_prompt,
                messages=[{"role": "user", "content": user_message}],
            ) as stream:
                response_text = ""
                for event in stream:
                    if event.type == "content_block_delta":
                        if hasattr(event.delta, "type") and event.delta.type == "text_delta":
                            if hasattr(event.delta, "text"):
                                response_text += event.delta.text
                    elif event.type == "message_stop":
                        break
            cleaned = response_text.strip()
            if cleaned.startswith("```json"):
                cleaned = cleaned[7:].strip()
            elif cleaned.startswith("```"):
                cleaned = cleaned[3:].strip()
            if cleaned.endswith("```"):
                cleaned = cleaned[:-3].strip()
            json_match = re.search(r"\{.*", cleaned, re.DOTALL)
            if json_match:
                parsed = json.loads(json_match.group(0))
                if "guide" in parsed and "rules" in parsed:
                    return parsed
            return {"error": "Failed to parse agent docs bundle JSON", "guide": None, "rules": []}
        except Exception as e:
            print(f"[LLMService] Error generating agent docs bundle: {e}")
            return {"error": str(e), "guide": None, "rules": []}

    def generate_uml_class_diagram(
        self,
        prompt: str,
        context_chunks: List[Dict[str, Any]],
        repo_name: str = "repository",
    ) -> Dict[str, Any]:
        """
        Generate a UML class diagram as structured JSON from RAG context.

        Args:
            prompt: User's description of what to include in the diagram.
            context_chunks: Relevant code chunks from vector search.
            repo_name: Repository name for the prompt.

        Returns:
            Dict with "classes" and "relationships" matching the frontend schema.
            On parse/validation failure, returns {"error": str, "classes": [], "relationships": []}.
        """
        schema_path = Path(__file__).parent.parent / "config" / "uml_class_diagram_schema.json"
        schema_template = ""
        if schema_path.exists():
            try:
                with open(schema_path, "r", encoding="utf-8") as f:
                    schema_template = json.dumps(json.load(f), indent=2)
            except Exception as e:
                print(f"[LLMService] Warning: Could not load UML schema: {e}")

        context_parts = []
        for i, chunk in enumerate(context_chunks, 1):
            meta = chunk.get("metadata", {})
            file_path = meta.get("file_path", "unknown")
            class_name = meta.get("class_name", "")
            function_name = meta.get("function_name", "")
            language = meta.get("language", "")
            start_line = meta.get("start_line", 0)
            end_line = meta.get("end_line", 0)
            content = chunk.get("content", "")
            header = f"--- Code Chunk {i} ---\nFile: {file_path}\n"
            if class_name:
                header += f"Class: {class_name}\n"
            if function_name:
                header += f"Function/Method: {function_name}\n"
            header += f"Language: {language}\nLines: {start_line}-{end_line}\n---\n"
            context_parts.append(header + content + "\n")
        context = "\n".join(context_parts)

        schema_section = ""
        if schema_template:
            schema_section = f"""

**REQUIRED JSON SCHEMA (you MUST follow this exactly):**
```json
{schema_template}
```

**CRITICAL:**
- Return ONLY valid JSON. No markdown code blocks (no ```json), no explanations.
- Every relationship "source" and "target" MUST be exactly one of the class "id" values from the classes array.
- For association, aggregation, and composition: ALWAYS include sourceMultiplicity and targetMultiplicity (e.g. "1", "0..1", "1..*", "*"). Infer from code when possible; otherwise use sensible defaults like "1" and "*".
- Use only the relationship types in the schema. Use only visibility + - # ~ for attributes and methods.
- Prefer inferring real classes, attributes, and methods from the code; only add minimal placeholder content when the code does not specify."""

        system_prompt = f"""You are an expert at producing clear, concise UML class diagrams from code. Use your judgment to design the best possible diagram.

**Design goals:**
- **Conceptual clarity:** Prefer domain-style class names that group related code concepts. For example, instead of listing every class (GitHubFetcher, FetchReposRequest, etc.), introduce clear conceptual nodes like "GitHub", "Visual Tree", "Vector DB", "Request", "Service"—whatever best tells the story of the code. Summarize and consolidate so the diagram is readable and purposeful.
- **No central hub / max 3 connections per class (HARD RULE):** Do NOT create a central class that many others connect to or from (e.g. avoid one "Documentation Structure", "RAG Pipeline", or "Orchestrator" node with 4+ relationships). Every class must have at most 3 relationships total (incoming + outgoing). If the real design has a hub, split it into 2–3 smaller conceptual classes or show only the 3 most important links for that node. Prefer chains (A→B→C) and small clusters over one node with many edges.
- **Every class must have at least one relationship:** Do not include any class that is not connected to at least one other class. Every node must appear as source or target in at least one relationship. If you list a class, it must have an association (or other relationship type) to some other class.
- **Capture members from the code:** For each class, include as many attributes and methods as you can get specifically from the code—prioritize real members that appear in the provided context. Do not add an excessive number; keep nodes readable (e.g. avoid huge lists). If the code has many members, choose the most representative ones. If the code has few or none for a class, use guesswork to add plausible attributes and methods (e.g. "config", "fetch", "process") so each class has at least one attribute and one method and remains meaningful.
- **Descriptions (stored, not displayed on the diagram):** For each class, include an "explanation" field: one brief sentence describing what the class represents or does in the system. For each attribute and each method, include an optional "description" field: one brief sentence (e.g. what the attribute holds, or what the method does). Infer from the code when possible; use short, clear prose. These are for documentation/tooltips later.

Your task is to output a single JSON object with "classes" and "relationships" that represents your best, clearest version of the structure inferred from the provided code.{schema_section}

Output ONLY the JSON object, nothing else."""

        user_message = f"""Repository: {repo_name}

User request for the diagram: {prompt}

Code context:
{context}

Produce your best UML class diagram: clear, conceptual (e.g. GitHub, Visual Tree, Vector DB, Request, Service). CRITICAL: No central hub—do not have one class with 4 or more connections. Every class must have at most 3 relationships total. Every class must have at least one relationship—no isolated nodes; each class must appear as source or target in at least one relationship. For each class, capture as many attributes and methods as you can from the code (without making nodes too long); if the code does not specify enough, use guesswork. Also provide: (1) an "explanation" for each class; (2) a brief "description" for each attribute and each method. Ensure every relationship source and target is a class id from the classes array. Include sourceMultiplicity and targetMultiplicity for association, aggregation, and composition (e.g. "1", "0..1", "1..*", "*")."""

        def extract_json_from_text(text: str) -> str:
            cleaned = text.strip()
            if cleaned.startswith("```json"):
                cleaned = cleaned[7:].strip()
            elif cleaned.startswith("```"):
                cleaned = cleaned[3:].strip()
            if cleaned.endswith("```"):
                cleaned = cleaned[:-3].strip()
            return cleaned

        try:
            response = self.client.messages.create(
                model=self.model,
                max_tokens=8192,
                system=system_prompt,
                messages=[{"role": "user", "content": user_message}],
            )
            response_text = ""
            if response.content and len(response.content) > 0:
                response_text = response.content[0].text.strip()
            cleaned = extract_json_from_text(response_text)
            json_match = re.search(r"\{.*", cleaned, re.DOTALL)
            if not json_match:
                return {"error": "No JSON object in response", "classes": [], "relationships": []}
            json_str = json_match.group(0)
            parsed = json.loads(json_str)
            classes = parsed.get("classes") or []
            relationships = parsed.get("relationships") or []
            if not isinstance(classes, list):
                classes = []
            if not isinstance(relationships, list):
                relationships = []

            class_ids = {c.get("id") or c.get("className") for c in classes if isinstance(c, dict)}
            for c in classes:
                if isinstance(c, dict) and "id" not in c and c.get("className"):
                    c["id"] = c["className"]
                    class_ids.add(c["className"])
            valid_rels = []
            need_multiplicity = ("association", "aggregation", "composition")
            for r in relationships:
                if not isinstance(r, dict):
                    continue
                src = r.get("source")
                tgt = r.get("target")
                if src in class_ids and tgt in class_ids:
                    rel_type = r.get("relationship")
                    if rel_type in need_multiplicity:
                        if not r.get("sourceMultiplicity"):
                            r["sourceMultiplicity"] = "1"
                        if not r.get("targetMultiplicity"):
                            r["targetMultiplicity"] = "*"
                    valid_rels.append(r)

            valid_rels = _enforce_max_connections_per_class(valid_rels, max_per_class=3)
            connected_ids = set()
            for r in valid_rels:
                if isinstance(r, dict):
                    src, tgt = r.get("source"), r.get("target")
                    if src:
                        connected_ids.add(src)
                    if tgt:
                        connected_ids.add(tgt)
            classes = [c for c in classes if isinstance(c, dict) and (c.get("id") or c.get("className")) in connected_ids]
            return {"classes": classes, "relationships": valid_rels}
        except json.JSONDecodeError as e:
            print(f"[LLMService] UML diagram JSON parse error: {e}")
            return {"error": str(e), "classes": [], "relationships": []}
        except Exception as e:
            print(f"[LLMService] Error generating UML class diagram: {e}")
            return {"error": str(e), "classes": [], "relationships": []}

    def generate_uml_sequence_diagram(
        self,
        prompt: str,
        context_chunks: List[Dict[str, Any]],
        repo_name: str = "repository",
    ) -> Dict[str, Any]:
        """
        Generate a UML sequence diagram as structured JSON from RAG context.
        Returns lifelines (ordered), messages (ordered), and optional fragments.
        """
        schema_path = Path(__file__).parent.parent / "config" / "uml_sequence_diagram_schema.json"
        schema_template = ""
        if schema_path.exists():
            try:
                with open(schema_path, "r", encoding="utf-8") as f:
                    schema_template = json.dumps(json.load(f), indent=2)
            except Exception as e:
                print(f"[LLMService] Warning: Could not load sequence schema: {e}")

        context_parts = []
        for i, chunk in enumerate(context_chunks, 1):
            meta = chunk.get("metadata", {})
            file_path = meta.get("file_path", "unknown")
            class_name = meta.get("class_name", "")
            function_name = meta.get("function_name", "")
            language = meta.get("language", "")
            start_line = meta.get("start_line", 0)
            end_line = meta.get("end_line", 0)
            content = chunk.get("content", "")
            header = f"--- Code Chunk {i} ---\nFile: {file_path}\n"
            if class_name:
                header += f"Class: {class_name}\n"
            if function_name:
                header += f"Function/Method: {function_name}\n"
            header += f"Language: {language}\nLines: {start_line}-{end_line}\n---\n"
            context_parts.append(header + content + "\n")
        context = "\n".join(context_parts)

        schema_section = ""
        if schema_template:
            schema_section = f"""

**REQUIRED JSON SCHEMA (you MUST follow this exactly):**
```json
{schema_template}
```

**CRITICAL:**
- Return ONLY valid JSON. No markdown code blocks (no ```json), no explanations.
- Lifelines array order = left-to-right. At least 2 lifelines.
- Every message fromLifeline and toLifeline MUST be a lifeline id from the lifelines array.
- ONE MESSAGE = ONE ROW. Strict top-to-bottom order.
- STRICT CALL-RETURN PAIRING: Every call A→B (where A!=B) MUST have a return B→A (isReturn: true). No exceptions. NEVER use self-returns (B→B with isReturn)—they are invalid and will be stripped. Only cross-lifeline returns close activations.
- SIMPLE: Use 3-5 lifelines. Keep it concise.
- SELF-MESSAGES: Max 1 per lifeline, max 2 total. Standalone (no self-return after). opensNewActivation: true.
- FRAGMENTS: Use if code has loops/conditionals. Not at index 0.
- DESTROY: At least one lifeline with isDestroyed: true.
- Optionally include "steps" with title and messageIndices."""

        system_prompt = f"""You are an expert at producing clean, simple UML sequence diagrams.

**RULES (follow ALL strictly):**

1. SIMPLE AND CLEAN: Keep diagrams concise. Use 3-5 lifelines (not 8+). Each lifeline should be a meaningful participant. Fewer lifelines = cleaner diagram.

2. STRICT CALL-RETURN SEQUENCE (MOST IMPORTANT):
   The diagram must read as a clear sequence. For every call from A to B (where A != B), there MUST be a return from B to A (isReturn: true) that closes B's activation.
   CORRECT pattern:
     A→B call, B→A return, A→C call, C→A return
   CORRECT nested pattern:
     A→B call, B→C call, C→B return, B→A return
   WRONG (missing returns):
     A→B call, A→C call (B never returned!)
   WRONG (self-return instead of real return):
     A→B call, B→B self-return (this does NOT close B's activation from A's call!)
   A self-message with isReturn: true is MEANINGLESS—never do it. Only cross-lifeline returns close activations.

3. SELF-MESSAGES: Max 1 per lifeline, max 2 total. Only for truly important internal work. Set opensNewActivation: true. Do NOT follow a self-message with a self-return—self-messages are standalone visual elements.

4. FRAGMENTS: Use one if the code has a loop or conditional. Not at index 0.

5. DESTROY: At least one lifeline with isDestroyed: true.

6. Each message = one row. Strict chronological order.{schema_section}

Output ONLY the JSON object, nothing else."""

        user_message = f"""Repository: {repo_name}

User request: {prompt}

Code context:
{context}

Produce a SIMPLE, CLEAN sequence diagram (3-5 lifelines). RULES:
1. Every call A→B MUST have a matching return B→A. No exceptions. Never use self-returns (B→B isReturn)—only cross-lifeline returns.
2. Max 1 self-message per lifeline (max 2 total). No self-returns.
3. Use a fragment if there's a loop/conditional (not at index 0).
4. At least one lifeline isDestroyed: true.
5. End with a return to the initial caller.
Output ONLY the JSON object."""

        def extract_json_from_text(text: str) -> str:
            cleaned = text.strip()
            if cleaned.startswith("```json"):
                cleaned = cleaned[7:].strip()
            elif cleaned.startswith("```"):
                cleaned = cleaned[3:].strip()
            if cleaned.endswith("```"):
                cleaned = cleaned[:-3].strip()
            return cleaned

        try:
            response = self.client.messages.create(
                model=self.model,
                max_tokens=8192,
                system=system_prompt,
                messages=[{"role": "user", "content": user_message}],
            )
            response_text = ""
            if response.content and len(response.content) > 0:
                response_text = response.content[0].text.strip()
            cleaned = extract_json_from_text(response_text)
            json_match = re.search(r"\{.*", cleaned, re.DOTALL)
            if not json_match:
                return {"error": "No JSON object in response", "lifelines": [], "messages": [], "fragments": []}
            json_str = json_match.group(0)
            parsed = json.loads(json_str)
            lifelines = parsed.get("lifelines") or []
            messages = parsed.get("messages") or []
            steps = parsed.get("steps") or []
            fragments = parsed.get("fragments") or []
            if not isinstance(lifelines, list):
                lifelines = []
            if not isinstance(messages, list):
                messages = []
            if not isinstance(steps, list):
                steps = []
            if not isinstance(fragments, list):
                fragments = []
            # Fragment must not be first: drop fragments that include message index 0
            def fragment_ok(frag: dict) -> bool:
                idx = frag.get("messageIndices") or []
                return not idx or min(idx) >= 1

            fragments = [f for f in fragments if isinstance(f, dict) and fragment_ok(f)]

            lifeline_ids = {ll.get("id") or ll.get("label") for ll in lifelines if isinstance(ll, dict)}
            for ll in lifelines:
                if isinstance(ll, dict) and "id" not in ll and ll.get("label"):
                    ll["id"] = ll["label"]
                    lifeline_ids.add(ll["label"])
            if len(lifelines) < 2:
                return {"error": "At least 2 lifelines required", "lifelines": lifelines, "messages": [], "steps": [], "fragments": fragments}

            valid_messages = []
            for m in messages:
                if not isinstance(m, dict):
                    continue
                src = m.get("fromLifeline")
                tgt = m.get("toLifeline")
                if src not in lifeline_ids or tgt not in lifeline_ids:
                    continue
                if src == tgt and m.get("isReturn"):
                    continue
                if src != tgt and "opensNewActivation" in m:
                    m = {k: v for k, v in m.items() if k != "opensNewActivation"}
                valid_messages.append(m)

            # Ensure every cross-lifeline call has a matching return.
            # If a lifeline makes a new call before the previous one was returned,
            # insert the missing return right before the new call.
            fixed_messages: list[dict] = []
            pending: dict[str, str] = {}
            for m in valid_messages:
                src = m.get("fromLifeline", "")
                tgt = m.get("toLifeline", "")
                is_return = m.get("isReturn", False)
                is_self = src == tgt
                if not is_return and not is_self:
                    if src in pending:
                        old_callee = pending.pop(src)
                        fixed_messages.append({
                            "fromLifeline": old_callee,
                            "toLifeline": src,
                            "label": "return",
                            "isReturn": True,
                        })
                    pending[src] = tgt
                    fixed_messages.append(m)
                elif is_return and not is_self:
                    if tgt in pending and pending[tgt] == src:
                        del pending[tgt]
                    fixed_messages.append(m)
                else:
                    fixed_messages.append(m)
            for caller, callee in list(pending.items()):
                fixed_messages.append({
                    "fromLifeline": callee,
                    "toLifeline": caller,
                    "label": "return",
                    "isReturn": True,
                })

            if lifelines:
                has_destroy = any(
                    isinstance(ll, dict) and ll.get("isDestroyed")
                    for ll in lifelines
                )
                if not has_destroy:
                    lifelines[-1]["isDestroyed"] = True
            return {"lifelines": lifelines, "messages": fixed_messages, "steps": steps, "fragments": fragments}
        except json.JSONDecodeError as e:
            print(f"[LLMService] Sequence diagram JSON parse error: {e}")
            return {"error": str(e), "lifelines": [], "messages": [], "steps": [], "fragments": []}
        except Exception as e:
            print(f"[LLMService] Error generating sequence diagram: {e}")
            return {"error": str(e), "lifelines": [], "messages": [], "steps": [], "fragments": []}

    def generate_uml_use_case_diagram(
        self,
        prompt: str,
        context_chunks: List[Dict[str, Any]],
        repo_name: str = "repository",
    ) -> Dict[str, Any]:
        """
        Generate a UML use case diagram as structured JSON from RAG context.
        Returns systemBoundary, actors, useCases, and relationships (communication, include, extend, generalization).
        """
        schema_path = Path(__file__).parent.parent / "config" / "uml_use_case_diagram_schema.json"
        schema_template = ""
        if schema_path.exists():
            try:
                with open(schema_path, "r", encoding="utf-8") as f:
                    schema_template = json.dumps(json.load(f), indent=2)
            except Exception as e:
                print(f"[LLMService] Warning: Could not load use case schema: {e}")

        context_parts = []
        for i, chunk in enumerate(context_chunks, 1):
            meta = chunk.get("metadata", {})
            file_path = meta.get("file_path", "unknown")
            class_name = meta.get("class_name", "")
            function_name = meta.get("function_name", "")
            language = meta.get("language", "")
            start_line = meta.get("start_line", 0)
            end_line = meta.get("end_line", 0)
            content = chunk.get("content", "")
            header = f"--- Code Chunk {i} ---\nFile: {file_path}\n"
            if class_name:
                header += f"Class: {class_name}\n"
            if function_name:
                header += f"Function/Method: {function_name}\n"
            header += f"Language: {language}\nLines: {start_line}-{end_line}\n---\n"
            context_parts.append(header + content + "\n")
        context = "\n".join(context_parts)

        schema_section = ""
        if schema_template:
            schema_section = f"""

**REQUIRED JSON SCHEMA (you MUST follow this exactly):**
```json
{schema_template}
```

**CRITICAL:**
- Return ONLY valid JSON. No markdown code blocks (no ```json), no explanations.
- ACTOR PLACEMENT: Every actor MUST have "placement": "left" or "right". left = primary actors who initiate (User, Customer, Student, Admin). right = secondary/system actors (Database, Payment Gateway, External API, Mail Service).
- Every relationship source and target MUST be an id from actors or useCases.
- MAX 3 ASSOCIATIONS PER USE CASE: Each use case must be the source or target of at most 3 relationships total. Prefer fewer, clearer links. If you need more, create a separate use case diagram instead.
- communication: actor-use case or use case-use case. include/extend/generalization as in schema.
- Keep diagram simple: 2-5 actors, 3-8 use cases. Every actor and use case in at least one relationship."""

        system_prompt = f"""You are an expert at producing clear UML use case diagrams from code and requirements.

**Design goals:**
- PRIMARY ACTORS (placement: left): users who initiate use cases (Customer, Student, Admin, User). Place on the left of the system boundary.
- SECONDARY/SYSTEM ACTORS (placement: right): systems that support use cases (Database, Payment Gateway, API, Mail Service). Place on the right of the boundary.
- Each use case must have at most 3 associations (total as source or target). Prefer simplicity; suggest multiple diagrams if needed.
- Use cases inside the boundary. Every actor and every use case must appear in at least one relationship.
- Use communication for actor-use case links; <<include>>/<<extend>>/generalization where appropriate.

Your task is to output a single JSON object with systemBoundary (label), actors, useCases, and relationships.{schema_section}

Output ONLY the JSON object, nothing else."""

        user_message = f"""Repository: {repo_name}

User request for the diagram: {prompt}

Code context:
{context}

Produce a UML use case diagram. For each actor set placement: "left" for primary (User, Admin, Customer) or "right" for systems (Database, Payment Gateway). Each use case must have at most 3 relationships. systemBoundary, actors, useCases, relationships. Output ONLY the JSON object."""

        def extract_json_from_text(text: str) -> str:
            cleaned = text.strip()
            if cleaned.startswith("```json"):
                cleaned = cleaned[7:].strip()
            elif cleaned.startswith("```"):
                cleaned = cleaned[3:].strip()
            if cleaned.endswith("```"):
                cleaned = cleaned[:-3].strip()
            return cleaned

        try:
            response = self.client.messages.create(
                model=self.model,
                max_tokens=8192,
                system=system_prompt,
                messages=[{"role": "user", "content": user_message}],
            )
            response_text = ""
            if response.content and len(response.content) > 0:
                response_text = response.content[0].text.strip()
            cleaned = extract_json_from_text(response_text)
            json_match = re.search(r"\{.*", cleaned, re.DOTALL)
            if not json_match:
                return {"error": "No JSON object in response", "systemBoundary": {}, "actors": [], "useCases": [], "relationships": []}
            json_str = json_match.group(0)
            parsed = json.loads(json_str)
            system_boundary = parsed.get("systemBoundary") or {}
            if not isinstance(system_boundary, dict):
                system_boundary = {"label": "System"}
            if "label" not in system_boundary:
                system_boundary["label"] = "System"
            actors = parsed.get("actors") or []
            use_cases = parsed.get("useCases") or []
            relationships = parsed.get("relationships") or []
            if not isinstance(actors, list):
                actors = []
            if not isinstance(use_cases, list):
                use_cases = []
            if not isinstance(relationships, list):
                relationships = []

            actor_ids = {a.get("id") or a.get("label") for a in actors if isinstance(a, dict)}
            for a in actors:
                if isinstance(a, dict):
                    if "id" not in a and a.get("label"):
                        a["id"] = a["label"]
                        actor_ids.add(a["label"])
                    if a.get("placement") not in ("left", "right"):
                        a["placement"] = "left"
            use_case_ids = {u.get("id") or u.get("label") for u in use_cases if isinstance(u, dict)}
            for u in use_cases:
                if isinstance(u, dict) and "id" not in u and u.get("label"):
                    u["id"] = u["label"]
                    use_case_ids.add(u["label"])
            all_ids = actor_ids | use_case_ids

            valid_rels = []
            for r in relationships:
                if not isinstance(r, dict):
                    continue
                src = r.get("source")
                tgt = r.get("target")
                if src not in all_ids or tgt not in all_ids:
                    continue
                rel_type = (r.get("relationship") or "communication").lower()
                if rel_type not in ("communication", "include", "extend", "generalization"):
                    rel_type = "communication"
                r["relationship"] = rel_type
                valid_rels.append(r)

            # Cap: each use case at most 3 relationships (as source or target). Prefer communication > include > extend > generalization.
            _priority = {"communication": 0, "include": 1, "extend": 2, "generalization": 3}

            def use_case_degree(uc_id: str, rels: list) -> int:
                return sum(1 for x in rels if x.get("source") == uc_id or x.get("target") == uc_id)

            def rels_for_use_case(uc_id: str, rels: list) -> list:
                return [r for r in rels if r.get("source") == uc_id or r.get("target") == uc_id]

            kept = set(id(r) for r in valid_rels)
            for uc_id in use_case_ids:
                if use_case_degree(uc_id, valid_rels) <= 3:
                    continue
                ucr = rels_for_use_case(uc_id, valid_rels)
                ucr_sorted = sorted(ucr, key=lambda r: _priority.get(r.get("relationship"), 0))
                for r in ucr_sorted[3:]:
                    kept.discard(id(r))
            valid_rels = [r for r in valid_rels if id(r) in kept]

            # Ensure no orphan: every actor and use case in at least one relationship
            connected = set()
            for r in valid_rels:
                if isinstance(r, dict):
                    connected.add(r.get("source"))
                    connected.add(r.get("target"))
            for aid in all_ids:
                if aid in connected:
                    continue
                for r in relationships:
                    if not isinstance(r, dict):
                        continue
                    src, tgt = r.get("source"), r.get("target")
                    if src not in all_ids or tgt not in all_ids or (src != aid and tgt != aid):
                        continue
                    rel_type = (r.get("relationship") or "communication").lower()
                    if rel_type not in ("communication", "include", "extend", "generalization"):
                        rel_type = "communication"
                    valid_rels.append({"source": src, "target": tgt, "relationship": rel_type})
                    connected.add(aid)
                    break

            return {
                "systemBoundary": system_boundary,
                "actors": actors,
                "useCases": use_cases,
                "relationships": valid_rels,
            }
        except json.JSONDecodeError as e:
            print(f"[LLMService] Use case diagram JSON parse error: {e}")
            return {"error": str(e), "systemBoundary": {}, "actors": [], "useCases": [], "relationships": []}
        except Exception as e:
            print(f"[LLMService] Error generating use case diagram: {e}")
            return {"error": str(e), "systemBoundary": {}, "actors": [], "useCases": [], "relationships": []}

    def generate_parameter_descriptions_batch(
        self,
        parameters: List[Dict[str, Any]],
        code_context: str
    ) -> Dict[str, str]:
        """
        Generate descriptions for multiple parameters in a single batch call.
        Uses cheaper Haiku model for cost optimization.
        
        Args:
            parameters: List of dicts with 'name', 'full_definition', 'function_name'
            code_context: Relevant code context (truncated)
        
        Returns:
            Dict mapping parameter names to descriptions
        """
        if not parameters:
            return {}
        
        # Build parameter list for prompt
        param_list = "\n".join([
            f"- {p['name']}: {p.get('full_definition', p['name'])} (from function: {p.get('function_name', 'unknown')})"
            for p in parameters
        ])
        
        prompt = f"""Generate clear, documentation-style descriptions for these function parameters.
Each description should be 1-2 sentences explaining what the parameter is used for and its purpose.

Parameters:
{param_list}

Code context:
{code_context[:3000]}

Return ONLY a JSON object mapping parameter names to descriptions, like this:
{{
  "param1": "Description for param1",
  "param2": "Description for param2"
}}

Do not include any other text, just the JSON object."""
        
        try:
            response = self.client.messages.create(
                model=self.model_fast,  # Use cheaper model
                max_tokens=1000,  # Enough for multiple descriptions
                messages=[{
                    "role": "user",
                    "content": prompt
                }]
            )
            
            if response.content and len(response.content) > 0:
                response_text = response.content[0].text.strip()
                
                # Extract JSON from response
                json_match = re.search(r'\{.*\}', response_text, re.DOTALL)
                if json_match:
                    try:
                        descriptions = json.loads(json_match.group(0))
                        return descriptions
                    except json.JSONDecodeError:
                        print(f"[LLMService] Failed to parse parameter descriptions JSON")
                
                # Fallback: try to extract descriptions line by line
                descriptions = {}
                for param in parameters:
                    param_name = param['name']
                    # Try to find description in response
                    pattern = rf'["\']?{re.escape(param_name)}["\']?\s*:\s*["\']([^"\']+)["\']'
                    match = re.search(pattern, response_text, re.IGNORECASE)
                    if match:
                        descriptions[param_name] = match.group(1).strip()
                    else:
                        descriptions[param_name] = f"The {param_name.replace('_', ' ')} parameter."
                
                return descriptions
            else:
                # Fallback: generate simple descriptions
                return {p['name']: f"The {p['name'].replace('_', ' ')} parameter." for p in parameters}
                
        except Exception as e:
            print(f"[LLMService] Error generating batch parameter descriptions: {e}")
            # Fallback: simple descriptions
            return {p['name']: f"The {p['name'].replace('_', ' ')} parameter." for p in parameters}
    
    def generate_code_reference_descriptions_batch(
        self,
        code_references: List[Dict[str, Any]]
    ) -> Dict[str, str]:
        """
        Generate descriptions for multiple code references in a single batch call.
        Uses cheaper Haiku model for cost optimization.
        
        Args:
            code_references: List of dicts with 'name', 'type', 'file_path', 'code'
        
        Returns:
            Dict mapping reference names to descriptions
        """
        if not code_references:
            return {}
        
        # Build reference list for prompt
        ref_list = "\n".join([
            f"- {ref['name']} ({ref.get('type', 'unknown')}) from {ref.get('file_path', 'unknown')}"
            for ref in code_references
        ])
        
        # Combine code contexts (truncated)
        code_contexts = []
        for ref in code_references:
            code = ref.get('code', '')[:1000]  # Limit each to 1000 chars
            code_contexts.append(f"{ref['name']}:\n{code}")
        combined_context = "\n\n".join(code_contexts)
        
        prompt = f"""Generate concise but detailed descriptions for these code references (functions, classes, methods).
Each description should be 2-4 sentences explaining what it does, its purpose, and key functionality.
Write in scikit-learn documentation style.

References:
{ref_list}

Code:
{combined_context[:4000]}
**CRITICAL INSTRUCTIONS - READ CAREFULLY:**
1. Do NOT include the reference name at the beginning of descriptions. Just describe what it does.
2. **ABSOLUTELY FORBIDDEN: DO NOT copy ANY text from the code, including:**
   - Prompt strings (f-strings with instructions like "You are an expert...")
   - Docstrings or comments
   - Instruction text
   - Any string literals
   - Template text
3. **YOU MUST: Analyze the FUNCTION'S BEHAVIOR, not its text content:**
   - What API does it call? (e.g., "calls OpenAI API")
   - What does it process? (e.g., "processes metadata")
   - What does it return? (e.g., "returns formatted citations")
   - What is its purpose? (e.g., "generates academic citations")
4. **If you see prompt strings in the code, they are DATA the function uses, NOT the function's description.**
   - Example: If code has `prompt = "You are an expert..."`, DO NOT copy that.
   - Instead, say: "Generates formatted citations using AI based on metadata"
5. Write COMPLETELY ORIGINAL descriptions based on code logic analysis, never copy text from code.

Return ONLY a JSON object mapping reference names to descriptions, like this:
{{
  "FunctionName": "Description of what the function does...",
  "ClassName": "Description of what the class does..."
}}

Do not include any other text, just the JSON object."""
        
        try:
            response = self.client.messages.create(
                model=self.model_fast,  # Use cheaper model
                max_tokens=2000,  # Enough for multiple descriptions
                messages=[{
                    "role": "user",
                    "content": prompt
                }]
            )
            
            if response.content and len(response.content) > 0:
                response_text = response.content[0].text.strip()
                
                # Extract JSON from response
                json_match = re.search(r'\{.*\}', response_text, re.DOTALL)
                if json_match:
                    try:
                        descriptions = json.loads(json_match.group(0))
                        return descriptions
                    except json.JSONDecodeError:
                        print(f"[LLMService] Failed to parse code reference descriptions JSON")
                
                # Fallback: try to extract descriptions
                descriptions = {}
                for ref in code_references:
                    ref_name = ref['name']
                    # Try to find description in response
                    pattern = rf'["\']?{re.escape(ref_name)}["\']?\s*:\s*["\']([^"\']+)["\']'
                    match = re.search(pattern, response_text, re.IGNORECASE)
                    if match:
                        descriptions[ref_name] = match.group(1).strip()
                    else:
                        # Fallback template
                        ref_type = ref.get('type', 'function')
                        if ref_type == 'class':
                            descriptions[ref_name] = "A class that provides functionality for managing operations and state within the application."
                        elif ref_type == 'function':
                            descriptions[ref_name] = "A function that processes input data and returns transformed output according to its implementation."
                        else:
                            descriptions[ref_name] = "A method that performs operations on the class instance."
                
                return descriptions
            else:
                # Fallback: generate template descriptions
                descriptions = {}
                for ref in code_references:
                    ref_type = ref.get('type', 'function')
                    if ref_type == 'class':
                        descriptions[ref['name']] = "A class that provides functionality for managing operations and state within the application."
                    elif ref_type == 'function':
                        descriptions[ref['name']] = "A function that processes input data and returns transformed output according to its implementation."
                    else:
                        descriptions[ref['name']] = "A method that performs operations on the class instance."
                return descriptions
                
        except Exception as e:
            print(f"[LLMService] Error generating batch code reference descriptions: {e}")
            # Fallback: template descriptions
            descriptions = {}
            for ref in code_references:
                ref_type = ref.get('type', 'function')
                if ref_type == 'class':
                    descriptions[ref['name']] = "A class that provides functionality for managing operations and state within the application."
                elif ref_type == 'function':
                    descriptions[ref['name']] = "A function that processes input data and returns transformed output according to its implementation."
                else:
                    descriptions[ref['name']] = "A method that performs operations on the class instance."
            return descriptions

    def enrich_chunks_for_retrieval(
        self,
        chunks: List[Dict[str, Any]],
        batch_size: int = 8,
        max_content_chars: int = 450,
    ) -> None:
        """
        Add one-sentence summary and retrieval keywords to each chunk's metadata.
        Uses Claude in batches to minimize tokens. Mutates chunks in place.
        """
        if not chunks:
            return
        for b in range(0, len(chunks), batch_size):
            batch = chunks[b : b + batch_size]
            parts = []
            for i, c in enumerate(batch, 1):
                content = (c.get("content") or "")[:max_content_chars]
                meta = c.get("metadata") or {}
                fn = meta.get("function_name") or meta.get("class_name") or ""
                parts.append(f"{i}: {fn}\n{content}")
            user_msg = "\n\n".join(parts)
            sys_msg = 'Output only a JSON array. Each item: {"s":"one sentence summary","k":["kw1","kw2","kw3"]}. No other text. Same number of items as chunks.'
            try:
                resp = self.client.messages.create(
                    model=self.model_fast,
                    max_tokens=500,
                    system=sys_msg,
                    messages=[{"role": "user", "content": user_msg}],
                )
                text = (resp.content[0].text.strip() if resp.content else "") or "[]"
            except Exception as e:
                print(f"[LLMService] Enrich batch failed: {e}", flush=True)
                for c in batch:
                    c.setdefault("metadata", {})["summary"] = ""
                    c["metadata"]["keywords"] = []
                continue
            raw = text.strip()
            if raw.startswith("```"):
                raw = raw.split("\n", 1)[-1].replace("```", "").strip()
            try:
                arr = json.loads(raw)
            except json.JSONDecodeError:
                try:
                    arr = json.loads(re.search(r"\[.*\]", raw, re.DOTALL).group(0))
                except (AttributeError, json.JSONDecodeError):
                    arr = []
            for i, c in enumerate(batch):
                meta = c.setdefault("metadata", {})
                if i < len(arr) and isinstance(arr[i], dict):
                    meta["summary"] = (arr[i].get("s") or "").strip()[:500]
                    k = arr[i].get("k")
                    meta["keywords"] = k if isinstance(k, list) else ([k] if k else [])
                else:
                    meta["summary"] = ""
                    meta["keywords"] = []
