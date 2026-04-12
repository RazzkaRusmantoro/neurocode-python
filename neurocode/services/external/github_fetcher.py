import os
import httpx
import asyncio
import base64
from typing import List, Dict, Any, Optional


def _source_priority(path: str) -> int:
    
    path_lower = path.lower()
    if path_lower.startswith("src/"):
        return 0
    if path_lower.startswith("app/") or path_lower.startswith("lib/") or path_lower.startswith("server/"):
        return 1
    if "/src/" in path_lower or "/lib/" in path_lower:
        return 2
    return 3


class GitHubFetcher:
    
    
    def __init__(self):
        self.max_files = int(os.getenv("INDEX_MAX_FILES", "500"))                                      
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
        
        files: List[Dict[str, Any]] = []
        token_preview = f"{access_token[:8]}..." if (access_token and len(access_token) > 8) else ("(empty)" if not access_token else "(present)")
        print(f"[GitHubFetcher] fetch_repository_files: repo={repo_full_name!r} branch={branch!r} token={token_preview}", flush=True)

        async with httpx.AsyncClient(timeout=60.0) as client:
                                                                    
            commit_sha = await self._get_branch_sha(
                client, repo_full_name, access_token, branch
            )
            if not commit_sha and branch in ("main", "master"):
                fallback = "master" if branch == "main" else "main"
                print(f"[GitHubFetcher] Trying fallback branch {fallback!r}.", flush=True)
                commit_sha = await self._get_branch_sha(
                    client, repo_full_name, access_token, fallback
                )
                if commit_sha:
                    branch = fallback
            if not commit_sha:
                print(f"[GitHubFetcher] No commit SHA for branch {branch!r}; cannot fetch tree.", flush=True)
                return files
            print(f"[GitHubFetcher] Branch SHA: {commit_sha[:12]}... (branch={branch!r})", flush=True)

                                                                
            tree_items = await self._get_tree_recursive(
                client, repo_full_name, access_token, commit_sha, path
            )
            
                                                          
            print(f"[GitHubFetcher] Tree items to fetch: {len(tree_items)}", flush=True)
            await self._batch_fetch_file_contents(
                client, repo_full_name, access_token, tree_items, files
            )
            print(f"[GitHubFetcher] Fetched {len(files)} file contents.", flush=True)

        return files

    async def get_default_branch(self, repo_full_name: str, access_token: str) -> Optional[str]:
        
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

    async def list_branches_with_latest_commit(
        self,
        repo_full_name: str,
        access_token: str,
        *,
        max_branches: int = 500,
    ) -> Dict[str, str]:
        
        out: Dict[str, str] = {}
        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                page = 1
                per_page = 100
                while len(out) < max_branches:
                    response = await client.get(
                        f"https://api.github.com/repos/{repo_full_name}/branches",
                        headers={
                            "Authorization": f"token {access_token}",
                            "Accept": "application/vnd.github.v3+json",
                        },
                        params={"per_page": per_page, "page": page},
                    )
                    if response.status_code != 200:
                        break
                    data = response.json()
                    if not data:
                        break
                    for b in data:
                        name = b.get("name")
                        sha = (b.get("commit") or {}).get("sha")
                        if name and sha:
                            out[name] = sha
                    if len(data) < per_page:
                        break
                    page += 1
        except Exception as e:
            print(f"[GitHubFetcher] list_branches_with_latest_commit failed: {e}")
        return out

    async def get_changed_file_paths(
        self,
        repo_full_name: str,
        access_token: str,
        base_sha: str,
        head_sha: str,
    ) -> List[str]:
        
        out: List[str] = []
        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                                                                                            
                                                           
                url = f"https://api.github.com/repos/{repo_full_name}/compare/{base_sha}...{head_sha}"
                response = await client.get(
                    url,
                    headers={
                        "Authorization": f"token {access_token}",
                        "Accept": "application/vnd.github.v3+json",
                    },
                )
                if response.status_code != 200:
                    return out
                data = response.json()
                files = data.get("files") or []
                seen = set()
                for f in files:
                    filename = f.get("filename")
                    if filename and filename not in seen:
                        seen.add(filename)
                        out.append(filename)
                                                                                                
                    prev = f.get("previous_filename")
                    if prev and prev not in seen:
                        seen.add(prev)
                        out.append(prev)
        except Exception as e:
            print(f"[GitHubFetcher] get_changed_file_paths failed: {e}")
        return out

    async def _get_branch_sha(
        self,
        client: httpx.AsyncClient,
        repo_full_name: str,
        access_token: str,
        branch: str
    ) -> Optional[str]:
        
        url = f"https://api.github.com/repos/{repo_full_name}/branches/{branch}"
        try:
            response = await client.get(
                url,
                headers={
                    "Authorization": f"token {access_token}",
                    "Accept": "application/vnd.github.v3+json",
                },
            )
            if response.status_code == 200:
                data = response.json()
                commit_sha = data.get("commit", {}).get("sha")
                return commit_sha
                                                   
            body = response.text[:500] if response.text else ""
            print(f"[GitHubFetcher] _get_branch_sha {response.status_code} {url!r}: {body}", flush=True)
        except Exception as e:
            print(f"[GitHubFetcher] _get_branch_sha error: {e}", flush=True)
        return None
    
    async def _get_tree_recursive(
        self,
        client: httpx.AsyncClient,
        repo_full_name: str,
        access_token: str,
        commit_sha: str,
        path: str = ""
    ) -> List[Dict[str, Any]]:
        
        try:
                                                    
            commit_url = f"https://api.github.com/repos/{repo_full_name}/git/commits/{commit_sha}"
            commit_response = await client.get(
                commit_url,
                headers={
                    "Authorization": f"token {access_token}",
                    "Accept": "application/vnd.github.v3+json",
                },
            )
            if commit_response.status_code != 200:
                print(f"[GitHubFetcher] _get_tree_recursive commit response {commit_response.status_code}: {commit_response.text[:300]}", flush=True)
                return []

            tree_sha = commit_response.json().get("tree", {}).get("sha")
            if not tree_sha:
                print(f"[GitHubFetcher] _get_tree_recursive: no tree.sha in commit response", flush=True)
                return []

                                           
            tree_url = f"https://api.github.com/repos/{repo_full_name}/git/trees/{tree_sha}?recursive=1"
            tree_response = await client.get(
                tree_url,
                headers={
                    "Authorization": f"token {access_token}",
                    "Accept": "application/vnd.github.v3+json",
                },
            )

            if tree_response.status_code != 200:
                print(f"[GitHubFetcher] _get_tree_recursive tree response {tree_response.status_code}: {tree_response.text[:300]}", flush=True)
                return []

            if tree_response.status_code == 200:
                tree_data = tree_response.json()
                all_items = tree_data.get("tree", [])
                
                                             
                if path:
                    all_items = [
                        item for item in all_items
                        if item.get("path", "").startswith(path)
                    ]
                
                                                              
                filtered = []
                for item in all_items:
                    if item.get("type") != "blob":                    
                        continue
                    
                    file_path = item.get("path", "")
                    file_name = file_path.split("/")[-1]
                    
                                                             
                    if file_path.startswith(".") or any(
                        skip in file_path for skip in ["node_modules", "dist", "build", ".git"]
                    ):
                        continue
                    
                                                
                    if file_name.endswith((".ts", ".tsx", ".js", ".jsx", ".py", ".java", ".go", ".rs", ".cpp", ".c")):
                        filtered.append(item)
                
                                                                                                       
                filtered.sort(key=lambda item: (_source_priority(item.get("path", "")), item.get("path", "")))
                limited = filtered[:self.max_files]
                print(f"[GitHubFetcher] Tree: {len(all_items)} items -> {len(filtered)} source files -> returning {len(limited)}", flush=True)
                if len(filtered) > self.max_files:
                    print(f"[GitHubFetcher] Capping at {self.max_files} files (repo has {len(filtered)} source files). Set INDEX_MAX_FILES to index more.", flush=True)
                return limited

        except Exception as e:
            print(f"[GitHubFetcher] _get_tree_recursive error: {e}", flush=True)

        return []
    
    async def _batch_fetch_file_contents(
        self,
        client: httpx.AsyncClient,
        repo_full_name: str,
        access_token: str,
        tree_items: List[Dict[str, Any]],
        files: List[Dict[str, Any]]
    ) -> None:
        
                                                                    
        tasks = []
        for item in tree_items[:self.max_files]:
            sha = item.get("sha")
            path = item.get("path", "")
            if sha:
                tasks.append(
                    self._fetch_blob_content(client, repo_full_name, access_token, sha, path)
                )
        
                                           
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
                
                                       
                if encoding == "base64":
                    try:
                        content = base64.b64decode(content).decode("utf-8")
                    except:
                        content = ""
                
                                                        
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

