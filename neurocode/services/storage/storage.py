"""
Storage service for saving analysis results
"""
import json
import os
from datetime import datetime
from typing import Dict, Any, Optional
from pathlib import Path


class StorageService:
    """Service for saving analysis results to local storage"""
    
    def __init__(self, base_dir: str = "data"):
        """
        Initialize storage service
        
        Args:
            base_dir: Base directory for storing results (default: "data")
        """
        self.base_dir = Path(base_dir)
        self.base_dir.mkdir(exist_ok=True)
    
    def save_analysis_results(
        self,
        repo_full_name: str,
        branch: str,
        results: Dict[str, Any]
    ) -> Dict[str, str]:
        """
        Save analysis results to local storage
        
        Args:
            repo_full_name: Repository full name (e.g., "owner/repo")
            branch: Branch name
            results: Analysis results from CodeAnalyzer
        
        Returns:
            Dictionary with saved file paths
        """
        # Create repository-specific directory
        repo_safe = repo_full_name.replace("/", "_")
        branch_safe = branch.replace("/", "_")
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        
        repo_dir = self.base_dir / repo_safe / branch_safe / timestamp
        repo_dir.mkdir(parents=True, exist_ok=True)
        
        saved_files = {}
        
        # Save repository structure
        structure_file = repo_dir / "repository_structure.json"
        with open(structure_file, 'w', encoding='utf-8') as f:
            json.dump(results.get("repository_structure", {}), f, indent=2)
        saved_files["repository_structure"] = str(structure_file)
        
        # Save symbols
        symbols_file = repo_dir / "symbols.json"
        with open(symbols_file, 'w', encoding='utf-8') as f:
            json.dump(results.get("symbols", {}), f, indent=2)
        saved_files["symbols"] = str(symbols_file)
        
        # Save dependencies
        dependencies_file = repo_dir / "dependencies.json"
        with open(dependencies_file, 'w', encoding='utf-8') as f:
            json.dump(results.get("dependencies", []), f, indent=2)
        saved_files["dependencies"] = str(dependencies_file)
        
        # Save function usage
        function_usage_file = repo_dir / "function_usage.json"
        with open(function_usage_file, 'w', encoding='utf-8') as f:
            json.dump(results.get("function_usage", {}), f, indent=2)
        saved_files["function_usage"] = str(function_usage_file)
        
        # Save chunks (this is the main data for vectorization)
        chunks_file = repo_dir / "chunks.json"
        with open(chunks_file, 'w', encoding='utf-8') as f:
            json.dump(results.get("chunks", []), f, indent=2)
        saved_files["chunks"] = str(chunks_file)
        
        # Save metadata
        metadata_file = repo_dir / "metadata.json"
        with open(metadata_file, 'w', encoding='utf-8') as f:
            json.dump(results.get("metadata", {}), f, indent=2)
        saved_files["metadata"] = str(metadata_file)
        
        # Save summary
        summary = {
            "repository": repo_full_name,
            "branch": branch,
            "timestamp": timestamp,
            "saved_files": saved_files,
            "metadata": results.get("metadata", {})
        }
        summary_file = repo_dir / "summary.json"
        with open(summary_file, 'w', encoding='utf-8') as f:
            json.dump(summary, f, indent=2)
        saved_files["summary"] = str(summary_file)
        
        print(f"[StorageService] ✓ Saved analysis results to: {repo_dir}")
        
        return {
            "directory": str(repo_dir),
            "files": saved_files
        }
    
    def save_documentation(
        self,
        repo_full_name: str,
        branch: str,
        prompt: str,
        documentation: str,
        metadata: Optional[Dict[str, Any]] = None
    ) -> Dict[str, str]:
        """
        Save generated documentation to local storage
        
        Args:
            repo_full_name: Repository full name (e.g., "owner/repo")
            branch: Branch name
            prompt: User's prompt/query
            documentation: Generated documentation text
            metadata: Optional metadata (chunks used, etc.)
        
        Returns:
            Dictionary with saved file path
        """
        # Create repository-specific directory
        repo_safe = repo_full_name.replace("/", "_")
        branch_safe = branch.replace("/", "_")
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        
        repo_dir = self.base_dir / repo_safe / branch_safe / timestamp
        repo_dir.mkdir(parents=True, exist_ok=True)
        
        # Save documentation as markdown file
        doc_file = repo_dir / "documentation.md"
        with open(doc_file, 'w', encoding='utf-8') as f:
            f.write(f"# Documentation\n\n")
            f.write(f"**Repository:** {repo_full_name}\n")
            f.write(f"**Branch:** {branch}\n")
            f.write(f"**Generated:** {datetime.now().isoformat()}\n\n")
            f.write(f"**Prompt:** {prompt}\n\n")
            f.write("---\n\n")
            f.write(documentation)
        
        # Save metadata if provided
        if metadata:
            metadata_file = repo_dir / "documentation_metadata.json"
            with open(metadata_file, 'w', encoding='utf-8') as f:
                json.dump({
                    "prompt": prompt,
                    "generated_at": datetime.now().isoformat(),
                    "repository": repo_full_name,
                    "branch": branch,
                    **metadata
                }, f, indent=2)
        
        print(f"[StorageService] ✓ Saved documentation to: {doc_file}")
        
        return {
            "directory": str(repo_dir),
            "documentation_file": str(doc_file),
            "metadata_file": str(metadata_file) if metadata else None
        }

