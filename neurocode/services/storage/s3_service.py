"""
S3 service for storing and retrieving documentation
"""
import os
import boto3
from botocore.exceptions import ClientError, NoCredentialsError
from typing import Optional
from dotenv import load_dotenv

# Load environment variables
load_dotenv()


class S3Service:
    """Service for S3 operations"""
    
    def __init__(self):
        """
        Initialize S3 service with credentials from environment variables
        """
        self.aws_access_key_id = os.getenv("AWS_ACCESS_KEY_ID")
        self.aws_secret_access_key = os.getenv("AWS_SECRET_ACCESS_KEY")
        self.aws_region = os.getenv("AWS_REGION", "us-east-1")
        self.bucket_name = os.getenv("S3_BUCKET_NAME")
        
        if not all([self.aws_access_key_id, self.aws_secret_access_key, self.bucket_name]):
            raise ValueError(
                "Missing required AWS credentials. Please set AWS_ACCESS_KEY_ID, "
                "AWS_SECRET_ACCESS_KEY, and S3_BUCKET_NAME in environment variables."
            )
        
        # Initialize S3 client
        self.s3_client = boto3.client(
            's3',
            aws_access_key_id=self.aws_access_key_id,
            aws_secret_access_key=self.aws_secret_access_key,
            region_name=self.aws_region
        )
    
    def generate_s3_key(
        self,
        organization_id: str,
        repository_id: str,
        branch: str,
        scope: str,
        documentation_id: Optional[str] = None,
        file_extension: str = "json"
    ) -> str:
        """
        Generate S3 key/path for documentation
        
        Structure: organizations/{org_id}/repositories/{repo_id}/documentation/{branch}/{scope}/{doc_id}.{ext}
        
        Args:
            organization_id: Organization ID
            repository_id: Repository ID
            branch: Git branch name
            scope: Documentation scope (file, module, repository, custom)
            documentation_id: Optional documentation ID (if None, uses timestamp)
            file_extension: File extension (default: "json")
        
        Returns:
            S3 key/path string
        """
        if documentation_id is None:
            from datetime import datetime
            documentation_id = datetime.now().strftime("%Y%m%d_%H%M%S")
        
        # Sanitize branch name (replace / with _)
        branch_safe = branch.replace("/", "_")
        
        # Build S3 key
        s3_key = (
            f"organizations/{organization_id}/"
            f"repositories/{repository_id}/"
            f"documentation/{branch_safe}/{scope}/"
            f"{documentation_id}.{file_extension}"
        )
        
        return s3_key
    
    def upload_documentation(
        self,
        content: str,
        s3_key: str,
        content_type: str = "application/json"
    ) -> dict:
        """
        Upload documentation content to S3
        
        Args:
            content: Documentation content (string)
            s3_key: S3 object key/path
            content_type: Content type (default: "application/json")
        
        Returns:
            Dictionary with success status and S3 URL/key
        """
        try:
            # Upload to S3
            self.s3_client.put_object(
                Bucket=self.bucket_name,
                Key=s3_key,
                Body=content.encode('utf-8'),
                ContentType=content_type
            )
            
            # Generate S3 URL
            s3_url = f"s3://{self.bucket_name}/{s3_key}"
            
            return {
                "success": True,
                "s3_key": s3_key,
                "s3_url": s3_url,
                "bucket": self.bucket_name,
                "content_size": len(content.encode('utf-8'))
            }
            
        except NoCredentialsError:
            return {
                "success": False,
                "error": "AWS credentials not found or invalid"
            }
        except ClientError as e:
            error_code = e.response.get('Error', {}).get('Code', 'Unknown')
            return {
                "success": False,
                "error": f"AWS S3 error: {error_code}",
                "details": str(e)
            }
        except Exception as e:
            return {
                "success": False,
                "error": f"Failed to upload to S3: {str(e)}"
            }
    
    def get_documentation(self, s3_key: str) -> dict:
        """
        Retrieve documentation content from S3
        
        Args:
            s3_key: S3 object key/path
        
        Returns:
            Dictionary with success status and content
        """
        try:
            # Get object from S3
            response = self.s3_client.get_object(
                Bucket=self.bucket_name,
                Key=s3_key
            )
            
            # Read content
            content = response['Body'].read().decode('utf-8')
            
            return {
                "success": True,
                "content": content,
                "content_type": response.get('ContentType', 'application/json'),
                "content_size": response.get('ContentLength', 0),
                "last_modified": response.get('LastModified')
            }
            
        except ClientError as e:
            error_code = e.response.get('Error', {}).get('Code', 'Unknown')
            if error_code == 'NoSuchKey':
                return {
                    "success": False,
                    "error": f"Documentation not found: {s3_key}"
                }
            return {
                "success": False,
                "error": f"AWS S3 error: {error_code}",
                "details": str(e)
            }
        except Exception as e:
            return {
                "success": False,
                "error": f"Failed to retrieve from S3: {str(e)}"
            }
    
    def delete_documentation(self, s3_key: str) -> dict:
        """
        Delete documentation from S3
        
        Args:
            s3_key: S3 object key/path
        
        Returns:
            Dictionary with success status
        """
        try:
            self.s3_client.delete_object(
                Bucket=self.bucket_name,
                Key=s3_key
            )
            
            return {
                "success": True,
                "message": f"Documentation deleted: {s3_key}"
            }
            
        except ClientError as e:
            error_code = e.response.get('Error', {}).get('Code', 'Unknown')
            return {
                "success": False,
                "error": f"AWS S3 error: {error_code}",
                "details": str(e)
            }
        except Exception as e:
            return {
                "success": False,
                "error": f"Failed to delete from S3: {str(e)}"
            }
    
    def check_connection(self) -> dict:
        """
        Check if S3 connection is working
        
        Returns:
            Dictionary with connection status
        """
        try:
            # Try to list bucket (head_bucket is more efficient)
            self.s3_client.head_bucket(Bucket=self.bucket_name)
            
            return {
                "success": True,
                "message": f"Successfully connected to S3 bucket: {self.bucket_name}",
                "bucket": self.bucket_name,
                "region": self.aws_region
            }
        except ClientError as e:
            error_code = e.response.get('Error', {}).get('Code', 'Unknown')
            if error_code == '404':
                return {
                    "success": False,
                    "error": f"Bucket not found: {self.bucket_name}"
                }
            elif error_code == '403':
                return {
                    "success": False,
                    "error": f"Access denied to bucket: {self.bucket_name}"
                }
            return {
                "success": False,
                "error": f"AWS S3 error: {error_code}",
                "details": str(e)
            }
        except NoCredentialsError:
            return {
                "success": False,
                "error": "AWS credentials not found or invalid"
            }
        except Exception as e:
            return {
                "success": False,
                "error": f"Failed to connect to S3: {str(e)}"
            }

