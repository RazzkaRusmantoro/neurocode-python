"""
LLM Service for documentation generation using Claude
"""
import os
from typing import List, Dict, Any
from anthropic import Anthropic


class LLMService:
    """Service for generating documentation using Claude"""
    
    def __init__(self):
        api_key = os.getenv("ANTHROPIC_API_KEY")
        if not api_key:
            raise ValueError("ANTHROPIC_API_KEY environment variable is required")
        
        self.client = Anthropic(api_key=api_key)
        self.model = "claude-sonnet-4-5-20250929"
    
    def generate_documentation(
        self,
        prompt: str,
        context_chunks: List[Dict[str, Any]],
        repo_name: str = "repository"
    ) -> str:
        """
        Generate documentation using Claude with RAG context
        
        Args:
            prompt: User's query/prompt
            context_chunks: List of relevant code chunks from vector search
            repo_name: Name of the repository
        
        Returns:
            Generated documentation text
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
        
        # Build system and user messages
        system_prompt = f"""You are a technical documentation expert specializing in API reference documentation similar to scikit-learn, NumPy, and other scientific Python libraries.

Your documentation should:
- Be code-focused and technical, highlighting specific methods, functions, classes, and code patterns
- Include detailed explanations of important conditional logic, control flow, and algorithmic decisions
- Reference specific code elements (function names, class names, parameters, return types) from the provided code
- Use proper code formatting with backticks for function names, class names, variables
- Include code examples showing how functions/methods are used
- Explain the "why" behind important if statements, loops, and design decisions
- Structure like API reference documentation with clear sections for classes, methods, parameters
- Use markdown formatting with code blocks, headers, and lists
- Be precise and technical, not generic descriptions
"""
        
        user_message = f"""Based on the following code from the {repo_name} repository, generate comprehensive, code-focused documentation that addresses this request:

**User Request:** {prompt}

**Relevant Code Context:**
{context}

Generate documentation that:
1. **Highlights specific code elements**: Reference exact function names, class names, methods, and important variables from the code
2. **Explains code logic**: Detail important if statements, loops, error handling, and algorithmic decisions
3. **Provides code examples**: Show how the functions/classes are used with actual code snippets
4. **API reference style**: Structure like scikit-learn docs with clear sections for each class/function
5. **Technical depth**: Explain parameters, return types, side effects, and implementation details
6. **Code formatting**: Use proper markdown code blocks and inline code formatting

Focus on being specific to the actual code provided, not generic descriptions. Reference file paths, function names, and specific code patterns from the context above."""

        try:
            message = self.client.messages.create(
                model=self.model,
                max_tokens=4096,
                system=system_prompt,
                messages=[
                    {
                        "role": "user",
                        "content": user_message
                    }
                ]
            )
            
            # Extract text content from response
            if message.content and len(message.content) > 0:
                return message.content[0].text
            else:
                return "No documentation generated."
                
        except Exception as e:
            print(f"[LLMService] Error generating documentation: {e}")
            raise

