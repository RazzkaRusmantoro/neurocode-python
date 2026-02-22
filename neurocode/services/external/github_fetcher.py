"""
GitHub repository file fetcher service
"""
import os
import httpx
import asyncio
import base64
from typing import List, Dict, Any, Optional


def _source_priority(path: str) -> int:
    """Lower = higher priority. Prefer src/app/lib/server over other paths."""
    path_lower = path.lower()
    if path_lower.startswith("src/"):
        return 0
    if path_lower.startswith("app/") or path_lower.startswith("lib/") or path_lower.startswith("server/"):
        return 1
    if "/src/" in path_lower or "/lib/" in path_lower:
        return 2
    return 3


class GitHubFetcher:
    """Fetches files from GitHub repositories"""
    
    def __init__(self):
        self.max_files = int(os.getenv("INDEX_MAX_FILES", "500"))  # Max source files to fetch per repo
        self.supported_languages = [
            'typescript', 'javascript', 'python', 'java', 'go',
            'rust', 'cpp', 'c', 'tsx', 'jsx'
        ]
    
    async def fetch_repository_files(
        self,
        repo_full_name: str,
        access_token: str,
        branch: str = "main",
        path: str = ""
    ) -> List[Dict[str, Any]]:
        """
        Fetch all repository files using Git Trees API (more efficient)
        
        Args:
            repo_full_name: Repository full name (e.g., "owner/repo")
            access_token: GitHub access token
            branch: Branch name (default: "main")
            path: Starting path (default: "" for root)
            
        Returns:
            List of file dictionaries with path, content, and language
        """
        files: List[Dict[str, Any]] = []
        
        async with httpx.AsyncClient(timeout=60.0) as client:
            # Step 1: Get the commit SHA for the branch (1 API call)
            commit_sha = await self._get_branch_sha(
                client, repo_full_name, access_token, branch
            )
            if not commit_sha:
                return files
            
            # Step 2: Get the full tree recursively (1 API call)
            tree_items = await self._get_tree_recursive(
                client, repo_full_name, access_token, commit_sha, path
            )
            
            # Step 3: Filter and batch fetch file contents
            await self._batch_fetch_file_contents(
                client, repo_full_name, access_token, tree_items, files
            )
        
        return files

    async def get_default_branch(self, repo_full_name: str, access_token: str) -> Optional[str]:
        """
        Get the repository's default branch (e.g. main, master, or whatever is set on GitHub).
        """
        try:
            async with httpx.AsyncClient(timeout=15.0) as client:
                response = await client.get(
                    f"https://api.github.com/repos/{repo_full_name}",
                    headers={
                        "Authorization": f"token {access_token}",
                        "Accept": "application/vnd.github.v3+json",
                    },
                )
                if response.status_code == 200:
                    data = response.json()
                    default = data.get("default_branch")
                    if default:
                        return default
        except Exception as e:
            print(f"[GitHubFetcher] get_default_branch failed: {e}")
        return None
    
    async def _get_branch_sha(
        self,
        client: httpx.AsyncClient,
        repo_full_name: str,
        access_token: str,
        branch: str
    ) -> Optional[str]:
        """Get the commit SHA for a branch (1 API call)"""
        try:
            response = await client.get(
                f"https://api.github.com/repos/{repo_full_name}/branches/{branch}",
                headers={
                    "Authorization": f"token {access_token}",
                    "Accept": "application/vnd.github.v3+json",
                },
            )
            if response.status_code == 200:
                data = response.json()
                commit_sha = data.get("commit", {}).get("sha")
                # Also get the tree SHA from the commit in the same response if available
                commit_data = data.get("commit", {})
                if commit_data.get("commit", {}).get("tree", {}).get("sha"):
                    # We can get tree SHA from commit object if it's nested
                    pass
                return commit_sha
        except Exception as e:
            print(f"Error getting branch SHA: {e}")
        return None
    
    async def _get_tree_recursive(
        self,
        client: httpx.AsyncClient,
        repo_full_name: str,
        access_token: str,
        commit_sha: str,
        path: str = ""
    ) -> List[Dict[str, Any]]:
        """Get the full repository tree recursively (1 API call)"""
        try:
            # Get the tree SHA from the commit first
            commit_response = await client.get(
                f"https://api.github.com/repos/{repo_full_name}/git/commits/{commit_sha}",
                headers={
                    "Authorization": f"token {access_token}",
                    "Accept": "application/vnd.github.v3+json",
                },
            )
            if commit_response.status_code != 200:
                return []
            
            tree_sha = commit_response.json().get("tree", {}).get("sha")
            if not tree_sha:
                return []
            
            # Get the full tree recursively
            tree_response = await client.get(
                f"https://api.github.com/repos/{repo_full_name}/git/trees/{tree_sha}?recursive=1",
                headers={
                    "Authorization": f"token {access_token}",
                    "Accept": "application/vnd.github.v3+json",
                },
            )
            
            if tree_response.status_code == 200:
                tree_data = tree_response.json()
                all_items = tree_data.get("tree", [])
                
                # Filter by path if specified
                if path:
                    all_items = [
                        item for item in all_items
                        if item.get("path", "").startswith(path)
                    ]
                
                # Filter out directories and unsupported files
                filtered = []
                for item in all_items:
                    if item.get("type") != "blob":  # Skip directories
                        continue
                    
                    file_path = item.get("path", "")
                    file_name = file_path.split("/")[-1]
                    
                    # Skip hidden files and build directories
                    if file_path.startswith(".") or any(
                        skip in file_path for skip in ["node_modules", "dist", "build", ".git"]
                    ):
                        continue
                    
                    # Check if file is supported
                    if file_name.endswith((".ts", ".tsx", ".js", ".jsx", ".py", ".java", ".go", ".rs", ".cpp", ".c")):
                        filtered.append(item)
                
                # Prefer source-like paths (src/, app/, lib/, server/) so we index important code first
                filtered.sort(key=lambda item: (_source_priority(item.get("path", "")), item.get("path", "")))
                limited = filtered[:self.max_files]
                if len(filtered) > self.max_files:
                    print(f"[GitHubFetcher] Capping at {self.max_files} files (repo has {len(filtered)} source files). Set INDEX_MAX_FILES to index more.", flush=True)
                return limited
        
        except Exception as e:
            print(f"Error getting tree: {e}")
        
        return []
    
    async def _batch_fetch_file_contents(
        self,
        client: httpx.AsyncClient,
        repo_full_name: str,
        access_token: str,
        tree_items: List[Dict[str, Any]],
        files: List[Dict[str, Any]]
    ) -> None:
        """Batch fetch file contents using Git Blobs API"""
        # Fetch all blobs concurrently (much faster than sequential)
        tasks = []
        for item in tree_items[:self.max_files]:
            sha = item.get("sha")
            path = item.get("path", "")
            if sha:
                tasks.append(
                    self._fetch_blob_content(client, repo_full_name, access_token, sha, path)
                )
        
        # Execute all requests concurrently
        results = await asyncio.gather(*tasks, return_exceptions=True)
        
        for i, result in enumerate(results):
            if isinstance(result, dict) and result.get("content"):
                files.append(result)
                if len(files) % 10 == 0:
                    print(f"Fetched {len(files)} files so far...", flush=True)
    
    async def _fetch_blob_content(
        self,
        client: httpx.AsyncClient,
        repo_full_name: str,
        access_token: str,
        blob_sha: str,
        file_path: str
    ) -> Dict[str, Any]:
        """Fetch a single blob content"""
        try:
            response = await client.get(
                f"https://api.github.com/repos/{repo_full_name}/git/blobs/{blob_sha}",
                headers={
                    "Authorization": f"token {access_token}",
                    "Accept": "application/vnd.github.v3+json",
                },
            )
            
            if response.status_code == 200:
                blob_data = response.json()
                content = blob_data.get("content", "")
                encoding = blob_data.get("encoding", "")
                
                # Decode base64 content
                if encoding == "base64":
                    try:
                        content = base64.b64decode(content).decode("utf-8")
                    except:
                        content = ""
                
                # Determine language from file extension
                language = "text"
                if file_path.endswith((".ts", ".tsx")):
                    language = "TypeScript"
                elif file_path.endswith((".js", ".jsx")):
                    language = "JavaScript"
                elif file_path.endswith(".py"):
                    language = "Python"
                elif file_path.endswith(".java"):
                    language = "Java"
                elif file_path.endswith(".go"):
                    language = "Go"
                elif file_path.endswith(".rs"):
                    language = "Rust"
                elif file_path.endswith((".cpp", ".c")):
                    language = "C++" if file_path.endswith(".cpp") else "C"
                
                return {
                    "path": file_path,
                    "content": content,
                    "language": language,
                }
        except Exception as e:
            print(f"Error fetching blob {blob_sha}: {e}")
        
        return {}

