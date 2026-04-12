import json
import os
from datetime import datetime
from typing import Dict, Any, Optional
from pathlib import Path


class StorageService:
    
    
    def __init__(self, base_dir: str = "data"):
        
        self.base_dir = Path(base_dir)
        self.base_dir.mkdir(exist_ok=True)
    
    def save_analysis_results(
        self,
        repo_full_name: str,
        branch: str,
        results: Dict[str, Any]
    ) -> Dict[str, str]:
        
                                              
        repo_safe = repo_full_name.replace("/", "_")
        branch_safe = branch.replace("/", "_")
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        
        repo_dir = self.base_dir / repo_safe / branch_safe / timestamp
        repo_dir.mkdir(parents=True, exist_ok=True)
        
        saved_files = {}
        
                                   
        structure_file = repo_dir / "repository_structure.json"
        with open(structure_file, 'w', encoding='utf-8') as f:
            json.dump(results.get("repository_structure", {}), f, indent=2)
        saved_files["repository_structure"] = str(structure_file)
        
                      
        symbols_file = repo_dir / "symbols.json"
        with open(symbols_file, 'w', encoding='utf-8') as f:
            json.dump(results.get("symbols", {}), f, indent=2)
        saved_files["symbols"] = str(symbols_file)
        
                           
        dependencies_file = repo_dir / "dependencies.json"
        with open(dependencies_file, 'w', encoding='utf-8') as f:
            json.dump(results.get("dependencies", []), f, indent=2)
        saved_files["dependencies"] = str(dependencies_file)
        
                             
        function_usage_file = repo_dir / "function_usage.json"
        with open(function_usage_file, 'w', encoding='utf-8') as f:
            json.dump(results.get("function_usage", {}), f, indent=2)
        saved_files["function_usage"] = str(function_usage_file)
        
                                                               
        chunks_file = repo_dir / "chunks.json"
        with open(chunks_file, 'w', encoding='utf-8') as f:
            json.dump(results.get("chunks", []), f, indent=2)
        saved_files["chunks"] = str(chunks_file)
        
                       
        metadata_file = repo_dir / "metadata.json"
        with open(metadata_file, 'w', encoding='utf-8') as f:
            json.dump(results.get("metadata", {}), f, indent=2)
        saved_files["metadata"] = str(metadata_file)
        
                      
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
        
                                              
        repo_safe = repo_full_name.replace("/", "_")
        branch_safe = branch.replace("/", "_")
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        
        repo_dir = self.base_dir / repo_safe / branch_safe / timestamp
        repo_dir.mkdir(parents=True, exist_ok=True)
        
                                             
        doc_file = repo_dir / "documentation.md"
        with open(doc_file, 'w', encoding='utf-8') as f:
            f.write(f"# Documentation\n\n")
            f.write(f"**Repository:** {repo_full_name}\n")
            f.write(f"**Branch:** {branch}\n")
            f.write(f"**Generated:** {datetime.now().isoformat()}\n\n")
            f.write(f"**Prompt:** {prompt}\n\n")
            f.write("---\n\n")
            f.write(documentation)
        
                                   
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

