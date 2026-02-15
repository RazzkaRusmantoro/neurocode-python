"""
LLM Service for documentation generation using Claude
"""
import os
import json
import re
from pathlib import Path
from typing import List, Dict, Any
from anthropic import Anthropic


class LLMService:
    """Service for generating documentation using Claude"""
    
    def __init__(self):
        api_key = os.getenv("ANTHROPIC_API_KEY")
        if not api_key:
            raise ValueError("ANTHROPIC_API_KEY environment variable is required")
        
        self.client = Anthropic(api_key=api_key)
        self.model = "claude-haiku-4-5-20251001"  # Premium model for main generation
        self.model_fast = "claude-haiku-4-5-20251001"  # Cheaper model for simple tasks (~10x cheaper)
    
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
   - MAXIMUM 5 sections total (including subsections count toward this limit)
   - Create sections with IDs like "1", "1.1", "2", "2.1", "2.2", etc.
   - **CRITICAL REQUIREMENT**: The documentation MUST include subsections. Not every section needs subsections, but the overall documentation structure MUST have at least some subsections (e.g., section "1" should have "1.1", "1.2", etc., or section "2" should have "2.1", "2.2", etc.). This is REQUIRED - do not generate documentation without any subsections.
   - Each section has: id, title, description, code_references (array of IDs), and optional subsections (but remember: subsections MUST exist somewhere in the documentation)
   - The description field must be DETAILED and THOROUGH, similar to scikit-learn documentation style:
     * Explain concepts, algorithms, and processes in clear English
     * **FORMATTING GUIDELINES**: 
       - Use paragraph breaks (`\n\n`) to separate different ideas or topics. Each paragraph should focus on one main concept.
       - Write in a natural, flowing documentation style - use a mix of paragraphs and lists as appropriate
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
   - MAXIMUM 10 code references total (but use only as many as needed - don't force it to 10)
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
